from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User, UserRole
from apps.contracts.models import ContractStatus, ServiceContract
from apps.contracts.serializers import (
    ContractTerminateSerializer,
    GeneratePreventiveWorkOrderSerializer,
    ServiceContractCreateSerializer,
    ServiceContractDetailSerializer,
    ServiceContractListSerializer,
)
from apps.contracts.services import ContractService
from apps.core.permissions import IsAdminOrManager
from apps.services.models import ServiceType
from apps.work_orders.serializers import WorkOrderDetailSerializer
from drf_spectacular.utils import extend_schema


class ServiceContractViewSet(viewsets.ModelViewSet):
    """
    CRUD and lifecycle operations for Annual Maintenance Contracts (AMC).
    Supports quota tracking, contract activation, termination, and
    automated preventive maintenance work order generation.
    """

    permission_classes = [permissions.IsAuthenticated]
    queryset = (
        ServiceContract.objects.select_related("customer", "service_location", "created_by")
        .prefetch_related("covered_services", "work_orders__assigned_technician")
        .all()
    )

    def get_serializer_class(self):
        if self.action == "create":
            return ServiceContractCreateSerializer
        elif self.action in ["retrieve", "update", "partial_update"]:
            return ServiceContractDetailSerializer
        return ServiceContractListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Multi-Tenant Visibility Isolation:
        if user.role == UserRole.CUSTOMER:
            qs = qs.filter(customer__user=user)

        # Filters
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        customer_param = self.request.query_params.get("customer")
        if customer_param:
            qs = qs.filter(customer_id=customer_param)

        location_param = self.request.query_params.get("service_location")
        if location_param:
            qs = qs.filter(service_location_id=location_param)

        is_expired = self.request.query_params.get("is_expired")
        if is_expired is not None:
            today = timezone.localdate()
            if is_expired.lower() == "true":
                qs = qs.filter(Q(end_date__lt=today) | Q(status=ContractStatus.EXPIRED))
            else:
                qs = qs.filter(end_date__gte=today).exclude(status=ContractStatus.EXPIRED)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(contract_number__icontains=search)
                | Q(title__icontains=search)
                | Q(customer__company_name__icontains=search)
            )

        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(request=None, responses={200: ServiceContractDetailSerializer})
    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        """
        Transition a contract from DRAFT to ACTIVE.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            return Response(
                {"detail": "Only Admins and Managers can activate service contracts."},
                status=status.HTTP_403_FORBIDDEN,
            )

        contract = self.get_object()
        try:
            active_contract = ContractService.activate_contract(contract, performed_by=request.user)
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ServiceContractDetailSerializer(active_contract, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=GeneratePreventiveWorkOrderSerializer, responses={201: WorkOrderDetailSerializer})
    @action(detail=True, methods=["post"], url_path="generate-work-order")
    def generate_work_order(self, request, pk=None):
        """
        Dispatch a scheduled preventive maintenance WorkOrder under the contract.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]:
            return Response(
                {"detail": "Only Admins, Managers, and Dispatchers can generate maintenance work orders."},
                status=status.HTTP_403_FORBIDDEN,
            )

        contract = self.get_object()
        serializer = GeneratePreventiveWorkOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        technician = None
        if data.get("assigned_technician_id"):
            technician = get_object_or_404(User, id=data["assigned_technician_id"], role=UserRole.TECHNICIAN)

        service_type = None
        if data.get("service_type_id"):
            service_type = get_object_or_404(ServiceType, id=data["service_type_id"])

        try:
            work_order = ContractService.generate_preventive_work_order(
                contract=contract,
                scheduled_date=data.get("scheduled_date"),
                assigned_technician=technician,
                service_type=service_type,
                performed_by=request.user,
                job_instructions=data.get("job_instructions", ""),
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            WorkOrderDetailSerializer(work_order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=ContractTerminateSerializer, responses={200: ServiceContractDetailSerializer})
    @action(detail=True, methods=["post"], url_path="terminate")
    def terminate(self, request, pk=None):
        """
        Prematurely cancel/terminate a contract with a mandatory justification reason.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            return Response(
                {"detail": "Only Admins and Managers can terminate contracts."},
                status=status.HTTP_403_FORBIDDEN,
            )

        contract = self.get_object()
        serializer = ContractTerminateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            terminated_contract = ContractService.terminate_contract(
                contract,
                reason=serializer.validated_data["reason"],
                performed_by=request.user,
            )
        except DjangoValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ServiceContractDetailSerializer(terminated_contract, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )
