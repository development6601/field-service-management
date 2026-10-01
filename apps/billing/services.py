import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.billing.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from apps.work_orders.models import WorkOrder, WorkOrderStatus


class BillingService:
    """
    Domain service handling financial invoice compilation, taxation arithmetic,
    installment reconciliation, overpayment checks, and payment audit tracking.
    """

    DEFAULT_HOURLY_RATE = Decimal("500.00")
    DEFAULT_TAX_RATE = Decimal("18.00")  # 18% GST

    @classmethod
    @db_transaction.atomic
    def generate_invoice_from_work_order(
        cls,
        *,
        work_order: WorkOrder,
        hourly_rate: Decimal = None,
        discount_amount: Decimal = Decimal("0.00"),
        tax_rate: Decimal = None,
        notes: str = "",
        performed_by=None,
    ) -> Invoice:
        """
        Generate a DRAFT Invoice from a COMPLETED WorkOrder according to the core formula:
        Labor + Parts + Base Service Charges - Discount + Tax = Total Amount.
        """
        if work_order.status != WorkOrderStatus.COMPLETED:
            raise ValidationError(
                f"Cannot generate invoice: Work order {work_order.work_order_number} is '{work_order.status}'. "
                f"Only COMPLETED work orders can be billed."
            )

        # Idempotency check: if invoice already exists, return it
        existing_invoice = (
            Invoice.objects.select_for_update()
            .filter(work_order=work_order)
            .exclude(status=InvoiceStatus.CANCELLED)
            .first()
        )
        if existing_invoice:
            return existing_invoice

        effective_hourly_rate = hourly_rate or cls.DEFAULT_HOURLY_RATE
        effective_tax_rate = tax_rate if tax_rate is not None else cls.DEFAULT_TAX_RATE

        # 1. Labor charges: actual logged hours × hourly rate
        labor_hours = work_order.labor_hours or Decimal("0.00")
        labor_amount = round(Decimal(str(labor_hours)) * effective_hourly_rate, 2)

        # 2. Parts charges: sum of all consumed billable items on the job card
        parts_amount = Decimal("0.00")
        for part_usage in work_order.parts_used.filter(status="CONSUMED"):
            parts_amount += part_usage.total_price

        # 3. Base Service fee:
        # If job is under an active ServiceContract (AMC), base service fee is waived (₹0.00)!
        if work_order.service_contract:
            service_amount = Decimal("0.00")
            amc_note = f" (Service fee waived under AMC {work_order.service_contract.contract_number})"
        else:
            service_amount = (
                work_order.service_type.base_price
                if work_order.service_type
                else Decimal("0.00")
            )
            amc_note = ""

        # 4. Subtotal & Taxation
        subtotal = max(
            Decimal("0.00"),
            labor_amount + parts_amount + service_amount - discount_amount,
        )
        tax_amount = round(subtotal * (effective_tax_rate / Decimal("100.00")), 2)
        total_amount = subtotal + tax_amount

        invoice_notes = (
            notes
            or f"Invoice for {work_order.title} [{work_order.work_order_number}]{amc_note}"
        )

        invoice = Invoice.objects.create(
            work_order=work_order,
            customer=work_order.customer,
            status=InvoiceStatus.DRAFT,
            issue_date=timezone.localdate(),
            labor_amount=labor_amount,
            parts_amount=parts_amount,
            service_amount=service_amount,
            discount_amount=discount_amount,
            tax_rate=effective_tax_rate,
            tax_amount=tax_amount,
            total_amount=total_amount,
            notes=invoice_notes,
            created_by=performed_by,
        )

        return invoice

    @staticmethod
    @db_transaction.atomic
    def issue_invoice(
        invoice: Invoice,
        due_date: datetime.date = None,
        performed_by=None,
    ) -> Invoice:
        """
        Transition invoice from DRAFT to ISSUED and set payment due date.
        """
        if invoice.status != InvoiceStatus.DRAFT:
            raise ValidationError(
                f"Only DRAFT invoices can be issued. Current status: '{invoice.status}'."
            )

        invoice.status = InvoiceStatus.ISSUED
        invoice.issue_date = timezone.localdate()
        invoice.due_date = due_date or (timezone.localdate() + datetime.timedelta(days=15))
        invoice.save(update_fields=["status", "issue_date", "due_date", "updated_at"])
        return invoice

    @staticmethod
    @db_transaction.atomic
    def record_payment(
        *,
        invoice: Invoice,
        amount: Decimal,
        payment_method: str = PaymentMethod.BANK_TRANSFER,
        transaction_reference: str = "",
        payment_date: datetime.date = None,
        notes: str = "",
        recorded_by=None,
    ) -> Payment:
        """
        Record a payment against an invoice. Supports installments and overpayment checks.
        """
        invoice = Invoice.objects.select_for_update().get(id=invoice.id)

        if invoice.status in [InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]:
            raise ValidationError(
                f"Cannot apply payment to an invoice with status '{invoice.status}'. "
                f"Invoice must be officially ISSUED first."
            )

        amount = Decimal(str(amount))
        if amount <= Decimal("0.00"):
            raise ValidationError({"amount": "Payment amount must be greater than zero."})

        # Overpayment safeguard
        if amount > invoice.balance_due:
            raise ValidationError(
                {
                    "amount": (
                        f"Payment amount (₹{amount}) cannot exceed the outstanding balance (₹{invoice.balance_due})."
                    )
                }
            )

        # Duplicate reference check
        ref = transaction_reference.strip() if transaction_reference else ""
        if ref:
            if Payment.objects.filter(transaction_reference=ref, payment_status=PaymentStatus.SUCCESS).exists():
                raise ValidationError(
                    {"transaction_reference": f"A payment with reference '{ref}' has already been processed."}
                )

        # Create payment record
        payment = Payment.objects.create(
            invoice=invoice,
            amount=amount,
            payment_method=payment_method,
            payment_status=PaymentStatus.SUCCESS,
            transaction_reference=ref,
            payment_date=payment_date or timezone.localdate(),
            notes=notes,
            recorded_by=recorded_by,
        )

        # Update invoice status according to remaining balance
        invoice.refresh_from_db()
        if invoice.balance_due == Decimal("0.00"):
            invoice.status = InvoiceStatus.PAID
        else:
            invoice.status = InvoiceStatus.PARTIALLY_PAID

        invoice.save(update_fields=["status", "updated_at"])
        return payment

    @staticmethod
    @db_transaction.atomic
    def cancel_invoice(invoice: Invoice, reason: str, performed_by=None) -> Invoice:
        """
        Void or cancel an unpaid invoice with a mandatory audit reason.
        """
        invoice = Invoice.objects.select_for_update().get(id=invoice.id)

        if not reason or not reason.strip():
            raise ValidationError({"reason": "A mandatory cancellation reason must be provided."})

        if invoice.payments.filter(payment_status=PaymentStatus.SUCCESS).exists():
            raise ValidationError(
                "Cannot cancel an invoice that already has successful payments. Refund or adjust payments first."
            )

        invoice.status = InvoiceStatus.CANCELLED
        invoice.cancellation_reason = reason.strip()
        invoice.save(update_fields=["status", "cancellation_reason", "updated_at"])
        return invoice
