from rest_framework import serializers

from apps.contracts.models import (
    ContractStatus,
    ServiceContract,
    ServiceFrequency,
)
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceType
from apps.services.serializers import ServiceTypeSerializer


class ServiceContractListSerializer(serializers.ModelSerializer):
    """
    Summary representation of maintenance contracts for table views.
    """

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    visits_remaining = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    can_generate_visit = serializers.BooleanField(read_only=True)

    class Meta:
        model = ServiceContract
        fields = [
            "id",
            "contract_number",
            "title",
            "customer",
            "customer_name",
            "service_location",
            "service_location_name",
            "status",
            "start_date",
            "end_date",
            "service_frequency",
            "total_visits_allowed",
            "visits_used",
            "visits_remaining",
            "next_scheduled_date",
            "is_expired",
            "can_generate_visit",
            "created_at",
        ]
        read_only_fields = fields


class ContractWorkOrderBriefSerializer(serializers.Serializer):
    """Brief representation of work orders attached to a contract."""

    id = serializers.UUIDField(read_only=True)
    work_order_number = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    assigned_technician_name = serializers.CharField(source="assigned_technician.get_full_name", read_only=True)
    scheduled_start = serializers.DateTimeField(read_only=True)
    actual_end = serializers.DateTimeField(read_only=True)


class ServiceContractDetailSerializer(serializers.ModelSerializer):
    """
    Comprehensive representation of maintenance contracts with covered services,
    terms, and linked work orders history.
    """

    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_location_address = serializers.CharField(source="service_location.full_address", read_only=True)
    covered_services = ServiceTypeSerializer(many=True, read_only=True)
    visits_remaining = serializers.IntegerField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    can_generate_visit = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    work_orders = ContractWorkOrderBriefSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceContract
        fields = [
            "id",
            "contract_number",
            "title",
            "customer",
            "customer_name",
            "customer_phone",
            "service_location",
            "service_location_name",
            "service_location_address",
            "covered_services",
            "start_date",
            "end_date",
            "status",
            "service_frequency",
            "total_visits_allowed",
            "visits_used",
            "visits_remaining",
            "contract_value",
            "sla_response_hours",
            "next_scheduled_date",
            "is_expired",
            "can_generate_visit",
            "terms_and_conditions",
            "termination_reason",
            "terminated_at",
            "created_by",
            "created_by_name",
            "work_orders",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ServiceContractCreateSerializer(serializers.ModelSerializer):
    """
    Payload for creating or updating a maintenance agreement.
    """

    covered_services = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ServiceType.objects.all(),
        required=False,
        default=list,
        help_text="Optional list of covered ServiceType UUIDs included in the contract",
    )

    class Meta:
        model = ServiceContract
        fields = [
            "id",
            "contract_number",
            "title",
            "customer",
            "service_location",
            "covered_services",
            "start_date",
            "end_date",
            "status",
            "service_frequency",
            "total_visits_allowed",
            "contract_value",
            "sla_response_hours",
            "terms_and_conditions",
            "created_at",
        ]
        read_only_fields = ["id", "contract_number", "status", "created_at"]

    def validate(self, attrs):
        start_date = attrs.get("start_date") or (self.instance.start_date if self.instance else None)
        end_date = attrs.get("end_date") or (self.instance.end_date if self.instance else None)

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "End date cannot be prior to start date."})

        customer = attrs.get("customer") or (self.instance.customer if self.instance else None)
        service_location = attrs.get("service_location") or (self.instance.service_location if self.instance else None)

        if customer and service_location and service_location.customer_id != customer.id:
            raise serializers.ValidationError(
                {"service_location": "The specified service location does not belong to this customer."}
            )

        return attrs


class GeneratePreventiveWorkOrderSerializer(serializers.Serializer):
    """
    Input payload for manually or periodically dispatching a contract preventive maintenance job.
    """

    scheduled_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Optional custom date for the visit (defaults to next_scheduled_date)",
    )
    assigned_technician_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of assigned technician",
    )
    service_type_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of covered service type being performed",
    )
    job_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Specific preventive maintenance instructions for technician",
    )


class ContractTerminateSerializer(serializers.Serializer):
    """
    Payload for prematurely terminating a contract with a mandatory reason.
    """

    reason = serializers.CharField(
        required=True,
        min_length=5,
        help_text="Mandatory business reason for contract cancellation",
    )
