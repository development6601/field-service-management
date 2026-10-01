from decimal import Decimal
from rest_framework import serializers

from apps.billing.models import Invoice, Payment, PaymentMethod
from apps.billing.serializers import PaymentSerializer
from apps.contracts.models import ServiceContract
from apps.customers.models import Customer, ServiceLocation
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.services.models import ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderStatus


class PortalCustomerInfoSerializer(serializers.ModelSerializer):
    """Basic profile information for the authenticated customer."""

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
        ]


class PortalDashboardSerializer(serializers.Serializer):
    """
    Aggregated operational and financial snapshot for the customer self-service home screen.
    """

    customer = PortalCustomerInfoSerializer()
    open_requests_count = serializers.IntegerField()
    active_work_orders_count = serializers.IntegerField()
    active_contracts_count = serializers.IntegerField()
    visits_remaining_total = serializers.IntegerField()
    outstanding_invoices_count = serializers.IntegerField()
    total_balance_due = serializers.DecimalField(max_digits=12, decimal_places=2)
    recent_work_orders = serializers.ListField(child=serializers.DictField())
    recent_requests = serializers.ListField(child=serializers.DictField())


class PortalServiceRequestSerializer(serializers.ModelSerializer):
    """
    Customer view of raised service tickets.
    """

    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_location_city = serializers.CharField(source="service_location.city", read_only=True)
    service_type_name = serializers.CharField(source="service_type.name", read_only=True, default=None)
    work_orders_summary = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_number",
            "title",
            "description",
            "priority",
            "status",
            "service_location",
            "service_location_name",
            "service_location_city",
            "service_type",
            "service_type_name",
            "sla_response_due_at",
            "sla_resolution_due_at",
            "work_orders_summary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_work_orders_summary(self, obj):
        return [
            {
                "id": str(wo.id),
                "work_order_number": wo.work_order_number,
                "status": wo.status,
                "assigned_technician_name": wo.assigned_technician.get_full_name() if wo.assigned_technician else None,
            }
            for wo in obj.work_orders.all()
        ]


class PortalCreateServiceRequestSerializer(serializers.ModelSerializer):
    """
    Input serializer for customers self-raising a service request.
    Enforces that the selected service location belongs to their account.
    """

    service_location = serializers.PrimaryKeyRelatedField(queryset=ServiceLocation.objects.all())
    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_type = serializers.PrimaryKeyRelatedField(queryset=ServiceType.objects.filter(is_active=True), required=False, allow_null=True)

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_number",
            "service_location",
            "service_location_name",
            "service_type",
            "title",
            "description",
            "priority",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "request_number",
            "service_location_name",
            "status",
            "created_at",
        ]

    def validate_service_location(self, value):
        customer = self.context.get("customer")
        if not customer:
            raise serializers.ValidationError("No customer profile found for this user account.")
        if value.customer != customer:
            raise serializers.ValidationError("Service location does not belong to your customer account.")
        return value


class PortalWorkOrderListSerializer(serializers.ModelSerializer):
    """
    Customer listing of work orders.
    """

    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_type_name = serializers.CharField(source="service_type.name", read_only=True, default=None)
    assigned_technician_name = serializers.CharField(source="assigned_technician.get_full_name", read_only=True, default=None)

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "work_order_number",
            "title",
            "status",
            "priority",
            "is_preventive_maintenance",
            "service_location",
            "service_location_name",
            "service_type",
            "service_type_name",
            "assigned_technician_name",
            "scheduled_start",
            "scheduled_end",
            "customer_rating",
            "created_at",
        ]
        read_only_fields = fields


