import os
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class AttachmentType(models.TextChoices):
    BEFORE_SERVICE = "BEFORE_SERVICE", "Before Service Photo"
    AFTER_SERVICE = "AFTER_SERVICE", "After Service Photo"
    COMPLETION_EVIDENCE = "COMPLETION_EVIDENCE", "Completion Evidence / Sign-off"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT", "Diagnostic / Inspection Report"
    PAYMENT_RECEIPT = "PAYMENT_RECEIPT", "Payment Receipt / Deposit Slip"
    CONTRACT_DOCUMENT = "CONTRACT_DOCUMENT", "Contract / Agreement Document"
    CUSTOMER_DOCUMENT = "CUSTOMER_DOCUMENT", "Customer Identity / KYC Document"
    GENERAL = "GENERAL", "General Attachment"


class RelatedEntityType(models.TextChoices):
    WORK_ORDER = "work_order", "Work Order"
    SERVICE_REQUEST = "service_request", "Service Request"
    CUSTOMER = "customer", "Customer"
    CONTRACT = "contract", "Service Contract"
    INVOICE = "invoice", "Invoice"
    PAYMENT = "payment", "Payment"
    GENERAL = "general", "General"


def attachment_upload_path(instance, filename):
    """
    Computes a clean, collision-free, directory-traversal-safe file path:
    attachments/<entity_type>/%Y/%m/<uuid>_<sanitized_filename>
    """
    clean_name = os.path.basename(filename).replace(" ", "_")
    unique_prefix = uuid.uuid4().hex[:8]
    unique_name = f"{unique_prefix}_{clean_name}"
    entity_dir = getattr(instance, "related_entity_type", None) or "general"
    now = timezone.now()
    return f"attachments/{entity_dir}/{now:%Y}/{now:%m}/{unique_name}"


class Attachment(BaseModel):
    """
    Universal binary attachment record storing photos, diagnostic sheets,
    signed job agreements, and payment slips linked across business entities.
    """

    file = models.FileField(
        upload_to=attachment_upload_path,
        help_text="Binary file stored on disk or storage bucket",
    )
    file_name = models.CharField(
        max_length=255,
        help_text="Original uploaded filename (e.g., 'chiller_pressure_log.pdf')",
    )
    file_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="Detected MIME content-type (e.g., 'image/jpeg', 'application/pdf')",
    )
    file_size_bytes = models.PositiveIntegerField(
        default=0,
        help_text="Physical file size in bytes",
    )
    attachment_type = models.CharField(
        max_length=30,
        choices=AttachmentType.choices,
        default=AttachmentType.GENERAL,
        db_index=True,
        help_text="Operational classification of this document",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional remarks, caption, or diagnosis note",
    )
    related_entity_type = models.CharField(
        max_length=50,
        choices=RelatedEntityType.choices,
        default=RelatedEntityType.GENERAL,
        db_index=True,
        help_text="Domain model category this file links to",
    )
    related_entity_id = models.UUIDField(
        db_index=True,
        help_text="UUID primary key of the associated entity instance",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entity_attachments",
        help_text="User account that uploaded this document",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Attachment"
        verbose_name_plural = "Attachments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["related_entity_type", "related_entity_id"]),
            models.Index(fields=["uploaded_by", "-created_at"]),
            models.Index(fields=["attachment_type", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.attachment_type} - {self.related_entity_type}:{self.related_entity_id})"

    @property
    def file_size_display(self) -> str:
        """Formatted human-readable size string (e.g. '2.4 MB', '450 KB')."""
        bytes_val = self.file_size_bytes
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        return f"{bytes_val / (1024 * 1024):.2f} MB"
