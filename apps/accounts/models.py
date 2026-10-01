from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel
from .managers import CustomUserManager


class UserRole(models.TextChoices):
    """Enumeration for system user roles."""

    ADMIN = "ADMIN", "Admin"
    DISPATCHER = "DISPATCHER", "Dispatcher"
    TECHNICIAN = "TECHNICIAN", "Technician"
    MANAGER = "MANAGER", "Manager"
    CUSTOMER = "CUSTOMER", "Customer"


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    """
    Custom User model with email authentication, UUID primary key,
    and enterprise role-based assignment.
    """

    email = models.EmailField(
        unique=True,
        db_index=True,
        help_text="Primary email address used for login",
    )
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Primary contact phone number",
    )
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True,
        help_text="Primary access role in the FSM system",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Designates whether the user can log into the admin site",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this user account is currently active",
    )
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = CustomUserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "role"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name or self.email

    @property
    def is_technician(self):
        return self.role == UserRole.TECHNICIAN

    @property
    def is_dispatcher(self):
        return self.role == UserRole.DISPATCHER

    @property
    def is_manager(self):
        return self.role == UserRole.MANAGER

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_customer(self):
        return self.role == UserRole.CUSTOMER


class TechnicianProfile(BaseModel):
    """
    Profile extension for field technicians.
    Stores operational metadata including skills, availability, and GPS coordinates.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="technician_profile",
        limit_choices_to={"role": UserRole.TECHNICIAN},
    )
    skills = models.JSONField(
        default=list,
        blank=True,
        help_text="List of technician skills e.g. ['HVAC', 'Electrical', 'Plumbing']",
    )
    is_available = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Real-time availability flag for dispatch scheduling",
    )
    working_hours_start = models.TimeField(
        default="09:00:00",
        help_text="Daily shift start time (e.g. 09:00:00)",
    )
    working_hours_end = models.TimeField(
        default="18:00:00",
        help_text="Daily shift end time (e.g. 18:00:00)",
    )
    current_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Current GPS Latitude",
    )
    current_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Current GPS Longitude",
    )
    emergency_contact = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True, help_text="Internal notes regarding technician")

    class Meta:
        verbose_name = "Technician Profile"
        verbose_name_plural = "Technician Profiles"

    def __str__(self):
        return f"Technician: {self.user.full_name}"
