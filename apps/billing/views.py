from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import UserRole
from apps.billing.models import (
    Invoice,
    InvoiceStatus,
    Payment,
)
from apps.billing.serializers import (
    CancelInvoiceSerializer,
    GenerateInvoiceSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    IssueInvoiceSerializer,
    PaymentSerializer,
    RecordPaymentSerializer,
)
from apps.billing.services import BillingService
from apps.work_orders.models import WorkOrder
from drf_spectacular.utils import extend_schema


class InvoiceViewSet(viewsets.ModelViewSet):
    """
    CRUD and financial lifecycle management for service Invoices.
    Supports auto-generation from completed jobs, issuing, partial/full payment,
    and cancellation.
    """

    permission_classes = [permissions.IsAuthenticated]
    queryset = (
        Invoice.objects.select_related(
            "work_order__service_type",
            "customer",
            "created_by",
        )
        .prefetch_related("payments__recorded_by", "work_order__parts_used")
        .all()
    )

    def get_serializer_class(self):
        if self.action in ["retrieve"]:
            return InvoiceDetailSerializer
        elif self.action == "generate_invoice":
            return GenerateInvoiceSerializer
        elif self.action == "issue":
            return IssueInvoiceSerializer
        elif self.action == "record_payment":
            return RecordPaymentSerializer
        elif self.action == "cancel_invoice":
            return CancelInvoiceSerializer
        return InvoiceListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Multi-Tenant Visibility Isolation:
        if user.role == UserRole.CUSTOMER:
            qs = qs.filter(customer__user=user)
        elif user.role == UserRole.TECHNICIAN:
            qs = qs.filter(work_order__assigned_technician=user)

        # Query Filters
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        customer_param = self.request.query_params.get("customer")
        if customer_param:
            qs = qs.filter(customer_id=customer_param)

        wo_param = self.request.query_params.get("work_order")
        if wo_param:
            qs = qs.filter(work_order_id=wo_param)

        unpaid = self.request.query_params.get("unpaid")
        if unpaid and unpaid.lower() == "true":
            qs = [inv for inv in qs if inv.balance_due > 0 and inv.status != InvoiceStatus.CANCELLED]

        return qs

    @extend_schema(request=GenerateInvoiceSerializer, responses={201: InvoiceDetailSerializer})
    @action(detail=False, methods=["post"], url_path="generate")
    def generate_invoice(self, request):
        """
        Compile and generate a DRAFT invoice from a completed WorkOrder.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]:
            return Response(
                {"detail": "Only Admins, Managers, and Dispatchers can generate invoices."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = GenerateInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        work_order = get_object_or_404(WorkOrder, id=data["work_order_id"])

        try:
            invoice = BillingService.generate_invoice_from_work_order(
                work_order=work_order,
                hourly_rate=data.get("hourly_rate"),
                discount_amount=data.get("discount_amount"),
                tax_rate=data.get("tax_rate"),
                notes=data.get("notes", ""),
                performed_by=request.user,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            InvoiceDetailSerializer(invoice, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=IssueInvoiceSerializer, responses={200: InvoiceDetailSerializer})
    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, pk=None):
        """
        Officially issue a DRAFT invoice to the customer with a payment due date.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            return Response(
                {"detail": "Only Admins and Managers can issue invoices."},
                status=status.HTTP_403_FORBIDDEN,
            )

        invoice = self.get_object()
        serializer = IssueInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            issued_invoice = BillingService.issue_invoice(
                invoice,
                due_date=serializer.validated_data.get("due_date"),
                performed_by=request.user,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            InvoiceDetailSerializer(issued_invoice, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=RecordPaymentSerializer, responses={201: PaymentSerializer})
    @action(detail=True, methods=["post"], url_path="payments")
    def record_payment(self, request, pk=None):
        """
        Record a customer remittance against this invoice.
        Enforces overpayment prevention and duplicate transaction checks.
        """
        invoice = self.get_object()
        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = BillingService.record_payment(
                invoice=invoice,
                amount=data["amount"],
                payment_method=data.get("payment_method"),
                transaction_reference=data.get("transaction_reference", ""),
                payment_date=data.get("payment_date"),
                notes=data.get("notes", ""),
                recorded_by=request.user,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            PaymentSerializer(payment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=CancelInvoiceSerializer, responses={200: InvoiceDetailSerializer})
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_invoice(self, request, pk=None):
        """
        Void or cancel an unpaid invoice with a mandatory audit reason.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            return Response(
                {"detail": "Only Admins and Managers can cancel invoices."},
                status=status.HTTP_403_FORBIDDEN,
            )

        invoice = self.get_object()
        serializer = CancelInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            cancelled_invoice = BillingService.cancel_invoice(
                invoice,
                reason=serializer.validated_data["reason"],
                performed_by=request.user,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            InvoiceDetailSerializer(cancelled_invoice, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only audit history of all recorded payments across invoices.
    """

    queryset = Payment.objects.select_related("invoice__customer", "recorded_by").all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        if user.role == UserRole.CUSTOMER:
            qs = qs.filter(invoice__customer__user=user)

        invoice_id = self.request.query_params.get("invoice")
        if invoice_id:
            qs = qs.filter(invoice_id=invoice_id)

        method = self.request.query_params.get("payment_method")
        if method:
            qs = qs.filter(payment_method=method)

        return qs
