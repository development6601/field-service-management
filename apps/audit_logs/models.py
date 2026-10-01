import uuid
from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    # Work Orders
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED", "Work Order Created"
    WORK_ORDER_ASSIGNED = "WORK_ORDER_ASSIGNED", "Work Order Assigned"
    WORK_ORDER_STATUS_CHANGED = "WORK_ORDER_STATUS_CHANGED", "Work Order Status Changed"
    WORK_ORDER_RESCHEDULED = "WORK_ORDER_RESCHEDULED", "Work Order Rescheduled"

    # Service Requests
    SERVICE_REQUEST_CREATED = "SERVICE_REQUEST_CREATED", "Service Request Created"
    SERVICE_REQUEST_REVIEWED = "SERVICE_REQUEST_REVIEWED", "Service Request Reviewed"
    SERVICE_REQUEST_CANCELLED = "SERVICE_REQUEST_CANCELLED", "Service Request Cancelled"

    # Billing & Financial
    INVOICE_GENERATED = "INVOICE_GENERATED", "Invoice Generated"
    INVOICE_ISSUED = "INVOICE_ISSUED", "Invoice Issued"
    INVOICE_CANCELLED = "INVOICE_CANCELLED", "Invoice Cancelled"
    PAYMENT_RECORDED = "PAYMENT_RECORDED", "Payment Recorded"

    # Inventory
    STOCK_ADJUSTED = "STOCK_ADJUSTED", "Stock Quantity Adjusted"
    PARTS_TRANSFERRED = "PARTS_TRANSFERRED", "Parts Transferred"

    # Contracts
    CONTRACT_ACTIVATED = "CONTRACT_ACTIVATED", "Service Contract Activated"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED", "Service Contract Terminated"

    # Users & Permissions
    USER_CREATED = "USER_CREATED", "User Account Created"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED", "User Role Changed"
    USER_DEACTIVATED = "USER_DEACTIVATED", "User Deactivated"

    # General
    GENERAL_ACTION = "GENERAL_ACTION", "General System Action"


class AuditLog(models.Model):
    """
    Immutable, append-only operational audit ledger tracking system modifications,
    state transitions, financial events, and user activities.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique UUIDv4 identifier for the audit event",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text="User who initiated or authorized this action",
    )
    actor_email = models.EmailField(
        max_length=255,
        blank=True,
        help_text="Cached email of the actor (retained even if user is deleted)",
    )
    actor_role = models.CharField(
        max_length=50,
        blank=True,
        help_text="Cached role of the actor at the moment of the action",
    )
    action = models.CharField(
        max_length=100,
        choices=AuditAction.choices,
        db_index=True,
        help_text="Formal business action classification",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable summary of the event",
    )
    entity_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Target domain model name (e.g., 'work_order', 'invoice', 'stock_item')",
    )
    entity_id = models.UUIDField(
        db_index=True,
        help_text="Primary key UUID of the modified entity",
    )
    entity_repr = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable business identifier (e.g., 'WO-20260928-CF97F4')",
    )
    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured before/after diff of field modifications: {'field': {'old': ..., 'new': ...}}",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Remote IP address of the client making the request",
    )
    user_agent = models.TextField(
        blank=True,
        help_text="Browser/client User-Agent string for security auditing",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Exact UTC timestamp when the action occurred (immutable)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        actor_display = self.actor_email or "System"
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {actor_display} -> {self.action} on {self.entity_type}:{self.entity_repr or self.entity_id}"
