import datetime
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.billing.models import Invoice, InvoiceStatus, PaymentMethod
from apps.contracts.models import ContractStatus, ServiceContract, ServiceFrequency
from apps.customers.models import Customer, ServiceLocation
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderStatus

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="portal_admin@fsm.com",
        password="Password123!",
        first_name="Admin",
        last_name="Portal",
        role=UserRole.ADMIN,
    )


@pytest.fixture
def technician_user(db):
    return User.objects.create_user(
        email="portal_tech@fsm.com",
        password="Password123!",
        first_name="Ramesh",
        last_name="Sharma",
        role=UserRole.TECHNICIAN,
        phone_number="+919877788899",
    )


@pytest.fixture
def customer_user_a(db):
    return User.objects.create_user(
        email="client_apex@fsm.com",
        password="Password123!",
        first_name="Mohan",
        last_name="Verma",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def customer_user_b(db):
    return User.objects.create_user(
        email="client_fortis@fsm.com",
        password="Password123!",
        first_name="Dr. Anil",
        last_name="Kapoor",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def customer_a_setup(db, customer_user_a):
    customer = Customer.objects.create(
        user=customer_user_a,
        primary_contact_name="Mohan Verma",
        company_name="Apex Super Specialty Hospital",
        email="client_apex@fsm.com",
        phone="+919822334455",
        billing_address="Plot 45, Sector 12, Whitefield, Bengaluru",
        tax_id="29AABCA1234F1Z9",
    )
    location = ServiceLocation.objects.create(
        customer=customer,
        location_name="Whitefield ICU Campus",
        address_line1="Plot 45, Sector 12",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560066",
        is_primary=True,
    )
    return customer, location


@pytest.fixture
def customer_b_setup(db, customer_user_b):
    customer = Customer.objects.create(
        user=customer_user_b,
        primary_contact_name="Dr. Anil Kapoor",
        company_name="Fortis Healthcare",
        email="client_fortis@fsm.com",
        phone="+919811998877",
        billing_address="Sector 62, Phase 8, Mohali",
        tax_id="03AAACF1234A1Z7",
    )
    location = ServiceLocation.objects.create(
        customer=customer,
        location_name="Mohali Main Block",
        address_line1="Sector 62, Phase 8",
        city="Mohali",
        state="Punjab",
        postal_code="160062",
        is_primary=True,
    )
    return customer, location


@pytest.fixture
def service_type(db):
    cat = ServiceCategory.objects.create(name="HVAC Services", code="HVAC-PORTAL")
    return ServiceType.objects.create(
        category=cat,
        name="Commercial Central AC Overhaul",
        code="AC-COMM-PORTAL",
        base_price=Decimal("5000.00"),
    )


@pytest.fixture
def customer_a_full_data(db, customer_a_setup, service_type, technician_user, admin_user):
    customer, location = customer_a_setup
    today = timezone.localdate()

    # 1. Open Ticket
    req = ServiceRequest.objects.create(
        customer=customer,
        service_location=location,
        service_type=service_type,
        title="ICU AC Cooling Ineffective",
        description="Temperature fluctuating between 24C and 28C",
        priority=RequestPriority.HIGH,
        status=RequestStatus.IN_PROGRESS,
        reported_by=customer.user,
    )

    # 2. Active Work Order (In Progress with live tracking data)
    wo = WorkOrder.objects.create(
        customer=customer,
        service_location=location,
        service_type=service_type,
        service_request=req,
        assigned_technician=technician_user,
        title="Emergency Chiller Repair",
        status=WorkOrderStatus.ARRIVED,
        priority="HIGH",
        scheduled_start=timezone.now() - datetime.timedelta(hours=2),
        scheduled_end=timezone.now() + datetime.timedelta(hours=1),
        travel_started_at=timezone.now() - datetime.timedelta(hours=1, minutes=30),
        arrived_at=timezone.now() - datetime.timedelta(minutes=45),
        actual_start=timezone.now() - datetime.timedelta(minutes=30),
    )

    # 3. Completed Work Order (Ready for feedback)
    completed_wo = WorkOrder.objects.create(
        customer=customer,
        service_location=location,
        service_type=service_type,
        assigned_technician=technician_user,
        title="Quarterly Preventive Inspection",
        status=WorkOrderStatus.COMPLETED,
        priority="MEDIUM",
        scheduled_start=timezone.now() - datetime.timedelta(days=2),
        scheduled_end=timezone.now() - datetime.timedelta(days=2, hours=-2),
        actual_start=timezone.now() - datetime.timedelta(days=2),
        actual_end=timezone.now() - datetime.timedelta(days=2, hours=-2),
        labor_hours=Decimal("2.00"),
        service_summary="Replaced condenser coil filter, system operating at 18C normally.",
        customer_signature="data:image/png;base64,iVBORw0KGgo...",
        signed_by_name="Mohan Verma",
        signed_at=timezone.now() - datetime.timedelta(days=2, hours=-2),
    )

    # 4. Active AMC Contract
    contract = ServiceContract.objects.create(
        contract_number="CNT-2026-APEX-01",
        title="Annual Central Chiller & HVAC Maintenance (AMC)",
        customer=customer,
        service_location=location,
        start_date=today - datetime.timedelta(days=60),
        end_date=today + datetime.timedelta(days=305),
        status=ContractStatus.ACTIVE,
        service_frequency=ServiceFrequency.QUARTERLY,
        total_visits_allowed=4,
        visits_used=1,
        contract_value=Decimal("80000.00"),
        next_scheduled_date=today + datetime.timedelta(days=30),
    )
    contract.covered_services.add(service_type)

    # 5. Issued Invoice
    invoice = Invoice.objects.create(
        invoice_number="INV-20260928-APEX01",
        work_order=completed_wo,
        customer=customer,
        status=InvoiceStatus.ISSUED,
        issue_date=today,
        due_date=today + datetime.timedelta(days=15),
        labor_amount=Decimal("1000.00"),
        parts_amount=Decimal("0.00"),
        service_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        tax_rate=Decimal("18.00"),
        tax_amount=Decimal("180.00"),
        total_amount=Decimal("1180.00"),
        notes="Invoice for Quarterly Preventive Inspection",
        created_by=admin_user,
    )

    return {
        "customer": customer,
        "location": location,
        "request": req,
        "active_work_order": wo,
        "completed_work_order": completed_wo,
        "contract": contract,
        "invoice": invoice,
    }


# =========================================================================
# Tests
# =========================================================================

@pytest.mark.django_db
class TestCustomerPortalDashboard:
    def test_customer_dashboard_metrics(self, api_client, customer_user_a, customer_a_full_data):
        """
        Verify aggregated customer dashboard provides accurate live stats.
        """
        api_client.force_authenticate(user=customer_user_a)
        res = api_client.get("/api/v1/portal/dashboard/")

        assert res.status_code == status.HTTP_200_OK
        data = res.data

        assert data["customer"]["company_name"] == "Apex Super Specialty Hospital"
        assert data["open_requests_count"] == 1
        assert data["active_work_orders_count"] == 1
        assert data["active_contracts_count"] == 1
        assert data["visits_remaining_total"] == 3  # 4 allowed - 1 used
        assert data["outstanding_invoices_count"] == 1
        assert Decimal(str(data["total_balance_due"])) == Decimal("1180.00")
        assert len(data["recent_work_orders"]) >= 1
        assert len(data["recent_requests"]) >= 1

    def test_technician_blocked_from_portal(self, api_client, technician_user):
        """
        Field technicians cannot access the customer self-service portal.
        """
        api_client.force_authenticate(user=technician_user)
        res = api_client.get("/api/v1/portal/dashboard/")
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestCustomerTicketing:
    def test_customer_can_raise_service_request(self, api_client, customer_user_a, customer_a_setup, service_type):
        customer, location = customer_a_setup
        api_client.force_authenticate(user=customer_user_a)

        payload = {
            "service_location": str(location.id),
            "service_type": str(service_type.id),
            "title": "Operation Theater Chiller Overheating",
            "description": "Alarm buzzer sounding in OT-3, immediate check needed.",
            "priority": "CRITICAL",
        }
        res = api_client.post("/api/v1/portal/requests/", payload, format="json")

        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["title"] == payload["title"]
        assert res.data["status"] == "NEW"
        assert res.data["service_location_name"] == location.location_name
        assert res.data["request_number"].startswith("SR-")

    def test_cross_tenant_location_injection_rejected(self, api_client, customer_user_a, customer_a_setup, customer_b_setup):
        """
        Customer A cannot raise a request specifying Customer B's location.
        """
        _, location_b = customer_b_setup
        api_client.force_authenticate(user=customer_user_a)

        payload = {
            "service_location": str(location_b.id),
            "title": "Malicious Request at Other Facility",
            "description": "Trying to book on another hospital's branch.",
        }
        res = api_client.post("/api/v1/portal/requests/", payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "service_location" in res.data


@pytest.mark.django_db
class TestLiveJobTrackingAndFeedback:
    def test_live_tracking_endpoint(self, api_client, customer_user_a, customer_a_full_data):
        active_wo = customer_a_full_data["active_work_order"]
        api_client.force_authenticate(user=customer_user_a)

        res = api_client.get(f"/api/v1/portal/work-orders/{active_wo.id}/track/")
        assert res.status_code == status.HTTP_200_OK

        data = res.data
        assert data["work_order_number"] == active_wo.work_order_number
        assert data["current_stage"] == "ARRIVED_ON_SITE"
        assert not data["is_completed"]
        assert data["technician"]["name"] == "Ramesh Sharma"
        assert data["technician"]["phone"] == "+919877788899"
        assert data["location"]["name"] == "Whitefield ICU Campus"
        assert data["timeline"]["arrived_at"] is not None

    def test_submit_feedback_and_star_rating(self, api_client, customer_user_a, customer_a_full_data):
        completed_wo = customer_a_full_data["completed_work_order"]
        api_client.force_authenticate(user=customer_user_a)

        feedback_payload = {
            "rating": 5,
            "feedback": "Outstanding prompt service! Ramesh resolved the cooling issue perfectly.",
        }
        res = api_client.post(
            f"/api/v1/portal/work-orders/{completed_wo.id}/feedback/",
            feedback_payload,
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["customer_rating"] == 5
        assert res.data["customer_feedback"] == feedback_payload["feedback"]

        completed_wo.refresh_from_db()
        assert completed_wo.customer_rating == 5

    def test_cannot_submit_feedback_for_uncompleted_work_order(self, api_client, customer_user_a, customer_a_full_data):
        active_wo = customer_a_full_data["active_work_order"]
        api_client.force_authenticate(user=customer_user_a)

        res = api_client.post(
            f"/api/v1/portal/work-orders/{active_wo.id}/feedback/",
            {"rating": 4, "feedback": "Good job so far"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "COMPLETED" in res.data["detail"]

    def test_invalid_star_rating_rejected(self, api_client, customer_user_a, customer_a_full_data):
        completed_wo = customer_a_full_data["completed_work_order"]
        api_client.force_authenticate(user=customer_user_a)

        # 6 stars should fail (valid is 1 to 5)
        res = api_client.post(
            f"/api/v1/portal/work-orders/{completed_wo.id}/feedback/",
            {"rating": 6, "feedback": "Super extra"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCustomerContractsAndBillingSelfService:
    def test_customer_views_amc_contracts_and_quota(self, api_client, customer_user_a, customer_a_full_data):
        api_client.force_authenticate(user=customer_user_a)
        res = api_client.get("/api/v1/portal/contracts/")
        assert res.status_code == status.HTTP_200_OK

        results = res.data.get("results", res.data)
        assert len(results) == 1
        contract_data = results[0]
        assert contract_data["contract_number"] == "CNT-2026-APEX-01"
        assert contract_data["total_visits_allowed"] == 4
        assert contract_data["visits_used"] == 1
        assert contract_data["visits_remaining"] == 3
        assert len(contract_data["covered_services"]) >= 1

    def test_customer_self_service_payment(self, api_client, customer_user_a, customer_a_full_data):
        invoice = customer_a_full_data["invoice"]
        api_client.force_authenticate(user=customer_user_a)

        # 1. View Invoice
        inv_res = api_client.get(f"/api/v1/portal/invoices/{invoice.id}/")
        assert inv_res.status_code == status.HTTP_200_OK
        assert inv_res.data["balance_due"] == "1180.00"

        # 2. Pay via UPI
        pay_res = api_client.post(
            f"/api/v1/portal/invoices/{invoice.id}/pay/",
            {
                "amount": "1180.00",
                "payment_method": PaymentMethod.UPI,
                "transaction_reference": "UPI/PORTAL/2026/001",
                "notes": "Paid by Mohan via Google Pay on Customer Portal",
            },
            format="json",
        )
        assert pay_res.status_code == status.HTTP_201_CREATED
        assert pay_res.data["status"] == "PAID"
        assert pay_res.data["balance_due"] == "0.00"
        assert pay_res.data["is_fully_paid"] is True


@pytest.mark.django_db
class TestCustomerTenantIsolation:
    def test_customer_b_cannot_see_customer_a_records(
        self, api_client, customer_user_b, customer_b_setup, customer_a_full_data
    ):
        """
        Verify complete multi-tenant wall: Customer B sees none of Customer A's
        requests, work orders, contracts, or invoices.
        """
        api_client.force_authenticate(user=customer_user_b)

        # Requests
        req_res = api_client.get("/api/v1/portal/requests/")
        assert len(req_res.data.get("results", req_res.data)) == 0

        # Work Orders
        wo_res = api_client.get("/api/v1/portal/work-orders/")
        assert len(wo_res.data.get("results", wo_res.data)) == 0

        # Contracts
        cnt_res = api_client.get("/api/v1/portal/contracts/")
        assert len(cnt_res.data.get("results", cnt_res.data)) == 0

        # Invoices
        inv_res = api_client.get("/api/v1/portal/invoices/")
        assert len(inv_res.data.get("results", inv_res.data)) == 0
