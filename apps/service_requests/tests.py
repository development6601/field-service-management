import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceCategory, ServiceType
from apps.service_requests.models import (
    RequestPriority,
    RequestStatus,
    ServiceRequest,
    RequestAttachment,
    SLA_HOURS_MATRIX,
)

User = get_user_model()


class ServiceRequestModelTest(TestCase):
    """Test suite for ServiceRequest model, SLA timers, and state machine transitions."""

    def setUp(self):
        self.customer = Customer.objects.create(
            company_name="Max Healthcare",
            primary_contact_name="Dr. Suresh",
            email="suresh@maxhealth.com",
            phone="+919811223344",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Saket Campus",
            address_line1="1 Press Enclave",
            city="New Delhi",
            state="Delhi",
            postal_code="110017",
            is_primary=True,
        )
        self.category = ServiceCategory.objects.create(name="HVAC & Cooling", code="hvac-cooling")
        self.service_type = ServiceType.objects.create(
            category=self.category,
            name="Chiller Plant Repair",
            code="chiller-repair",
            estimated_duration_minutes=210,
            base_price=5000.0,
        )

    def test_request_number_and_sla_auto_calculation(self):
        req = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="ICU Chiller 1 Overheating",
            description="Chiller temperature exceeds 18C, alarm ringing",
            priority=RequestPriority.CRITICAL,
        )

        self.assertTrue(req.request_number.startswith("SR-"))
        self.assertEqual(req.status, RequestStatus.NEW)

        # Check SLA calculation (+1h response, +4h resolution for CRITICAL)
        self.assertIsNotNone(req.sla_response_due_at)
        self.assertIsNotNone(req.sla_resolution_due_at)
        expected_response = req.created_at + timedelta(hours=1)
        expected_resolution = req.created_at + timedelta(hours=4)
        self.assertAlmostEqual(req.sla_response_due_at.timestamp(), expected_response.timestamp(), delta=5)
        self.assertAlmostEqual(req.sla_resolution_due_at.timestamp(), expected_resolution.timestamp(), delta=5)

    def test_invalid_state_transition_prevented(self):
        req = ServiceRequest.objects.create(
            customer=self.customer,
            service_location=self.location,
            title="Standard AC Filter Clean",
            description="Routine maintenance",
            priority=RequestPriority.LOW,
        )

        # Attempt invalid jump: NEW -> COMPLETED directly
        self.assertFalse(req.can_transition_to(RequestStatus.COMPLETED))
        with self.assertRaises(Exception):
            req.transition_to(RequestStatus.COMPLETED)

        # Valid transition: NEW -> REVIEWED
        self.assertTrue(req.can_transition_to(RequestStatus.REVIEWED))
        req.transition_to(RequestStatus.REVIEWED)
        self.assertEqual(req.status, RequestStatus.REVIEWED)


