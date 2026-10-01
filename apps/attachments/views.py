import os
from django.db import models
from django.http import FileResponse, Http404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.models import UserRole
from apps.attachments.models import Attachment, RelatedEntityType
from apps.attachments.serializers import (
    AttachmentListSerializer,
    AttachmentUploadSerializer,
)
from apps.attachments.services import AttachmentService


class AttachmentViewSet(viewsets.ModelViewSet):
    """
    Universal Document and Attachment Management API.
    Handles secure multipart uploads, file type validation, download streaming,
    and role-based multi-tenant access control.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return AttachmentUploadSerializer
        return AttachmentListSerializer

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Attachment.objects.none()

        qs = Attachment.objects.select_related("uploaded_by").order_by("-created_at")

        # Staff can inspect all system attachments
        if user.role in [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]:
            pass

        # Field Technicians: see documents uploaded by self OR linked to their assigned work orders
        elif user.role == UserRole.TECHNICIAN:
            from apps.work_orders.models import WorkOrder
            my_wo_ids = WorkOrder.objects.filter(assigned_technician=user).values_list("id", flat=True)
            qs = qs.filter(
                models.Q(uploaded_by=user)
                | (
                    models.Q(related_entity_type=RelatedEntityType.WORK_ORDER)
                    & models.Q(related_entity_id__in=my_wo_ids)
                )
            )

        # Customers: see documents strictly belonging to their own customer profile
        elif user.role == UserRole.CUSTOMER:
            customer_profile = getattr(user, "customer_profile", None)
            if not customer_profile:
                from apps.customers.models import Customer
                customer_profile = Customer.objects.filter(user=user).first()

            if not customer_profile:
                return Attachment.objects.none()

            from apps.work_orders.models import WorkOrder
            from apps.service_requests.models import ServiceRequest
            from apps.billing.models import Invoice
            from apps.contracts.models import ServiceContract

            cust_id = customer_profile.id
            wo_ids = WorkOrder.objects.filter(customer_id=cust_id).values_list("id", flat=True)
            sr_ids = ServiceRequest.objects.filter(customer_id=cust_id).values_list("id", flat=True)
            inv_ids = Invoice.objects.filter(customer_id=cust_id).values_list("id", flat=True)
            cnt_ids = ServiceContract.objects.filter(customer_id=cust_id).values_list("id", flat=True)

            qs = qs.filter(
                models.Q(related_entity_type=RelatedEntityType.CUSTOMER, related_entity_id=cust_id)
                | models.Q(related_entity_type=RelatedEntityType.WORK_ORDER, related_entity_id__in=wo_ids)
                | models.Q(related_entity_type=RelatedEntityType.SERVICE_REQUEST, related_entity_id__in=sr_ids)
                | models.Q(related_entity_type=RelatedEntityType.INVOICE, related_entity_id__in=inv_ids)
                | models.Q(related_entity_type=RelatedEntityType.CONTRACT, related_entity_id__in=cnt_ids)
            )

        # Query Filters
        entity_type = self.request.query_params.get("entity_type")
        if entity_type:
            qs = qs.filter(related_entity_type__iexact=entity_type)

        entity_id = self.request.query_params.get("entity_id")
        if entity_id:
            qs = qs.filter(related_entity_id=entity_id)

        attachment_type = self.request.query_params.get("attachment_type")
        if attachment_type:
            qs = qs.filter(attachment_type__iexact=attachment_type)

        return qs

    def perform_destroy(self, instance):
        # Allow deletion if user is staff or the original uploader
        user = self.request.user
        if user.role in [UserRole.ADMIN, UserRole.MANAGER] or instance.uploaded_by == user:
            instance.delete()
        else:
            return Response(
                {"detail": "You do not have permission to delete this attachment."},
                status=status.HTTP_403_FORBIDDEN,
            )

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """
        Secure file download stream with content-disposition headers.
        """
        attachment = self.get_object()

        if not attachment.file or not os.path.exists(attachment.file.path):
            raise Http404("The requested file was not found on the server storage.")

        file_handle = open(attachment.file.path, "rb")
        response = FileResponse(file_handle, content_type=attachment.file_type or "application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{attachment.file_name}"'
        response["Content-Length"] = attachment.file_size_bytes
        return response
