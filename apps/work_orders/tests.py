import uuid
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceCategory, ServiceType
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.work_orders.models import WorkOrder, WorkOrderHistory, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class WorkOrderModelTest(TestCase):
    """Test suite for WorkOrder model rules, technician role enforcement, and state transitions."""

    def setUp(self):
        self.customer = Customer.objects.create(
            company_name="Apollo Hospitals",
            primary_contact_name="Dr. Reddy",
            email="facilities@apollo.com",
            phone="+919840012345",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Main Campus",
            address_line1="Greams Road",
            city="Chennai",
            state="Tamil Nadu",
            postal_code="600006",
            is_primary=True,
        )
        self.tech_user = User.objects.create_user(
            email="tech.ramesh@fsm.com",
            password="TechPassword123!",
            first_name="Ramesh",
            last_name="Verma",
            role=UserRole.TECHNICIAN,
        )
        self.non_tech_user = User.objects.create_user(
            email="cust.user@apollo.com",
            password="CustPassword123!",
            first_name="Alice",
            last_name="Customer",
            role=UserRole.CUSTOMER,
        )

    def test_work_order_number_auto_generation(self):
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            title="AC Chiller Maintenance",
        )
        self.assertTrue(wo.work_order_number.startswith("WO-"))
        self.assertEqual(wo.status, WorkOrderStatus.DRAFT)

    def test_technician_role_enforcement(self):
        # Assigning a user with role=CUSTOMER must fail validation
        wo = WorkOrder(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.non_tech_user,
            title="Invalid Assignment",
        )
        with self.assertRaises(ValidationError):
            wo.full_clean()

        # Assigning a valid technician succeeds
        wo.assigned_technician = self.tech_user
        wo.full_clean()  # should not raise
        wo.save()
        self.assertEqual(wo.assigned_technician, self.tech_user)

    def test_state_machine_and_audit_history(self):
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_user,
            title="Generator Servicing",
        )
        # Because technician was assigned, status auto-promotes to ASSIGNED
        self.assertEqual(wo.status, WorkOrderStatus.ASSIGNED)

        # Valid transition: ASSIGNED -> IN_PROGRESS
        self.assertTrue(wo.can_transition_to(WorkOrderStatus.IN_PROGRESS))
        wo.transition_to(WorkOrderStatus.IN_PROGRESS, user=self.tech_user, notes="Job started on site")
        self.assertEqual(wo.status, WorkOrderStatus.IN_PROGRESS)
        self.assertIsNotNone(wo.actual_start)

        # Check audit history was written
        self.assertTrue(wo.history.filter(to_status=WorkOrderStatus.IN_PROGRESS).exists())

        # Invalid jump: IN_PROGRESS directly to DRAFT
        self.assertFalse(wo.can_transition_to(WorkOrderStatus.DRAFT))
        with self.assertRaises(ValidationError):
            wo.transition_to(WorkOrderStatus.DRAFT)


