from rest_framework import serializers
from apps.services.models import ServiceCategory, ServiceType


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "code", "description", "is_active"]


class ServiceTypeSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = ServiceType
        fields = [
            "id",
            "category",
            "category_name",
            "name",
            "code",
            "description",
            "base_price",
            "estimated_duration_minutes",
            "required_skill",
            "is_active",
        ]
