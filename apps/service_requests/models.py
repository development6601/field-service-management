import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class RequestPriority(models.TextChoices):
    LOW = "LOW", "Low (Routine / Maintenance)"
    MEDIUM = "MEDIUM", "Medium (Standard Issue)"
    HIGH = "HIGH", "High (Urgent / Business Impaired)"
    CRITICAL = "CRITICAL", "Critical (Emergency / Facility Down)"


class RequestStatus(models.TextChoices):
    NEW = "NEW", "New / Submitted"
    REVIEWED = "REVIEWED", "Reviewed / Triaged"
    SCHEDULED = "SCHEDULED", "Scheduled"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    CLOSED = "CLOSED", "Closed"
    CANCELLED = "CANCELLED", "Cancelled"


# Standard SLA response and resolution targets in hours
SLA_HOURS_MATRIX = {
    RequestPriority.CRITICAL: {"response_hours": 1, "resolution_hours": 4},
    RequestPriority.HIGH: {"response_hours": 2, "resolution_hours": 12},
    RequestPriority.MEDIUM: {"response_hours": 4, "resolution_hours": 24},
    RequestPriority.LOW: {"response_hours": 24, "resolution_hours": 72},
}

# Strict state transition matrix to prevent invalid skips
ALLOWED_STATUS_TRANSITIONS = {
    RequestStatus.NEW: [RequestStatus.REVIEWED, RequestStatus.CANCELLED],
    RequestStatus.REVIEWED: [RequestStatus.SCHEDULED, RequestStatus.CANCELLED],
    RequestStatus.SCHEDULED: [RequestStatus.ASSIGNED, RequestStatus.CANCELLED],
    RequestStatus.ASSIGNED: [RequestStatus.IN_PROGRESS, RequestStatus.CANCELLED],
    RequestStatus.IN_PROGRESS: [RequestStatus.COMPLETED, RequestStatus.CANCELLED],
    RequestStatus.COMPLETED: [RequestStatus.CLOSED],
    RequestStatus.CLOSED: [],
    RequestStatus.CANCELLED: [],
}