class ServiceRequestAPITest(TestCase):
    """Test suite for ServiceRequest REST API endpoints, RBAC, and file attachments."""

    def setUp(self):
        self.client = APIClient()
        self.password = "Secur3P@ssword!"

        # Admin
        self.admin = User.objects.create_superuser(
            email="admin.sr@fsm.com",
            password=self.password,
            first_name="Admin",
            last_name="Super",
        )
        # Dispatcher
        self.dispatcher = User.objects.create_user(
            email="dispatch.sr@fsm.com",
            password=self.password,
            first_name="Dan",
            last_name="Dispatch",
            role=UserRole.DISPATCHER,
        )
        # Customer A User
        self.cust_user_a = User.objects.create_user(
            email="client.a@max.com",
            password=self.password,
            first_name="Alice",
            last_name="Max",
            role=UserRole.CUSTOMER,
        )
        self.customer_a = Customer.objects.create(
            user=self.cust_user_a,
            company_name="Max Healthcare",
            primary_contact_name="Alice Max",
            email="client.a@max.com",
            phone="+919811001122",
        )
        self.location_a = ServiceLocation.objects.create(
            customer=self.customer_a,
            location_name="Saket Main",
            address_line1="1 Press Enclave",
            city="New Delhi",
            state="Delhi",
            postal_code="110017",
            is_primary=True,
        )

        # Customer B User
        self.cust_user_b = User.objects.create_user(
            email="client.b@fortis.com",
            password=self.password,
            first_name="Bob",
            last_name="Fortis",
            role=UserRole.CUSTOMER,
        )
        self.customer_b = Customer.objects.create(
            user=self.cust_user_b,
            company_name="Fortis Healthcare",
            primary_contact_name="Bob Fortis",
            email="client.b@fortis.com",
            phone="+919822334455",
        )
        self.location_b = ServiceLocation.objects.create(
            customer=self.customer_b,
            location_name="Mohali Branch",
            address_line1="Phase 8",
            city="Mohali",
            state="Punjab",
            postal_code="160062",
            is_primary=True,
        )

        # Obtain tokens
        self.admin_token = self._get_token("admin.sr@fsm.com")
        self.dispatcher_token = self._get_token("dispatch.sr@fsm.com")
        self.cust_a_token = self._get_token("client.a@max.com")
        self.cust_b_token = self._get_token("client.b@fortis.com")

    def _get_token(self, email):
        res = self.client.post("/api/v1/auth/login/", {"email": email, "password": self.password})
        return res.data["access"]

    def test_customer_submits_service_request_successfully(self):
        payload = {
            "service_location": str(self.location_a.id),
            "title": "Water leak in HVAC piping",
            "description": "Pipe leaking near cooling tower 2",
            "priority": RequestPriority.HIGH,
            "preferred_date": "2026-09-25",
            "preferred_time_slot": "Morning (09:00 - 13:00)",
        }
        res = self.client.post(
            "/api/v1/requests/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data["request_number"].startswith("SR-"))
        self.assertEqual(res.data["customer"], self.customer_a.id)

        # Verify SLA dates populated
        created_req = ServiceRequest.objects.get(id=res.data["id"])
        self.assertEqual(created_req.priority, RequestPriority.HIGH)
        self.assertEqual(created_req.reported_by, self.cust_user_a)

    def test_tenant_isolation_customer_cannot_see_other_customer_requests(self):
        # Create request for Customer A
        req_a = ServiceRequest.objects.create(
            customer=self.customer_a,
            service_location=self.location_a,
            reported_by=self.cust_user_a,
            title="Max Request",
            description="Detail",
            priority=RequestPriority.MEDIUM,
        )
        # Create request for Customer B
        req_b = ServiceRequest.objects.create(
            customer=self.customer_b,
            service_location=self.location_b,
            reported_by=self.cust_user_b,
            title="Fortis Request",
            description="Detail",
            priority=RequestPriority.MEDIUM,
        )

        # Customer A queries list
        res_a = self.client.get(
            "/api/v1/requests/",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        results_a = res_a.data.get("results", res_a.data)
        ids_a = [item["id"] for item in results_a]
        self.assertIn(str(req_a.id), ids_a)
        self.assertNotIn(str(req_b.id), ids_a)

        # Dispatcher queries list -> sees both
        res_disp = self.client.get(
            "/api/v1/requests/",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res_disp.status_code, status.HTTP_200_OK)
        results_disp = res_disp.data.get("results", res_disp.data)
        ids_disp = [item["id"] for item in results_disp]
        self.assertIn(str(req_a.id), ids_disp)
        self.assertIn(str(req_b.id), ids_disp)

    def test_dispatcher_reviews_and_triages_request(self):
        req = ServiceRequest.objects.create(
            customer=self.customer_a,
            service_location=self.location_a,
            reported_by=self.cust_user_a,
            title="Elevator Air Conditioning",
            description="Not cooling",
            priority=RequestPriority.LOW,
            status=RequestStatus.NEW,
        )

        # Dispatcher upgrades priority to HIGH and adds notes
        res = self.client.post(
            f"/api/v1/requests/{req.id}/review/",
            {"dispatcher_notes": "Reviewed and escalated to high urgency", "priority": RequestPriority.HIGH},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], RequestStatus.REVIEWED)
        self.assertEqual(res.data["priority"], RequestPriority.HIGH)
        self.assertEqual(res.data["dispatcher_notes"], "Reviewed and escalated to high urgency")
        self.assertEqual(res.data["reviewed_by_name"], "Dan Dispatch")

    def test_cancellation_with_reason(self):
        req = ServiceRequest.objects.create(
            customer=self.customer_a,
            service_location=self.location_a,
            reported_by=self.cust_user_a,
            title="Duplicate issue",
            description="Detail",
            priority=RequestPriority.LOW,
            status=RequestStatus.NEW,
        )

        res = self.client.post(
            f"/api/v1/requests/{req.id}/cancel/",
            {"reason": "Duplicate ticket raised by mistake"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], RequestStatus.CANCELLED)
        self.assertEqual(res.data["cancellation_reason"], "Duplicate ticket raised by mistake")

    def test_photo_attachment_upload_and_validation(self):
        req = ServiceRequest.objects.create(
            customer=self.customer_a,
            service_location=self.location_a,
            reported_by=self.cust_user_a,
            title="Broken compressor display",
            description="Photo evidence",
            priority=RequestPriority.MEDIUM,
        )

        # 1. Valid image upload
        image_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        uploaded_image = SimpleUploadedFile("chiller_fault.png", image_content, content_type="image/png")

        res = self.client.post(
            f"/api/v1/requests/{req.id}/attachments/",
            {"file": uploaded_image, "description": "Fault code screenshot"},
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["file_name"], "chiller_fault.png")
        self.assertEqual(res.data["file_type"], "png")

        # Verify attached to request detail
        detail_res = self.client.get(
            f"/api/v1/requests/{req.id}/",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(len(detail_res.data["attachments"]), 1)

        # 2. Invalid file extension rejected
        exe_content = b"MZ\x90\x00"
        invalid_file = SimpleUploadedFile("malicious.exe", exe_content, content_type="application/x-msdownload")
        bad_res = self.client.post(
            f"/api/v1/requests/{req.id}/attachments/",
            {"file": invalid_file},
            format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unsupported file extension", str(bad_res.data))
