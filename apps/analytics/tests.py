from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentMethod
from apps.customers.models import Customer, ServiceLocation
from apps.inventory.models import Part, UnitOfMeasure, Warehouse, WorkOrderPart, WorkOrderPartStatus
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class AnalyticsEngineTests(APITestCase):
    def setUp(self):
        # 1. Users
        self.admin = User.objects.create_user(
            email="admin.analytics@fsm.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            first_name="Admin",
            last_name="Leader",
        )
        self.manager = User.objects.create_user(
            email="manager.analytics@fsm.com",
            password="ManagerPassword123!",
            role=UserRole.MANAGER,
            first_name="Operations",
            last_name="Manager",
        )
        self.technician = User.objects.create_user(
            email="tech.analytics@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Ravi",
            last_name="Kumar",
        )
        self.customer_user = User.objects.create_user(
            email="client.analytics@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Sanjay",
            last_name="Singhania",
        )

        # 2. Customer and Location
        self.customer = Customer.objects.create(
            user=self.customer_user,
            company_name="Max Super Specialty Hospital",
            primary_contact_name="Sanjay Singhania",
            email="client.analytics@fsm.com",
            phone="+919876543210",
            billing_address="Saket, New Delhi",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Max Saket Tower A",
            address_line1="1 Press Enclave Road",
            city="New Delhi",
            state="Delhi",
            postal_code="110017",
            is_primary=True,
        )

        # 3. Services
        self.category = ServiceCategory.objects.create(
            name="Medical Gas Pipeline",
            code="MED-GAS",
        )
        self.service_type = ServiceType.objects.create(
            category=self.category,
            name="Oxygen Pipeline Annual Audit",
            code="O2-AUDIT",
            estimated_duration_minutes=120,
            base_price=Decimal("12000.00"),
        )

        # 4. Service Request
        self.request = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Oxygen Pressure Fluctuations in ICU",
            description="Critical oxygen pressure drops observed on ventilator lines in ICU.",
            priority=RequestPriority.CRITICAL,
            status=RequestStatus.COMPLETED,
            reviewed_at=timezone.now() - timedelta(hours=1),
            sla_response_due_at=timezone.now() + timedelta(hours=1),
            sla_resolution_due_at=timezone.now() + timedelta(hours=4),
        )

        # 5. Work Order
        self.work_order = WorkOrder.objects.create(
            service_request=self.request,
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            assigned_technician=self.technician,
            title="ICU O2 Pressure Calibration",
            priority=WorkOrderPriority.CRITICAL,
            status=WorkOrderStatus.COMPLETED,
            labor_hours=Decimal("2.50"),
            actual_start=timezone.now() - timedelta(hours=3),
            actual_end=timezone.now() - timedelta(minutes=30),
        )

        # 6. Invoice and Payment
        self.invoice = Invoice.objects.create(
            work_order=self.work_order,
            customer=self.customer,
            status=InvoiceStatus.ISSUED,
            issue_date=timezone.localdate(),
            labor_amount=Decimal("2500.00"),
            parts_amount=Decimal("3500.00"),
            service_amount=Decimal("12000.00"),
            tax_rate=Decimal("18.00"),
            tax_amount=Decimal("3240.00"),
            total_amount=Decimal("21240.00"),
        )
        self.payment = Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("10000.00"),
            payment_method=PaymentMethod.BANK_TRANSFER,
            transaction_reference="NEFT-MAX-001",
        )

        # 7. Inventory
        self.part = Part.objects.create(
            name="High Pressure Regulator Valve",
            sku="REG-VALVE-01",
            unit_of_measure=UnitOfMeasure.PIECE,
            cost_price=Decimal("1500.00"),
            selling_price=Decimal("3500.00"),
            reorder_threshold=5,
        )
        self.warehouse = Warehouse.objects.create(
            name="Delhi Central Depo",
            code="WH-DEL-01",
            city="New Delhi",
        )
        self.wo_part = WorkOrderPart.objects.create(
            work_order=self.work_order,
            part=self.part,
            quantity=1,
            unit_price=Decimal("3500.00"),
            status=WorkOrderPartStatus.CONSUMED,
        )

    def test_executive_overview_endpoint(self):
        """Admin can fetch high-level executive KPI overview."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/analytics/overview/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn("period", res.data)
        self.assertIn("work_orders", res.data)
        self.assertIn("finances", res.data)
        self.assertIn("sla", res.data)

        self.assertGreaterEqual(res.data["work_orders"]["total"], 1)
        self.assertGreaterEqual(res.data["work_orders"]["completed"], 1)
        self.assertEqual(res.data["finances"]["total_billed"], 21240.0)
        self.assertEqual(res.data["finances"]["total_collected"], 10000.0)
        self.assertEqual(res.data["finances"]["outstanding_receivables"], 11240.0)

    def test_revenue_analytics_endpoint(self):
        """Manager can fetch deep financial analysis."""
        self.client.force_authenticate(user=self.manager)
        res = self.client.get("/api/v1/analytics/revenue/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn("totals", res.data)
        self.assertIn("by_service_category", res.data)
        self.assertIn("top_customers", res.data)
        self.assertIn("monthly_trend", res.data)

        self.assertEqual(res.data["totals"]["total_billed"], 21240.0)
        self.assertEqual(len(res.data["by_service_category"]), 1)
        self.assertEqual(res.data["by_service_category"][0]["category_name"], "Medical Gas Pipeline")
        self.assertEqual(res.data["top_customers"][0]["customer_name"], "Max Super Specialty Hospital")

    def test_technician_productivity_endpoint(self):
        """Admin can fetch technician scorecard and utilization metrics."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/analytics/technicians/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn("summary", res.data)
        self.assertIn("technicians", res.data)
        self.assertGreaterEqual(len(res.data["technicians"]), 1)

        tech_metric = next(t for t in res.data["technicians"] if t["technician_id"] == str(self.technician.id))
        self.assertEqual(tech_metric["jobs_assigned"], 1)
        self.assertEqual(tech_metric["jobs_completed"], 1)
        self.assertEqual(tech_metric["first_time_fix_rate_pct"], 100.0)
        self.assertEqual(tech_metric["total_labor_hours"], 2.5)

    def test_sla_compliance_endpoint(self):
        """Admin can view response and resolution SLA compliance."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/analytics/sla/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn("summary", res.data)
        self.assertIn("by_priority", res.data)
        self.assertGreaterEqual(res.data["summary"]["total_tickets"], 1)
        self.assertGreaterEqual(res.data["summary"]["total_resolved"], 1)

    def test_inventory_analytics_endpoint(self):
        """Admin can view parts consumption trends."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.get("/api/v1/analytics/inventory/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn("summary", res.data)
        self.assertIn("top_consumed_parts", res.data)
        self.assertGreaterEqual(res.data["summary"]["total_units_consumed"], 1)
        self.assertEqual(res.data["summary"]["total_valuation_consumed"], 3500.0)
        self.assertEqual(res.data["top_consumed_parts"][0]["sku"], "REG-VALVE-01")

    def test_csv_export_endpoint(self):
        """Managers can download streaming CSV reports."""
        self.client.force_authenticate(user=self.manager)

        # 1. Work Orders export
        res_wo = self.client.get("/api/v1/analytics/export/?report_type=work_orders")
        self.assertEqual(res_wo.status_code, status.HTTP_200_OK)
        self.assertEqual(res_wo["Content-Type"], "text/csv")
        self.assertIn("Work Order Number", res_wo.content.decode("utf-8"))
        self.assertIn(self.work_order.work_order_number, res_wo.content.decode("utf-8"))

        # 2. Revenue export
        res_rev = self.client.get("/api/v1/analytics/export/?report_type=revenue")
        self.assertEqual(res_rev.status_code, status.HTTP_200_OK)
        self.assertEqual(res_rev["Content-Type"], "text/csv")
        self.assertIn(self.invoice.invoice_number, res_rev.content.decode("utf-8"))

        # 3. Technicians export
        res_tech = self.client.get("/api/v1/analytics/export/?report_type=technicians")
        self.assertEqual(res_tech.status_code, status.HTTP_200_OK)
        self.assertIn("Ravi Kumar", res_tech.content.decode("utf-8"))

        # 4. Invalid report type returns 400
        res_bad = self.client.get("/api/v1/analytics/export/?report_type=invalid_type")
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_date_range_filtering(self):
        """Analytics endpoints support time_frame and explicit start/end dates."""
        self.client.force_authenticate(user=self.admin)

        res_today = self.client.get("/api/v1/analytics/overview/?time_frame=today")
        self.assertEqual(res_today.status_code, status.HTTP_200_OK)

        res_custom = self.client.get("/api/v1/analytics/overview/?start_date=2026-09-01&end_date=2026-09-30")
        self.assertEqual(res_custom.status_code, status.HTTP_200_OK)
        self.assertEqual(res_custom.data["period"]["start_date"], "2026-09-01")
        self.assertEqual(res_custom.data["period"]["end_date"], "2026-09-30")

    def test_rbac_technicians_and_customers_denied(self):
        """Non-management roles are forbidden from accessing business analytics."""
        endpoints = [
            "/api/v1/analytics/overview/",
            "/api/v1/analytics/revenue/",
            "/api/v1/analytics/technicians/",
            "/api/v1/analytics/sla/",
            "/api/v1/analytics/inventory/",
            "/api/v1/analytics/export/?report_type=work_orders",
        ]

        for ep in endpoints:
            # Technician gets 403
            self.client.force_authenticate(user=self.technician)
            res_tech = self.client.get(ep)
            self.assertEqual(res_tech.status_code, status.HTTP_403_FORBIDDEN)

            # Customer gets 403
            self.client.force_authenticate(user=self.customer_user)
            res_cust = self.client.get(ep)
            self.assertEqual(res_cust.status_code, status.HTTP_403_FORBIDDEN)

            # Unauthenticated gets 401
            self.client.force_authenticate(user=None)
            res_anon = self.client.get(ep)
            self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)