class ServiceRequest(BaseModel):
    """
    Core customer intake model representing a problem report or service ticket.
    Encapsulates lifecycle transitions, priority scoring, and SLA tracking.
    """

    request_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Human-readable tracking identifier (e.g. SR-20260923-A1B2C3)",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="service_requests",
        help_text="Customer company or entity raising the service ticket",
    )
    service_location = models.ForeignKey(
        "customers.ServiceLocation",
        on_delete=models.PROTECT,
        related_name="service_requests",
        help_text="Physical branch or job site where service is required",
    )
    service_type = models.ForeignKey(
        "services.ServiceType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
        help_text="Primary category of service requested (HVAC, Electrical, Plumbing, etc.)",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_service_requests",
        help_text="User who submitted this service request",
    )

    title = models.CharField(max_length=255, help_text="Concise summary of the reported issue")
    description = models.TextField(help_text="Detailed description of symptoms, fault codes, or equipment")
    priority = models.CharField(
        max_length=20,
        choices=RequestPriority.choices,
        default=RequestPriority.MEDIUM,
        db_index=True,
        help_text="Urgency level determining automated SLA response and resolution deadlines",
    )
    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.NEW,
        db_index=True,
        help_text="Current state in the request lifecycle state machine",
    )

    preferred_date = models.DateField(null=True, blank=True, help_text="Customer's requested service date")
    preferred_time_slot = models.CharField(
        max_length=50,
        blank=True,
        help_text="Preferred time window (e.g. '09:00 - 13:00' or 'Afternoon')",
    )

    # SLA Target Timers
    sla_response_due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Calculated deadline for dispatcher review/first response",
    )
    sla_resolution_due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Calculated deadline for field resolution",
    )

    # Triage and Review metadata
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_service_requests",
        help_text="Dispatcher or manager who triaged this ticket",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    dispatcher_notes = models.TextField(
        blank=True,
        help_text="Internal dispatcher/scheduling notes (not visible to customer)",
    )
    cancellation_reason = models.TextField(blank=True, help_text="Reason recorded if request was cancelled")

    class Meta:
        verbose_name = "Service Request"
        verbose_name_plural = "Service Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["priority", "status"]),
            models.Index(fields=["sla_resolution_due_at"]),
        ]

    def __str__(self):
        return f"{self.request_number} - {self.title} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        # Verify that service_location belongs to customer
        if self.service_location_id and self.customer_id:
            if self.service_location.customer_id != self.customer_id:
                raise ValidationError({
                    "service_location": "The selected service location does not belong to the chosen customer."
                })

    def save(self, *args, **kwargs):
        # Auto-generate tracking number if missing
        if not self.request_number:
            now = timezone.now()
            short_id = uuid.uuid4().hex[:6].upper()
            self.request_number = f"SR-{now.strftime('%Y%m%d')}-{short_id}"

        # Calculate SLA target dates if not set or priority changed
        if not self.sla_response_due_at or not self.sla_resolution_due_at:
            self.calculate_sla_targets()

        self.full_clean()
        super().save(*args, **kwargs)

    def calculate_sla_targets(self, base_time=None):
        """Calculates SLA deadlines based on priority matrix."""
        reference_time = base_time or self.created_at or timezone.now()
        matrix = SLA_HOURS_MATRIX.get(self.priority, SLA_HOURS_MATRIX[RequestPriority.MEDIUM])
        self.sla_response_due_at = reference_time + timedelta(hours=matrix["response_hours"])
        self.sla_resolution_due_at = reference_time + timedelta(hours=matrix["resolution_hours"])

    @property
    def is_sla_breached(self) -> bool:
        """Determines if the resolution SLA has been breached."""
        if self.status in [RequestStatus.COMPLETED, RequestStatus.CLOSED, RequestStatus.CANCELLED]:
            return False
        if self.sla_resolution_due_at and timezone.now() > self.sla_resolution_due_at:
            return True
        return False

    def can_transition_to(self, target_status: str) -> bool:
        """Checks whether the requested status transition is valid according to the state machine."""
        allowed = ALLOWED_STATUS_TRANSITIONS.get(self.status, [])
        return target_status in allowed

    def transition_to(self, target_status: str, user=None, notes=None, reason=None):
        """
        Executes a formal state machine transition, saving audit details.
        Raises ValidationError if transition is invalid.
        """
        if not self.can_transition_to(target_status):
            raise ValidationError(
                f"Invalid state transition from '{self.status}' to '{target_status}'. "
                f"Allowed transitions: {ALLOWED_STATUS_TRANSITIONS.get(self.status, [])}"
            )

        self.status = target_status
        now = timezone.now()

        if target_status == RequestStatus.REVIEWED:
            self.reviewed_by = user
            self.reviewed_at = now
            if notes:
                self.dispatcher_notes = notes

        elif target_status == RequestStatus.CANCELLED:
            if reason:
                self.cancellation_reason = reason

        self.save()


class RequestAttachment(BaseModel):
    """
    Stores photo evidence, fault logs, diagrams, or PDF attachments
    uploaded for a service request.
    """

    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="attachments",
        help_text="Service request this attachment belongs to",
    )
    file = models.FileField(
        upload_to="service_requests/attachments/%Y/%m/",
        help_text="Uploaded photo or document",
    )
    file_name = models.CharField(max_length=255, help_text="Original file name")
    file_type = models.CharField(max_length=100, blank=True, help_text="MIME type or file extension")
    file_size_bytes = models.PositiveIntegerField(default=0, help_text="Size of the file in bytes")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_attachments",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional description (e.g. 'Fault display error E-04' or 'Water leak on pipe 2')",
    )

    class Meta:
        verbose_name = "Request Attachment"
        verbose_name_plural = "Request Attachments"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.service_request.request_number})"
