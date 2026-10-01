import uuid
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.accounts.models import UserRole, TechnicianProfile

User = get_user_model()


class CustomUserModelTest(TestCase):
    """Test suite for Custom User model and role behaviors."""

    def test_create_standard_user(self):
        user = User.objects.create_user(
            email="technician1@example.com",
            password="SecurePassword123!",
            first_name="Ramesh",
            last_name="Kumar",
            role=UserRole.TECHNICIAN,
        )

        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.email, "technician1@example.com")
        self.assertEqual(user.role, UserRole.TECHNICIAN)
        self.assertTrue(user.is_technician)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("SecurePassword123!"))
        self.assertFalse(user.is_deleted)

    def test_create_superuser(self):
        admin_user = User.objects.create_superuser(
            email="admin@fsm.com",
            password="AdminPassword123!",
            first_name="Super",
            last_name="Admin",
        )

        self.assertEqual(admin_user.role, UserRole.ADMIN)
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_admin)

    def test_user_email_normalization(self):
        email = "TEST.USER@EXAMPLE.COM"
        user = User.objects.create_user(email=email, password="Password123!")
        self.assertEqual(user.email, "TEST.USER@example.com")

    def test_role_queryset_filters(self):
        User.objects.create_user(email="t1@example.com", role=UserRole.TECHNICIAN)
        User.objects.create_user(email="d1@example.com", role=UserRole.DISPATCHER)
        User.objects.create_user(email="c1@example.com", role=UserRole.CUSTOMER)

        self.assertEqual(User.objects.technicians().count(), 1)
        self.assertEqual(User.objects.dispatchers().count(), 1)
        self.assertEqual(User.objects.customers().count(), 1)

    def test_technician_profile_link(self):
        tech_user = User.objects.create_user(
            email="tech.hvac@example.com",
            role=UserRole.TECHNICIAN,
            first_name="Amit",
            last_name="Sharma",
        )
        profile = TechnicianProfile.objects.create(
            user=tech_user,
            skills=["HVAC", "Electrical"],
            working_hours_start="08:00:00",
            working_hours_end="17:00:00",
        )

        self.assertIsInstance(profile.id, uuid.UUID)
        self.assertEqual(tech_user.technician_profile.skills, ["HVAC", "Electrical"])
        self.assertTrue(tech_user.technician_profile.is_available)

    def test_soft_deletion(self):
        user = User.objects.create_user(email="deleted@example.com", password="Pass123!")
        user_id = user.id

        # Perform soft-delete
        user.delete()

        # Should not be in default queryset
        self.assertFalse(User.objects.filter(id=user_id).exists())
        # Should still exist in all_objects (or alive vs dead querysets)
        self.assertTrue(User.objects.deleted_only().filter(id=user_id).exists())

        # Restore user
        user.restore()
        self.assertTrue(User.objects.filter(id=user_id).exists())


