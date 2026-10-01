from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.audit_logs.models import AuditLog
from apps.billing.models import Invoice, InvoiceStatus
from apps.billing.tasks import send_overdue_invoice_reminders
from apps.customers.models import Customer, ServiceLocation
from apps.inventory.models import Part, UnitOfMeasure
from apps.inventory.tasks import check_low_stock_thresholds
from apps.notifications.models import Notification, NotificationType
from apps.notifications.tasks import dispatch_async_notification
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.service_requests.tasks import check_and_escalate_sla_breaches
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class HealthCheckAPITest(APITestCase):
    """Test suite for the API health check endpoint."""

    def test_health_check_endpoint(self):
        url = reverse("health-check")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")
        self.assertEqual(response.data["service"], "field-service-management-api")
        self.assertEqual(response.data["database"], "ok")
        self.assertIn("timestamp", response.data)


class CeleryBackgroundTasksTests(APITestCase):
    """Test suite for Celery background worker tasks, periodic cron jobs, and health APIs."""

    def setUp(self):
        # 1. Users with various roles
        self.admin = User.objects.create_user(
            email="admin.celery@fsm.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            first_name="Admin",
            last_name="Commander",
        )
        self.dispatcher = User.objects.create_user(
            email="dispatcher.celery@fsm.com",
            password="DispatcherPassword123!",
            role=UserRole.DISPATCHER,
            first_name="Dispatch",
            last_name="Lead",
        )
        self.technician = User.objects.create_user(
            email="tech.celery@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Vikram",
            last_name="Singh",
        )
        self.customer_user = User.objects.create_user(
            email="client.celery@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Rajesh",
            last_name="Khanna",
        )

        # 2. Business Domain Entities
        self.customer = Customer.objects.create(
            user=self.customer_user,
            company_name="Fortis Escorts Heart Institute",
            primary_contact_name="Rajesh Khanna",
            email="client.celery@fsm.com",
            phone="+919811223344",
            billing_address="Okhla Road, New Delhi",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Fortis Okhla Wing B",
            address_line1="Okhla Road",
            city="New Delhi",
            state="Delhi",
            postal_code="110025",
            is_primary=True,
        )
        self.category = ServiceCategory.objects.create(
            name="Critical Infrastructure",
            code="CRIT-INFRA",
        )
        self.service_type = ServiceType.objects.create(
            category=self.category,
            name="Backup Generator Auto-Start Audit",
            code="GEN-AUTO-START",
            estimated_duration_minutes=90,
            base_price=Decimal("8000.00"),
        )

    def test_celery_health_endpoint(self):
        """Admin can inspect Celery queue status, broker config, and beat schedule."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/health/celery/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertEqual(res.data["status"], "operational")
        self.assertIn("registered_tasks", res.data)
        self.assertIn("scheduled_beat_jobs", res.data)
        self.assertIn("check-sla-breaches-every-15-mins", res.data["scheduled_beat_jobs"])
        self.assertIn("send-overdue-invoice-reminders-daily", res.data["scheduled_beat_jobs"])
        self.assertIn("check-low-stock-thresholds-hourly", res.data["scheduled_beat_jobs"])

    def test_automated_sla_breach_detection_task(self):
        """SLA breach task identifies past-due tickets and dispatches escalations."""
        # Create an active service request whose resolution SLA is in the past
        past_time = timezone.now() - timedelta(hours=2)
        breached_sr = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Generator Failed to Switch On During Outage",
            description="Automatic transfer switch did not engage on mains drop.",
            priority=RequestPriority.CRITICAL,
            status=RequestStatus.IN_PROGRESS,
            sla_response_due_at=past_time,
            sla_resolution_due_at=past_time,
        )
        ServiceRequest.objects.filter(id=breached_sr.id).update(
            sla_response_due_at=past_time,
            sla_resolution_due_at=past_time,
        )
        breached_sr.refresh_from_db()

        initial_notif_count = Notification.objects.filter(
            notification_type=NotificationType.GENERAL,
            related_entity_id=breached_sr.id,
        ).count()
        self.assertEqual(initial_notif_count, 0)

        # Execute Celery Task
        result = check_and_escalate_sla_breaches()

        self.assertGreaterEqual(result["breached_count"], 1)
        self.assertIn(str(breached_sr.id), result["escalated_ids"])

        # Verify that supervisory staff (Admin & Dispatcher) received notification
        admin_notif = Notification.objects.filter(
            recipient=self.admin,
            notification_type=NotificationType.GENERAL,
            related_entity_id=breached_sr.id,
        ).first()
        self.assertIsNotNone(admin_notif)
        self.assertIn("SLA Breached", admin_notif.title)

        # Verify audit log was recorded
        audit_log = AuditLog.objects.filter(
            entity_type="service_request",
            entity_id=breached_sr.id,
            description__icontains="SLA breach escalation",
        ).first()
        self.assertIsNotNone(audit_log)

    def test_overdue_invoice_reminders_task(self):
        """Overdue invoice reminder task detects past-due bills and notifies customer & finance."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            assigned_technician=self.technician,
            title="Generator testing",
            priority=WorkOrderPriority.HIGH,
            status=WorkOrderStatus.COMPLETED,
        )
        overdue_inv = Invoice.objects.create(
            work_order=wo,
            customer=self.customer,
            status=InvoiceStatus.ISSUED,
            issue_date=timezone.localdate() - timedelta(days=20),
            due_date=timezone.localdate() - timedelta(days=5),
            labor_amount=Decimal("3000.00"),
            total_amount=Decimal("3000.00"),
        )

        # Execute Celery Task
        result = send_overdue_invoice_reminders()

        self.assertGreaterEqual(result["overdue_count"], 1)
        self.assertIn(overdue_inv.invoice_number, result["processed_invoices"])

        # Customer received payment reminder
        cust_notif = Notification.objects.filter(
            recipient=self.customer_user,
            related_entity_id=overdue_inv.id,
        ).first()
        self.assertIsNotNone(cust_notif)
        self.assertIn("PAYMENT OVERDUE", cust_notif.title)

    def test_low_stock_inventory_scan_task(self):
        """Low stock scanner identifies parts below threshold and alerts managers."""
        part = Part.objects.create(
            name="ATS Transfer Relay Unit",
            sku="ATS-RELAY-12V",
            unit_of_measure=UnitOfMeasure.PIECE,
            cost_price=Decimal("800.00"),
            selling_price=Decimal("1800.00"),
            reorder_threshold=10,  # 0 on hand <= 10 threshold
        )

        # Execute Celery Task
        result = check_low_stock_thresholds()

        self.assertGreaterEqual(result["low_stock_count"], 1)
        found_skus = [p["sku"] for p in result["low_stock_parts"]]
        self.assertIn("ATS-RELAY-12V", found_skus)

        # Admin received low stock alert
        admin_notif = Notification.objects.filter(
            recipient=self.admin,
            notification_type=NotificationType.LOW_STOCK_ALERT,
            related_entity_id=part.id,
        ).first()
        self.assertIsNotNone(admin_notif)

    def test_async_notification_worker_task(self):
        """Async notification worker creates notification in background with retry policy."""
        res = dispatch_async_notification(
            recipient_id=self.technician.id,
            title="Emergency Dispatch",
            message="New urgent assignment assigned.",
            priority="HIGH",
        )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["recipient_email"], self.technician.email)

        notif = Notification.objects.get(id=res["notification_id"])
        self.assertEqual(notif.recipient, self.technician)
        self.assertEqual(notif.title, "Emergency Dispatch")

    def test_task_trigger_api_endpoint(self):
        """Admin can trigger background jobs on-demand via the REST API."""
        self.client.force_authenticate(user=self.admin)

        # Trigger SLA breach task
        res = self.client.post("/api/v1/tasks/trigger/", {"task_name": "check_sla_breaches"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "EXECUTED")
        self.assertEqual(res.data["task_name"], "check_sla_breaches")

        # Invalid task name returns 400
        res_bad = self.client.post("/api/v1/tasks/trigger/", {"task_name": "invalid_fake_task"})
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rbac_technician_and_customer_denied(self):
        """Technicians and Customers cannot access Celery health or trigger tasks."""
        endpoints = [
            ("/api/v1/health/celery/", "get"),
            ("/api/v1/tasks/trigger/", "get"),
            ("/api/v1/tasks/trigger/", "post"),
        ]

        for ep, method in endpoints:
            # Technician gets 403
            self.client.force_authenticate(user=self.technician)
            fn = getattr(self.client, method)
            res_tech = fn(ep, {"task_name": "check_sla_breaches"} if method == "post" else None)
            self.assertEqual(res_tech.status_code, status.HTTP_403_FORBIDDEN)

            # Customer gets 403
            self.client.force_authenticate(user=self.customer_user)
            res_cust = fn(ep, {"task_name": "check_sla_breaches"} if method == "post" else None)
            self.assertEqual(res_cust.status_code, status.HTTP_403_FORBIDDEN)
