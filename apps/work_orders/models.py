import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.core.models import BaseModel


class WorkOrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft / Unassigned"
    ASSIGNED = "ASSIGNED", "Assigned"
    SCHEDULED = "SCHEDULED", "Scheduled"
    ACCEPTED = "ACCEPTED", "Accepted"
    TRAVELING = "TRAVELING", "Traveling"
    ARRIVED = "ARRIVED", "Arrived"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    ON_HOLD = "ON_HOLD", "On Hold"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    REJECTED = "REJECTED", "Rejected"


class WorkOrderPriority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    CRITICAL = "CRITICAL", "Critical"


ALLOWED_WO_TRANSITIONS = {
    WorkOrderStatus.DRAFT: [WorkOrderStatus.ASSIGNED, WorkOrderStatus.SCHEDULED, WorkOrderStatus.CANCELLED],
    WorkOrderStatus.ASSIGNED: [
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.TRAVELING,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.REJECTED,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.SCHEDULED: [
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.TRAVELING,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.REJECTED,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.ACCEPTED: [
        WorkOrderStatus.TRAVELING,
        WorkOrderStatus.ARRIVED,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.TRAVELING: [
        WorkOrderStatus.ARRIVED,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.ARRIVED: [
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.IN_PROGRESS: [
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.COMPLETED,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.ON_HOLD: [
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.REJECTED: [
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.CANCELLED,
    ],
    WorkOrderStatus.COMPLETED: [],
    WorkOrderStatus.CANCELLED: [],
}


class WorkOrder(BaseModel):
    """
    Operational field job card dispatched to a technician.
    Manages scheduling, labor execution, status transitions, and parent ticket linkage.
    """

    work_order_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Human-readable tracking identifier (e.g. WO-20260924-A1B2C3)",
    )
    service_request = models.ForeignKey(
        "service_requests.ServiceRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        help_text="Parent service ticket this work order was generated from (if applicable)",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="work_orders",
        help_text="Customer company or account being serviced",
    )
    service_location = models.ForeignKey(
        "customers.ServiceLocation",
        on_delete=models.PROTECT,
        related_name="work_orders",
        help_text="Job site where the technician must report",
    )
    service_type = models.ForeignKey(
        "services.ServiceType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        help_text="Specific service SKU / maintenance task being performed",
    )
    service_contract = models.ForeignKey(
        "contracts.ServiceContract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        help_text="Parent maintenance contract (if this is an AMC / preventive visit)",
    )
    is_preventive_maintenance = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Flag indicating scheduled periodic preventive maintenance under a contract",
    )
    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_work_orders",
        help_text="Field technician responsible for executing the job (must have role=TECHNICIAN)",
    )

    status = models.CharField(
        max_length=20,
        choices=WorkOrderStatus.choices,
        default=WorkOrderStatus.DRAFT,
        db_index=True,
        help_text="Current state in the work order lifecycle state machine",
    )
    priority = models.CharField(
        max_length=20,
        choices=WorkOrderPriority.choices,
        default=WorkOrderPriority.MEDIUM,
        db_index=True,
        help_text="Urgency level for scheduling prioritization",
    )

    title = models.CharField(max_length=255, help_text="Short title of the job card")
    description = models.TextField(blank=True, help_text="Detailed problem summary and scope of work")
    job_instructions = models.TextField(
        blank=True,
        help_text="Technical notes, access codes, PPE requirements, safety precautions",
    )

    # Scheduling Timestamps
    scheduled_start = models.DateTimeField(null=True, blank=True, help_text="Scheduled job start time")
    scheduled_end = models.DateTimeField(null=True, blank=True, help_text="Scheduled job completion time")

    # Actual Execution Timestamps
    actual_start = models.DateTimeField(null=True, blank=True, help_text="Timestamp when technician clicked start")
    actual_end = models.DateTimeField(null=True, blank=True, help_text="Timestamp when job was finished")

    estimated_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Expected duration in minutes for scheduling planning",
    )
    labor_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Actual billable labor hours logged",
    )

    hold_reason = models.TextField(blank=True, help_text="Explanation if job is put ON_HOLD")
    cancellation_reason = models.TextField(blank=True, help_text="Explanation if job is CANCELLED")
    rejection_reason = models.TextField(blank=True, help_text="Explanation if job is REJECTED by technician")

    # Live Tracking & Travel Timestamps
    travel_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when technician started traveling to site",
    )
    arrived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when technician reached customer site",
    )

    # Resolution & Sign-off Fields
    service_summary = models.TextField(
        blank=True,
        help_text="Technical summary of diagnosis, repair, or service rendered",
    )
    customer_signature = models.TextField(
        blank=True,
        help_text="Base64 encoded digital signature image string",
    )
    signed_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of client/representative who signed",
    )
    signed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when digital signature was captured",
    )
    customer_rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Customer satisfaction rating from 1 to 5",
    )
    customer_feedback = models.TextField(
        blank=True,
        help_text="Customer remarks or feedback",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_work_orders",
    )

    class Meta:
        verbose_name = "Work Order"
        verbose_name_plural = "Work Orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["assigned_technician", "status"]),
            models.Index(fields=["scheduled_start", "scheduled_end"]),
        ]

    def __str__(self):
        return f"{self.work_order_number} - {self.title} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        # Verify location belongs to customer
        if self.service_location and self.customer:
            if self.service_location.customer_id != self.customer_id:
                raise ValidationError({
                    "service_location": "The selected service location does not belong to the chosen customer."
                })

        # Verify assigned technician role is TECHNICIAN
        if self.assigned_technician:
            if self.assigned_technician.role != UserRole.TECHNICIAN:
                raise ValidationError({
                    "assigned_technician": f"User '{self.assigned_technician.email}' has role '{self.assigned_technician.role}'. Only users with role TECHNICIAN can be assigned to work orders."
                })

        # Verify scheduled time ordering
        if self.scheduled_start and self.scheduled_end:
            if self.scheduled_end <= self.scheduled_start:
                raise ValidationError({
                    "scheduled_end": "Scheduled end time must be after scheduled start time."
                })

        # Verify actual time ordering
        if self.actual_start and self.actual_end:
            if self.actual_end < self.actual_start:
                raise ValidationError({
                    "actual_end": "Actual end time cannot be earlier than actual start time."
                })

    def save(self, *args, **kwargs):
        # Auto-generate tracking number
        if not self.work_order_number:
            now = timezone.now()
            short_id = uuid.uuid4().hex[:6].upper()
            self.work_order_number = f"WO-{now.strftime('%Y%m%d')}-{short_id}"

        # Auto-promote DRAFT to ASSIGNED / SCHEDULED when technician & timing are provided
        if self.status == WorkOrderStatus.DRAFT and self.assigned_technician:
            if self.scheduled_start:
                self.status = WorkOrderStatus.SCHEDULED
            else:
                self.status = WorkOrderStatus.ASSIGNED

        self.full_clean()
        super().save(*args, **kwargs)

    def can_transition_to(self, target_status: str) -> bool:
        """Verifies if the transition is allowed by the state machine."""
        allowed = ALLOWED_WO_TRANSITIONS.get(self.status, [])
        return target_status in allowed

    def transition_to(self, target_status: str, user=None, notes="", reason=""):
        """
        Executes a formal state machine transition, records audit trail in WorkOrderHistory,
        and sets execution timestamps.
        """
        if not self.can_transition_to(target_status):
            raise ValidationError(
                f"Invalid transition from '{self.status}' to '{target_status}'. "
                f"Allowed transitions: {ALLOWED_WO_TRANSITIONS.get(self.status, [])}"
            )

        old_status = self.status
        self.status = target_status
        now = timezone.now()

        if target_status == WorkOrderStatus.TRAVELING:
            if not self.travel_started_at:
                self.travel_started_at = now

        elif target_status == WorkOrderStatus.ARRIVED:
            if not self.arrived_at:
                self.arrived_at = now

        elif target_status == WorkOrderStatus.IN_PROGRESS:
            if not self.actual_start:
                self.actual_start = now

        elif target_status == WorkOrderStatus.COMPLETED:
            if not self.actual_end:
                self.actual_end = now
            # Compute labor hours if actual_start is set and labor_hours not manually logged
            if self.actual_start and self.labor_hours == Decimal("0.00"):
                diff_seconds = (self.actual_end - self.actual_start).total_seconds()
                hours = Decimal(str(round(diff_seconds / 3600.0, 2)))
                self.labor_hours = max(hours, Decimal("0.25"))  # Minimum 15 mins

        elif target_status == WorkOrderStatus.REJECTED:
            if reason or notes:
                self.rejection_reason = reason or notes

        elif target_status == WorkOrderStatus.ON_HOLD:
            if reason or notes:
                self.hold_reason = reason or notes

        elif target_status == WorkOrderStatus.CANCELLED:
            if reason or notes:
                self.cancellation_reason = reason or notes

        self.save()

        # Audit history log
        WorkOrderHistory.objects.create(
            work_order=self,
            changed_by=user,
            from_status=old_status,
            to_status=target_status,
            notes=notes,
        )


class WorkOrderHistory(BaseModel):
    """
    Audit trail recording every state change and dispatcher note on a work order.
    """

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="history",
        help_text="Work order this audit log belongs to",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_order_history_entries",
    )
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Work Order History"
        verbose_name_plural = "Work Order History"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.work_order.work_order_number}: {self.from_status} -> {self.to_status} ({self.created_at})"
