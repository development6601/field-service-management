import datetime
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentMethod, PaymentStatus
from apps.billing.services import BillingService
from apps.contracts.models import ContractStatus, ServiceContract, ServiceFrequency
from apps.customers.models import Customer, ServiceLocation
from apps.inventory.models import Part, Warehouse, StockItem, WorkOrderPart
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderStatus

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="billing_admin@fsm.com",
        password="Password123!",
        first_name="Admin",
        last_name="Billing",
        role=UserRole.ADMIN,
    )


@pytest.fixture
def manager_user(db):
    return User.objects.create_user(
        email="billing_manager@fsm.com",
        password="Password123!",
        first_name="Finance",
        last_name="Manager",
        role=UserRole.MANAGER,
    )


@pytest.fixture
def dispatcher_user(db):
    return User.objects.create_user(
        email="billing_disp@fsm.com",
        password="Password123!",
        first_name="Vikram",
        last_name="Dispatcher",
        role=UserRole.DISPATCHER,
    )


@pytest.fixture
def technician_user(db):
    return User.objects.create_user(
        email="billing_tech@fsm.com",
        password="Password123!",
        first_name="Ramesh",
        last_name="Tech",
        role=UserRole.TECHNICIAN,
    )


@pytest.fixture
def customer_user(db):
    return User.objects.create_user(
        email="billing_cust@fsm.com",
        password="Password123!",
        first_name="Mohan",
        last_name="Customer",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def other_customer_user(db):
    return User.objects.create_user(
        email="other_cust@fsm.com",
        password="Password123!",
        first_name="Other",
        last_name="Customer",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def customer_and_location(db, customer_user):
    customer = Customer.objects.create(
        user=customer_user,
        primary_contact_name="Mohan Customer",
        company_name="Apex Healthcare Ltd",
        email="billing_cust@fsm.com",
        phone="+919811122233",
        billing_address="123 Hospital Road, Surat",
        tax_id="24AAAAA0000A1Z5",
    )
    location = ServiceLocation.objects.create(
        customer=customer,
        location_name="Main Hospital Building",
        address_line1="123 Hospital Road",
        city="Surat",
        state="Gujarat",
        postal_code="395001",
        is_primary=True,
    )
    return customer, location


@pytest.fixture
def service_type(db):
    category = ServiceCategory.objects.create(
        name="HVAC Services",
        code="HVAC-BILLING",
    )
    return ServiceType.objects.create(
        category=category,
        name="Commercial AC Overhaul",
        code="AC-OVERHAUL-TEST",
        base_price=Decimal("4000.00"),
    )


@pytest.fixture
def completed_work_order(db, customer_and_location, service_type, technician_user):
    customer, location = customer_and_location
    wo = WorkOrder.objects.create(
        customer=customer,
        service_location=location,
        service_type=service_type,
        assigned_technician=technician_user,
        status=WorkOrderStatus.COMPLETED,
        title="Complete AC Maintenance",
        labor_hours=Decimal("2.50"),
        scheduled_start=timezone.now() - datetime.timedelta(hours=4),
        scheduled_end=timezone.now() - datetime.timedelta(hours=1),
    )

    # Attach consumed parts
    warehouse = Warehouse.objects.create(
        name="Main Warehouse",
        code="WH-MAIN-BILLING",
    )
    part = Part.objects.create(
        name="Heavy Air Filter",
        sku="HAF-99",
        selling_price=Decimal("1200.00"),
    )
    StockItem.objects.create(
        part=part,
        warehouse=warehouse,
        quantity_on_hand=50,
    )
    WorkOrderPart.objects.create(
        work_order=wo,
        part=part,
        quantity=2,
        unit_price=Decimal("1200.00"),
        status="CONSUMED",
    )
    return wo


@pytest.fixture
def amc_contract(db, customer_and_location, service_type):
    customer, location = customer_and_location
    today = timezone.localdate()
    return ServiceContract.objects.create(
        title="Comprehensive Annual AC AMC",
        customer=customer,
        service_location=location,
        start_date=today - datetime.timedelta(days=30),
        end_date=today + datetime.timedelta(days=335),
        status=ContractStatus.ACTIVE,
        service_frequency=ServiceFrequency.QUARTERLY,
        total_visits_allowed=4,
        visits_used=1,
        contract_value=Decimal("45000.00"),
    )


@pytest.fixture
def amc_work_order(db, customer_and_location, service_type, technician_user, amc_contract):
    customer, location = customer_and_location
    return WorkOrder.objects.create(
        customer=customer,
        service_location=location,
        service_type=service_type,
        service_contract=amc_contract,
        is_preventive_maintenance=True,
        assigned_technician=technician_user,
        status=WorkOrderStatus.COMPLETED,
        title="Quarterly AMC AC Inspection",
        labor_hours=Decimal("1.50"),
    )


# -------------------------------------------------------------------------
# Test Cases
# -------------------------------------------------------------------------

@pytest.mark.django_db
class TestBillingMathAndGeneration:
    def test_invoice_calculation_standard_job(self, completed_work_order, admin_user):
        """
        Verify: Labor + Parts + Base Service - Discount + Tax = Total Amount
        Labor: 2.5h @ 500 = 1250.00
        Parts: 2 * 1200 = 2400.00
        Service: 4000.00
        Discount: 200.00
        Subtotal: 1250 + 2400 + 4000 - 200 = 7450.00
        Tax (18%): 1341.00
        Total: 8791.00
        """
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            hourly_rate=Decimal("500.00"),
            discount_amount=Decimal("200.00"),
            tax_rate=Decimal("18.00"),
            performed_by=admin_user,
        )

        assert invoice.status == InvoiceStatus.DRAFT
        assert invoice.labor_amount == Decimal("1250.00")
        assert invoice.parts_amount == Decimal("2400.00")
        assert invoice.service_amount == Decimal("4000.00")
        assert invoice.discount_amount == Decimal("200.00")
        assert invoice.subtotal == Decimal("7450.00")
        assert invoice.tax_amount == Decimal("1341.00")
        assert invoice.total_amount == Decimal("8791.00")
        assert invoice.amount_paid == Decimal("0.00")
        assert invoice.balance_due == Decimal("8791.00")
        assert not invoice.is_fully_paid

    def test_invoice_service_fee_waived_under_amc(self, amc_work_order, admin_user):
        """
        If work order is covered under AMC, base service fee must be 0.00.
        Labor: 1.5h @ 500 = 750.00
        Parts: 0.00
        Service: 0.00 (waived!)
        Subtotal: 750.00
        Tax (18%): 135.00
        Total: 885.00
        """
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=amc_work_order,
            performed_by=admin_user,
        )

        assert invoice.service_amount == Decimal("0.00")
        assert invoice.labor_amount == Decimal("750.00")
        assert invoice.subtotal == Decimal("750.00")
        assert invoice.tax_amount == Decimal("135.00")
        assert invoice.total_amount == Decimal("885.00")
        assert "waived under AMC" in invoice.notes

    def test_invoice_generation_idempotency(self, completed_work_order, admin_user):
        """
        Calling invoice generation twice on the same work order returns the existing invoice.
        """
        inv1 = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        inv2 = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        assert inv1.id == inv2.id
        assert Invoice.objects.filter(work_order=completed_work_order).count() == 1

    def test_cannot_generate_invoice_for_uncompleted_work_order(self, db, customer_and_location, service_type):
        customer, location = customer_and_location
        in_progress_wo = WorkOrder.objects.create(
            customer=customer,
            service_location=location,
            service_type=service_type,
            status=WorkOrderStatus.IN_PROGRESS,
            title="Active Unfinished Job",
        )
        with pytest.raises(Exception) as exc:
            BillingService.generate_invoice_from_work_order(work_order=in_progress_wo)
        assert "Only COMPLETED work orders can be billed" in str(exc.value)


