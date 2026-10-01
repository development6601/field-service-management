from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class NotificationType(models.TextChoices):
    WORK_ORDER_ASSIGNED = "WORK_ORDER_ASSIGNED", "Work Order Assigned"
    WORK_ORDER_STATUS_CHANGED = "WORK_ORDER_STATUS_CHANGED", "Work Order Status Changed"
    WORK_ORDER_COMPLETED = "WORK_ORDER_COMPLETED", "Work Order Completed"
    SERVICE_REQUEST_CREATED = "SERVICE_REQUEST_CREATED", "Service Request Created"
    INVOICE_GENERATED = "INVOICE_GENERATED", "Invoice Generated"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Payment Received"
    LOW_STOCK_ALERT = "LOW_STOCK_ALERT", "Low Stock Alert"
    CONTRACT_EXPIRING = "CONTRACT_EXPIRING", "Contract Expiring"
    GENERAL = "GENERAL", "General Notification"


class NotificationPriority(models.TextChoices):
    LOW = "LOW", "Low"
    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


class Notification(BaseModel):
    """
    Core persistence entity for automated user alerts and event dispatches.
    Encapsulates recipient targeting, urgency classification, read states, and entity linkages.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="Target user receiving this notification alert.",
    )
    title = models.CharField(
        max_length=255,
        help_text="Short alert headline or subject.",
    )
    message = models.TextField(
        help_text="Detailed notification body or action context.",
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
        db_index=True,
        help_text="Category of business event triggering this notification.",
    )
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        db_index=True,
        help_text="Urgency ranking of the notification.",
    )
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether the recipient has acknowledged/read this notification.",
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the notification was marked as read.",
    )
    related_entity_type = models.CharField(
        max_length=50,
        blank=True,
        help_text="Name of the associated model entity (e.g., 'work_order', 'invoice', 'part').",
    )
    related_entity_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID primary key of the associated model entity.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        indexes = [
            models.Index(fields=["recipient", "is_read"]),
            models.Index(fields=["recipient", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.priority}] {self.recipient.email} - {self.title}"

    def mark_as_read(self):
        """Marks the notification as read with a timestamp."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at", "updated_at"])
