from decimal import Decimal
from django.db import transaction
from rest_framework import serializers
from .models import Customer, ServiceLocation


class ServiceLocationSerializer(serializers.ModelSerializer):
    """
    Serializer for physical service sites and branch locations.
    Enforces strict geographical coordinate validations.
    """

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)

    class Meta:
        model = ServiceLocation
        fields = [
            "id",
            "customer",
            "customer_name",
            "location_name",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "country",
            "latitude",
            "longitude",
            "contact_person",
            "contact_phone",
            "access_instructions",
            "is_primary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "customer": {"required": False},  # Can be inferred from URL context
        }

    def validate_latitude(self, value):
        if value is not None and not (Decimal("-90.0") <= value <= Decimal("90.0")):
            raise serializers.ValidationError("Latitude must be between -90.0 and 90.0 degrees.")
        return value

    def validate_longitude(self, value):
        if value is not None and not (Decimal("-180.0") <= value <= Decimal("180.0")):
            raise serializers.ValidationError("Longitude must be between -180.0 and 180.0 degrees.")
        return value


class CustomerSerializer(serializers.ModelSerializer):
    """
    Complete representation of a Customer account, including
    nested service locations and summary counts.
    """

    service_locations = ServiceLocationSerializer(many=True, read_only=True)
    locations_count = serializers.IntegerField(source="service_locations.count", read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "user",
            "company_name",
            "primary_contact_name",
            "display_name",
            "email",
            "phone",
            "billing_address",
            "tax_id",
            "notes",
            "locations_count",
            "service_locations",
            "created_at",
            "updated_at",
        ]
class NestedInitialLocationSerializer(serializers.ModelSerializer):
    """Nested serializer for Customer intake (parent customer is automatically linked)."""

    latitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
        min_value=Decimal("-90.0"),
        max_value=Decimal("90.0"),
        default=Decimal("19.076000"),
    )
    longitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
        min_value=Decimal("-180.0"),
        max_value=Decimal("180.0"),
        default=Decimal("72.877700"),
    )

    class Meta:
        model = ServiceLocation
        fields = [
            "location_name",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "country",
            "latitude",
            "longitude",
            "contact_person",
            "contact_phone",
            "access_instructions",
        ]


class CustomerCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating customer accounts.
    Supports optional initial primary service location in a single atomic transaction.
    """

    initial_location = NestedInitialLocationSerializer(required=False, write_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "company_name",
            "primary_contact_name",
            "email",
            "phone",
            "billing_address",
            "tax_id",
            "notes",
            "initial_location",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        initial_location_data = validated_data.pop("initial_location", None)

        with transaction.atomic():
            customer = Customer.objects.create(**validated_data)

            # If initial location provided, create it as the primary site
            if initial_location_data:
                initial_location_data["is_primary"] = True
                ServiceLocation.objects.create(customer=customer, **initial_location_data)

            return customer
