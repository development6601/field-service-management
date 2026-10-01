from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.models import UserRole
from .models import LeaveStatus, LeaveType, ScheduleOverrideLog, TechnicianLeave

User = get_user_model()


class TechnicianLeaveSerializer(serializers.ModelSerializer):
    """Serializer for managing technician leaves and time-off requests."""

    technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRole.TECHNICIAN, is_active=True),
        required=False,
    )
    technician_name = serializers.CharField(source="technician.full_name", read_only=True)
    leave_type_display = serializers.CharField(source="get_leave_type_display", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.full_name", read_only=True, default=None)

    class Meta:
        model = TechnicianLeave
        fields = [
            "id",
            "technician",
            "technician_name",
            "leave_type",
            "leave_type_display",
            "start_date",
            "end_date",
            "reason",
            "status",
            "approved_by",
            "approved_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "status", "approved_by", "created_at"]

    def validate_technician(self, value):
        if value.role != UserRole.TECHNICIAN:
            raise serializers.ValidationError("Leaves can only be scheduled for technicians.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        if "technician" not in attrs:
            if request and getattr(request.user, "role", None) == UserRole.TECHNICIAN:
                attrs["technician"] = request.user
            else:
                raise serializers.ValidationError({"technician": "Technician field is required."})

        start = attrs.get("start_date")
        end = attrs.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "End date cannot be earlier than start date."})
        return attrs


class AvailabilityCheckSerializer(serializers.Serializer):
    """Payload for pre-checking technician scheduling collisions."""

    technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRole.TECHNICIAN, is_active=True)
    )
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()
    work_order_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["scheduled_end"] <= attrs["scheduled_start"]:
            raise serializers.ValidationError({
                "scheduled_end": "Scheduled end time must be after scheduled start time."
            })
        return attrs


class ScheduleOverrideLogSerializer(serializers.ModelSerializer):
    """Serializer for inspecting override history and emergency bypass audit logs."""

    work_order_number = serializers.CharField(source="work_order.work_order_number", read_only=True)
    work_order_title = serializers.CharField(source="work_order.title", read_only=True)
    technician_name = serializers.CharField(source="technician.full_name", read_only=True)
    overridden_by_name = serializers.CharField(source="overridden_by.full_name", read_only=True)

    class Meta:
        model = ScheduleOverrideLog
        fields = [
            "id",
            "work_order",
            "work_order_number",
            "work_order_title",
            "technician",
            "technician_name",
            "overridden_by",
            "overridden_by_name",
            "conflict_details",
            "override_reason",
            "created_at",
        ]
        read_only_fields = fields