@pytest.mark.django_db
class TestInvoiceLifecycleAndPayments:
    def test_issue_invoice(self, completed_work_order, admin_user):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        assert invoice.status == InvoiceStatus.DRAFT

        due_date = timezone.localdate() + datetime.timedelta(days=20)
        issued_invoice = BillingService.issue_invoice(invoice, due_date=due_date, performed_by=admin_user)

        assert issued_invoice.status == InvoiceStatus.ISSUED
        assert issued_invoice.due_date == due_date

    def test_cannot_pay_draft_invoice(self, completed_work_order, admin_user):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        with pytest.raises(Exception) as exc:
            BillingService.record_payment(
                invoice=invoice,
                amount=Decimal("1000.00"),
                recorded_by=admin_user,
            )
        assert "must be officially ISSUED first" in str(exc.value)

    def test_partial_payment_lifecycle(self, completed_work_order, admin_user):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            discount_amount=Decimal("200.00"),
            performed_by=admin_user,
        )
        BillingService.issue_invoice(invoice, performed_by=admin_user)
        total = invoice.total_amount  # 8791.00

        # 1st Payment (Partial)
        p1 = BillingService.record_payment(
            invoice=invoice,
            amount=Decimal("3000.00"),
            payment_method=PaymentMethod.UPI,
            transaction_reference="UPI/2026/001",
            recorded_by=admin_user,
        )
        assert p1.amount == Decimal("3000.00")
        assert p1.payment_status == PaymentStatus.SUCCESS

        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.PARTIALLY_PAID
        assert invoice.amount_paid == Decimal("3000.00")
        assert invoice.balance_due == total - Decimal("3000.00")
        assert not invoice.is_fully_paid

        # 2nd Payment (Full settlement)
        remaining = invoice.balance_due
        p2 = BillingService.record_payment(
            invoice=invoice,
            amount=remaining,
            payment_method=PaymentMethod.BANK_TRANSFER,
            transaction_reference="NEFT-HDFC-998811",
            recorded_by=admin_user,
        )
        assert p2.amount == remaining

        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.balance_due == Decimal("0.00")
        assert invoice.amount_paid == total
        assert invoice.is_fully_paid

    def test_overpayment_rejected(self, completed_work_order, admin_user):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        BillingService.issue_invoice(invoice, performed_by=admin_user)
        too_much = invoice.total_amount + Decimal("100.00")

        with pytest.raises(Exception) as exc:
            BillingService.record_payment(
                invoice=invoice,
                amount=too_much,
                recorded_by=admin_user,
            )
        assert "cannot exceed the outstanding balance" in str(exc.value)

    def test_duplicate_transaction_reference_rejected(self, completed_work_order, admin_user):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        BillingService.issue_invoice(invoice, performed_by=admin_user)

        BillingService.record_payment(
            invoice=invoice,
            amount=Decimal("100.00"),
            transaction_reference="UNIQUE-REF-12345",
            recorded_by=admin_user,
        )

        with pytest.raises(Exception) as exc:
            BillingService.record_payment(
                invoice=invoice,
                amount=Decimal("100.00"),
                transaction_reference="UNIQUE-REF-12345",
                recorded_by=admin_user,
            )
        assert "already been processed" in str(exc.value)

    def test_cancel_invoice_success_and_protection(self, completed_work_order, admin_user):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        # Cancel unpaid invoice
        BillingService.cancel_invoice(
            invoice=invoice,
            reason="Customer requested duplicate invoice cancellation",
            performed_by=admin_user,
        )
        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.CANCELLED
        assert invoice.cancellation_reason == "Customer requested duplicate invoice cancellation"

        # Cannot cancel paid invoice
        inv2 = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )
        BillingService.issue_invoice(inv2, performed_by=admin_user)
        BillingService.record_payment(
            invoice=inv2,
            amount=Decimal("50.00"),
            transaction_reference="REF-PARTIAL",
            recorded_by=admin_user,
        )

        with pytest.raises(Exception) as exc:
            BillingService.cancel_invoice(inv2, reason="Should fail", performed_by=admin_user)
        assert "Cannot cancel an invoice that already has successful payments" in str(exc.value)


