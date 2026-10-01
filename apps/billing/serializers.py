from decimal import Decimal
from rest_framework import serializers

from apps.billing.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)


class PaymentSerializer(serializers.ModelSerializer):
    """
    Serializer representing individual payment remittances against an invoice.
    """

    recorded_by_name = serializers.CharField(source="recorded_by.get_full_name", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "payment_number",
            "invoice",
            "amount",
            "payment_method",
            "payment_status",
            "transaction_reference",
            "payment_date",
            "notes",
            "recorded_by",
            "recorded_by_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "payment_number",
            "recorded_by",
            "recorded_by_name",
            "created_at",
        ]


class InvoiceListSerializer(serializers.ModelSerializer):
    """
    Summary view of invoices for listing and table grids.
    """

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    work_order_number = serializers.CharField(source="work_order.work_order_number", read_only=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_fully_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "work_order",
            "work_order_number",
            "customer",
            "customer_name",
            "status",
            "issue_date",
            "due_date",
            "total_amount",
            "amount_paid",
            "balance_due",
            "is_fully_paid",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """
    Full invoice detail representation with comprehensive mathematical breakdown,
    line items, and payment history.
    """

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    customer_billing_address = serializers.CharField(source="customer.billing_address", read_only=True)
    customer_tax_id = serializers.CharField(source="customer.tax_id", read_only=True)
    work_order_number = serializers.CharField(source="work_order.work_order_number", read_only=True)
    work_order_title = serializers.CharField(source="work_order.title", read_only=True)
    labor_hours = serializers.DecimalField(source="work_order.labor_hours", max_digits=5, decimal_places=2, read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_fully_paid = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "work_order",
            "work_order_number",
            "work_order_title",
            "customer",
            "customer_name",
            "customer_phone",
            "customer_billing_address",
            "customer_tax_id",
            "status",
            "issue_date",
            "due_date",
            "labor_hours",
            "labor_amount",
            "parts_amount",
            "service_amount",
            "discount_amount",
            "subtotal",
            "tax_rate",
            "tax_amount",
            "total_amount",
            "amount_paid",
            "balance_due",
            "is_fully_paid",
            "notes",
            "cancellation_reason",
            "created_by",
            "created_by_name",
            "payments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class GenerateInvoiceSerializer(serializers.Serializer):
    """
    Input payload for generating an invoice from a completed WorkOrder.
    """

    work_order_id = serializers.UUIDField(help_text="UUID of the COMPLETED WorkOrder")
    hourly_rate = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        required=False,
        default=Decimal("500.00"),
        help_text="Custom technician hourly rate (defaults to ₹500/hr)",
    )
    discount_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        help_text="Optional promotional or contract discount",
    )
    tax_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        default=Decimal("18.00"),
        help_text="Applicable GST rate (defaults to 18%)",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional remarks for invoice",
    )


class IssueInvoiceSerializer(serializers.Serializer):
    """
    Input payload for officially issuing an invoice with a due date.
    """

    due_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Optional payment deadline date (defaults to 15 days from issue)",
    )


class RecordPaymentSerializer(serializers.Serializer):
    """
    Input payload for recording a customer payment against an invoice.
    """

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Remittance amount (must be > 0 and <= balance_due)",
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
        help_text="Instrument used (CASH, BANK_TRANSFER, UPI, CREDIT_CARD, CHEQUE)",
    )
    transaction_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Bank UTR number, UPI transaction ID, or Cheque number",
    )
    payment_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Date remittance occurred (defaults to today)",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Cashier or bank remarks",
    )


class CancelInvoiceSerializer(serializers.Serializer):
    """
    Payload for cancelling/voiding an invoice with a mandatory reason.
    """

    reason = serializers.CharField(
        required=True,
        min_length=5,
        help_text="Mandatory audit justification for voiding the invoice",
    )
