from django.contrib import admin
from .models import Customer, ServiceLocation


class ServiceLocationInline(admin.StackedInline):
    model = ServiceLocation
    extra = 1
    fields = ("location_name", "address_line1", "city", "state", "postal_code", "is_primary")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "primary_contact_name", "email", "phone", "created_at")
    search_fields = ("company_name", "primary_contact_name", "email", "phone")
    list_filter = ("created_at",)
    inlines = [ServiceLocationInline]


@admin.register(ServiceLocation)
class ServiceLocationAdmin(admin.ModelAdmin):
    list_display = ("location_name", "customer", "city", "state", "postal_code", "is_primary")
    list_filter = ("city", "state", "is_primary")
    search_fields = ("location_name", "customer__company_name", "customer__primary_contact_name", "address_line1", "city")
