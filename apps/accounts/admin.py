from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, TechnicianProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name", "phone_number")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        ("Permissions & Roles", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "role", "password", "first_name", "last_name"),
        }),
    )


@admin.register(TechnicianProfile)
class TechnicianProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_available", "working_hours_start", "working_hours_end", "emergency_contact")
    list_filter = ("is_available",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "skills")
