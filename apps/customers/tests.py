import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.accounts.models import UserRole
from apps.customers.models import Customer, ServiceLocation

User = get_user_model()


class CustomerModelTest(TestCase):
    """Test suite for Customer and multi-location management."""

    def setUp(self):
        self.customer = Customer.objects.create(
            company_name="Acme Corp India",
            primary_contact_name="Rajesh Patel",
            email="rajesh@acme.com",
            phone="+919876543210",
            billing_address="101 Tech Park, Whitefield, Bengaluru, KA",
            tax_id="29ABCDE1234F1Z5",
        )

    def test_customer_creation(self):
        self.assertIsInstance(self.customer.id, uuid.UUID)
        self.assertEqual(self.customer.display_name, "Acme Corp India")
        self.assertEqual(str(self.customer), "Acme Corp India (Rajesh Patel)")

    def test_multi_service_locations(self):
        loc1 = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="HQ Office",
            address_line1="Tower A, Ground Floor",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560066",
            latitude=12.9716,
            longitude=77.5946,
            is_primary=True,
        )
        loc2 = ServiceLocation.objects.create(
            customer=self.customer,
            location_name="Warehouse 2",
            address_line1="Peenya Industrial Area",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560058",
            latitude=13.0285,
            longitude=77.5197,
            is_primary=False,
        )

        self.assertEqual(self.customer.service_locations.count(), 2)
        self.assertTrue(loc1.is_primary)
        self.assertFalse(loc2.is_primary)

    def test_customer_soft_delete_preserves_records(self):
        cust_id = self.customer.id
        self.customer.delete()

        # Regular queries ignore soft-deleted records
        self.assertFalse(Customer.objects.filter(id=cust_id).exists())
        # Restore user
        # Soft-deleted records exist in deleted_only
        self.assertTrue(Customer.objects.deleted_only().filter(id=cust_id).exists())


