from django.db import models
from apps.core.models import BaseModel


class ServiceCategory(BaseModel):
    """
    Broad category grouping for services (e.g., HVAC, Electrical, Plumbing, IT Networking).
    """

    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Short unique identifier code e.g. HVAC, ELEC, PLUMB",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Service Category"
        verbose_name_plural = "Service Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ServiceType(BaseModel):
    """
    Specific billable service or maintenance task.
    Defines baseline pricing, estimated duration, and technician skill requirements.
    """

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="services",
        help_text="Parent category (Protected from deletion if active services exist)",
    )
    name = models.CharField(max_length=150)
    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Unique SKU/Service identifier e.g. AC-COMPRESSOR-REPAIR",
    )
    description = models.TextField(blank=True)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Base standard service fee in currency units (INR)",
    )
    estimated_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Expected job duration in minutes for scheduling calculations",
    )
    required_skill = models.CharField(
        max_length=100,
        blank=True,
        help_text="Matching skill requirement for technician dispatching e.g. HVAC, Electrical",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Service Type"
        verbose_name_plural = "Service Types"
        ordering = ["category", "name"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["required_skill"]),
        ]

    def __str__(self):
        return f"{self.category.name} - {self.name} ({self.code})"
