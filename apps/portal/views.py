from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.billing.models import Invoice, InvoiceStatus, PaymentMethod
from apps.billing.services import BillingService
from apps.contracts.models import ContractStatus, ServiceContract
from apps.customers.models import Customer
from apps.portal.serializers import (
    PortalContractSerializer,
    PortalCreateServiceRequestSerializer,
    PortalCustomerFeedbackSerializer,
    PortalCustomerInfoSerializer,
    PortalDashboardSerializer,
    PortalInvoiceSerializer,
    PortalSelfPaymentSerializer,
    PortalServiceRequestSerializer,
    PortalWorkOrderDetailSerializer,
    PortalWorkOrderListSerializer,
    PortalWorkOrderTrackSerializer,
)
from apps.service_requests.models import RequestStatus, ServiceRequest
from apps.work_orders.models import WorkOrder, WorkOrderStatus


def get_portal_customer(request) -> Customer:
    """
    Resolves the active Customer context for the request.
    - If user is a CUSTOMER: strictly uses their own linked Customer record.
    - If user is ADMIN/DISPATCHER/MANAGER: allows inspecting on behalf of ?customer=<id> or default.
    """
    user = request.user
    if user.role == UserRole.CUSTOMER:
        return getattr(user, "customer_profile", None) or Customer.objects.filter(user=user).first()

    if user.role in [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.MANAGER]:
        customer_id = request.query_params.get("customer")
        if customer_id:
            return Customer.objects.filter(id=customer_id).first()
        return Customer.objects.first()

    return None