class CustomerAPITest(TestCase):
    """Test suite for Customer and ServiceLocation REST APIs."""

    def setUp(self):
        self.password = "Secur3P@ssword!"
        # Admin
        self.admin = User.objects.create_superuser(
            email="admin.cust@example.com",
            password=self.password,
            first_name="Admin",
            last_name="Super",
        )
        # Dispatcher
        self.dispatcher = User.objects.create_user(
            email="dispatch.cust@example.com",
            password=self.password,
            first_name="Dan",
            last_name="Dispatch",
            role=UserRole.DISPATCHER,
        )
        # Customer A user & profile
        self.customer_user_a = User.objects.create_user(
            email="cust.a@example.com",
            password=self.password,
            first_name="Alice",
            last_name="Alpha",
            role=UserRole.CUSTOMER,
        )
        self.cust_a = Customer.objects.create(
            user=self.customer_user_a,
            company_name="Alpha Corp",
            primary_contact_name="Alice Alpha",
            email="cust.a@example.com",
            phone="+919800000001",
        )
        # Customer B user & profile
        self.customer_user_b = User.objects.create_user(
            email="cust.b@example.com",
            password=self.password,
            first_name="Bob",
            last_name="Beta",
            role=UserRole.CUSTOMER,
        )
        self.cust_b = Customer.objects.create(
            user=self.customer_user_b,
            company_name="Beta Corp",
            primary_contact_name="Bob Beta",
            email="cust.b@example.com",
            phone="+919800000002",
        )

        self.admin_token = self._get_token("admin.cust@example.com")
        self.dispatcher_token = self._get_token("dispatch.cust@example.com")
        self.cust_a_token = self._get_token("cust.a@example.com")
        self.cust_b_token = self._get_token("cust.b@example.com")

    def _get_token(self, email):
        res = self.client.post(
            "/api/v1/auth/login/",
            {"email": email, "password": self.password},
            content_type="application/json",
        )
        return res.data["access"]

    def test_admin_creates_customer_with_primary_location(self):
        payload = {
            "company_name": "Zenith Tech Park",
            "primary_contact_name": "Siddharth Jain",
            "email": "sid@zenith.com",
            "phone": "+919833445566",
            "billing_address": "Tower 4, Electronic City, Bengaluru",
            "tax_id": "29XYZAB1234K1Z1",
            "initial_location": {
                "location_name": "Main Tech Campus",
                "address_line1": "Plot 12, Phase 1",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560100",
                "latitude": "12.845200",
                "longitude": "77.660200",
            },
        }
        res = self.client.post(
            "/api/v1/customers/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 201)

        customer = Customer.objects.get(email="sid@zenith.com")
        self.assertEqual(customer.service_locations.count(), 1)
        primary_loc = customer.service_locations.first()
        self.assertEqual(primary_loc.location_name, "Main Tech Campus")
        self.assertTrue(primary_loc.is_primary)

    def test_atomic_primary_location_switch(self):
        # Create initial location as primary
        loc1 = ServiceLocation.objects.create(
            customer=self.cust_a,
            location_name="Branch 1",
            address_line1="1st Main Rd",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            is_primary=True,
        )

        # Create 2nd location via API with is_primary=True
        payload = {
            "location_name": "Branch 2 (New HQ)",
            "address_line1": "2nd Cross Rd",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560002",
            "is_primary": True,
        }
        res = self.client.post(
            f"/api/v1/customers/{self.cust_a.id}/locations/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 201)

        # Atomic switch verification: loc1 must be demoted to is_primary=False
        loc1.refresh_from_db()
        self.assertFalse(loc1.is_primary)

        # loc2 must be primary
        loc2 = ServiceLocation.objects.get(id=res.data["id"])
        self.assertTrue(loc2.is_primary)

    def test_invalid_latitude_and_longitude_rejected(self):
        payload = {
            "location_name": "Invalid Coordinates Site",
            "address_line1": "Somewhere Outer Space",
            "city": "Unknown",
            "state": "Unknown",
            "postal_code": "000000",
            "latitude": "99.999999",  # Invalid > 90
            "longitude": "200.000000",  # Invalid > 180
        }
        res = self.client.post(
            f"/api/v1/customers/{self.cust_a.id}/locations/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("latitude", res.data)
        self.assertIn("longitude", res.data)

    def test_tenant_isolation_customer_only_accesses_own_records(self):
        # Customer A lists customers: only cust_a is returned
        res = self.client.get(
            "/api/v1/customers/",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results", res.data)
        customer_ids = [str(c["id"]) for c in results]
        self.assertIn(str(self.cust_a.id), customer_ids)
        self.assertNotIn(str(self.cust_b.id), customer_ids)

        # Customer A attempts to add location to Customer B -> 403 Forbidden
        payload = {
            "location_name": "Intruder Branch",
            "address_line1": "Illegal St",
            "city": "Delhi",
            "state": "Delhi",
            "postal_code": "110001",
        }
        res_hack = self.client.post(
            f"/api/v1/customers/{self.cust_b.id}/locations/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.cust_a_token}",
        )
        self.assertEqual(res_hack.status_code, 403)

    def test_dispatcher_manages_all_customers_and_locations(self):
        # Dispatcher lists all customers: sees both cust_a and cust_b
        res = self.client.get(
            "/api/v1/customers/",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results", res.data)
        self.assertTrue(len(results) >= 2)

        # Dispatcher adds location to cust_b
        payload = {
            "location_name": "Beta Warehouse Pune",
            "address_line1": "MIDC Bhosari",
            "city": "Pune",
            "state": "Maharashtra",
            "postal_code": "411026",
            "latitude": "18.627900",
            "longitude": "73.843600",
        }
        res_add = self.client.post(
            f"/api/v1/customers/{self.cust_b.id}/locations/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res_add.status_code, 201)

    def test_customer_soft_deletion(self):
        res = self.client.delete(
            f"/api/v1/customers/{self.cust_b.id}/",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 204)
        self.cust_b.refresh_from_db()
        self.assertTrue(self.cust_b.is_deleted)

