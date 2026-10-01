import os
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceType
from .models import ServiceRequest, RequestAttachment, RequestPriority, RequestStatus

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_FILE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic"]


class RequestAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for photo and diagnostic document attachments."""

    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True)

    class Meta:
        model = RequestAttachment
        fields = [
            "id",
            "service_request",
            "file",
            "file_name",
            "file_type",
            "file_size_bytes",
            "uploaded_by",
            "uploaded_by_name",
            "description",
            "created_at",
        ]
        read_only_fields = ["id", "service_request", "file_name", "file_type", "file_size_bytes", "uploaded_by", "created_at"]

    def validate_file(self, file_obj):
        # Validate file size
        if file_obj.size > MAX_FILE_SIZE_BYTES:
            raise serializers.ValidationError(
                f"File size exceeds 10 MB limit ({file_obj.size / (1024 * 1024):.2f} MB provided)."
            )

        # Validate file extension
        ext = os.path.splitext(file_obj.name)[1].lower()
        if ext not in ALLOWED_FILE_EXTENSIONS:
            raise serializers.ValidationError(
                f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_FILE_EXTENSIONS)}"
            )

        return file_obj

    def create(self, validated_data):
        file_obj = validated_data["file"]
        validated_data["file_name"] = file_obj.name
        validated_data["file_size_bytes"] = file_obj.size
        ext = os.path.splitext(file_obj.name)[1].lower()
        validated_data["file_type"] = ext.lstrip(".")
        return super().create(validated_data)


class ServiceRequestCreateSerializer(serializers.ModelSerializer):
    """
    Intake serializer for submitting a new service request.
    Enforces customer and location matching and auto-computes SLA timers.
    """

    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.filter(is_deleted=False),
        required=False,
    )
    service_location = serializers.PrimaryKeyRelatedField(
        queryset=ServiceLocation.objects.all(),
    )
    service_type = serializers.PrimaryKeyRelatedField(
        queryset=ServiceType.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_number",
            "customer",
            "service_location",
            "service_type",
            "title",
            "description",
            "priority",
            "preferred_date",
            "preferred_time_slot",
            "created_at",
        ]
        read_only_fields = ["id", "request_number", "created_at"]

    def validate(self, attrs):
        request = self.context.get("request")
        user = request.user if request else None

        # Resolve customer for CUSTOMER role
        customer = attrs.get("customer")
        if user and user.role == UserRole.CUSTOMER:
            if hasattr(user, "customer_profile") and user.customer_profile:
                customer = user.customer_profile
                attrs["customer"] = customer
            else:
                raise serializers.ValidationError({"customer": "No linked customer profile found for this user."})
        elif not customer:
            raise serializers.ValidationError({"customer": "Customer is required for dispatchers and administrators."})

        # Validate that the service_location belongs to the customer
        service_location = attrs.get("service_location")
        if service_location and customer:
            if service_location.customer_id != customer.id:
                raise serializers.ValidationError({
                    "service_location": f"Location '{service_location.location_name}' does not belong to customer '{customer.display_name}'."
                })

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["reported_by"] = request.user

        instance = ServiceRequest(**validated_data)
        instance.calculate_sla_targets()
        instance.save()
        return instance


class ServiceRequestListSerializer(serializers.ModelSerializer):
    """Compact summary serializer for table and list views."""

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    city = serializers.CharField(source="service_location.city", read_only=True)
    service_type_name = serializers.CharField(source="service_type.name", read_only=True, default=None)
    attachments_count = serializers.IntegerField(source="attachments.count", read_only=True)
    is_sla_breached = serializers.BooleanField(read_only=True)

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_number",
            "title",
            "customer",
            "customer_name",
            "service_location",
            "location_name",
            "city",
            "service_type",
            "service_type_name",
            "priority",
            "status",
            "sla_response_due_at",
            "sla_resolution_due_at",
            "is_sla_breached",
            "attachments_count",
            "created_at",
        ]


class ServiceRequestDetailSerializer(serializers.ModelSerializer):
    """Comprehensive detail representation with full nested relations."""

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_location_address = serializers.CharField(source="service_location.full_address", read_only=True)
    service_location_latitude = serializers.DecimalField(
        source="service_location.latitude", max_digits=9, decimal_places=6, read_only=True
    )
    service_location_longitude = serializers.DecimalField(
        source="service_location.longitude", max_digits=9, decimal_places=6, read_only=True
    )
    service_type_name = serializers.CharField(source="service_type.name", read_only=True, default=None)
    reported_by_name = serializers.CharField(source="reported_by.get_full_name", read_only=True, default=None)
    reported_by_email = serializers.CharField(source="reported_by.email", read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source="reviewed_by.get_full_name", read_only=True, default=None)
    is_sla_breached = serializers.BooleanField(read_only=True)
    attachments = RequestAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_number",
            "customer",
            "customer_name",
            "customer_phone",
            "service_location",
            "service_location_name",
            "service_location_address",
            "service_location_latitude",
            "service_location_longitude",
            "service_type",
            "service_type_name",
            "title",
            "description",
            "priority",
            "status",
            "preferred_date",
            "preferred_time_slot",
            "sla_response_due_at",
            "sla_resolution_due_at",
            "is_sla_breached",
            "reported_by",
            "reported_by_name",
            "reported_by_email",
            "reviewed_by",
            "reviewed_by_name",
            "reviewed_at",
            "dispatcher_notes",
            "cancellation_reason",
            "attachments",
            "created_at",
            "updated_at",
        ]


class ServiceRequestReviewSerializer(serializers.Serializer):
    """Payload for Dispatcher triage and review action."""

    dispatcher_notes = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=RequestPriority.choices, required=False)


class ServiceRequestCancelSerializer(serializers.Serializer):
    """Payload for cancelling a service ticket."""

    reason = serializers.CharField(required=True, min_length=5, help_text="Reason for cancelling this request")
