import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.audit_logs.models import AuditAction, AuditLog
from apps.audit_logs.services import AuditLogService
from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentMethod
from apps.customers.models import Customer, ServiceLocation
from apps.service_requests.models import RequestPriority, ServiceRequest
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class AuditLogsEngineTests(APITestCase):
    def setUp(self):
        # Create users with different roles
        self.admin = User.objects.create_user(
            email="admin.audit@fsm.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            first_name="Admin",
            last_name="Auditor",
        )
        self.manager = User.objects.create_user(
            email="manager.audit@fsm.com",
            password="ManagerPassword123!",
            role=UserRole.MANAGER,
            first_name="Manager",
            last_name="Auditor",
        )
        self.technician1 = User.objects.create_user(
            email="tech1.audit@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Ramesh",
            last_name="Kumar",
        )
        self.technician2 = User.objects.create_user(
            email="tech2.audit@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Suresh",
            last_name="Patil",
        )
        self.customer_user = User.objects.create_user(
            email="client.audit@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Anil",
            last_name="Sharma",
        )

        # Create business domain entities
        self.customer = Customer.objects.create(
            user=self.customer_user,
            company_name="Apex Healthcare Ltd",
            primary_contact_name="Anil Sharma",
            email="client.audit@fsm.com",
            phone="+919876543210",
            billing_address="Bandra Kurla Complex, Mumbai",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Apex Mumbai HQ",
            address_line1="BKC Central",
            city="Mumbai",
            state="Maharashtra",
            postal_code="400051",
            is_primary=True,
        )
        self.category = ServiceCategory.objects.create(
            name="HVAC Maintenance",
            code="HVAC",
        )
        self.service_type = ServiceType.objects.create(
            category=self.category,
            name="Chiller Annual Overhaul",
            code="CHILL-OVERHAUL",
            estimated_duration_minutes=180,
            base_price=Decimal("15000.00"),
        )

    def test_audit_log_service_record_directly(self):
        """Verify AuditLogService creates log entries accurately."""
        log = AuditLogService.record(
            action=AuditAction.GENERAL_ACTION,
            entity_type="system_config",
            entity_id=uuid.uuid4(),
            entity_repr="CONFIG-001",
            description="System configuration updated manually.",
            changes={"timeout": {"old": 30, "new": 60}},
            actor=self.admin,
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.actor_email, self.admin.email)
        self.assertEqual(log.actor_role, UserRole.ADMIN)
        self.assertEqual(log.action, AuditAction.GENERAL_ACTION)
        self.assertEqual(log.changes["timeout"]["new"], 60)

    def test_work_order_created_signal(self):
        """Creating a WorkOrder automatically generates a WORK_ORDER_CREATED audit log."""
        initial_count = AuditLog.objects.filter(action=AuditAction.WORK_ORDER_CREATED).count()
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Inspect Chiller Unit 1",
            priority=WorkOrderPriority.HIGH,
            status=WorkOrderStatus.DRAFT,
        )
        new_count = AuditLog.objects.filter(
            action=AuditAction.WORK_ORDER_CREATED,
            entity_id=wo.id,
        ).count()
        self.assertEqual(new_count, 1)

        log = AuditLog.objects.get(
            action=AuditAction.WORK_ORDER_CREATED,
            entity_id=wo.id,
        )
        self.assertEqual(log.entity_type, "work_order")
        self.assertEqual(log.entity_repr, wo.work_order_number)
        self.assertEqual(log.changes["status"]["new"], WorkOrderStatus.DRAFT)

    def test_work_order_status_change_signal(self):
        """Updating WorkOrder status creates a WORK_ORDER_STATUS_CHANGED audit entry with diff."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Inspect Chiller Unit 2",
            priority=WorkOrderPriority.MEDIUM,
            status=WorkOrderStatus.SCHEDULED,
        )
        wo.status = WorkOrderStatus.IN_PROGRESS
        wo.save()

        log = AuditLog.objects.filter(
            action=AuditAction.WORK_ORDER_STATUS_CHANGED,
            entity_id=wo.id,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["status"]["old"], WorkOrderStatus.SCHEDULED)
        self.assertEqual(log.changes["status"]["new"], WorkOrderStatus.IN_PROGRESS)

    def test_work_order_technician_assignment_signal(self):
        """Assigning/reassigning a technician creates a WORK_ORDER_ASSIGNED audit log."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Inspect Chiller Unit 3",
            priority=WorkOrderPriority.CRITICAL,
            status=WorkOrderStatus.SCHEDULED,
            assigned_technician=self.technician1,
        )

        wo.assigned_technician = self.technician2
        wo.save()

        log = AuditLog.objects.filter(
            action=AuditAction.WORK_ORDER_ASSIGNED,
            entity_id=wo.id,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes["assigned_technician"]["old"], str(self.technician1.id))
        self.assertEqual(log.changes["assigned_technician"]["new"], str(self.technician2.id))

    def test_service_request_created_signal(self):
        """Creating a ServiceRequest generates a SERVICE_REQUEST_CREATED audit log."""
        sr = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="AC Not Cooling in ICU",
            description="Temperature rising rapidly in server room.",
            priority=RequestPriority.CRITICAL,
        )
        log = AuditLog.objects.filter(
            action=AuditAction.SERVICE_REQUEST_CREATED,
            entity_id=sr.id,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.entity_type, "service_request")
        self.assertEqual(log.entity_repr, sr.request_number)

    def test_invoice_and_payment_signals(self):
        """Invoice issue and Payment creation generate respective audit logs."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Chiller overhaul completed",
            priority=WorkOrderPriority.MEDIUM,
            status=WorkOrderStatus.COMPLETED,
        )
        inv = Invoice.objects.create(
            work_order=wo,
            customer=self.customer,
            labor_amount=Decimal("2000.00"),
            parts_amount=Decimal("3000.00"),
            service_amount=Decimal("15000.00"),
            total_amount=Decimal("20000.00"),
            status=InvoiceStatus.DRAFT,
        )
        inv.status = InvoiceStatus.ISSUED
        inv.save()

        inv_log = AuditLog.objects.filter(
            action=AuditAction.INVOICE_ISSUED,
            entity_id=inv.id,
        ).first()
        self.assertIsNotNone(inv_log)

        # Payment signal
        pmt = Payment.objects.create(
            invoice=inv,
            amount=Decimal("20000.00"),
            payment_method=PaymentMethod.BANK_TRANSFER,
            transaction_reference="NEFT-998877",
        )
        pmt_log = AuditLog.objects.filter(
            action=AuditAction.PAYMENT_RECORDED,
            entity_id=pmt.id,
        ).first()
        self.assertIsNotNone(pmt_log)
        self.assertEqual(pmt_log.changes["amount"]["new"], "20000.00")

    def test_rbac_admin_and_manager_access(self):
        """ADMIN and MANAGER can list and retrieve audit logs."""
        # Create an audit entry
        AuditLogService.record(
            action=AuditAction.GENERAL_ACTION,
            entity_type="work_order",
            entity_id=uuid.uuid4(),
            description="Testing RBAC list access",
            actor=self.admin,
        )

        # Admin access
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Manager access
        self.client.force_authenticate(user=self.manager)
        res = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_rbac_technician_and_customer_denied(self):
        """TECHNICIAN and CUSTOMER receive 403 Forbidden on audit logs."""
        self.client.force_authenticate(user=self.technician1)
        res = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.customer_user)
        res = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Unauthenticated receives 401
        self.client.force_authenticate(user=None)
        res = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_immutability_enforced(self):
        """Audit logs cannot be created, modified, or deleted via the API."""
        log = AuditLogService.record(
            action=AuditAction.GENERAL_ACTION,
            entity_type="work_order",
            entity_id=uuid.uuid4(),
            description="Testing immutability",
            actor=self.admin,
        )
        self.client.force_authenticate(user=self.admin)

        # POST not allowed
        res_post = self.client.post("/api/v1/audit-logs/", {"action": "TEST"})
        self.assertEqual(res_post.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # PUT not allowed
        res_put = self.client.put(f"/api/v1/audit-logs/{log.id}/", {"description": "Hacked"})
        self.assertEqual(res_put.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # PATCH not allowed
        res_patch = self.client.patch(f"/api/v1/audit-logs/{log.id}/", {"description": "Hacked"})
        self.assertEqual(res_patch.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # DELETE not allowed
        res_delete = self.client.delete(f"/api/v1/audit-logs/{log.id}/")
        self.assertEqual(res_delete.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_timeline_endpoint(self):
        """Timeline endpoint returns ordered event trail for a specific entity."""
        target_id = uuid.uuid4()

        AuditLogService.record(
            action=AuditAction.WORK_ORDER_CREATED,
            entity_type="work_order",
            entity_id=target_id,
            description="Work order created",
            actor=self.admin,
        )
        AuditLogService.record(
            action=AuditAction.WORK_ORDER_STATUS_CHANGED,
            entity_type="work_order",
            entity_id=target_id,
            description="Work order started",
            actor=self.admin,
        )

        self.client.force_authenticate(user=self.admin)
        res = self.client.get(f"/api/v1/audit-logs/timeline/?entity_type=work_order&entity_id={target_id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total_events"], 2)
        self.assertEqual(len(res.data["timeline"]), 2)
        self.assertEqual(res.data["timeline"][0]["action"], AuditAction.WORK_ORDER_CREATED)
        self.assertEqual(res.data["timeline"][1]["action"], AuditAction.WORK_ORDER_STATUS_CHANGED)

        # Missing query parameters returns 400
        res_bad = self.client.get("/api/v1/audit-logs/timeline/")
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)