class JWTAuthenticationAPITest(TestCase):
    """Test suite for JWT authentication, refresh, blacklist, and profile endpoints."""

    def setUp(self):
        self.password = "P@ssword1234!"
        self.user = User.objects.create_user(
            email="tech.jwt@example.com",
            password=self.password,
            first_name="Karan",
            last_name="Verma",
            role=UserRole.TECHNICIAN,
        )
        self.login_url = "/api/v1/auth/login/"
        self.refresh_url = "/api/v1/auth/refresh/"
        self.logout_url = "/api/v1/auth/logout/"
        self.me_url = "/api/v1/auth/me/"
        self.change_password_url = "/api/v1/auth/change-password/"

    def test_login_success(self):
        response = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["role"], UserRole.TECHNICIAN)
        self.assertEqual(response.data["user"]["email"], self.user.email)
        self.assertEqual(response.data["user"]["full_name"], "Karan Verma")

    def test_login_invalid_credentials(self):
        response = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": "WrongPassword123!"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_login_soft_deleted_account_rejected(self):
        self.user.delete()  # soft-delete
        response = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_token_refresh(self):
        login_res = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        refresh_token = login_res.data["refresh"]

        refresh_res = self.client.post(
            self.refresh_url,
            {"refresh": refresh_token},
            content_type="application/json",
        )
        self.assertEqual(refresh_res.status_code, 200)
        self.assertIn("access", refresh_res.data)

    def test_logout_and_token_blacklisting(self):
        login_res = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        access_token = login_res.data["access"]
        refresh_token = login_res.data["refresh"]

        # Logout with access token in header and refresh in body
        logout_res = self.client.post(
            self.logout_url,
            {"refresh": refresh_token},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(logout_res.status_code, 200)

        # Attempting to refresh with blacklisted token should fail
        reuse_res = self.client.post(
            self.refresh_url,
            {"refresh": refresh_token},
            content_type="application/json",
        )
        self.assertEqual(reuse_res.status_code, 401)

    def test_profile_endpoint(self):
        login_res = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        access_token = login_res.data["access"]

        # Authenticated request
        profile_res = self.client.get(
            self.me_url,
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(profile_res.status_code, 200)
        self.assertEqual(profile_res.data["email"], self.user.email)
        self.assertEqual(profile_res.data["role"], UserRole.TECHNICIAN)

        # Unauthenticated request should fail
        unauth_res = self.client.get(self.me_url)
        self.assertEqual(unauth_res.status_code, 401)

    def test_change_password(self):
        login_res = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        access_token = login_res.data["access"]

        new_password = "BrandNewSecurePassword123!"
        change_res = self.client.post(
            self.change_password_url,
            {"old_password": self.password, "new_password": new_password},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(change_res.status_code, 200)

        # Old password must fail now
        old_login = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": self.password},
            content_type="application/json",
        )
        self.assertEqual(old_login.status_code, 401)

        # New password must succeed
        new_login = self.client.post(
            self.login_url,
            {"email": self.user.email, "password": new_password},
            content_type="application/json",
        )
        self.assertEqual(new_login.status_code, 200)


class UserRolesAndPermissionsAPITest(TestCase):
    """Test suite for Phase 4: RBAC, registration, user management, and technician roster."""

    def setUp(self):
        self.password = "Secur3P@ssword!"
        # Admin user
        self.admin = User.objects.create_superuser(
            email="admin.rbac@example.com",
            password=self.password,
            first_name="Admin",
            last_name="Boss",
        )
        # Dispatcher user
        self.dispatcher = User.objects.create_user(
            email="dispatcher.rbac@example.com",
            password=self.password,
            first_name="David",
            last_name="Dispatch",
            role=UserRole.DISPATCHER,
        )
        # Technician user
        self.technician = User.objects.create_user(
            email="tech.rbac@example.com",
            password=self.password,
            first_name="Tom",
            last_name="Tech",
            role=UserRole.TECHNICIAN,
        )
        TechnicianProfile.objects.create(
            user=self.technician,
            skills=["HVAC", "Cooling"],
            is_available=True,
            working_hours_start="09:00:00",
            working_hours_end="18:00:00",
        )
        # Customer user
        self.customer = User.objects.create_user(
            email="cust.rbac@example.com",
            password=self.password,
            first_name="Charlie",
            last_name="Client",
            role=UserRole.CUSTOMER,
        )

        # Pre-authenticate users
        self.admin_token = self._get_token("admin.rbac@example.com")
        self.dispatcher_token = self._get_token("dispatcher.rbac@example.com")
        self.technician_token = self._get_token("tech.rbac@example.com")
        self.customer_token = self._get_token("cust.rbac@example.com")

    def _get_token(self, email):
        res = self.client.post(
            "/api/v1/auth/login/",
            {"email": email, "password": self.password},
            content_type="application/json",
        )
        return res.data["access"]

    def test_customer_registration_success(self):
        from apps.customers.models import Customer

        payload = {
            "email": "new.customer@example.com",
            "password": "CustomerSecure123!",
            "first_name": "Pooja",
            "last_name": "Nair",
            "phone_number": "+919876500000",
            "company_name": "Nair Logistics",
        }
        res = self.client.post(
            "/api/v1/auth/register/",
            payload,
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["email"], "new.customer@example.com")
        self.assertEqual(res.data["role"], UserRole.CUSTOMER)

        # Verify linked Customer model was created
        created_user = User.objects.get(email="new.customer@example.com")
        self.assertTrue(Customer.objects.filter(user=created_user).exists())
        cust = Customer.objects.get(user=created_user)
        self.assertEqual(cust.company_name, "Nair Logistics")

    def test_customer_registration_prevents_privilege_escalation(self):
        payload = {
            "email": "hacker@example.com",
            "password": "HackerSecure123!",
            "first_name": "Sneaky",
            "last_name": "Hacker",
            "role": "ADMIN",  # Hacker tries to become admin!
        }
        res = self.client.post(
            "/api/v1/auth/register/",
            payload,
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        # Must strictly be assigned CUSTOMER role
        created_user = User.objects.get(email="hacker@example.com")
        self.assertEqual(created_user.role, UserRole.CUSTOMER)
        self.assertFalse(created_user.is_staff)

    def test_admin_creates_technician_with_skills(self):
        payload = {
            "email": "tech.new@example.com",
            "password": "NewTechPassword123!",
            "first_name": "Suresh",
            "last_name": "Rao",
            "phone_number": "+919988776611",
            "role": "TECHNICIAN",
            "technician_profile": {
                "skills": ["Electrical", "Solar Panels"],
                "is_available": True,
                "working_hours_start": "08:30:00",
                "working_hours_end": "17:30:00",
            },
        }
        res = self.client.post(
            "/api/v1/users/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 201)
        new_tech = User.objects.get(email="tech.new@example.com")
        self.assertEqual(new_tech.role, UserRole.TECHNICIAN)
        self.assertEqual(new_tech.technician_profile.skills, ["Electrical", "Solar Panels"])

    def test_non_admin_cannot_create_or_delete_users(self):
        payload = {
            "email": "illegal.user@example.com",
            "password": "IllegalPassword123!",
            "first_name": "Illegal",
            "last_name": "User",
            "role": "DISPATCHER",
        }
        # Customer attempts to create user -> 403 Forbidden
        res_cust = self.client.post(
            "/api/v1/users/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.customer_token}",
        )
        self.assertEqual(res_cust.status_code, 403)

        # Dispatcher attempts to create user -> 403 Forbidden
        res_disp = self.client.post(
            "/api/v1/users/",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res_disp.status_code, 403)

        # Customer attempts to delete technician -> 403 Forbidden
        res_del = self.client.delete(
            f"/api/v1/users/{self.technician.id}/",
            HTTP_AUTHORIZATION=f"Bearer {self.customer_token}",
        )
        self.assertEqual(res_del.status_code, 403)

    def test_admin_cannot_delete_own_account(self):
        res = self.client.delete(
            f"/api/v1/users/{self.admin.id}/",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 400)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_deleted)

    def test_admin_soft_deletes_other_user(self):
        res = self.client.delete(
            f"/api/v1/users/{self.technician.id}/",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(res.status_code, 204)
        self.technician.refresh_from_db()
        self.assertTrue(self.technician.is_deleted)

    def test_dispatcher_can_access_technician_roster(self):
        res = self.client.get(
            "/api/v1/users/technicians/roster/",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res.status_code, 200)
        items = res.data.get("results", res.data)
        self.assertTrue(len(items) >= 1)

        # Test filter by skill
        res_skill = self.client.get(
            "/api/v1/users/technicians/roster/?skill=HVAC",
            HTTP_AUTHORIZATION=f"Bearer {self.dispatcher_token}",
        )
        self.assertEqual(res_skill.status_code, 200)
        skill_items = res_skill.data.get("results", res_skill.data)
        emails = [item["email"] for item in skill_items]
        self.assertIn(self.technician.email, emails)

    def test_customer_cannot_access_technician_roster(self):
        res = self.client.get(
            "/api/v1/users/technicians/roster/",
            HTTP_AUTHORIZATION=f"Bearer {self.customer_token}",
        )
        self.assertEqual(res.status_code, 403)


