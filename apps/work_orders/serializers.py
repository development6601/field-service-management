from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceType
from apps.service_requests.models import RequestStatus, ServiceRequest
from .models import WorkOrder, WorkOrderHistory, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class WorkOrderHistorySerializer(serializers.ModelSerializer):
    """Read-only audit trail representation of status transitions."""

    changed_by_name = serializers.CharField(source="changed_by.full_name", read_only=True, default="System")

    class Meta:
        model = WorkOrderHistory
        fields = [
            "id",
            "from_status",
            "to_status",
            "notes",
            "changed_by",
            "changed_by_name",
            "created_at",
        ]
        read_only_fields = fields


class WorkOrderConvertSerializer(serializers.Serializer):
    """
    Converts a REVIEWED Service Request ticket into an operational Work Order.
    Automatically links customer, site, priority, and updates parent ticket status.
    """

    service_request = serializers.PrimaryKeyRelatedField(
        queryset=ServiceRequest.objects.filter(is_deleted=False)
    )
    assigned_technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRole.TECHNICIAN, is_active=True),
        required=False,
        allow_null=True,
    )
    scheduled_start = serializers.DateTimeField(required=False, allow_null=True)
    scheduled_end = serializers.DateTimeField(required=False, allow_null=True)
    job_instructions = serializers.CharField(required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=WorkOrderPriority.choices, required=False)
    force_override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        service_request = attrs["service_request"]

        # Guard: Cannot convert tickets that are not yet reviewed
        if service_request.status != RequestStatus.REVIEWED:
            raise serializers.ValidationError({
                "service_request": (
                    f"Cannot convert ticket. Service Request '{service_request.request_number}' "
                    f"is in status '{service_request.status}'. Only '{RequestStatus.REVIEWED}' tickets can be converted."
                )
            })

        # Scheduled time validation
        start = attrs.get("scheduled_start")
        end = attrs.get("scheduled_end")
        if start and end and end <= start:
            raise serializers.ValidationError({
                "scheduled_end": "Scheduled end time must be after scheduled start time."
            })

        # Conflict Detection check
        tech = attrs.get("assigned_technician")
        force_override = attrs.get("force_override", False)
        override_reason = attrs.get("override_reason", "")
        if tech and start and end:
            from apps.scheduling.services import SchedulingConflictService

            conflict_check = SchedulingConflictService.check_availability(tech, start, end)
            if conflict_check["has_conflicts"]:
                if not force_override:
                    raise serializers.ValidationError({
                        "scheduling_conflict": conflict_check["conflicts"],
                        "message": "Scheduling collision detected. Pass force_override=true with override_reason to bypass.",
                    })
                elif not override_reason.strip():
                    raise serializers.ValidationError({
                        "override_reason": "An override reason is mandatory when forcing a conflicting schedule."
                    })

        return attrs

    def create(self, validated_data):
        service_request = validated_data["service_request"]
        assigned_technician = validated_data.get("assigned_technician")
        scheduled_start = validated_data.get("scheduled_start")
        scheduled_end = validated_data.get("scheduled_end")
        job_instructions = validated_data.get("job_instructions", "")
        priority = validated_data.get("priority") or service_request.priority
        force_override = validated_data.get("force_override", False)
        override_reason = validated_data.get("override_reason", "")

        request = self.context.get("request")
        user = request.user if request else None

        with transaction.atomic():
            work_order = WorkOrder.objects.create(
                service_request=service_request,
                customer=service_request.customer,
                service_location=service_request.service_location,
                service_type=service_request.service_type,
                assigned_technician=assigned_technician,
                title=f"WO: {service_request.title}",
                description=service_request.description,
                job_instructions=job_instructions,
                priority=priority,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                created_by=user,
            )

            # Record schedule override if forced
            if force_override and assigned_technician and override_reason:
                from apps.scheduling.models import ScheduleOverrideLog

                ScheduleOverrideLog.objects.create(
                    work_order=work_order,
                    technician=assigned_technician,
                    overridden_by=user,
                    override_reason=override_reason,
                )

            # Synchronize parent ticket state to SCHEDULED or ASSIGNED
            target_ticket_status = RequestStatus.SCHEDULED if scheduled_start else RequestStatus.ASSIGNED
            if service_request.can_transition_to(target_ticket_status):
                service_request.transition_to(
                    target_ticket_status,
                    user=user,
                    notes=f"Converted to Work Order {work_order.work_order_number}",
                )

            # Record initial history
            WorkOrderHistory.objects.create(
                work_order=work_order,
                changed_by=user,
                from_status="NONE",
                to_status=work_order.status,
                notes=f"Generated from Service Request {service_request.request_number}",
            )

            return work_order


