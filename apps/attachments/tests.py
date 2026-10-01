import io
import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.attachments.models import Attachment, AttachmentType, RelatedEntityType
from apps.attachments.services import AttachmentService
from apps.billing.models import Invoice, InvoiceStatus
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class AttachmentModelAndServiceTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin.attach@fsm.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            first_name="Admin",
            last_name="User",
        )
        self.technician = User.objects.create_user(
            email="tech.attach@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Vinod",
            last_name="Mehta",
        )
        self.customer_user = User.objects.create_user(
            email="client.attach@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Kiran",
            last_name="Shah",
        )
        self.customer = Customer.objects.create(
            user=self.customer_user,
            company_name="Ruby Hall Clinic",
            primary_contact_name="Kiran Shah",
            email="client.attach@fsm.com",
            phone="+919811223344",
            billing_address="Sasoon Road, Pune",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Ruby Hall Central",
            address_line1="Sasoon Road",
            city="Pune",
            state="Maharashtra",
            postal_code="411001",
            is_primary=True,
        )
        self.category = ServiceCategory.objects.create(name="Ventilation", code="VENT")
        self.service_type = ServiceType.objects.create(
            name="Ventilator Inspection",
            code="VENT-INSP",
            category=self.category,
            base_price=Decimal("4000.00"),
            estimated_duration_minutes=90,
        )
        self.work_order = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Bi-Annual ICU Ventilator Check",
            status=WorkOrderStatus.ASSIGNED,
            priority=WorkOrderPriority.HIGH,
            assigned_technician=self.technician,
            created_by=self.admin,
        )

    def test_file_size_display_formatting(self):
        att = Attachment(file_size_bytes=500)
        self.assertEqual(att.file_size_display, "500 B")

        att.file_size_bytes = 1024 * 350
        self.assertEqual(att.file_size_display, "350.0 KB")

        att.file_size_bytes = 1024 * 1024 * 4
        self.assertEqual(att.file_size_display, "4.00 MB")

    def test_validate_file_allowed_extension(self):
        file = SimpleUploadedFile("diagnostic_report.pdf", b"%PDF-1.4 sample pdf content", content_type="application/pdf")
        clean_name, mime_type, file_size = AttachmentService.validate_file(file)
        self.assertEqual(clean_name, "diagnostic_report.pdf")
        self.assertEqual(mime_type, "application/pdf")
        self.assertGreater(file_size, 0)

    def test_validate_file_rejects_malicious_executable(self):
        file = SimpleUploadedFile("malicious_script.exe", b"MZBinaryExecContent", content_type="application/octet-stream")
        with self.assertRaises(Exception) as ctx:
            AttachmentService.validate_file(file)
        self.assertIn("strictly prohibited", str(ctx.exception))

    def test_validate_file_rejects_unsupported_format(self):
        file = SimpleUploadedFile("archive.xyz", b"sample random bytes", content_type="application/octet-stream")
        with self.assertRaises(Exception) as ctx:
            AttachmentService.validate_file(file)
        self.assertIn("Unsupported file format", str(ctx.exception))

    def test_validate_file_rejects_oversized_file(self):
        oversized_content = b"x" * (11 * 1024 * 1024)  # 11 MB
        file = SimpleUploadedFile("giant_diagram.pdf", oversized_content, content_type="application/pdf")
        with self.assertRaises(Exception) as ctx:
            AttachmentService.validate_file(file)
        self.assertIn("exceeds the 10 MB limit", str(ctx.exception))

    def test_validate_file_rejects_empty_file(self):
        file = SimpleUploadedFile("empty.png", b"", content_type="image/png")
        with self.assertRaises(Exception) as ctx:
            AttachmentService.validate_file(file)
        self.assertIn("empty (0 bytes)", str(ctx.exception))

    def test_resolve_entity_validation(self):
        # Valid Work Order
        wo_obj = AttachmentService.resolve_entity("work_order", self.work_order.id)
        self.assertEqual(wo_obj.id, self.work_order.id)

        # Invalid Entity ID
        with self.assertRaises(Exception) as ctx:
            AttachmentService.resolve_entity("work_order", uuid.uuid4())
        self.assertIn("does not exist", str(ctx.exception))


class AttachmentAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin.api@fsm.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            first_name="Admin",
            last_name="Super",
        )
        self.technician = User.objects.create_user(
            email="tech.api@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Amit",
            last_name="Roy",
        )
        self.other_technician = User.objects.create_user(
            email="other.tech@fsm.com",
            password="OtherTechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Pooja",
            last_name="Verma",
        )
        self.customer1_user = User.objects.create_user(
            email="client1@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Client",
            last_name="One",
        )
        self.customer2_user = User.objects.create_user(
            email="client2@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Client",
            last_name="Two",
        )
        self.customer1 = Customer.objects.create(
            user=self.customer1_user,
            company_name="Apex Care Center",
            primary_contact_name="Client One",
            email="client1@fsm.com",
        )
        self.customer2 = Customer.objects.create(
            user=self.customer2_user,
            company_name="Fortis Hospital",
            primary_contact_name="Client Two",
            email="client2@fsm.com",
        )
        self.location1 = ServiceLocation.objects.create(
            customer=self.customer1,
            location_name="Apex Wing A",
            address_line1="123 Hospital Lane",
            city="Mumbai",
            state="Maharashtra",
            postal_code="400001",
        )
        self.category = ServiceCategory.objects.create(name="HVAC Units", code="HVAC-UNITS")
        self.service_type = ServiceType.objects.create(
            name="Air Duct Sanitization",
            code="DUCT-SANI",
            category=self.category,
            base_price=Decimal("2500.00"),
            estimated_duration_minutes=60,
        )
        self.work_order1 = WorkOrder.objects.create(
            customer=self.customer1,
            service_location=self.location1,
            service_type=self.service_type,
            title="Ward Air Duct Sanitization",
            status=WorkOrderStatus.ASSIGNED,
            priority=WorkOrderPriority.MEDIUM,
            assigned_technician=self.technician,
            created_by=self.admin,
        )
        self.upload_url = reverse("attachment-list")

    def test_upload_attachment_success(self):
        self.client.force_authenticate(user=self.admin)
        test_file = SimpleUploadedFile("compressor_before.jpg", b"fake image bytes", content_type="image/jpeg")

        payload = {
            "file": test_file,
            "attachment_type": AttachmentType.BEFORE_SERVICE,
            "related_entity_type": RelatedEntityType.WORK_ORDER,
            "related_entity_id": str(self.work_order1.id),
            "description": "Pre-service physical inspection of condenser unit",
        }
        response = self.client.post(self.upload_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["file_name"], "compressor_before.jpg")
        self.assertEqual(response.data["attachment_type"], AttachmentType.BEFORE_SERVICE)
        self.assertEqual(response.data["related_entity_id"], str(self.work_order1.id))
        self.assertIn("download_url", response.data)

    def test_list_attachments_filtered_by_entity(self):
        self.client.force_authenticate(user=self.admin)
        test_file = SimpleUploadedFile("clean_filter.png", b"fake png bytes", content_type="image/png")
        att = Attachment.objects.create(
            file=test_file,
            file_name="clean_filter.png",
            file_type="image/png",
            file_size_bytes=100,
            attachment_type=AttachmentType.AFTER_SERVICE,
            related_entity_type=RelatedEntityType.WORK_ORDER,
            related_entity_id=self.work_order1.id,
            uploaded_by=self.admin,
        )

        response = self.client.get(
            f"{self.upload_url}?entity_type=work_order&entity_id={self.work_order1.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(att.id))

    def test_download_attachment_stream(self):
        self.client.force_authenticate(user=self.admin)
        test_file = SimpleUploadedFile("spec_sheet.pdf", b"%PDF-1.4 test download", content_type="application/pdf")
        att = Attachment.objects.create(
            file=test_file,
            file_name="spec_sheet.pdf",
            file_type="application/pdf",
            file_size_bytes=len(b"%PDF-1.4 test download"),
            attachment_type=AttachmentType.DIAGNOSTIC_REPORT,
            related_entity_type=RelatedEntityType.WORK_ORDER,
            related_entity_id=self.work_order1.id,
            uploaded_by=self.admin,
        )

        download_url = reverse("attachment-download", kwargs={"pk": att.id})
        response = self.client.get(download_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("attachment; filename=\"spec_sheet.pdf\"", response["Content-Disposition"])

    def test_customer_cannot_upload_to_other_customer_entity(self):
        # Customer 2 attempts to upload attachment to Customer 1's work order
        self.client.force_authenticate(user=self.customer2_user)
        test_file = SimpleUploadedFile("illegal_upload.jpg", b"image bytes", content_type="image/jpeg")

        payload = {
            "file": test_file,
            "attachment_type": AttachmentType.BEFORE_SERVICE,
            "related_entity_type": RelatedEntityType.WORK_ORDER,
            "related_entity_id": str(self.work_order1.id),
        }
        response = self.client.post(self.upload_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("permission", str(response.data))

    def test_customer_cannot_view_other_customer_attachments(self):
        # Admin uploads file for Customer 1's work order
        test_file = SimpleUploadedFile("customer1_private.pdf", b"pdf content", content_type="application/pdf")
        att = Attachment.objects.create(
            file=test_file,
            file_name="customer1_private.pdf",
            file_type="application/pdf",
            file_size_bytes=100,
            attachment_type=AttachmentType.CONTRACT_DOCUMENT,
            related_entity_type=RelatedEntityType.WORK_ORDER,
            related_entity_id=self.work_order1.id,
            uploaded_by=self.admin,
        )

        # Customer 2 lists attachments
        self.client.force_authenticate(user=self.customer2_user)
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 0)

        # Customer 2 attempts to retrieve Customer 1's attachment by ID
        detail_url = reverse("attachment-detail", kwargs={"pk": att.id})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_technician_cannot_upload_to_unassigned_work_order(self):
        # Other technician attempts to upload to work_order1
        self.client.force_authenticate(user=self.other_technician)
        test_file = SimpleUploadedFile("unauthorized.jpg", b"image bytes", content_type="image/jpeg")

        payload = {
            "file": test_file,
            "attachment_type": AttachmentType.BEFORE_SERVICE,
            "related_entity_type": RelatedEntityType.WORK_ORDER,
            "related_entity_id": str(self.work_order1.id),
        }
        response = self.client.post(self.upload_url, data=payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
