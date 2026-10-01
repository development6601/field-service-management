from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.models import UserRole
from .models import RequestAttachment, RequestPriority, RequestStatus, ServiceRequest
from .serializers import (
    RequestAttachmentSerializer,
    ServiceRequestCancelSerializer,
    ServiceRequestCreateSerializer,
    ServiceRequestDetailSerializer,
    ServiceRequestListSerializer,
    ServiceRequestReviewSerializer,
)


class ServiceRequestViewSet(viewsets.ModelViewSet):
    """
    CRUD and operational lifecycle API for Service Requests.
    Supports role-based filtering, status transition state machine,
    and multipart photo attachment uploads.
    """

    permission_classes = [permissions.IsAuthenticated]
    queryset = (
        ServiceRequest.objects.select_related(
            "customer",
            "service_location",
            "service_type",
            "reported_by",
            "reviewed_by",
        )
        .prefetch_related("attachments")
        .all()
    )

    def get_serializer_class(self):
        if self.action == "create":
            return ServiceRequestCreateSerializer
        elif self.action in ["retrieve", "update", "partial_update"]:
            return ServiceRequestDetailSerializer
        elif self.action == "review":
            return ServiceRequestReviewSerializer
        elif self.action == "cancel":
            return ServiceRequestCancelSerializer
        elif self.action == "attachments":
            return RequestAttachmentSerializer
        return ServiceRequestListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Strict Tenant Isolation: CUSTOMER users only see their own tickets
        if user.role == UserRole.CUSTOMER:
            qs = qs.filter(customer__user=user)

        # Status filtering (e.g. ?status=NEW or ?status=REVIEWED)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        # Priority filtering (e.g. ?priority=CRITICAL)
        priority_param = self.request.query_params.get("priority")
        if priority_param:
            qs = qs.filter(priority__iexact=priority_param)

        # Customer filtering (e.g. ?customer=<uuid>)
        customer_param = self.request.query_params.get("customer")
        if customer_param:
            qs = qs.filter(customer_id=customer_param)

        # Service Location filtering (e.g. ?service_location=<uuid>)
        location_param = self.request.query_params.get("service_location")
        if location_param:
            qs = qs.filter(service_location_id=location_param)

        # Search query (by title, request_number, description, or customer company name)
        search_query = self.request.query_params.get("search")
        if search_query:
            qs = qs.filter(
                Q(request_number__icontains=search_query)
                | Q(title__icontains=search_query)
                | Q(description__icontains=search_query)
                | Q(customer__company_name__icontains=search_query)
            )

        # SLA Breached filter (e.g. ?is_sla_breached=true)
        breached_param = self.request.query_params.get("is_sla_breached")
        if breached_param is not None and breached_param.lower() in ("true", "1", "t"):
            now = timezone.now()
            qs = qs.filter(
                sla_resolution_due_at__lt=now
            ).exclude(
                status__in=[RequestStatus.COMPLETED, RequestStatus.CLOSED, RequestStatus.CANCELLED]
            )

        return qs

    def perform_create(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            raise PermissionDenied("Only Administrators and Managers can delete service requests.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        """
        Dispatcher or Manager triages and reviews a NEW service request.
        Transitions state from NEW -> REVIEWED.
        """
        instance = self.get_object()
        user = request.user

        # Only internal staff can review requests
        if user.role not in [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.MANAGER]:
            raise PermissionDenied("Only dispatchers, managers, and administrators can review service requests.")

        if not instance.can_transition_to(RequestStatus.REVIEWED):
            raise ValidationError(
                f"Cannot review request. Current status is '{instance.status}'. Allowed from 'NEW' only."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dispatcher_notes = serializer.validated_data.get("dispatcher_notes", "")
        new_priority = serializer.validated_data.get("priority")

        with transaction.atomic():
            if new_priority and new_priority != instance.priority:
                instance.priority = new_priority
                instance.calculate_sla_targets()

            instance.transition_to(
                RequestStatus.REVIEWED,
                user=user,
                notes=dispatcher_notes,
            )
            instance.refresh_from_db()

        detail_serializer = ServiceRequestDetailSerializer(instance, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """
        Cancels an open service request with a mandatory reason.
        """
        instance = self.get_object()
        user = request.user

        # Customer can only cancel their own ticket if not already completed/closed
        if user.role == UserRole.CUSTOMER and instance.customer.user != user:
            raise PermissionDenied("You cannot cancel service requests belonging to other customers.")

        if not instance.can_transition_to(RequestStatus.CANCELLED):
            raise ValidationError(
                f"Request in status '{instance.status}' cannot be cancelled."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]

        instance.transition_to(RequestStatus.CANCELLED, user=user, reason=reason)

        detail_serializer = ServiceRequestDetailSerializer(instance, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="attachments",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_attachment(self, request, pk=None):
        """
        Uploads a photo or document attachment for this service request.
        """
        instance = self.get_object()
        user = request.user

        # Tenant permission check
        if user.role == UserRole.CUSTOMER and instance.customer.user != user:
            raise PermissionDenied("You cannot upload attachments to other customers' service requests.")

        serializer = RequestAttachmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        attachment = serializer.save(
            service_request=instance,
            uploaded_by=user,
        )

        return Response(
            RequestAttachmentSerializer(attachment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
