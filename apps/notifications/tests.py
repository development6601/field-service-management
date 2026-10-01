import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import UserRole
from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentMethod, PaymentStatus
from apps.customers.models import Customer, ServiceLocation
from apps.inventory.models import Part, PartCategory, StockItem, Warehouse
from apps.notifications.models import Notification, NotificationPriority, NotificationType
from apps.notifications.services import NotificationService
from apps.service_requests.models import RequestPriority, RequestStatus, ServiceRequest
from apps.services.models import ServiceCategory, ServiceType
from apps.work_orders.models import WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()


class NotificationModelAndServiceTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin.notif@fsm.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            first_name="Admin",
            last_name="User",
        )
        self.technician = User.objects.create_user(
            email="tech.notif@fsm.com",
            password="TechPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="Sanjay",
            last_name="Dutta",
        )
        self.customer_user = User.objects.create_user(
            email="client.notif@fsm.com",
            password="ClientPassword123!",
            role=UserRole.CUSTOMER,
            first_name="Ravi",
            last_name="Patel",
        )
        self.customer = Customer.objects.create(
            user=self.customer_user,
            company_name="Sterling Healthcare",
            primary_contact_name="Ravi Patel",
            email="client.notif@fsm.com",
            phone="+919800112233",
            billing_address="Sterling Towers, MG Road, Pune",
        )
        self.location = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Sterling Pune Central",
            address_line1="MG Road",
            city="Pune",
            state="Maharashtra",
            postal_code="411001",
            is_primary=True,
        )
        self.category = ServiceCategory.objects.create(name="Medical Systems", code="MED-SYS")
        self.service_type = ServiceType.objects.create(
            name="MRI Maintenance",
            code="MRI-MAINT",
            category=self.category,
            base_price=Decimal("5000.00"),
            estimated_duration_minutes=120,
        )

    def test_notification_creation_and_mark_as_read(self):
        notif = NotificationService.send(
            recipient=self.technician,
            title="Emergency Job Alert",
            message="Immediate response required at Sterling Pune Central.",
            notification_type=NotificationType.WORK_ORDER_ASSIGNED,
            priority=NotificationPriority.URGENT,
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.technician)
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)

        notif.mark_as_read()
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)

    def test_notify_work_order_assigned_service(self):
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Quarterly MRI Calibration",
            status=WorkOrderStatus.ASSIGNED,
            priority=WorkOrderPriority.HIGH,
            assigned_technician=self.technician,
            created_by=self.admin,
        )
        notif = NotificationService.notify_work_order_assigned(wo)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.technician)
        self.assertEqual(notif.notification_type, NotificationType.WORK_ORDER_ASSIGNED)
        self.assertIn("Quarterly MRI Calibration", notif.message)

    def test_notify_work_order_status_change(self):
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Quarterly MRI Calibration",
            status=WorkOrderStatus.TRAVELING,
            priority=WorkOrderPriority.HIGH,
            assigned_technician=self.technician,
            created_by=self.admin,
        )
        notif = NotificationService.notify_work_order_status_change(wo)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.customer_user)
        self.assertIn("Technician On The Way", notif.title)

    def test_notify_invoice_generated_and_payment_received(self):
        wo = WorkOrder.objects.create(
            customer=self.customer,
            service_location=self.location,
            service_type=self.service_type,
            title="Quarterly MRI Calibration",
            status=WorkOrderStatus.COMPLETED,
            created_by=self.admin,
        )
        invoice = Invoice.objects.create(
            work_order=wo,
            customer=self.customer,
            status=InvoiceStatus.ISSUED,
            issue_date="2026-09-28",
            total_amount=Decimal("5900.00"),
            created_by=self.admin,
        )
        notif_inv = NotificationService.notify_invoice_generated(invoice)
        self.assertIsNotNone(notif_inv)
        self.assertEqual(notif_inv.recipient, self.customer_user)
        self.assertIn("New Invoice Issued", notif_inv.title)

        payment = Payment.objects.create(
            invoice=invoice,
            amount=Decimal("5900.00"),
            payment_method=PaymentMethod.UPI,
            payment_status=PaymentStatus.SUCCESS,
            transaction_reference="UPI-REF-112233",
            payment_date="2026-09-28",
            recorded_by=self.admin,
        )
        notif_pay = NotificationService.notify_payment_received(payment)
        self.assertIsNotNone(notif_pay)
        self.assertEqual(notif_pay.recipient, self.customer_user)
        self.assertIn("Payment Received", notif_pay.title)

    def test_notify_low_stock(self):
        wh = Warehouse.objects.create(code="WH-PUNE-01", name="Pune Depot", city="Pune")
        part = Part.objects.create(
            sku="MRI-COIL-01",
            name="RF Receiver Coil",
            category=PartCategory.ELECTRICAL,
            reorder_threshold=5,
        )
        stock = StockItem.objects.create(
            part=part,
            location_type="WAREHOUSE",
            warehouse=wh,
            quantity_on_hand=3,
        )
        notifs = NotificationService.notify_low_stock(stock)
        self.assertGreater(len(notifs), 0)
        self.assertTrue(any(n.recipient == self.admin for n in notifs))
        self.assertEqual(notifs[0].notification_type, NotificationType.LOW_STOCK_ALERT)


