from django.contrib import admin
from .models import ServiceCategory, ServiceType


class ServiceTypeInline(admin.TabularInline):
    model = ServiceType
    extra = 1
    fields = ("name", "code", "base_price", "estimated_duration_minutes", "required_skill", "is_active")


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")
    list_filter = ("is_active",)
    prepopulated_fields = {"code": ("name",)}
    inlines = [ServiceTypeInline]


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "code", "base_price", "estimated_duration_minutes", "required_skill", "is_active")
    list_filter = ("category", "is_active", "required_skill")
    search_fields = ("name", "code", "category__name")
    prepopulated_fields = {"code": ("name",)}
