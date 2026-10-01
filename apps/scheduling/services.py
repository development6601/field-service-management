from datetime import datetime, time, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import zoneinfo

from apps.accounts.models import UserRole
from apps.work_orders.models import WorkOrder, WorkOrderStatus
from .models import LeaveStatus, TechnicianLeave

User = get_user_model()


class SchedulingConflictService:
    """
    Intelligent dispatch and collision engine.
    Calculates interval overlaps, working hours adherence, and planned leaves.
    """

    @classmethod
    def check_availability(
        cls,
        technician,
        start_datetime: datetime,
        end_datetime: datetime,
        exclude_work_order_id=None,
    ) -> dict:
        """
        Evaluates availability for a technician across a requested [start, end] window.
        Returns a dict containing conflict flags, detailed collision records, and shift warnings.
        """
        conflicts = []
        warnings = []

        if not technician or technician.role != UserRole.TECHNICIAN:
            return {
                "is_available": False,
                "has_conflicts": True,
                "conflicts": [{"type": "INVALID_ROLE", "message": "Selected user is not a technician."}],
                "warnings": [],
            }

        profile = getattr(technician, "technician_profile", None)

        # 1. Profile Availability Flag
        if profile and not profile.is_available:
            conflicts.append({
                "type": "UNAVAILABLE",
                "message": f"Technician '{technician.full_name}' is currently marked as unavailable for dispatch.",
            })

        # 2. Approved Leaves & Time-Off Check
        start_date = start_datetime.date()
        end_date = end_datetime.date()
        active_leaves = TechnicianLeave.objects.filter(
            technician=technician,
            status=LeaveStatus.APPROVED,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        for leave in active_leaves:
            conflicts.append({
                "type": "ON_LEAVE",
                "message": (
                    f"Technician '{technician.full_name}' is on {leave.get_leave_type_display()} "
                    f"from {leave.start_date} to {leave.end_date}."
                ),
                "leave_id": str(leave.id),
                "leave_type": leave.leave_type,
            })

        # 3. Shift Working Hours Adherence
        tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        local_start = start_datetime.astimezone(tz)
        local_end = end_datetime.astimezone(tz)

        shift_start = profile.working_hours_start if profile and profile.working_hours_start else time(8, 30)
        shift_end = profile.working_hours_end if profile and profile.working_hours_end else time(17, 30)

        # Check if outside daily shift
        if local_start.time() < shift_start or local_end.time() > shift_end:
            warnings.append({
                "type": "OUTSIDE_SHIFT",
                "message": (
                    f"Requested slot ({local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}) "
                    f"is outside technician's regular shift ({shift_start.strftime('%H:%M')} - {shift_end.strftime('%H:%M')})."
                ),
                "shift_start": shift_start.strftime("%H:%M"),
                "shift_end": shift_end.strftime("%H:%M"),
            })

        # 4. Work Order Interval Collision (Interval Overlap Math)
        # S_existing < E_new AND E_existing > S_new
        overlapping_wos = (
            WorkOrder.objects.filter(
                assigned_technician=technician,
                scheduled_start__isnull=False,
                scheduled_end__isnull=False,
                scheduled_start__lt=end_datetime,
                scheduled_end__gt=start_datetime,
            )
            .exclude(status__in=[WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED, WorkOrderStatus.REJECTED])
            .select_related("customer", "service_location")
        )

        if exclude_work_order_id:
            overlapping_wos = overlapping_wos.exclude(id=exclude_work_order_id)

        for wo in overlapping_wos:
            wo_local_start = wo.scheduled_start.astimezone(tz)
            wo_local_end = wo.scheduled_end.astimezone(tz)
            conflicts.append({
                "type": "WORK_ORDER_COLLISION",
                "message": (
                    f"Double-booking conflict with {wo.work_order_number} ({wo.title}) "
                    f"scheduled from {wo_local_start.strftime('%H:%M')} to {wo_local_end.strftime('%H:%M')}."
                ),
                "work_order_id": str(wo.id),
                "work_order_number": wo.work_order_number,
                "work_order_title": wo.title,
                "scheduled_start": wo.scheduled_start.isoformat(),
                "scheduled_end": wo.scheduled_end.isoformat(),
            })

        has_conflicts = any(c["type"] in ["WORK_ORDER_COLLISION", "ON_LEAVE", "UNAVAILABLE"] for c in conflicts)

        return {
            "is_available": not has_conflicts,
            "has_conflicts": has_conflicts,
            "conflicts": conflicts,
            "warnings": warnings,
        }

    @classmethod
    def get_daily_timeline(cls, target_date, technician_id=None) -> list:
        """
        Generates visual timeline intervals for dispatchers.
        Computes busy blocks and free intervals within each technician's daily shift.
        """
        if isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

        tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        day_start = timezone.make_aware(datetime.combine(target_date, time(0, 0, 0)), tz)
        day_end = timezone.make_aware(datetime.combine(target_date, time(23, 59, 59)), tz)

        tech_qs = User.objects.filter(role=UserRole.TECHNICIAN, is_active=True).select_related("technician_profile")
        if technician_id:
            tech_qs = tech_qs.filter(id=technician_id)

        timeline = []

        for tech in tech_qs:
            profile = getattr(tech, "technician_profile", None)
            shift_start_time = profile.working_hours_start if profile and profile.working_hours_start else time(8, 30)
            shift_end_time = profile.working_hours_end if profile and profile.working_hours_end else time(17, 30)

            shift_start_dt = timezone.make_aware(datetime.combine(target_date, shift_start_time), tz)
            shift_end_dt = timezone.make_aware(datetime.combine(target_date, shift_end_time), tz)

            # Check if technician is on leave on this date
            on_leave = TechnicianLeave.objects.filter(
                technician=tech,
                status=LeaveStatus.APPROVED,
                start_date__lte=target_date,
                end_date__gte=target_date,
            ).first()

            # Query scheduled work orders for this day
            scheduled_wos = (
                WorkOrder.objects.filter(
                    assigned_technician=tech,
                    scheduled_start__isnull=False,
                    scheduled_end__isnull=False,
                    scheduled_start__lt=day_end,
                    scheduled_end__gt=day_start,
                )
                .exclude(status__in=[WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED, WorkOrderStatus.REJECTED])
                .select_related("customer", "service_location")
                .order_by("scheduled_start")
            )

            busy_slots = []
            for wo in scheduled_wos:
                busy_slots.append({
                    "work_order_id": str(wo.id),
                    "work_order_number": wo.work_order_number,
                    "title": wo.title,
                    "customer_name": wo.customer.display_name,
                    "location_name": wo.service_location.location_name,
                    "status": wo.status,
                    "priority": wo.priority,
                    "start": wo.scheduled_start.isoformat(),
                    "end": wo.scheduled_end.isoformat(),
                    "start_time": wo.scheduled_start.astimezone(tz).strftime("%H:%M"),
                    "end_time": wo.scheduled_end.astimezone(tz).strftime("%H:%M"),
                })

            # Calculate free slots within shift hours
            free_slots = []
            if not on_leave:
                current_cursor = shift_start_dt
                for wo in scheduled_wos:
                    wo_start = max(wo.scheduled_start, shift_start_dt)
                    if wo_start > current_cursor:
                        diff_minutes = int((wo_start - current_cursor).total_seconds() / 60)
                        if diff_minutes >= 15:  # meaningful gap of at least 15 mins
                            free_slots.append({
                                "start": current_cursor.isoformat(),
                                "end": wo_start.isoformat(),
                                "start_time": current_cursor.astimezone(tz).strftime("%H:%M"),
                                "end_time": wo_start.astimezone(tz).strftime("%H:%M"),
                                "duration_minutes": diff_minutes,
                            })
                    current_cursor = max(current_cursor, wo.scheduled_end)

                if current_cursor < shift_end_dt:
                    diff_minutes = int((shift_end_dt - current_cursor).total_seconds() / 60)
                    if diff_minutes >= 15:
                        free_slots.append({
                            "start": current_cursor.isoformat(),
                            "end": shift_end_dt.isoformat(),
                            "start_time": current_cursor.astimezone(tz).strftime("%H:%M"),
                            "end_time": shift_end_dt.astimezone(tz).strftime("%H:%M"),
                            "duration_minutes": diff_minutes,
                        })

            timeline.append({
                "technician_id": str(tech.id),
                "technician_name": tech.full_name,
                "email": tech.email,
                "phone_number": tech.phone_number,
                "skills": profile.skills if profile else [],
                "shift": f"{shift_start_time.strftime('%H:%M')} - {shift_end_time.strftime('%H:%M')}",
                "is_available": profile.is_available if profile else True,
                "on_leave": bool(on_leave),
                "leave_reason": on_leave.reason if on_leave else None,
                "busy_slots": busy_slots,
                "free_slots": free_slots,
            })

        return timeline