class NotificationAPITests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            email="user1@fsm.com",
            password="UserPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="User",
            last_name="One",
        )
        self.user2 = User.objects.create_user(
            email="user2@fsm.com",
            password="UserPassword123!",
            role=UserRole.TECHNICIAN,
            first_name="User",
            last_name="Two",
        )

        # Seed notifications for user1
        self.n1 = Notification.objects.create(
            recipient=self.user1,
            title="Ticket 1 Assigned",
            message="You have been assigned to Ticket 1",
            notification_type=NotificationType.WORK_ORDER_ASSIGNED,
            priority=NotificationPriority.HIGH,
            is_read=False,
        )
        self.n2 = Notification.objects.create(
            recipient=self.user1,
            title="Invoice Alert",
            message="Invoice paid",
            notification_type=NotificationType.INVOICE_GENERATED,
            priority=NotificationPriority.NORMAL,
            is_read=True,
        )

        # Seed notification for user2
        self.n3 = Notification.objects.create(
            recipient=self.user2,
            title="Private Alert",
            message="For user2 only",
            notification_type=NotificationType.GENERAL,
            is_read=False,
        )

        self.list_url = reverse("notification-list")
        self.unread_url = reverse("notification-unread-count")
        self.mark_all_url = reverse("notification-mark-all-read")

    def test_list_notifications_user_isolation(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should see user1's 2 notifications, and NEVER user2's
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 2)
        returned_ids = [item["id"] for item in results]
        self.assertIn(str(self.n1.id), returned_ids)
        self.assertIn(str(self.n2.id), returned_ids)
        self.assertNotIn(str(self.n3.id), returned_ids)

    def test_filter_notifications_by_is_read(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"{self.list_url}?is_read=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.n1.id))

    def test_unread_count_endpoint(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(self.unread_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["unread_count"], 1)

    def test_mark_single_notification_read(self):
        self.client.force_authenticate(user=self.user1)
        mark_url = reverse("notification-mark-read", kwargs={"pk": self.n1.pk})
        response = self.client.post(mark_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_read"])
        self.assertIsNotNone(response.data["read_at"])

        # Unread count should now be 0
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)

    def test_cross_user_mark_read_blocked(self):
        # User 1 tries to mark User 2's notification as read
        self.client.force_authenticate(user=self.user1)
        mark_url = reverse("notification-mark-read", kwargs={"pk": self.n3.pk})
        response = self.client.post(mark_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_all_read(self):
        self.client.force_authenticate(user=self.user1)
        response = self.client.post(self.mark_all_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["marked_count"], 1)

        # Verification
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
