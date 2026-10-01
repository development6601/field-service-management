from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.accounts.models import UserRole
from apps.core.models import BaseModel


class LeaveType(models.TextChoices):
    VACATION = "VACATION", "Vacation / Paid Leave"
    SICK = "SICK", "Sick Leave"
    EMERGENCY = "EMERGENCY", "Emergency Leave"
    TRAINING = "TRAINING", "Training / Certification"
    PERSONAL = "PERSONAL", "Personal Leave"


class LeaveStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Approval"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class TechnicianLeave(BaseModel):
    """
    Tracks planned time off, vacations, sick leaves, and training days for technicians.
    Scheduling engine intercepts assignments falling within approved leave dates.
    """

    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="leaves",
        help_text="Technician taking time off",
    )
    leave_type = models.CharField(
        max_length=20,
        choices=LeaveType.choices,
        default=LeaveType.VACATION,
    )
    start_date = models.DateField(help_text="First date of leave (inclusive)")
    end_date = models.DateField(help_text="Last date of leave (inclusive)")
    reason = models.TextField(blank=True, help_text="Optional description for the leave request")
    status = models.CharField(
        max_length=20,
        choices=LeaveStatus.choices,
        default=LeaveStatus.APPROVED,
        db_index=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_technician_leaves",
    )

    class Meta:
        verbose_name = "Technician Leave"
        verbose_name_plural = "Technician Leaves"
        ordering = ["-start_date"]
        indexes = [
            models.Index(fields=["technician", "status"]),
            models.Index(fields=["start_date", "end_date"]),
        ]

    def __str__(self):
        return f"{self.technician.full_name}: {self.get_leave_type_display()} ({self.start_date} to {self.end_date})"

    def clean(self):
        super().clean()
        if self.technician and self.technician.role != UserRole.TECHNICIAN:
            raise ValidationError({"technician": "Leaves can only be recorded for users with role TECHNICIAN."})

        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValidationError({"end_date": "End date cannot be earlier than start date."})


class ScheduleOverrideLog(BaseModel):
    """
    Audit log recorded whenever a dispatcher or manager explicitly overrides
    a scheduling conflict (e.g. emergency hospital repair).
    """

    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.CASCADE,
        related_name="schedule_overrides",
        help_text="Work order scheduled with an intentional override",
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="technician_overrides",
        help_text="Technician who received the conflicting schedule",
    )
    overridden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authorized_overrides",
        help_text="Dispatcher or administrator who authorized the override",
    )
    conflict_details = models.JSONField(
        default=dict,
        help_text="Snapshot of the conflicts detected prior to override",
    )
    override_reason = models.TextField(
        help_text="Mandatory business justification for forcing the scheduling override",
    )

    class Meta:
        verbose_name = "Schedule Override Log"
        verbose_name_plural = "Schedule Override Logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Override on {self.work_order.work_order_number} by {self.overridden_by.full_name} ({self.created_at})"
