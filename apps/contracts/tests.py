import datetime
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.contracts.models import ContractStatus, ServiceContract, ServiceFrequency
from apps.contracts.services import ContractService
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderStatus

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="test_admin_cnt@fsm.com",
        password="Password123!",
        first_name="Admin",
        last_name="Boss",
        role=UserRole.ADMIN,
    )


@pytest.fixture
def dispatcher_user(db):
    return User.objects.create_user(
        email="test_disp_cnt@fsm.com",
        password="Password123!",
        first_name="Vikram",
        last_name="Malhotra",
        role=UserRole.DISPATCHER,
    )


@pytest.fixture
def technician_ramesh(db):
    return User.objects.create_user(
        email="test_ramesh_cnt@fsm.com",
        password="Password123!",
        first_name="Ramesh",
        last_name="Sharma",
        role=UserRole.TECHNICIAN,
    )


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="client_apex@fsm.com",
        password="Password123!",
        first_name="Mohan",
        last_name="Verma",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def customer_and_location(db, customer_user):
    customer = Customer.objects.create(
        user=customer_user,
        primary_contact_name="Mohan Verma",
        company_name="Apex Healthcare Ltd",
        email="apex@hospital.com",
        phone="+919811122233",
    )
    location = ServiceLocation.objects.create(
        customer=customer,
        location_name="Cardiology ICU Block",
        address_line1="Whitefield Campus",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560066",
        latitude=Decimal("12.969800"),
        longitude=Decimal("77.749900"),
        is_primary=True,
    )
    return customer, location


@pytest.fixture
def service_type_hvac(db):
    category = ServiceCategory.objects.create(
        name="HVAC & Cooling",
        code="HVAC-TEST",
    )
    return ServiceType.objects.create(
        category=category,
        name="Chiller Periodic Overhaul",
        code="CHILLER-OVERHAUL",
        base_price=Decimal("4500.00"),
    )


@pytest.fixture
def active_contract(db, customer_and_location, service_type_hvac, admin_user):
    customer, location = customer_and_location
    today = timezone.localdate()
    contract = ServiceContract.objects.create(
        title="Annual Chiller Preventive AMC",
        customer=customer,
        service_location=location,
        start_date=today,
        end_date=today + datetime.timedelta(days=365),
        status=ContractStatus.ACTIVE,
        service_frequency=ServiceFrequency.QUARTERLY,
        total_visits_allowed=4,
        visits_used=1,
        contract_value=Decimal("50000.00"),
        next_scheduled_date=today + datetime.timedelta(days=90),
        created_by=admin_user,
    )
    contract.covered_services.add(service_type_hvac)
    return contract


# ---------------------------------------------------------
# Test Suite 1: Contract Creation & CRUD
# ---------------------------------------------------------
@pytest.mark.django_db
class TestContractCreationAndCRUD:
    def test_admin_creates_contract_successfully(
        self, api_client, admin_user, customer_and_location, service_type_hvac
    ):
        customer, location = customer_and_location
        api_client.force_authenticate(user=admin_user)
        today = timezone.localdate()

        payload = {
            "title": "Comprehensive Facility AMC",
            "customer": str(customer.id),
            "service_location": str(location.id),
            "covered_services": [str(service_type_hvac.id)],
            "start_date": str(today),
            "end_date": str(today + datetime.timedelta(days=365)),
            "service_frequency": ServiceFrequency.QUARTERLY,
            "total_visits_allowed": 4,
            "contract_value": "48000.00",
            "sla_response_hours": 12,
        }
        res = api_client.post("/api/v1/contracts/", payload)
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["contract_number"].startswith("CNT-")
        assert res.data["status"] == ContractStatus.DRAFT
        assert res.data["total_visits_allowed"] == 4

    def test_invalid_dates_rejected(self, api_client, admin_user, customer_and_location):
        customer, location = customer_and_location
        api_client.force_authenticate(user=admin_user)
        today = timezone.localdate()

        payload = {
            "title": "Invalid Date Contract",
            "customer": str(customer.id),
            "service_location": str(location.id),
            "start_date": str(today),
            "end_date": str(today - datetime.timedelta(days=10)),  # Past end date
            "service_frequency": ServiceFrequency.QUARTERLY,
        }
        res = api_client.post("/api/v1/contracts/", payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "end_date" in str(res.data)

    def test_customer_visibility_isolation(
        self, api_client, customer_user, admin_user, active_contract
    ):
        # Customer sees their own contract
        api_client.force_authenticate(user=customer_user)
        res = api_client.get("/api/v1/contracts/")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data["results"]) == 1
        assert res.data["results"][0]["id"] == str(active_contract.id)

        # Another customer sees 0 contracts
        other_user = User.objects.create_user(
            email="other_client@fsm.com",
            password="Password123!",
            role=UserRole.CUSTOMER,
        )
        api_client.force_authenticate(user=other_user)
        res_other = api_client.get("/api/v1/contracts/")
        assert res_other.status_code == status.HTTP_200_OK
        assert len(res_other.data["results"]) == 0


