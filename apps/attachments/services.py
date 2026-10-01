import mimetypes
import os
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import UserRole
from apps.attachments.models import Attachment, AttachmentType, RelatedEntityType


class AttachmentService:
    """
    Business service orchestrating file security checks, MIME verification,
    entity resolution, access permission checking, and attachment persistence.
    """

    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
    ALLOWED_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".pdf",
        ".docx",
        ".xlsx",
        ".txt",
    }
    BLOCKED_EXTENSIONS = {
        ".exe",
        ".sh",
        ".bat",
        ".cmd",
        ".php",
        ".py",
        ".js",
        ".vbs",
        ".dll",
        ".bin",
        ".msi",
    }

    @classmethod
    def validate_file(cls, file_obj) -> tuple[str, str, int]:
        """
        Validates file size, checks extension whitelist/blacklist,
        and determines sanitized filename and MIME type.
        Returns (sanitized_file_name, mime_type, file_size_bytes).
        """
        if not file_obj:
            raise ValidationError("No file was provided for upload.")

        file_size = getattr(file_obj, "size", 0)
        if file_size <= 0:
            raise ValidationError("The provided file is empty (0 bytes).")

        if file_size > cls.MAX_FILE_SIZE_BYTES:
            max_mb = cls.MAX_FILE_SIZE_BYTES / (1024 * 1024)
            provided_mb = file_size / (1024 * 1024)
            raise ValidationError(
                f"File size exceeds the {max_mb:.0f} MB limit ({provided_mb:.2f} MB uploaded)."
            )

        orig_name = getattr(file_obj, "name", "unnamed_file")
        clean_name = os.path.basename(orig_name)
        ext = os.path.splitext(clean_name)[1].lower()

        if ext in cls.BLOCKED_EXTENSIONS:
            raise ValidationError(
                f"Potentially hazardous file extension '{ext}' is strictly prohibited."
            )

        if ext not in cls.ALLOWED_EXTENSIONS:
            allowed_str = ", ".join(sorted(cls.ALLOWED_EXTENSIONS))
            raise ValidationError(
                f"Unsupported file format '{ext}'. Allowed formats: {allowed_str}"
            )

        # Detect MIME type
        mime_type, _ = mimetypes.guess_type(clean_name)
        if not mime_type:
            mime_type = getattr(file_obj, "content_type", "application/octet-stream")

        return clean_name, mime_type, file_size

    @classmethod
    def resolve_entity(cls, entity_type: str, entity_id):
        """
        Resolves and verifies existence of target domain entity.
        Raises ValidationError if entity does not exist.
        """
        if not entity_id:
            raise ValidationError("Target entity ID is required.")

        if entity_type == RelatedEntityType.WORK_ORDER:
            from apps.work_orders.models import WorkOrder
            try:
                return WorkOrder.objects.select_related("customer", "assigned_technician").get(id=entity_id)
            except WorkOrder.DoesNotExist:
                raise ValidationError(f"Work order with ID '{entity_id}' does not exist.")

        elif entity_type == RelatedEntityType.SERVICE_REQUEST:
            from apps.service_requests.models import ServiceRequest
            try:
                return ServiceRequest.objects.select_related("customer").get(id=entity_id)
            except ServiceRequest.DoesNotExist:
                raise ValidationError(f"Service request with ID '{entity_id}' does not exist.")

        elif entity_type == RelatedEntityType.CUSTOMER:
            from apps.customers.models import Customer
            try:
                return Customer.objects.get(id=entity_id)
            except Customer.DoesNotExist:
                raise ValidationError(f"Customer with ID '{entity_id}' does not exist.")

        elif entity_type == RelatedEntityType.CONTRACT:
            from apps.contracts.models import ServiceContract
            try:
                return ServiceContract.objects.select_related("customer").get(id=entity_id)
            except ServiceContract.DoesNotExist:
                raise ValidationError(f"Contract with ID '{entity_id}' does not exist.")

        elif entity_type == RelatedEntityType.INVOICE:
            from apps.billing.models import Invoice
            try:
                return Invoice.objects.select_related("customer").get(id=entity_id)
            except Invoice.DoesNotExist:
                raise ValidationError(f"Invoice with ID '{entity_id}' does not exist.")

        elif entity_type == RelatedEntityType.PAYMENT:
            from apps.billing.models import Payment
            try:
                return Payment.objects.select_related("invoice__customer").get(id=entity_id)
            except Payment.DoesNotExist:
                raise ValidationError(f"Payment with ID '{entity_id}' does not exist.")

        elif entity_type == RelatedEntityType.GENERAL:
            return None

        raise ValidationError(f"Unknown entity type '{entity_type}'.")

    @classmethod
    def check_user_access(cls, user, entity_type: str, entity_obj) -> bool:
        """
        Enforces Role-Based Access Control and multi-tenant data boundaries.
        Returns True if the user has access to upload or view files for this entity.
        """
        if not user or not user.is_authenticated:
            return False

        # Staff users have full access across the system
        if user.role in [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]:
            return True

        if entity_type == RelatedEntityType.GENERAL:
            return True

        if not entity_obj:
            return True

        # Field Technicians: only allowed for their assigned Work Orders or linked requests
        if user.role == UserRole.TECHNICIAN:
            if entity_type == RelatedEntityType.WORK_ORDER:
                return getattr(entity_obj, "assigned_technician_id", None) == user.id
            elif entity_type == RelatedEntityType.SERVICE_REQUEST:
                # Allowed if technician is assigned to any work order of this ticket
                return entity_obj.work_orders.filter(assigned_technician=user).exists()
            return False

        # Customers: only allowed for records belonging to their own customer profile
        if user.role == UserRole.CUSTOMER:
            customer_profile = getattr(user, "customer_profile", None)
            if not customer_profile:
                from apps.customers.models import Customer
                customer_profile = Customer.objects.filter(user=user).first()

            if not customer_profile:
                return False

            if entity_type == RelatedEntityType.CUSTOMER:
                return entity_obj.id == customer_profile.id
            elif entity_type in [
                RelatedEntityType.WORK_ORDER,
                RelatedEntityType.SERVICE_REQUEST,
                RelatedEntityType.CONTRACT,
                RelatedEntityType.INVOICE,
            ]:
                return getattr(entity_obj, "customer_id", None) == customer_profile.id
            elif entity_type == RelatedEntityType.PAYMENT:
                return getattr(entity_obj.invoice, "customer_id", None) == customer_profile.id

        return False

    @classmethod
    @transaction.atomic
    def upload_attachment(
        cls,
        *,
        file_obj,
        attachment_type: str,
        related_entity_type: str,
        related_entity_id,
        description: str = "",
        uploaded_by=None,
    ) -> Attachment:
        """
        Validates, resolves, checks permissions, and persists an attachment record.
        """
        clean_name, mime_type, file_size = cls.validate_file(file_obj)
        entity_obj = cls.resolve_entity(related_entity_type, related_entity_id)

        if uploaded_by and not cls.check_user_access(uploaded_by, related_entity_type, entity_obj):
            raise ValidationError(
                "You do not have permission to attach documents to this entity."
            )

        attachment = Attachment.objects.create(
            file=file_obj,
            file_name=clean_name,
            file_type=mime_type,
            file_size_bytes=file_size,
            attachment_type=attachment_type or AttachmentType.GENERAL,
            related_entity_type=related_entity_type or RelatedEntityType.GENERAL,
            related_entity_id=related_entity_id,
            description=description or "",
            uploaded_by=uploaded_by,
        )
        return attachment