@pytest.mark.django_db
class TestBillingAPIEndpoints:
    def test_api_generate_and_issue_invoice(self, api_client, admin_user, completed_work_order):
        api_client.force_authenticate(user=admin_user)

        # 1. Generate Invoice via POST /api/v1/billing/invoices/generate/
        resp = api_client.post(
            "/api/v1/billing/invoices/generate/",
            {
                "work_order_id": str(completed_work_order.id),
                "discount_amount": "150.00",
                "notes": "Postman test invoice",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        invoice_id = resp.data["id"]
        assert resp.data["status"] == "DRAFT"
        assert resp.data["discount_amount"] == "150.00"

        # 2. Issue Invoice via POST /api/v1/billing/invoices/<id>/issue/
        issue_resp = api_client.post(
            f"/api/v1/billing/invoices/{invoice_id}/issue/",
            {"due_date": "2026-10-30"},
            format="json",
        )
        assert issue_resp.status_code == status.HTTP_200_OK
        assert issue_resp.data["status"] == "ISSUED"
        assert issue_resp.data["due_date"] == "2026-10-30"

        # 3. Record Payment via POST /api/v1/billing/invoices/<id>/payments/
        pay_resp = api_client.post(
            f"/api/v1/billing/invoices/{invoice_id}/payments/",
            {
                "amount": "5000.00",
                "payment_method": "UPI",
                "transaction_reference": "UPI-IND-778899",
                "notes": "Advance installment paid via GPay",
            },
            format="json",
        )
        assert pay_resp.status_code == status.HTTP_201_CREATED
        assert pay_resp.data["payment_status"] == "SUCCESS"

        # 4. Check Detail View
        detail_resp = api_client.get(f"/api/v1/billing/invoices/{invoice_id}/")
        assert detail_resp.status_code == status.HTTP_200_OK
        assert detail_resp.data["status"] == "PARTIALLY_PAID"
        assert Decimal(detail_resp.data["amount_paid"]) == Decimal("5000.00")
        assert len(detail_resp.data["payments"]) == 1

    def test_multi_tenant_isolation(
        self,
        api_client,
        admin_user,
        customer_user,
        other_customer_user,
        completed_work_order,
    ):
        invoice = BillingService.generate_invoice_from_work_order(
            work_order=completed_work_order,
            performed_by=admin_user,
        )

        # Owner customer can see their invoice
        api_client.force_authenticate(user=customer_user)
        resp = api_client.get("/api/v1/billing/invoices/")
        assert resp.status_code == status.HTTP_200_OK
        results = resp.data.get("results", resp.data)
        assert len(results) == 1
        assert results[0]["id"] == str(invoice.id)

        # Other customer cannot see it
        api_client.force_authenticate(user=other_customer_user)
        resp = api_client.get("/api/v1/billing/invoices/")
        assert resp.status_code == status.HTTP_200_OK
        other_results = resp.data.get("results", resp.data)
        assert len(other_results) == 0