class WorkOrderCreateSerializer(serializers.ModelSerializer):
    """Direct work order creation serializer for Dispatchers."""

    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.filter(is_deleted=False)
    )
    service_location = serializers.PrimaryKeyRelatedField(
        queryset=ServiceLocation.objects.all()
    )
    service_type = serializers.PrimaryKeyRelatedField(
        queryset=ServiceType.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    assigned_technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRole.TECHNICIAN, is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "work_order_number",
            "customer",
            "service_location",
            "service_type",
            "assigned_technician",
            "title",
            "description",
            "job_instructions",
            "priority",
            "scheduled_start",
            "scheduled_end",
            "estimated_duration_minutes",
            "created_at",
        ]
        read_only_fields = ["id", "work_order_number", "created_at"]

    def validate(self, attrs):
        customer = attrs.get("customer")
        service_location = attrs.get("service_location")
        if customer and service_location and service_location.customer_id != customer.id:
            raise serializers.ValidationError({
                "service_location": f"Location '{service_location.location_name}' does not belong to customer '{customer.display_name}'."
            })
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user

        work_order = super().create(validated_data)

        # Initial history
        WorkOrderHistory.objects.create(
            work_order=work_order,
            changed_by=validated_data.get("created_by"),
            from_status="NONE",
            to_status=work_order.status,
            notes="Work Order created",
        )
        return work_order


class WorkOrderAssignSerializer(serializers.Serializer):
    """Payload for assigning a technician and scheduling time window with collision detection."""

    assigned_technician = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=UserRole.TECHNICIAN, is_active=True)
    )
    scheduled_start = serializers.DateTimeField(required=False, allow_null=True)
    scheduled_end = serializers.DateTimeField(required=False, allow_null=True)
    job_instructions = serializers.CharField(required=False, allow_blank=True)
    force_override = serializers.BooleanField(required=False, default=False)
    override_reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        start = attrs.get("scheduled_start")
        end = attrs.get("scheduled_end")
        if start and end and end <= start:
            raise serializers.ValidationError({
                "scheduled_end": "Scheduled end time must be after scheduled start time."
            })

        tech = attrs.get("assigned_technician")
        force_override = attrs.get("force_override", False)
        override_reason = attrs.get("override_reason", "")

        if tech and start and end:
            from apps.scheduling.services import SchedulingConflictService

            wo_instance = self.context.get("work_order")
            conflict_check = SchedulingConflictService.check_availability(
                tech,
                start,
                end,
                exclude_work_order_id=wo_instance.id if wo_instance else None,
            )
            if conflict_check["has_conflicts"]:
                if not force_override:
                    raise serializers.ValidationError({
                        "scheduling_conflict": conflict_check["conflicts"],
                        "message": "Scheduling collision detected. Pass force_override=true with override_reason to bypass.",
                    })
                elif not override_reason.strip():
                    raise serializers.ValidationError({
                        "override_reason": "An override reason is mandatory when forcing a conflicting schedule."
                    })

        return attrs


