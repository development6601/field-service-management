import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import BaseModel


class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ISSUED = "ISSUED", "Issued"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
    PAID = "PAID", "Paid"
    CANCELLED = "CANCELLED", "Cancelled"


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Cash"
    BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer (NEFT/RTGS/IMPS)"
    UPI = "UPI", "UPI / QR Code"
    CREDIT_CARD = "CREDIT_CARD", "Credit / Debit Card"
    CHEQUE = "CHEQUE", "Cheque / Demand Draft"


class PaymentStatus(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    PENDING = "PENDING", "Pending"
    FAILED = "FAILED", "Failed"


def generate_invoice_number() -> str:
    """Generates unique invoice tracking identifier (e.g. INV-20260928-8F2B1A)."""
    date_str = timezone.now().strftime("%Y%m%d")
    random_hex = uuid.uuid4().hex[:6].upper()
    return f"INV-{date_str}-{random_hex}"


def generate_payment_number() -> str:
    """Generates unique payment transaction identifier (e.g. PAY-20260928-4E7A2C)."""
    date_str = timezone.now().strftime("%Y%m%d")
    random_hex = uuid.uuid4().hex[:6].upper()
    return f"PAY-{date_str}-{random_hex}"


class Invoice(BaseModel):
    """
    Financial bill generated from a completed WorkOrder.
    Calculates: Labor + Parts + Base Service Charges - Discount + Tax = Total Amount.
    """

    invoice_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        default=generate_invoice_number,
        help_text="Unique tracking invoice number (e.g. INV-20260928-8F2B1A)",
    )
    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.PROTECT,
        related_name="invoices",
        help_text="Work order billed",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="invoices",
        help_text="Customer account billed",
    )
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
        db_index=True,
        help_text="Current state of invoice collection",
    )
    issue_date = models.DateField(
        default=timezone.localdate,
        help_text="Date invoice was issued to customer",
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Payment due date",
    )
    labor_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total billable labor charge (hours × rate)",
    )
    parts_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total spare parts and consumables charge",
    )
    service_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Base standard service fee (0.00 if covered under AMC contract)",
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Goodwill, promotional, or contract discount applied",
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("18.00"),
        help_text="Tax percentage (e.g. 18.00 for 18% GST)",
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Calculated GST / tax amount",
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Final net payable amount (Subtotal + Tax)",
    )
    notes = models.TextField(
        blank=True,
        help_text="Invoice remarks or payment instructions",
    )
    cancellation_reason = models.TextField(
        blank=True,
        help_text="Mandatory note if invoice is voided or cancelled",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_invoices",
        help_text="Staff member who generated this invoice",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invoice_number} - {self.customer.display_name} (₹{self.total_amount}) [{self.status}]"

    def recalculate_totals(self) -> None:
        """
        Recalculates Subtotal, GST Tax, and Net Total according to the core billing formula.
        """
        subtotal = max(
            Decimal("0.00"),
            self.labor_amount + self.parts_amount + self.service_amount - self.discount_amount,
        )
        self.tax_amount = round(subtotal * (self.tax_rate / Decimal("100.00")), 2)
        self.total_amount = subtotal + self.tax_amount

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_invoice_number()
        super().save(*args, **kwargs)

    @property
    def subtotal(self) -> Decimal:
        """Net amount prior to taxation."""
        return max(
            Decimal("0.00"),
            self.labor_amount + self.parts_amount + self.service_amount - self.discount_amount,
        )

    @property
    def amount_paid(self) -> Decimal:
        """Cumulative sum of successfully settled payments."""
        total = self.payments.filter(payment_status=PaymentStatus.SUCCESS).aggregate(
            total=Sum("amount")
        )["total"]
        return total or Decimal("0.00")

    @property
    def balance_due(self) -> Decimal:
        """Remaining outstanding balance on this invoice."""
        return max(Decimal("0.00"), self.total_amount - self.amount_paid)

    @property
    def is_fully_paid(self) -> bool:
        """True if invoice has been fully settled."""
        return self.total_amount > Decimal("0.00") and self.balance_due == Decimal("0.00")


class Payment(BaseModel):
    """
    Payment receipt recording customer remittances against an Invoice.
    Supports partial payments, multiple installment settlements, and payment method audit.
    """

    payment_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        default=generate_payment_number,
        help_text="Unique receipt tracking number (e.g. PAY-20260928-4E7A2C)",
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="payments",
        help_text="Invoice this payment is applied against",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount remitted in this transaction",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
        help_text="Payment instrument used by customer",
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.SUCCESS,
        db_index=True,
        help_text="Payment execution status",
    )
    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Bank UTR number, UPI transaction ID, or Cheque number",
    )
    payment_date = models.DateField(
        default=timezone.localdate,
        help_text="Date remittance was credited",
    )
    notes = models.TextField(
        blank=True,
        help_text="Payer details, bank branch, or internal cashier notes",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_payments",
        help_text="Staff member or cashier who registered this payment",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.payment_number} - ₹{self.amount} for {self.invoice.invoice_number} ({self.payment_method})"

    def clean(self):
        super().clean()
        if self.amount <= Decimal("0.00"):
            raise ValidationError({"amount": "Payment amount must be greater than zero."})

    def save(self, *args, **kwargs):
        if not self.payment_number:
            self.payment_number = generate_payment_number()
        super().save(*args, **kwargs)