class IsCustomerOrStaff(permissions.BasePermission):
    """
    Permits access only to verified CUSTOMER users or internal operations staff.
    Blocks TECHNICIAN accounts from accessing the client-facing portal.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role == UserRole.TECHNICIAN:
            return False
        return True


class PortalDashboardView(APIView):
    """
    Aggregated operational and financial metrics dashboard for the customer portal home.
    """

    permission_classes = [IsCustomerOrStaff]

    def get(self, request):
        customer = get_portal_customer(request)
        if not customer:
            return Response(
                {"detail": "No customer profile found for this user account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 1. Open Tickets count
        open_requests = ServiceRequest.objects.filter(
            customer=customer
        ).exclude(status__in=[RequestStatus.COMPLETED, RequestStatus.CLOSED, RequestStatus.CANCELLED])
        open_requests_count = open_requests.count()

        # 2. Active Work Orders count
        active_jobs = WorkOrder.objects.filter(
            customer=customer
        ).exclude(status__in=[WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED])
        active_work_orders_count = active_jobs.count()

        # 3. Active AMC Contracts & remaining quota
        active_contracts = ServiceContract.objects.filter(
            customer=customer, status=ContractStatus.ACTIVE
        )
        active_contracts_count = active_contracts.count()
        visits_remaining_total = sum(c.visits_remaining for c in active_contracts)

        # 4. Invoices & Outstanding Balance
        invoices = Invoice.objects.filter(customer=customer).exclude(status=InvoiceStatus.CANCELLED)
        outstanding_invoices = [inv for inv in invoices if inv.balance_due > Decimal("0.00")]
        outstanding_invoices_count = len(outstanding_invoices)
        total_balance_due = sum((inv.balance_due for inv in outstanding_invoices), Decimal("0.00"))

        # 5. Recent Activity
        recent_wo = (
            WorkOrder.objects.filter(customer=customer)
            .select_related("service_location", "service_type", "assigned_technician")
            .order_by("-created_at")[:5]
        )
        recent_req = (
            ServiceRequest.objects.filter(customer=customer)
            .select_related("service_location", "service_type")
            .order_by("-created_at")[:5]
        )

        data = {
            "customer": PortalCustomerInfoSerializer(customer).data,
            "open_requests_count": open_requests_count,
            "active_work_orders_count": active_work_orders_count,
            "active_contracts_count": active_contracts_count,
            "visits_remaining_total": visits_remaining_total,
            "outstanding_invoices_count": outstanding_invoices_count,
            "total_balance_due": total_balance_due,
            "recent_work_orders": PortalWorkOrderListSerializer(recent_wo, many=True).data,
            "recent_requests": PortalServiceRequestSerializer(recent_req, many=True).data,
        }

        return Response(data, status=status.HTTP_200_OK)


class PortalServiceRequestViewSet(viewsets.ModelViewSet):
    """
    Customer ticketing endpoint: view tickets and submit new maintenance requests.
    """

    permission_classes = [IsCustomerOrStaff]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return PortalCreateServiceRequestSerializer
        return PortalServiceRequestSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["customer"] = get_portal_customer(self.request)
        return ctx

    def get_queryset(self):
        customer = get_portal_customer(self.request)
        if not customer:
            return ServiceRequest.objects.none()

        qs = (
            ServiceRequest.objects.filter(customer=customer)
            .select_related("service_location", "service_type")
            .prefetch_related("work_orders__assigned_technician")
            .order_by("-created_at")
        )

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        return qs

    def perform_create(self, serializer):
        customer = get_portal_customer(self.request)
        serializer.save(
            customer=customer,
            status=RequestStatus.NEW,
            reported_by=self.request.user,
        )


class PortalWorkOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Customer work orders view with live tracking and post-completion star ratings.
    """

    permission_classes = [IsCustomerOrStaff]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PortalWorkOrderDetailSerializer
        return PortalWorkOrderListSerializer

    def get_queryset(self):
        customer = get_portal_customer(self.request)
        if not customer:
            return WorkOrder.objects.none()

        qs = (
            WorkOrder.objects.filter(customer=customer)
            .select_related(
                "service_location",
                "service_type",
                "service_contract",
                "assigned_technician",
            )
            .order_by("-created_at")
        )

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        location_param = self.request.query_params.get("location")
        if location_param:
            qs = qs.filter(service_location_id=location_param)

        return qs

    @action(detail=True, methods=["get"], url_path="track")
    def track(self, request, pk=None):
        """
        Live Swiggy/Uber-style delivery tracking for the service job.
        Exposes technician details, location, and progress milestones.
        """
        work_order = self.get_object()
        serializer = PortalWorkOrderTrackSerializer(work_order)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="feedback")
    def submit_feedback(self, request, pk=None):
        """
        Customer submits 1-5 star rating and review on a completed job.
        """
        work_order = self.get_object()
        if work_order.status != WorkOrderStatus.COMPLETED:
            return Response(
                {"detail": "Feedback can only be submitted for COMPLETED work orders."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PortalCustomerFeedbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rating = serializer.validated_data["rating"]
        feedback = serializer.validated_data.get("feedback", "")

        work_order.customer_rating = rating
        work_order.customer_feedback = feedback
        work_order.save(update_fields=["customer_rating", "customer_feedback", "updated_at"])

        return Response(
            PortalWorkOrderDetailSerializer(work_order).data,
            status=status.HTTP_200_OK,
        )


class PortalContractViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Customer portal view of active and past maintenance contracts (AMC).
    """

    permission_classes = [IsCustomerOrStaff]
    serializer_class = PortalContractSerializer

    def get_queryset(self):
        customer = get_portal_customer(self.request)
        if not customer:
            return ServiceContract.objects.none()

        qs = (
            ServiceContract.objects.filter(customer=customer)
            .select_related("service_location")
            .prefetch_related("covered_services__category")
            .order_by("-created_at")
        )

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        return qs


class PortalInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Customer billing portal: view invoices and make self-service online payments.
    """

    permission_classes = [IsCustomerOrStaff]
    serializer_class = PortalInvoiceSerializer

    def get_queryset(self):
        customer = get_portal_customer(self.request)
        if not customer:
            return Invoice.objects.none()

        # By default exclude DRAFT internal invoices from customer view
        qs = (
            Invoice.objects.filter(customer=customer)
            .exclude(status=InvoiceStatus.CANCELLED)
            .select_related("work_order", "customer")
            .prefetch_related("payments__recorded_by")
            .order_by("-created_at")
        )

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        unpaid = self.request.query_params.get("unpaid")
        if unpaid and unpaid.lower() == "true":
            qs = [inv for inv in qs if inv.balance_due > Decimal("0.00")]

        return qs

    @action(detail=True, methods=["post"], url_path="pay")
    def pay_invoice(self, request, pk=None):
        """
        Customer triggers an online self-service payment on an issued invoice.
        """
        invoice = self.get_object()

        if invoice.status in [InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]:
            return Response(
                {"detail": f"Invoice cannot accept payment in status '{invoice.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if invoice.balance_due <= Decimal("0.00"):
            return Response(
                {"detail": "This invoice is already fully paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PortalSelfPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Default payment amount to remaining balance if not explicitly specified
        amount = data.get("amount") or invoice.balance_due

        try:
            payment = BillingService.record_payment(
                invoice=invoice,
                amount=amount,
                payment_method=data.get("payment_method", PaymentMethod.UPI),
                transaction_reference=data.get("transaction_reference", ""),
                notes=data.get("notes", "Customer self-service portal payment"),
                recorded_by=request.user,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        invoice.refresh_from_db()
        return Response(
            PortalInvoiceSerializer(invoice).data,
            status=status.HTTP_201_CREATED,
        )