# ---------------------------------------------------------
# Test Suite 2: Contract Lifecycle (Activate / Terminate)
# ---------------------------------------------------------
@pytest.mark.django_db
class TestContractLifecycle:
    def test_activate_draft_contract(self, api_client, admin_user, customer_and_location):
        customer, location = customer_and_location
        today = timezone.localdate()
        draft_contract = ServiceContract.objects.create(
            title="Draft Contract",
            customer=customer,
            service_location=location,
            start_date=today,
            end_date=today + datetime.timedelta(days=180),
            status=ContractStatus.DRAFT,
            created_by=admin_user,
        )

        api_client.force_authenticate(user=admin_user)
        res = api_client.post(f"/api/v1/contracts/{draft_contract.id}/activate/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == ContractStatus.ACTIVE
        assert res.data["next_scheduled_date"] is not None

    def test_terminate_contract_requires_reason(self, api_client, admin_user, active_contract):
        api_client.force_authenticate(user=admin_user)

        # Missing reason fails
        res_fail = api_client.post(f"/api/v1/contracts/{active_contract.id}/terminate/", {})
        assert res_fail.status_code == status.HTTP_400_BAD_REQUEST

        # Valid reason terminates
        res = api_client.post(
            f"/api/v1/contracts/{active_contract.id}/terminate/",
            {"reason": "Facility decommissioned by client"},
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == ContractStatus.TERMINATED
        assert res.data["termination_reason"] == "Facility decommissioned by client"


# ---------------------------------------------------------
# Test Suite 3: Preventive Work Order Generation & Quota
# ---------------------------------------------------------
@pytest.mark.django_db
class TestPreventiveWorkOrderGeneration:
    def test_generate_preventive_work_order_and_quota_consumption(
        self, api_client, dispatcher_user, technician_ramesh, active_contract, service_type_hvac
    ):
        api_client.force_authenticate(user=dispatcher_user)

        # 1. Dispatch preventive maintenance work order
        gen_payload = {
            "assigned_technician_id": str(technician_ramesh.id),
            "service_type_id": str(service_type_hvac.id),
            "job_instructions": "Check refrigerant pressure and test compressor safety valve.",
        }
        res = api_client.post(
            f"/api/v1/contracts/{active_contract.id}/generate-work-order/", gen_payload
        )
        assert res.status_code == status.HTTP_201_CREATED
        wo_id = res.data["id"]
        assert res.data["is_preventive_maintenance"] is True
        assert str(res.data["service_contract"]) == str(active_contract.id)

        # Contract next_scheduled_date advanced
        active_contract.refresh_from_db()
        assert active_contract.next_scheduled_date > timezone.localdate()

        # 2. Technician accepts and completes the work order
        api_client.force_authenticate(user=technician_ramesh)
        api_client.post(f"/api/v1/work-orders/{wo_id}/accept/")
        api_client.post(f"/api/v1/work-orders/{wo_id}/start-work/")

        complete_payload = {
            "service_summary": "Cleaned evaporator coils, topped up refrigerant, operating normally.",
            "labor_hours": "2.00",
            "customer_signature": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
            "signed_by_name": "Facility Mgr Mohan",
        }
        res_complete = api_client.post(f"/api/v1/work-orders/{wo_id}/complete/", complete_payload)
        assert res_complete.status_code == status.HTTP_200_OK

        # 3. Verify contract visits quota was consumed (+1)
        active_contract.refresh_from_db()
        assert active_contract.visits_used == 2  # was 1 initially, now 2
        assert active_contract.visits_remaining == 2  # 4 - 2 = 2


# ---------------------------------------------------------
# Test Suite 4: Critical Edge Cases (Exhausted / Expired)
# ---------------------------------------------------------
@pytest.mark.django_db
class TestContractEdgeCases:
    def test_exhausted_visits_prevents_work_order_generation(
        self, api_client, dispatcher_user, active_contract
    ):
        # Set visits_used = total_visits_allowed (0 remaining)
        active_contract.visits_used = active_contract.total_visits_allowed
        active_contract.save()

        api_client.force_authenticate(user=dispatcher_user)
        res = api_client.post(f"/api/v1/contracts/{active_contract.id}/generate-work-order/", {})
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "exhausted" in str(res.data).lower()

    def test_expired_contract_prevents_work_order_generation(
        self, api_client, dispatcher_user, active_contract
    ):
        # Set contract end_date in the past
        active_contract.end_date = timezone.localdate() - datetime.timedelta(days=1)
        active_contract.save()

        api_client.force_authenticate(user=dispatcher_user)
        res = api_client.post(f"/api/v1/contracts/{active_contract.id}/generate-work-order/", {})
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired" in str(res.data).lower()
