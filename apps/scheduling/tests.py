from datetime import date, datetime, time, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
import zoneinfo

from apps.accounts.models import TechnicianProfile, UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.scheduling.models import LeaveStatus, LeaveType, ScheduleOverrideLog, TechnicianLeave
from apps.scheduling.services import SchedulingConflictService
from apps.work_orders.models import WorkOrder, WorkOrderStatus

User = get_user_model()


class SchedulingConflictServiceTest(TestCase):
    """Test unit logic for interval overlap math, leaves, and shift adherence."""

    def setUp(self):
        self.tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        self.customer = Customer.objects.create(
            company_name="Max Healthcare",
            primary_contact_name="Dr. Sharma",
            email="dr.sharma@max.com",
            phone="+919811223344",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Saket Wing A",
            address_line1="1 Press Enclave Marg",
            city="New Delhi",
            state="Delhi",
            postal_code="110017",
            is_primary=True,
        )
        self.technician = User.objects.create_user(
            email="tech.ramesh@fsm.com",
            password="TechPassword123!",
            first_name="Ramesh",
            last_name="Verma",
            role=UserRole.TECHNICIAN,
        )
        TechnicianProfile.objects.create(
            user=self.technician,
            working_hours_start=time(9, 0),
            working_hours_end=time(18, 0),
            is_available=True,
        )

        # Existing scheduled job from 10:00 to 12:00
        today = timezone.localdate()
        self.existing_start = timezone.make_aware(datetime.combine(today, time(10, 0)), self.tz)
        self.existing_end = timezone.make_aware(datetime.combine(today, time(12, 0)), self.tz)

        self.existing_wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.technician,
            title="Scheduled Chiller Maintenance",
            scheduled_start=self.existing_start,
            scheduled_end=self.existing_end,
            status=WorkOrderStatus.SCHEDULED,
        )

    def test_interval_overlap_inside(self):
        """New job completely inside existing job (10:30 to 11:30) must collide."""
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time(10, 30)), self.tz)
        end = timezone.make_aware(datetime.combine(today, time(11, 30)), self.tz)

        res = SchedulingConflictService.check_availability(self.technician, start, end)
        self.assertFalse(res["is_available"])
        self.assertTrue(res["has_conflicts"])
        self.assertEqual(res["conflicts"][0]["type"], "WORK_ORDER_COLLISION")

    def test_interval_overlap_engulfing(self):
        """New job completely engulfs existing job (09:30 to 12:30) must collide."""
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time(9, 30)), self.tz)
        end = timezone.make_aware(datetime.combine(today, time(12, 30)), self.tz)

        res = SchedulingConflictService.check_availability(self.technician, start, end)
        self.assertFalse(res["is_available"])
        self.assertTrue(res["has_conflicts"])

    def test_interval_overlap_partial_start(self):
        """New job starts before and ends inside existing job (09:30 to 10:30) must collide."""
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time(9, 30)), self.tz)
        end = timezone.make_aware(datetime.combine(today, time(10, 30)), self.tz)

        res = SchedulingConflictService.check_availability(self.technician, start, end)
        self.assertFalse(res["is_available"])
        self.assertTrue(res["has_conflicts"])

    def test_interval_overlap_partial_end(self):
        """New job starts inside and ends after existing job (11:30 to 13:00) must collide."""
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time(11, 30)), self.tz)
        end = timezone.make_aware(datetime.combine(today, time(13, 0)), self.tz)

        res = SchedulingConflictService.check_availability(self.technician, start, end)
        self.assertFalse(res["is_available"])
        self.assertTrue(res["has_conflicts"])

    def test_adjacent_time_slots_do_not_collide(self):
        """Job ending exactly when existing starts (09:00 - 10:00) or starting when existing ends (12:00 - 14:00) must NOT collide."""
        today = timezone.localdate()
        # Adjacent before: 09:00 - 10:00
        start_before = timezone.make_aware(datetime.combine(today, time(9, 0)), self.tz)
        end_before = timezone.make_aware(datetime.combine(today, time(10, 0)), self.tz)
        res_before = SchedulingConflictService.check_availability(self.technician, start_before, end_before)
        self.assertTrue(res_before["is_available"])
        self.assertFalse(res_before["has_conflicts"])

        # Adjacent after: 12:00 - 14:00
        start_after = timezone.make_aware(datetime.combine(today, time(12, 0)), self.tz)
        end_after = timezone.make_aware(datetime.combine(today, time(14, 0)), self.tz)
        res_after = SchedulingConflictService.check_availability(self.technician, start_after, end_after)
        self.assertTrue(res_after["is_available"])
        self.assertFalse(res_after["has_conflicts"])

    def test_exclude_work_order_id_when_rescheduling(self):
        """Updating same work order should exclude itself from conflict check."""
        res = SchedulingConflictService.check_availability(
            self.technician,
            self.existing_start,
            self.existing_end,
            exclude_work_order_id=self.existing_wo.id,
        )
        self.assertTrue(res["is_available"])
        self.assertFalse(res["has_conflicts"])

    def test_approved_leave_blocks_scheduling(self):
        """Technician on approved leave cannot be scheduled without override."""
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        TechnicianLeave.objects.create(
            technician=self.technician,
            leave_type=LeaveType.SICK,
            start_date=tomorrow,
            end_date=tomorrow,
            status=LeaveStatus.APPROVED,
        )

        start = timezone.make_aware(datetime.combine(tomorrow, time(10, 0)), self.tz)
        end = timezone.make_aware(datetime.combine(tomorrow, time(12, 0)), self.tz)

        res = SchedulingConflictService.check_availability(self.technician, start, end)
        self.assertFalse(res["is_available"])
        self.assertTrue(res["has_conflicts"])
        self.assertEqual(res["conflicts"][0]["type"], "ON_LEAVE")

    def test_outside_shift_generates_warning(self):
        """Booking outside shift hours (e.g. 06:00 - 08:00 when shift is 09:00 - 18:00) gives shift warning."""
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time(6, 0)), self.tz)
        end = timezone.make_aware(datetime.combine(today, time(8, 0)), self.tz)

        res = SchedulingConflictService.check_availability(self.technician, start, end)
        self.assertTrue(res["is_available"])  # Shift alone is a warning, not a hard double-booking conflict
        self.assertTrue(any(w["type"] == "OUTSIDE_SHIFT" for w in res["warnings"]))


