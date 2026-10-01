from datetime import datetime
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.accounts.models import UserRole
from apps.core.permissions import IsDispatcher
from .models import LeaveStatus, ScheduleOverrideLog, TechnicianLeave
from .serializers import (
    AvailabilityCheckSerializer,
    ScheduleOverrideLogSerializer,
    TechnicianLeaveSerializer,
)
from .services import SchedulingConflictService

User = get_user_model()


class TechnicianLeaveViewSet(viewsets.ModelViewSet):
    """
    CRUD for technician leave and time-off requests.
    - Technicians can request leaves for themselves and view their own leave history.
    - Dispatchers, Managers, and Admins can view all leaves and approve or reject requests.
    """

    serializer_class = TechnicianLeaveSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return TechnicianLeave.objects.none()

        if user.role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER):
            qs = TechnicianLeave.objects.all().select_related("technician", "approved_by")
            tech_id = self.request.query_params.get("technician")
            if tech_id:
                qs = qs.filter(technician_id=tech_id)
            status_param = self.request.query_params.get("status")
            if status_param:
                qs = qs.filter(status=status_param.upper())
            return qs

        if user.role == UserRole.TECHNICIAN:
            return TechnicianLeave.objects.filter(technician=user).select_related("technician", "approved_by")

        return TechnicianLeave.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == UserRole.TECHNICIAN:
            # Technicians can only apply for themselves in PENDING status
            serializer.save(technician=user, status=LeaveStatus.PENDING, approved_by=None)
        elif user.role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER):
            # Dispatchers logging leave on behalf of technician are auto-approved
            serializer.save(status=LeaveStatus.APPROVED, approved_by=user)
        else:
            serializer.save()

    @action(detail=True, methods=["post"], url_path="approve", permission_classes=[IsDispatcher])
    def approve(self, request, pk=None):
        """Approve a pending leave request (Dispatchers/Managers/Admins only)."""
        leave = self.get_object()
        if leave.status == LeaveStatus.APPROVED:
            return Response({"detail": "Leave is already approved."}, status=status.HTTP_400_BAD_REQUEST)

        leave.status = LeaveStatus.APPROVED
        leave.approved_by = request.user
        leave.save(update_fields=["status", "approved_by", "updated_at"])
        serializer = self.get_serializer(leave)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reject", permission_classes=[IsDispatcher])
    def reject(self, request, pk=None):
        """Reject a pending leave request (Dispatchers/Managers/Admins only)."""
        leave = self.get_object()
        if leave.status == LeaveStatus.REJECTED:
            return Response({"detail": "Leave is already rejected."}, status=status.HTTP_400_BAD_REQUEST)

        leave.status = LeaveStatus.REJECTED
        leave.save(update_fields=["status", "updated_at"])
        serializer = self.get_serializer(leave)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """Cancel a pending or approved leave."""
        leave = self.get_object()
        if request.user.role == UserRole.TECHNICIAN and leave.technician != request.user:
            return Response({"detail": "You cannot cancel another technician's leave."}, status=status.HTTP_403_FORBIDDEN)

        if leave.status == LeaveStatus.CANCELLED:
            return Response({"detail": "Leave is already cancelled."}, status=status.HTTP_400_BAD_REQUEST)

        leave.status = LeaveStatus.CANCELLED
        leave.save(update_fields=["status", "updated_at"])
        serializer = self.get_serializer(leave)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SchedulingViewSet(viewsets.ViewSet):
    """
    Dispatch and Scheduling Engine API endpoints:
    - Pre-dispatch collision check
    - Visual timeline and free/busy interval grid
    """

    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["post"], url_path="check", permission_classes=[IsDispatcher])
    def check_availability(self, request):
        """
        Check whether a technician is available for a requested time slot.
        Returns detailed collision analysis, leave detection, and shift adherence warnings.
        """
        serializer = AvailabilityCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        result = SchedulingConflictService.check_availability(
            technician=data["technician"],
            start_datetime=data["scheduled_start"],
            end_datetime=data["scheduled_end"],
            exclude_work_order_id=data.get("work_order_id"),
        )
        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target schedule date (YYYY-MM-DD, defaults to today)",
            ),
            OpenApiParameter(
                name="technician",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional technician UUID filter",
            ),
        ]
    )
    @action(detail=False, methods=["get"], url_path="timeline")
    def daily_timeline(self, request):
        """
        Generates visual timeline intervals for dispatchers and technicians.
        Query params:
        - date: YYYY-MM-DD (defaults to today)
        - technician: UUID (optional filter)
        """
        user = request.user
        date_str = request.query_params.get("date")

        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"error": "Invalid date format. Expected YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = timezone.localdate()

        technician_id = request.query_params.get("technician")
        if user.role == UserRole.TECHNICIAN:
            # Technicians are scoped to their own timeline
            technician_id = str(user.id)
        elif user.role not in (UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER):
            return Response(
                {"detail": "You do not have permission to view technician schedules."},
                status=status.HTTP_403_FORBIDDEN,
            )

        timeline = SchedulingConflictService.get_daily_timeline(
            target_date=target_date,
            technician_id=technician_id,
        )

        return Response(
            {
                "date": target_date.isoformat(),
                "count": len(timeline),
                "timeline": timeline,
            },
            status=status.HTTP_200_OK,
        )


class ScheduleOverrideLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Audit log of emergency dispatch schedule overrides.
    Dispatchers and Admins can inspect justification and collision snapshots.
    """

    serializer_class = ScheduleOverrideLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return ScheduleOverrideLog.objects.none()

        if user.role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER):
            qs = ScheduleOverrideLog.objects.all().select_related("work_order", "technician", "overridden_by")
            wo_id = self.request.query_params.get("work_order")
            if wo_id:
                qs = qs.filter(work_order_id=wo_id)
            tech_id = self.request.query_params.get("technician")
            if tech_id:
                qs = qs.filter(technician_id=tech_id)
            return qs

        if user.role == UserRole.TECHNICIAN:
            return ScheduleOverrideLog.objects.filter(technician=user).select_related(
                "work_order", "technician", "overridden_by"
            )

        return ScheduleOverrideLog.objects.none()