class PortalWorkOrderDetailSerializer(serializers.ModelSerializer):
    """
    Full customer-facing work order detail. Hides internal labor wage costs
    and technician margins while exposing resolution, signature, and feedback.
    """

    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_location_address = serializers.CharField(source="service_location.address_line1", read_only=True)
    service_location_city = serializers.CharField(source="service_location.city", read_only=True)
    service_type_name = serializers.CharField(source="service_type.name", read_only=True, default=None)
    contract_number = serializers.CharField(source="service_contract.contract_number", read_only=True, default=None)
    assigned_technician_name = serializers.CharField(source="assigned_technician.get_full_name", read_only=True, default=None)
    assigned_technician_phone = serializers.CharField(source="assigned_technician.phone_number", read_only=True, default=None)

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "work_order_number",
            "title",
            "description",
            "status",
            "priority",
            "is_preventive_maintenance",
            "contract_number",
            "service_location",
            "service_location_name",
            "service_location_address",
            "service_location_city",
            "service_type",
            "service_type_name",
            "assigned_technician_name",
            "assigned_technician_phone",
            "scheduled_start",
            "scheduled_end",
            "travel_started_at",
            "arrived_at",
            "actual_start",
            "actual_end",
            "service_summary",
            "customer_signature",
            "signed_by_name",
            "signed_at",
            "customer_rating",
            "customer_feedback",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PortalWorkOrderTrackSerializer(serializers.Serializer):
    """
    Live job tracking payload for the client portal (Uber/Swiggy-style tracking view).
    """

    id = serializers.UUIDField(source="pk")
    work_order_number = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    priority = serializers.CharField()
    current_stage = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()
    technician = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()

    def get_current_stage(self, obj):
        stages = {
            WorkOrderStatus.DRAFT: "PENDING_DISPATCH",
            WorkOrderStatus.SCHEDULED: "SCHEDULED",
            WorkOrderStatus.ASSIGNED: "ASSIGNED",
            WorkOrderStatus.ACCEPTED: "ACCEPTED",
            WorkOrderStatus.TRAVELING: "ON_THE_WAY",
            WorkOrderStatus.ARRIVED: "ARRIVED_ON_SITE",
            WorkOrderStatus.IN_PROGRESS: "WORK_IN_PROGRESS",
            WorkOrderStatus.COMPLETED: "COMPLETED",
            WorkOrderStatus.ON_HOLD: "ON_HOLD",
            WorkOrderStatus.CANCELLED: "CANCELLED",
            WorkOrderStatus.REJECTED: "REJECTED",
        }
        return stages.get(obj.status, obj.status)

    def get_is_completed(self, obj):
        return obj.status == WorkOrderStatus.COMPLETED

    def get_technician(self, obj):
        if not obj.assigned_technician:
            return None
        return {
            "name": obj.assigned_technician.get_full_name(),
            "phone": obj.assigned_technician.phone_number,
            "email": obj.assigned_technician.email,
        }

    def get_location(self, obj):
        loc = obj.service_location
        return {
            "name": loc.location_name,
            "address": loc.address_line1,
            "city": loc.city,
            "state": loc.state,
            "postal_code": loc.postal_code,
            "latitude": str(loc.latitude) if loc.latitude else None,
            "longitude": str(loc.longitude) if loc.longitude else None,
        }

    def get_timeline(self, obj):
        return {
            "created_at": obj.created_at,
            "scheduled_start": obj.scheduled_start,
            "scheduled_end": obj.scheduled_end,
            "travel_started_at": obj.travel_started_at,
            "arrived_at": obj.arrived_at,
            "actual_start": obj.actual_start,
            "actual_end": obj.actual_end,
            "signed_at": obj.signed_at,
        }


class PortalCustomerFeedbackSerializer(serializers.Serializer):
    """
    Payload for customer submitting star rating and review on a completed job.
    """

    rating = serializers.IntegerField(
        min_value=1,
        max_value=5,
        required=True,
        help_text="Customer satisfaction star rating from 1 (poor) to 5 (excellent)",
    )
    feedback = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional remarks, review notes, or technician appreciation",
    )


class PortalContractSerializer(serializers.ModelSerializer):
    """
    Customer view of active and historical maintenance agreements (AMC).
    """

    service_location_name = serializers.CharField(source="service_location.location_name", read_only=True)
    service_location_city = serializers.CharField(source="service_location.city", read_only=True)
    visits_remaining = serializers.IntegerField(read_only=True)
    covered_services = serializers.SerializerMethodField()

    class Meta:
        model = ServiceContract
        fields = [
            "id",
            "contract_number",
            "title",
            "status",
            "service_frequency",
            "start_date",
            "end_date",
            "total_visits_allowed",
            "visits_used",
            "visits_remaining",
            "contract_value",
            "sla_response_hours",
            "next_scheduled_date",
            "service_location",
            "service_location_name",
            "service_location_city",
            "covered_services",
            "terms_and_conditions",
            "created_at",
        ]
        read_only_fields = fields

    def get_covered_services(self, obj):
        return [
            {
                "id": str(s.id),
                "name": s.name,
                "code": s.code,
                "category_name": s.category.name if s.category else None,
            }
            for s in obj.covered_services.all()
        ]


class PortalInvoiceSerializer(serializers.ModelSerializer):
    """
    Customer financial invoice view with itemized charges and payments.
    """

    work_order_number = serializers.CharField(source="work_order.work_order_number", read_only=True)
    work_order_title = serializers.CharField(source="work_order.title", read_only=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_fully_paid = serializers.BooleanField(read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "work_order",
            "work_order_number",
            "work_order_title",
            "status",
            "issue_date",
            "due_date",
            "labor_amount",
            "parts_amount",
            "service_amount",
            "discount_amount",
            "tax_rate",
            "tax_amount",
            "total_amount",
            "amount_paid",
            "balance_due",
            "is_fully_paid",
            "notes",
            "payments",
            "created_at",
        ]
        read_only_fields = fields


class PortalSelfPaymentSerializer(serializers.Serializer):
    """
    Payload for customer initiating self-service payment on an invoice.
    """

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
        help_text="Remittance amount (defaults to outstanding balance_due)",
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        default=PaymentMethod.UPI,
        help_text="Selected payment instrument (UPI, BANK_TRANSFER, CREDIT_CARD, etc.)",
    )
    transaction_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Bank UTR number or UPI transaction ID",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional remarks for payment",
    )
