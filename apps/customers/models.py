from django.conf import settings
from django.db import models
from apps.core.models import BaseModel


class Customer(BaseModel):
    """
    Customer entity representing either a B2B business client
    or an individual B2C homeowner.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
        help_text="Optional linked portal login user",
    )
    company_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Company name for corporate accounts",
    )
    primary_contact_name = models.CharField(
        max_length=150,
        help_text="Full name of the primary contact person",
    )
    email = models.EmailField(
        db_index=True,
        help_text="Billing and primary notification email",
    )
    phone = models.CharField(
        max_length=20,
        db_index=True,
        help_text="Primary contact phone number",
    )
    billing_address = models.TextField(
        blank=True,
        help_text="Official billing address for invoice generation",
    )
    tax_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="GST / Tax Identification Number",
    )
    notes = models.TextField(blank=True, help_text="Internal account management notes")

    class Meta:
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "phone"]),
            models.Index(fields=["company_name"]),
        ]

    def __str__(self):
        if self.company_name:
            return f"{self.company_name} ({self.primary_contact_name})"
        return self.primary_contact_name

    @property
    def display_name(self):
        return self.company_name or self.primary_contact_name


class ServiceLocation(BaseModel):
    """
    Physical address location where service requests and work orders take place.
    One Customer can have multiple service locations (branches, facilities, sites).
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="service_locations",
        help_text="Customer who owns or manages this site",
    )
    location_name = models.CharField(
        max_length=150,
        help_text="Descriptive title e.g. Main Plant, Downtown Office, Home",
    )
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, db_index=True)
    country = models.CharField(max_length=100, default="India")

    # Geocoding coordinates for technician dispatch and distance calculation
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="GPS Latitude for routing",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="GPS Longitude for routing",
    )

    contact_person = models.CharField(
        max_length=150,
        blank=True,
        help_text="On-site contact person if different from customer",
    )
    contact_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="On-site phone number",
    )
    access_instructions = models.TextField(
        blank=True,
        help_text="Gate codes, security clearance, parking instructions",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Flag indicating the primary or headquarters location",
    )

    class Meta:
        verbose_name = "Service Location"
        verbose_name_plural = "Service Locations"
        ordering = ["-is_primary", "-created_at"]
        indexes = [
            models.Index(fields=["customer", "city"]),
            models.Index(fields=["postal_code"]),
        ]

    def __str__(self):
        return f"{self.customer.display_name} - {self.location_name} ({self.city})"
