import calendar
import datetime
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class ContractStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    TERMINATED = "TERMINATED", "Terminated"
    CANCELLED = "CANCELLED", "Cancelled"


class ServiceFrequency(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly (Every Month)"
    BI_MONTHLY = "BI_MONTHLY", "Bi-Monthly (Every 2 Months)"
    QUARTERLY = "QUARTERLY", "Quarterly (Every 3 Months)"
    HALF_YEARLY = "HALF_YEARLY", "Half-Yearly (Every 6 Months)"
    ANNUALLY = "ANNUALLY", "Annually (Once a Year)"


def _add_months(source_date: datetime.date, months: int) -> datetime.date:
    """Exact calendar month addition preserving end-of-month boundaries."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def generate_contract_number() -> str:
    """Generates human-readable contract identifier (e.g. CNT-20260928-8F2B1A)."""
    date_str = timezone.now().strftime("%Y%m%d")
    random_hex = uuid.uuid4().hex[:6].upper()
    return f"CNT-{date_str}-{random_hex}"


class ServiceContract(BaseModel):
    """
    Annual Maintenance Contract (AMC) or Service Level Agreement (SLA)
    binding a client account to periodic preventive maintenance visits.
    """

    contract_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        default=generate_contract_number,
        help_text="Unique tracking identifier (e.g. CNT-20260928-8F2B1A)",
    )
    title = models.CharField(
        max_length=255,
        help_text="Contract title (e.g., Annual Chiller & HVAC Maintenance)",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="contracts",
        help_text="Client organization holding the maintenance agreement",
    )
    service_location = models.ForeignKey(
        "customers.ServiceLocation",
        on_delete=models.PROTECT,
        related_name="contracts",
        help_text="Physical facility covered under this contract",
    )
    covered_services = models.ManyToManyField(
        "services.ServiceType",
        blank=True,
        related_name="contracts",
        help_text="Service types included in this maintenance contract",
    )
    start_date = models.DateField(
        db_index=True,
        help_text="Contract commencement date",
    )
    end_date = models.DateField(
        db_index=True,
        help_text="Contract expiration date",
    )
    status = models.CharField(
        max_length=20,
        choices=ContractStatus.choices,
        default=ContractStatus.DRAFT,
        db_index=True,
        help_text="Current agreement status",
    )
    service_frequency = models.CharField(
        max_length=20,
        choices=ServiceFrequency.choices,
        default=ServiceFrequency.QUARTERLY,
        help_text="Frequency of scheduled preventive maintenance visits",
    )
    total_visits_allowed = models.PositiveIntegerField(
        default=4,
        help_text="Total number of service visits included in the contract quota",
    )
    visits_used = models.PositiveIntegerField(
        default=0,
        help_text="Number of completed maintenance visits consumed",
    )
    contract_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total monetary contract billing value",
    )
    sla_response_hours = models.PositiveIntegerField(
        default=24,
        help_text="Guaranteed SLA emergency breakdown response time in hours",
    )
    next_scheduled_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Projected date for the next periodic preventive maintenance visit",
    )
    terms_and_conditions = models.TextField(
        blank=True,
        help_text="Specific SLA clauses, warranty exclusions, or special terms",
    )
    termination_reason = models.TextField(
        blank=True,
        help_text="Mandatory justification note if contract is prematurely cancelled",
    )
    terminated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when contract was terminated",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_contracts",
        help_text="Staff member who created the contract record",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Service Contract"
        verbose_name_plural = "Service Contracts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.contract_number} - {self.title} ({self.customer.display_name})"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be prior to start date."})

        if hasattr(self, "service_location") and hasattr(self, "customer"):
            if self.service_location and self.customer and self.service_location.customer_id != self.customer_id:
                raise ValidationError({"service_location": "Service location must belong to the selected customer."})

    def save(self, *args, **kwargs):
        if not self.contract_number:
            self.contract_number = generate_contract_number()

        # If active and no next date set, initialize next_scheduled_date to start_date
        if self.status == ContractStatus.ACTIVE and not self.next_scheduled_date and self.start_date:
            self.next_scheduled_date = self.start_date

        super().save(*args, **kwargs)

    @property
    def visits_remaining(self) -> int:
        """Remaining visits in the contract quota."""
        return max(0, self.total_visits_allowed - self.visits_used)

    @property
    def is_expired(self) -> bool:
        """True if the contract expiration date has passed."""
        return timezone.localdate() > self.end_date

    @property
    def can_generate_visit(self) -> bool:
        """Whether a new preventive maintenance work order can be dispatched."""
        return (
            self.status == ContractStatus.ACTIVE
            and not self.is_expired
            and self.visits_remaining > 0
        )

    def calculate_next_date_from(self, base_date: datetime.date) -> datetime.date:
        """Calculates the subsequent scheduled maintenance date following a service cycle."""
        freq = self.service_frequency
        if freq == ServiceFrequency.WEEKLY:
            return base_date + datetime.timedelta(days=7)
        elif freq == ServiceFrequency.MONTHLY:
            return _add_months(base_date, 1)
        elif freq == ServiceFrequency.BI_MONTHLY:
            return _add_months(base_date, 2)
        elif freq == ServiceFrequency.QUARTERLY:
            return _add_months(base_date, 3)
        elif freq == ServiceFrequency.HALF_YEARLY:
            return _add_months(base_date, 6)
        elif freq == ServiceFrequency.ANNUALLY:
            return _add_months(base_date, 12)
        return _add_months(base_date, 3)