class WorkOrderAPITest(TestCase):
    """Test suite for WorkOrder REST APIs, conversion, scheduling, and RBAC."""

    def setUp(self):
        self.client = APIClient()
        self.password = "Secur3P@ssword!"

        # Admin
        self.admin = User.objects.create_superuser(
            email="admin.wo@fsm.com",
            password=self.password,
            first_name="Admin",
            last_name="Super",
        )
        # Dispatcher
        self.dispatcher = User.objects.create_user(
            email="dispatch.wo@fsm.com",
            password=self.password,
            first_name="Dan",
            last_name="Dispatcher",
            role=UserRole.DISPATCHER,
        )
        # Technician 1
        self.tech_1 = User.objects.create_user(
            email="tech1@fsm.com",
            password=self.password,
            first_name="Ramesh",
            last_name="Kumar",
            role=UserRole.TECHNICIAN,
        )
        # Technician 2
        self.tech_2 = User.objects.create_user(
            email="tech2@fsm.com",
            password=self.password,
            first_name="Suresh",
            last_name="Patel",
            role=UserRole.TECHNICIAN,
        )
        # Customer User
        self.cust_user = User.objects.create_user(
            email="client@fortis.com",
            password=self.password,
            first_name="Dr. Naresh",
            last_name="Trehan",
            role=UserRole.CUSTOMER,
        )
        self.customer = Customer.objects.create(
            user=self.cust_user,
            company_name="Fortis Healthcare",
            primary_contact_name="Dr. Naresh Trehan",
            email="facilities@fortis.com",
            phone="+919811002233",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Okhla Hospital",
            address_line1="Okhla Road",
            city="New Delhi",
            state="Delhi",
            postal_code="110025",
            is_primary=True,
        )

        # Tokens
        self.admin_token = self._get_token("admin.wo@fsm.com")
        self.dispatcher_token = self._get_token("dispatch.wo@fsm.com")
        self.tech_1_token = self._get_token("tech1@fsm.com")
        self.tech_2_token = self._get_token("tech2@fsm.com")
        self.cust_token = self._get_token("client@fortis.com")

    def _get_token(self, email):
        res = self.client.post("/api/v1/auth/login/", {"email": email, "password": self.password})
        return res.data["access"]

    def test_convert_reviewed_service_request_to_work_order(self):
        # Create a REVIEWED Service Request
        sr = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            reported_by=self.cust_user,
            title="Chiller leak in basement",
            description="Refrigerant pressure dropped to zero",
            priority=RequestPriority.CRITICAL,
            status=RequestStatus.REVIEWED,
        )

        now = timezone.now()
        payload = {
            "service_request": str(sr.id),
            "assigned_technician": str(self.tech_1.id),
            "scheduled_start": (now + timedelta(hours=2)).isoformat(),
            "scheduled_end": (now + timedelta(hours=4)).isoformat(),
            "job_instructions": "Check safety valves and pressure gauges first",
        }

        res = self.client.post(
            "/api/v1/work-orders/convert/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["work_order_number"].startswith("WO-"))
        self.assertEqual(res.data["customer"], self.customer.id)
        self.assertEqual(res.data["assigned_technician"], self.tech_1.id)
        self.assertEqual(res.data["status"], WorkOrderStatus.SCHEDULED)

        # Verify parent service request status synchronized to SCHEDULED
        sr.refresh_from_db()
        self.assertEqual(sr.status, RequestStatus.SCHEDULED)

    def test_conversion_fails_if_service_request_not_reviewed(self):
        # Service Request in status NEW
        sr_new = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            reported_by=self.cust_user,
            title="Draft request",
            description="Details",
            status=RequestStatus.NEW,
        )

        payload = {"service_request": str(sr_new.id)}
        res = self.client.post(
            "/api/v1/work-orders/convert/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only 'REVIEWED' tickets can be converted", str(res.data))

    def test_technician_job_lifecycle_execution(self):
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="Electrical DB Box Inspection",
            status=WorkOrderStatus.ASSIGNED,
        )

        # 1. Tech 1 starts job
        res_start = self.client.post(
            f"/api/v1/work-orders/{wo.id}/status/",
            {"status": WorkOrderStatus.IN_PROGRESS, "notes": "Arrived at site, opened DB box"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_start.status_code, status.HTTP_200_OK)
        self.assertEqual(res_start.data["status"], WorkOrderStatus.IN_PROGRESS)
        self.assertIsNotNone(res_start.data["actual_start"])

        # 2. Tech 1 completes job with labor hours
        res_done = self.client.post(
            f"/api/v1/work-orders/{wo.id}/status/",
            {
                "status": WorkOrderStatus.COMPLETED,
                "notes": "Replaced 32A MCB, power restored",
                "labor_hours": "1.75",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_done.status_code, status.HTTP_200_OK)
        self.assertEqual(res_done.data["status"], WorkOrderStatus.COMPLETED)
        self.assertEqual(Decimal(str(res_done.data["labor_hours"])), Decimal("1.75"))

    def test_tenant_and_role_isolation(self):
        # Work order assigned to Tech 1
        wo_1 = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="Job for Tech 1",
            status=WorkOrderStatus.ASSIGNED,
        )
        # Work order assigned to Tech 2
        wo_2 = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_2,
            title="Job for Tech 2",
            status=WorkOrderStatus.ASSIGNED,
        )

        # Tech 1 only sees wo_1
        res_t1 = self.client.get(
            "/api/v1/work-orders/",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_t1.status_code, status.HTTP_200_OK)
        results_t1 = res_t1.data.get("results", res_t1.data)
        ids_t1 = [item["id"] for item in results_t1]
        self.assertIn(str(wo_1.id), ids_t1)
        self.assertNotIn(str(wo_2.id), ids_t1)

        # Tech 2 cannot modify Tech 1's work order
        bad_update = self.client.post(
            f"/api/v1/work-orders/{wo_1.id}/status/",
            {"status": WorkOrderStatus.IN_PROGRESS},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_2_token}",
        )
        self.assertIn(bad_update.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # Dispatcher sees both
        res_disp = self.client.get(
            "/api/v1/work-orders/",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        results_disp = res_disp.data.get("results", res_disp.data)
        ids_disp = [item["id"] for item in results_disp]
        self.assertIn(str(wo_1.id), ids_disp)
        self.assertIn(str(wo_2.id), ids_disp)

    def test_technician_step_by_step_mobile_workflow(self):
        """Tests the full mobile lifecycle: ACCEPTED -> TRAVELING -> ARRIVED -> IN_PROGRESS -> COMPLETED."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="MRI Chiller Emergency Maintenance",
            status=WorkOrderStatus.SCHEDULED,
        )

        # 1. Accept Job
        res_accept = self.client.post(
            f"/api/v1/work-orders/{wo.id}/accept/",
            {"notes": "Accepting job, prepping toolkit"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_accept.status_code, status.HTTP_200_OK)
        self.assertEqual(res_accept.data["status"], WorkOrderStatus.ACCEPTED)

        # 2. Start Travel
        res_travel = self.client.post(
            f"/api/v1/work-orders/{wo.id}/start-travel/",
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_travel.status_code, status.HTTP_200_OK)
        self.assertEqual(res_travel.data["status"], WorkOrderStatus.TRAVELING)
        self.assertIsNotNone(res_travel.data["travel_started_at"])

        # 3. Arrive on site
        res_arrive = self.client.post(
            f"/api/v1/work-orders/{wo.id}/arrive/",
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_arrive.status_code, status.HTTP_200_OK)
        self.assertEqual(res_arrive.data["status"], WorkOrderStatus.ARRIVED)
        self.assertIsNotNone(res_arrive.data["arrived_at"])

        # 4. Start Work
        res_work = self.client.post(
            f"/api/v1/work-orders/{wo.id}/start-work/",
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_work.status_code, status.HTTP_200_OK)
        self.assertEqual(res_work.data["status"], WorkOrderStatus.IN_PROGRESS)
        self.assertIsNotNone(res_work.data["actual_start"])

        # 5. Complete with Digital Signature & Customer Rating
        complete_payload = {
            "service_summary": "Replaced cracked compressor gasket, topped up 3.5kg R-410A refrigerant, calibrated pressure switch.",
            "labor_hours": "2.25",
            "customer_signature": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
            "signed_by_name": "Dr. A. K. Reddy (Medical Director)",
            "customer_rating": 5,
            "customer_feedback": "Outstanding speed and thorough diagnostic tests.",
        }
        res_complete = self.client.post(
            f"/api/v1/work-orders/{wo.id}/complete/",
            complete_payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_complete.status_code, status.HTTP_200_OK)
        self.assertEqual(res_complete.data["status"], WorkOrderStatus.COMPLETED)
        self.assertEqual(res_complete.data["labor_hours"], "2.25")
        self.assertIsNotNone(res_complete.data["actual_end"])
        self.assertEqual(res_complete.data["signed_by_name"], "Dr. A. K. Reddy (Medical Director)")
        self.assertIsNotNone(res_complete.data["signed_at"])
        self.assertEqual(res_complete.data["customer_rating"], 5)
        self.assertEqual(res_complete.data["customer_signature"], "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...")

    def test_technician_rejection_workflow(self):
        """Technician rejects assigned job with mandatory justification reason."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="Elevator Main Motor Overhaul",
            status=WorkOrderStatus.SCHEDULED,
        )

        # Missing reason fails
        res_bad = self.client.post(
            f"/api/v1/work-orders/{wo.id}/reject/",
            {},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)

        # Valid rejection succeeds
        res_good = self.client.post(
            f"/api/v1/work-orders/{wo.id}/reject/",
            {"rejection_reason": "Lack certified high-voltage elevator rig equipment"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res_good.status_code, status.HTTP_200_OK)
        self.assertEqual(res_good.data["status"], WorkOrderStatus.REJECTED)
        self.assertEqual(res_good.data["rejection_reason"], "Lack certified high-voltage elevator rig equipment")

    def test_unassigned_technician_cannot_act_on_other_jobs(self):
        """Technician 2 cannot accept or complete Technician 1's work order."""
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="Private tech 1 assignment",
            status=WorkOrderStatus.SCHEDULED,
        )

        res_illegal = self.client.post(
            f"/api/v1/work-orders/{wo.id}/accept/",
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_2_token}",
        )
        self.assertIn(res_illegal.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_my_jobs_mobile_dashboard_endpoint(self):
        """GET /api/v1/work-orders/my-jobs/ returns categorized active, upcoming, and completed jobs."""
        # Active job
        wo_active = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="Active Emergency Job",
            status=WorkOrderStatus.IN_PROGRESS,
        )
        # Upcoming job
        wo_upcoming = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            assigned_technician=self.tech_1,
            title="Upcoming Routine Maintenance",
            status=WorkOrderStatus.SCHEDULED,
        )

        res = self.client.get(
            "/api/v1/work-orders/my-jobs/",
            HTTP_AUTHORIZATION=f"Bearer {self.tech_1_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(res.data["active_job"])
        self.assertEqual(res.data["active_job"]["id"], str(wo_active.id))
        self.assertEqual(res.data["active_jobs_count"], 1)
        self.assertEqual(len(res.data["upcoming_jobs"]), 1)
        self.assertEqual(res.data["upcoming_jobs"][0]["id"], str(wo_upcoming.id))

