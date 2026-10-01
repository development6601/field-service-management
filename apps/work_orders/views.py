from django.db.models import Q
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from apps.accounts.models import UserRole
from apps.service_requests.models import RequestStatus
from .models import WorkOrder, WorkOrderStatus
from .serializers import (
    WorkOrderActionNotesSerializer,
    WorkOrderAssignSerializer,
    WorkOrderCompleteSerializer,
    WorkOrderConvertSerializer,
    WorkOrderCreateSerializer,
    WorkOrderDetailSerializer,
    WorkOrderListSerializer,
    WorkOrderRejectSerializer,
    WorkOrderStatusUpdateSerializer,
)


class WorkOrderViewSet(viewsets.ModelViewSet):
    """
    CRUD and operational lifecycle API for field Work Orders.
    Supports role-based filtering, conversion from Service Requests,
    technician assignment scheduling, and state machine transitions.
    """

    permission_classes = [permissions.IsAuthenticated]
    queryset = (
        WorkOrder.objects.select_related(
            "customer",
            "service_location",
            "service_type",
            "assigned_technician",
            "created_by",
            "service_request",
        )
        .prefetch_related("history__changed_by")
        .all()
    )

    def get_serializer_class(self):
        if self.action == "create":
            return WorkOrderCreateSerializer
        elif self.action in ["retrieve", "update", "partial_update"]:
            return WorkOrderDetailSerializer
        elif self.action == "convert":
            return WorkOrderConvertSerializer
        elif self.action == "assign":
            return WorkOrderAssignSerializer
        elif self.action == "update_status":
            return WorkOrderStatusUpdateSerializer
        elif self.action == "complete_job":
            return WorkOrderCompleteSerializer
        elif self.action == "reject_job":
            return WorkOrderRejectSerializer
        elif self.action in ["accept_job", "start_travel", "arrive_on_site", "start_work"]:
            return WorkOrderActionNotesSerializer
        return WorkOrderListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Multi-Tenant Visibility Isolation:
        if user.role == UserRole.CUSTOMER:
            # Customers only see work orders raised for their company
            qs = qs.filter(customer__user=user)
        elif user.role == UserRole.TECHNICIAN:
            # Technicians only see work orders assigned to them
            qs = qs.filter(assigned_technician=user)
        # Dispatchers, Managers, and Admins see all work orders

        # Status filter (e.g. ?status=ASSIGNED)
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        # Priority filter (e.g. ?priority=CRITICAL)
        priority_param = self.request.query_params.get("priority")
        if priority_param:
            qs = qs.filter(priority__iexact=priority_param)

        # Technician filter (for dispatchers filtering by specific tech)
        tech_param = self.request.query_params.get("technician")
        if tech_param:
            qs = qs.filter(assigned_technician_id=tech_param)

        # Customer filter
        customer_param = self.request.query_params.get("customer")
        if customer_param:
            qs = qs.filter(customer_id=customer_param)

        # Search filter (by work order number, title, description, company name)
        search_query = self.request.query_params.get("search")
        if search_query:
            qs = qs.filter(
                Q(work_order_number__icontains=search_query)
                | Q(title__icontains=search_query)
                | Q(description__icontains=search_query)
                | Q(customer__company_name__icontains=search_query)
                | Q(service_location__location_name__icontains=search_query)
            )

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if user.role not in [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.MANAGER]:
            raise PermissionDenied("Only dispatchers, managers, and administrators can create work orders.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            raise PermissionDenied("Only Administrators and Managers can delete work orders.")
        instance.delete()

    @action(detail=False, methods=["post"], url_path="convert")
    def convert(self, request):
        """
        Converts a REVIEWED Service Request into a new Work Order.
        Only Dispatchers, Managers, and Administrators can convert tickets.
        """
        user = request.user
        if user.role not in [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.MANAGER]:
            raise PermissionDenied("Only dispatchers, managers, and administrators can convert service requests.")

        serializer = WorkOrderConvertSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        work_order = serializer.save()

        detail_serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        """
        Assigns or reassigns a technician and schedule window to an existing work order.
        """
        user = request.user
        if user.role not in [UserRole.ADMIN, UserRole.DISPATCHER, UserRole.MANAGER]:
            raise PermissionDenied("Only dispatchers, managers, and administrators can schedule and assign work orders.")

        work_order = self.get_object()
        serializer = WorkOrderAssignSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        technician = serializer.validated_data["assigned_technician"]
        scheduled_start = serializer.validated_data.get("scheduled_start")
        scheduled_end = serializer.validated_data.get("scheduled_end")
        job_instructions = serializer.validated_data.get("job_instructions")

        force_override = serializer.validated_data.get("force_override", False)
        override_reason = serializer.validated_data.get("override_reason", "")

        work_order.assigned_technician = technician
        if scheduled_start:
            work_order.scheduled_start = scheduled_start
        if scheduled_end:
            work_order.scheduled_end = scheduled_end
        if job_instructions:
            work_order.job_instructions = job_instructions

        # State transition if in DRAFT
        if work_order.status == WorkOrderStatus.DRAFT:
            target_status = WorkOrderStatus.SCHEDULED if scheduled_start else WorkOrderStatus.ASSIGNED
            work_order.transition_to(
                target_status,
                user=user,
                notes=f"Assigned to {technician.full_name}",
            )
        else:
            work_order.save()

        # Record schedule override if forced
        if force_override and override_reason:
            from apps.scheduling.models import ScheduleOverrideLog

            ScheduleOverrideLog.objects.create(
                work_order=work_order,
                technician=technician,
                overridden_by=user,
                override_reason=override_reason,
            )

        work_order.refresh_from_db()
        detail_serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="status")
    def update_status(self, request, pk=None):
        """
        Executes a formal state machine transition on the work order
        (e.g., IN_PROGRESS, ON_HOLD, COMPLETED, CANCELLED).
        """
        work_order = self.get_object()
        user = request.user

        # Technicians can only update their own assigned work orders
        if user.role == UserRole.TECHNICIAN and work_order.assigned_technician != user:
            raise PermissionDenied("You can only update work orders assigned to you.")

        # Customers cannot directly modify field technician work order statuses
        if user.role == UserRole.CUSTOMER:
            raise PermissionDenied("Customers cannot change work order execution status.")

        serializer = WorkOrderStatusUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        target_status = serializer.validated_data["status"]
        notes = serializer.validated_data.get("notes", "")
        reason = serializer.validated_data.get("reason", "")
        labor_hours = serializer.validated_data.get("labor_hours")

        if not work_order.can_transition_to(target_status):
            raise ValidationError(
                f"Cannot change status from '{work_order.status}' to '{target_status}'. "
                f"Valid next states: {work_order.can_transition_to(target_status)}"
            )

        if labor_hours is not None:
            work_order.labor_hours = labor_hours

        work_order.transition_to(
            target_status,
            user=user,
            notes=notes,
            reason=reason,
        )

        if target_status == WorkOrderStatus.COMPLETED and work_order.service_contract:
            from apps.contracts.services import ContractService
            ContractService.record_contract_visit_completion(work_order)

        work_order.refresh_from_db()
        detail_serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    def _check_technician_permission(self, work_order, user):
        """Enforces that field technicians can only execute actions on their own jobs."""
        if user.role == UserRole.TECHNICIAN and work_order.assigned_technician != user:
            raise PermissionDenied("You can only execute actions on work orders assigned to you.")
        if user.role == UserRole.CUSTOMER:
            raise PermissionDenied("Customers cannot perform technician actions on work orders.")

    @action(detail=True, methods=["post"], url_path="accept")
    def accept_job(self, request, pk=None):
        """Technician accepts an assigned/scheduled work order."""
        work_order = self.get_object()
        self._check_technician_permission(work_order, request.user)
        notes = request.data.get("notes") or "Job accepted by technician"
        work_order.transition_to(WorkOrderStatus.ACCEPTED, user=request.user, notes=notes)
        work_order.refresh_from_db()
        serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject_job(self, request, pk=None):
        """Technician rejects an assigned job with mandatory justification."""
        work_order = self.get_object()
        self._check_technician_permission(work_order, request.user)
        serializer = WorkOrderRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["rejection_reason"]
        work_order.transition_to(
            WorkOrderStatus.REJECTED,
            user=request.user,
            notes=f"Job rejected by technician: {reason}",
            reason=reason,
        )
        work_order.refresh_from_db()
        detail_serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="start-travel")
    def start_travel(self, request, pk=None):
        """Technician marks departure / traveling en-route to customer site."""
        work_order = self.get_object()
        self._check_technician_permission(work_order, request.user)
        notes = request.data.get("notes") or "Technician departed for site (Traveling)"
        work_order.transition_to(WorkOrderStatus.TRAVELING, user=request.user, notes=notes)
        work_order.refresh_from_db()
        serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="arrive")
    def arrive_on_site(self, request, pk=None):
        """Technician marks physical arrival at customer gate / facility."""
        work_order = self.get_object()
        self._check_technician_permission(work_order, request.user)
        notes = request.data.get("notes") or "Technician arrived on customer site"
        work_order.transition_to(WorkOrderStatus.ARRIVED, user=request.user, notes=notes)
        work_order.refresh_from_db()
        serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="start-work")
    def start_work(self, request, pk=None):
        """Technician starts diagnosis, repair, or maintenance (IN_PROGRESS)."""
        work_order = self.get_object()
        self._check_technician_permission(work_order, request.user)
        notes = request.data.get("notes") or "Field diagnosis and work started"
        work_order.transition_to(WorkOrderStatus.IN_PROGRESS, user=request.user, notes=notes)
        work_order.refresh_from_db()
        serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=WorkOrderCompleteSerializer, responses={200: WorkOrderDetailSerializer})
    @action(detail=True, methods=["post"], url_path="complete")
    def complete_job(self, request, pk=None):
        """
        Completes the work order, capturing technical service summary,
        customer digital signature, satisfaction rating, and logs final labor hours.
        """
        work_order = self.get_object()
        self._check_technician_permission(work_order, request.user)
        serializer = WorkOrderCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        work_order.service_summary = data["service_summary"]
        if data.get("labor_hours") is not None:
            work_order.labor_hours = data["labor_hours"]
        if data.get("customer_signature"):
            work_order.customer_signature = data["customer_signature"]
        if data.get("signed_by_name"):
            work_order.signed_by_name = data["signed_by_name"]
            work_order.signed_at = timezone.now()
        if data.get("customer_rating") is not None:
            work_order.customer_rating = data["customer_rating"]
        if data.get("customer_feedback"):
            work_order.customer_feedback = data["customer_feedback"]

        notes = data.get("notes") or f"Service completed. Summary: {data['service_summary']}"
        work_order.transition_to(WorkOrderStatus.COMPLETED, user=request.user, notes=notes)

        # Cascade completion to parent ticket if applicable
        if work_order.service_request and work_order.service_request.can_transition_to(RequestStatus.COMPLETED):
            work_order.service_request.transition_to(
                RequestStatus.COMPLETED,
                user=request.user,
                notes=f"Completed via Work Order {work_order.work_order_number}",
            )

        # Update contract visit quota if linked to maintenance contract
        if work_order.service_contract:
            from apps.contracts.services import ContractService
            ContractService.record_contract_visit_completion(work_order)

        work_order.refresh_from_db()
        detail_serializer = WorkOrderDetailSerializer(work_order, context={"request": request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="my-jobs")
    def my_jobs(self, request):
        """
        Technician mobile dashboard view.
        Returns active job, upcoming jobs, and completed history.
        """
        user = request.user
        if user.role != UserRole.TECHNICIAN:
            return Response(
                {"detail": "This endpoint is dedicated to field technicians."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tech_wos = WorkOrder.objects.filter(assigned_technician=user).select_related(
            "customer", "service_location", "service_type"
        )
        active_statuses = [
            WorkOrderStatus.ACCEPTED,
            WorkOrderStatus.TRAVELING,
            WorkOrderStatus.ARRIVED,
            WorkOrderStatus.IN_PROGRESS,
            WorkOrderStatus.ON_HOLD,
        ]
        upcoming_statuses = [WorkOrderStatus.ASSIGNED, WorkOrderStatus.SCHEDULED]
        completed_statuses = [WorkOrderStatus.COMPLETED]

        active_jobs = tech_wos.filter(status__in=active_statuses).order_by("-updated_at")
        upcoming_jobs = tech_wos.filter(status__in=upcoming_statuses).order_by("scheduled_start")
        completed_jobs = tech_wos.filter(status__in=completed_statuses).order_by("-actual_end")[:20]

        return Response(
            {
                "active_job": (
                    WorkOrderDetailSerializer(active_jobs.first(), context={"request": request}).data
                    if active_jobs.exists()
                    else None
                ),
                "active_jobs_count": active_jobs.count(),
                "upcoming_jobs": WorkOrderListSerializer(
                    upcoming_jobs, many=True, context={"request": request}
                ).data,
                "completed_recent": WorkOrderListSerializer(
                    completed_jobs, many=True, context={"request": request}
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="parts")
    def parts(self, request, pk=None):
        """
        GET: List all parts attached to this work order.
        POST: Add / consume a part on this work order from technician van or warehouse.
        """
        work_order = self.get_object()

        if request.method == "GET":
            from apps.inventory.serializers import WorkOrderPartSerializer
            parts_qs = work_order.parts_used.select_related("part", "warehouse", "technician").all()
            serializer = WorkOrderPartSerializer(parts_qs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # POST: Consume part
        from apps.inventory.models import Part, Warehouse, LocationType
        from apps.inventory.serializers import ConsumeWorkOrderPartSerializer, WorkOrderPartSerializer
        from apps.inventory.services import InventoryService
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.shortcuts import get_object_or_404

        if work_order.status in [WorkOrderStatus.CANCELLED, WorkOrderStatus.REJECTED]:
            return Response(
                {"detail": f"Cannot add parts to a work order with status '{work_order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        if user.role == UserRole.TECHNICIAN:
            if work_order.assigned_technician != user:
                raise PermissionDenied("You can only add parts to work orders assigned to you.")

        serializer = ConsumeWorkOrderPartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        part = get_object_or_404(Part, id=data["part_id"])
        source_type = data.get("source_location_type", LocationType.TECHNICIAN_VAN)

        warehouse = None
        technician = None
        if source_type == LocationType.WAREHOUSE:
            if user.role == UserRole.TECHNICIAN:
                raise PermissionDenied("Technicians can only consume parts directly from their van stock.")
            if not data.get("warehouse_id"):
                return Response(
                    {"warehouse_id": ["Warehouse ID is required when consuming from warehouse."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            warehouse = get_object_or_404(Warehouse, id=data["warehouse_id"])
        else:
            technician = work_order.assigned_technician or user

        try:
            wo_part = InventoryService.consume_part_on_work_order(
                work_order=work_order,
                part=part,
                quantity=data["quantity"],
                source_location_type=source_type,
                warehouse=warehouse,
                technician=technician,
                performed_by=user,
                notes=data.get("notes", ""),
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(WorkOrderPartSerializer(wo_part).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="return-part")
    def return_part(self, request, pk=None):
        """
        Return an unused or incorrectly consumed part back to van or warehouse inventory.
        """
        work_order = self.get_object()
        from apps.inventory.models import WorkOrderPart
        from apps.inventory.serializers import WorkOrderPartSerializer
        from apps.inventory.services import InventoryService
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.shortcuts import get_object_or_404

        user = request.user
        if user.role == UserRole.TECHNICIAN and work_order.assigned_technician != user:
            raise PermissionDenied("You can only return parts on work orders assigned to you.")

        part_usage_id = request.data.get("work_order_part_id")
        if not part_usage_id:
            return Response(
                {"work_order_part_id": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wo_part = get_object_or_404(WorkOrderPart, id=part_usage_id, work_order=work_order)
        notes = request.data.get("notes", "")

        try:
            returned_part = InventoryService.return_part_from_work_order(
                work_order_part=wo_part,
                performed_by=user,
                notes=notes,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(WorkOrderPartSerializer(returned_part).data, status=status.HTTP_200_OK)


