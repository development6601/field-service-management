from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from apps.services.models import ServiceCategory, ServiceType


class ServiceCatalogModelTest(TestCase):
    """Test suite for Service Categories and Types catalog."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(
            name="HVAC & Cooling",
            code="HVAC",
            description="Heating, ventilation, and air conditioning services",
        )

    def test_service_type_creation(self):
        service = ServiceType.objects.create(
            category=self.category,
            name="Commercial AC Overhaul",
            code="AC-OVERHAUL-01",
            base_price=Decimal("4500.00"),
            estimated_duration_minutes=180,
            required_skill="HVAC",
        )

        self.assertEqual(service.base_price, Decimal("4500.00"))
        self.assertEqual(service.estimated_duration_minutes, 180)
        self.assertEqual(str(service), "HVAC & Cooling - Commercial AC Overhaul (AC-OVERHAUL-01)")

    def test_category_deletion_protection(self):
        """Verifies on_delete=models.PROTECT prevents deleting a category with active services."""
        ServiceType.objects.create(
            category=self.category,
            name="Emergency Compressor Fix",
            code="AC-COMP-01",
            base_price=Decimal("2500.00"),
        )

        # Deleting category should raise ProtectedError to safeguard data integrity
        with self.assertRaises(ProtectedError):
            self.category.hard_delete()