class WorkOrderActionNotesSerializer(serializers.Serializer):
    """Optional operational notes for technician status actions."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")


class WorkOrderStatusUpdateSerializer(serializers.Serializer):
    """Payload for transitioning the work order through its state machine."""

    status = serializers.ChoiceField(choices=WorkOrderStatus.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    labor_hours = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )


class WorkOrderRejectSerializer(serializers.Serializer):
    """Payload when a technician declines/rejects an assigned job."""

    rejection_reason = serializers.CharField(
        required=True,
        allow_blank=False,
        error_messages={"required": "A rejection reason must be provided."},
        help_text="Detailed justification why the job cannot be accepted",
    )


class WorkOrderCompleteSerializer(serializers.Serializer):
    """Payload for completing work, capturing digital signature, and customer feedback."""

    service_summary = serializers.CharField(
        required=True,
        allow_blank=False,
        error_messages={"required": "A technical service summary is required to complete the job."},
        help_text="Detailed technical description of repairs and diagnostic checks performed",
    )
    labor_hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Actual billable labor hours logged by technician",
    )
    customer_signature = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Base64 encoded digital signature image string",
    )
    signed_by_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Full name of client supervisor who verified the work",
    )
    customer_rating = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=5,
        help_text="Client satisfaction rating from 1 (poor) to 5 (excellent)",
    )
    customer_feedback = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Customer remarks or review notes",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Internal technician completion notes",
    )


class WorkOrderListSerializer(serializers.ModelSerializer):
    """Compact summary serializer for table and list views."""

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    city = serializers.CharField(source="service_location.city", read_only=True)
    service_type_name = serializers.CharField(source="service_type.name", read_only=True, default=None)
    assigned_technician_name = serializers.CharField(
        source="assigned_technician.full_name", read_only=True, default="Unassigned"
    )

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "work_order_number",
            "title",
            "customer",
            "customer_name",
            "service_location",
            "location_name",
            "city",
            "service_type",
            "service_type_name",
            "assigned_technician",
            "assigned_technician_name",
            "status",
            "priority",
            "is_preventive_maintenance",
            "service_contract",
            "scheduled_start",
            "scheduled_end",
            "created_at",
        ]


class WorkOrderDetailSerializer(serializers.ModelSerializer):
    """Comprehensive detail representation with relations, timestamps, signatures, and audit history."""

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
    assigned_technician_name = serializers.CharField(
        source="assigned_technician.full_name", read_only=True, default="Unassigned"
    )
    assigned_technician_phone = serializers.CharField(
        source="assigned_technician.phone_number", read_only=True, default=None
    )
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    service_request_number = serializers.CharField(
        source="service_request.request_number", read_only=True, default=None
    )
    history = WorkOrderHistorySerializer(many=True, read_only=True)
    parts_used = serializers.SerializerMethodField()
    parts_total_cost = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "work_order_number",
            "service_request",
            "service_request_number",
            "service_contract",
            "is_preventive_maintenance",
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
            "assigned_technician",
            "assigned_technician_name",
            "assigned_technician_phone",
            "status",
            "priority",
            "title",
            "description",
            "job_instructions",
            "scheduled_start",
            "scheduled_end",
            "travel_started_at",
            "arrived_at",
            "actual_start",
            "actual_end",
            "estimated_duration_minutes",
            "labor_hours",
            "rejection_reason",
            "service_summary",
            "customer_signature",
            "signed_by_name",
            "signed_at",
            "customer_rating",
            "customer_feedback",
            "hold_reason",
            "cancellation_reason",
            "created_by",
            "created_by_name",
            "parts_used",
            "parts_total_cost",
            "history",
            "created_at",
            "updated_at",
        ]

    def get_parts_used(self, obj):
        from apps.inventory.serializers import WorkOrderPartSerializer
        return WorkOrderPartSerializer(obj.parts_used.all(), many=True).data

    def get_parts_total_cost(self, obj):
        from decimal import Decimal
        total = sum(p.total_price for p in obj.parts_used.filter(status="CONSUMED"))
        return str(total)