class SchedulingAPITest(TestCase):
    """Test REST API endpoints for dispatch timeline, leaves, and collision overrides."""

    def setUp(self):
        self.client = APIClient()
        self.tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)

        # Users
        self.dispatcher = User.objects.create_user(
            email="dispatcher@fsm.com",
            password="DispatcherPassword123!",
            first_name="Anita",
            last_name="Desai",
            role=UserRole.DISPATCHER,
        )
        self.technician = User.objects.create_user(
            email="tech.ramesh@fsm.com",
            password="TechPassword123!",
            first_name="Ramesh",
            last_name="Verma",
            role=UserRole.TECHNICIAN,
        )
        TechnicianProfile.objects.create(
            user=self.technician,
            working_hours_start=time(9, 0),
            working_hours_end=time(18, 0),
            is_available=True,
        )

        # Customer & Location
        self.customer = Customer.objects.create(
            company_name="Fortis Healthcare",
            primary_contact_name="Dr. Trehan",
            email="escorts@fortis.com",
            phone="+919811998877",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Okhla Facility",
            address_line1="Okhla Road",
            city="New Delhi",
            state="Delhi",
            postal_code="110025",
            is_primary=True,
        )

        # Pre-existing scheduled work order
        today = timezone.localdate()
        self.today = today
        self.slot1_start = timezone.make_aware(datetime.combine(today, time(10, 0)), self.tz)
        self.slot1_end = timezone.make_aware(datetime.combine(today, time(12, 0)), self.tz)

        self.wo1 = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.technician,
            title="Chiller 1 Repair",
            scheduled_start=self.slot1_start,
            scheduled_end=self.slot1_end,
            status=WorkOrderStatus.SCHEDULED,
        )

        # New unassigned work order to test assignment
        self.wo2 = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            title="Chiller 2 Compressor Failure",
            status=WorkOrderStatus.DRAFT,
        )

    def test_check_availability_api(self):
        """Dispatcher checks technician availability via POST /api/v1/scheduling/check/."""
        self.client.force_authenticate(user=self.dispatcher)
        url = "/api/v1/scheduling/check/"
        payload = {
            "technician": str(self.technician.id),
            "scheduled_start": self.slot1_start.isoformat(),
            "scheduled_end": self.slot1_end.isoformat(),
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_available"])
        self.assertTrue(response.data["has_conflicts"])
        self.assertEqual(response.data["conflicts"][0]["type"], "WORK_ORDER_COLLISION")

    def test_assign_colliding_slot_fails_without_override(self):
        """Assigning a conflicting slot returns 400 Bad Request."""
        self.client.force_authenticate(user=self.dispatcher)
        url = f"/api/v1/work-orders/{self.wo2.id}/assign/"
        payload = {
            "assigned_technician": str(self.technician.id),
            "scheduled_start": self.slot1_start.isoformat(),
            "scheduled_end": self.slot1_end.isoformat(),
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Double-booking conflict", str(response.data))

    def test_assign_colliding_slot_succeeds_with_emergency_override(self):
        """Assigning with force_override=True and reason succeeds and logs audit entry."""
        self.client.force_authenticate(user=self.dispatcher)
        url = f"/api/v1/work-orders/{self.wo2.id}/assign/"
        payload = {
            "assigned_technician": str(self.technician.id),
            "scheduled_start": self.slot1_start.isoformat(),
            "scheduled_end": self.slot1_end.isoformat(),
            "force_override": True,
            "override_reason": "Emergency ICU cooling failure requires immediate two-person response.",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.wo2.refresh_from_db()
        self.assertEqual(self.wo2.assigned_technician, self.technician)
        self.assertEqual(self.wo2.status, WorkOrderStatus.SCHEDULED)

        # Verify audit log was created
        override_log = ScheduleOverrideLog.objects.filter(work_order=self.wo2).first()
        self.assertIsNotNone(override_log)
        self.assertEqual(override_log.overridden_by, self.dispatcher)
        self.assertIn("ICU cooling", override_log.override_reason)

    def test_daily_timeline_api(self):
        """GET /api/v1/scheduling/timeline/?date=YYYY-MM-DD returns timeline grid."""
        self.client.force_authenticate(user=self.dispatcher)
        url = f"/api/v1/scheduling/timeline/?date={self.today.isoformat()}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["date"], self.today.isoformat())
        self.assertGreaterEqual(response.data["count"], 1)

        tech_timeline = response.data["timeline"][0]
        self.assertEqual(tech_timeline["technician_name"], "Ramesh Verma")
        self.assertEqual(len(tech_timeline["busy_slots"]), 1)
        self.assertEqual(tech_timeline["busy_slots"][0]["title"], "Chiller 1 Repair")
        self.assertGreater(len(tech_timeline["free_slots"]), 0)

    def test_technician_leave_workflow(self):
        """Technician requests leave (PENDING), dispatcher approves (APPROVED)."""
        # Technician applies
        self.client.force_authenticate(user=self.technician)
        leave_url = "/api/v1/scheduling/leaves/"
        tomorrow = self.today + timedelta(days=2)
        payload = {
            "leave_type": LeaveType.VACATION,
            "start_date": tomorrow.isoformat(),
            "end_date": tomorrow.isoformat(),
            "reason": "Family wedding in Jaipur",
        }
        res_create = self.client.post(leave_url, payload, format="json")
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        leave_id = res_create.data["id"]
        self.assertEqual(res_create.data["status"], LeaveStatus.PENDING)

        # Dispatcher approves
        self.client.force_authenticate(user=self.dispatcher)
        approve_url = f"/api/v1/scheduling/leaves/{leave_id}/approve/"
        res_approve = self.client.post(approve_url)
        self.assertEqual(res_approve.status_code, status.HTTP_200_OK)
        self.assertEqual(res_approve.data["status"], LeaveStatus.APPROVED)
        self.assertEqual(res_approve.data["approved_by_name"], "Anita Desai")
