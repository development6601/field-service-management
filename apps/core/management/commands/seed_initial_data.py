from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.accounts.models import UserRole, TechnicianProfile
from apps.customers.models import Customer, ServiceLocation
from apps.services.models import ServiceCategory, ServiceType

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds initial demo data (Admin, Dispatcher, Technician, Customer, and Services)"

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")

        # 1. Admin Superuser
        admin_user, created = User.objects.get_or_create(
            email="admin@fsm.com",
            defaults={
                "first_name": "System",
                "last_name": "Administrator",
                "role": UserRole.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin_user.set_password("Admin123!")
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created Admin: admin@fsm.com (Password: Admin123!)"))
        else:
            self.stdout.write("Admin user already exists.")

        # 2. Dispatcher User
        disp_user, created = User.objects.get_or_create(
            email="dispatcher@fsm.com",
            defaults={
                "first_name": "Vikram",
                "last_name": "Malhotra",
                "role": UserRole.DISPATCHER,
                "phone_number": "+919811122233",
            },
        )
        if created:
            disp_user.set_password("Dispatch123!")
            disp_user.save()
            self.stdout.write(self.style.SUCCESS("Created Dispatcher: dispatcher@fsm.com"))

        # 3. Technician User & Profile
        tech_user, created = User.objects.get_or_create(
            email="tech.ramesh@fsm.com",
            defaults={
                "first_name": "Ramesh",
                "last_name": "Sharma",
                "role": UserRole.TECHNICIAN,
                "phone_number": "+919877788899",
            },
        )
        if created:
            tech_user.set_password("Tech123!")
            tech_user.save()
            TechnicianProfile.objects.create(
                user=tech_user,
                skills=["HVAC", "Electrical"],
                working_hours_start="09:00:00",
                working_hours_end="18:00:00",
                is_available=True,
                current_latitude=12.9716,
                current_longitude=77.5946,
                emergency_contact="+919988776655",
            )
            self.stdout.write(self.style.SUCCESS("Created Technician: tech.ramesh@fsm.com (Skills: HVAC, Electrical)"))

        # 4. Service Categories & Types
        hvac_cat, _ = ServiceCategory.objects.get_or_create(
            code="HVAC",
            defaults={
                "name": "HVAC & Air Conditioning",
                "description": "Heating, ventilation, and air conditioning equipment",
            },
        )
        ServiceType.objects.get_or_create(
            code="AC-COMM-OVERHAUL",
            defaults={
                "category": hvac_cat,
                "name": "Commercial Central AC Overhaul",
                "base_price": Decimal("5500.00"),
                "estimated_duration_minutes": 180,
                "required_skill": "HVAC",
            },
        )

        elec_cat, _ = ServiceCategory.objects.get_or_create(
            code="ELEC",
            defaults={
                "name": "Electrical Infrastructure",
                "description": "High voltage wiring, panel boards, and power backup",
            },
        )
        ServiceType.objects.get_or_create(
            code="ELEC-PANEL-INSPECT",
            defaults={
                "category": elec_cat,
                "name": "Main LT Panel Safety Inspection",
                "base_price": Decimal("3200.00"),
                "estimated_duration_minutes": 120,
                "required_skill": "Electrical",
            },
        )
        self.stdout.write(self.style.SUCCESS("Created Service Categories & Types (HVAC, Electrical)"))

        # 5. Customer & Locations
        customer, created = Customer.objects.get_or_create(
            email="facility@apexhospitals.in",
            defaults={
                "company_name": "Apex Super Specialty Hospital",
                "primary_contact_name": "Dr. Sameer Joshi",
                "phone": "+919822334455",
                "billing_address": "Plot 45, Sector 12, Whitefield, Bengaluru, KA 560066",
                "tax_id": "29AABCA1234F1Z9",
            },
        )
        if created:
            ServiceLocation.objects.create(
                customer=customer,
                location_name="Main Hospital Block",
                address_line1="Plot 45, Sector 12, Whitefield",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560066",
                latitude=12.9698,
                longitude=77.7499,
                contact_person="Facility Manager Mohan",
                contact_phone="+919822334499",
                access_instructions="Report to Gate 2 security desk for visitor badge",
                is_primary=True,
            )
            ServiceLocation.objects.create(
                customer=customer,
                location_name="Diagnostics & Imaging Wing",
                address_line1="Building B, Campus Road",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560066",
                latitude=12.9705,
                longitude=77.7510,
                contact_person="Sub-station Eng. Ritu",
                contact_phone="+919822334488",
                access_instructions="Requires high-voltage PPE gear",
                is_primary=False,
            )
            self.stdout.write(self.style.SUCCESS("Created Customer 'Apex Hospital' with 2 service locations"))

        # 6. Inventory: Warehouses, Parts & Van Stock
        from apps.inventory.models import Part, Warehouse, PartCategory, UnitOfMeasure, LocationType
        from apps.inventory.services import InventoryService

        warehouse, created = Warehouse.objects.get_or_create(
            code="WH-DEL-01",
            defaults={
                "name": "Delhi Central Logistics Depot",
                "city": "New Delhi",
                "address": "Okhla Industrial Area Phase III, New Delhi",
                "manager": admin_user,
                "is_primary": True,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created Primary Warehouse: WH-DEL-01"))

        parts_data = [
            {
                "sku": "COMP-R410A-10KG",
                "name": "Refrigerant Gas Cylinder R410A (10kg)",
                "category": PartCategory.HVAC,
                "unit_of_measure": UnitOfMeasure.KG,
                "cost_price": Decimal("2200.00"),
                "selling_price": Decimal("3500.00"),
                "reorder_threshold": 5,
            },
            {
                "sku": "FLT-HEPA-24X24",
                "name": "Commercial HEPA Air Filter 24x24 inch",
                "category": PartCategory.HVAC,
                "unit_of_measure": UnitOfMeasure.PIECE,
                "cost_price": Decimal("1100.00"),
                "selling_price": Decimal("1850.00"),
                "reorder_threshold": 10,
            },
            {
                "sku": "VLV-EXPV-05",
                "name": "Electronic Expansion Valve (5-Ton Chiller)",
                "category": PartCategory.MECHANICAL,
                "unit_of_measure": UnitOfMeasure.PIECE,
                "cost_price": Decimal("2800.00"),
                "selling_price": Decimal("4400.00"),
                "reorder_threshold": 3,
            },
        ]

        for p_data in parts_data:
            part, p_created = Part.objects.get_or_create(
                sku=p_data["sku"],
                defaults=p_data,
            )
            if p_created:
                # Inward initial stock to warehouse
                InventoryService.receive_purchase_stock(
                    warehouse=warehouse,
                    part=part,
                    quantity=30,
                    performed_by=admin_user,
                    notes="Initial warehouse inventory stocking",
                )
                # Transfer 4 units to Ramesh's van
                InventoryService.transfer_to_van(
                    warehouse=warehouse,
                    technician=tech_user,
                    part=part,
                    quantity=4,
                    performed_by=disp_user,
                    notes=f"Van morning kit allocation for {tech_user.get_full_name()}",
                )
                self.stdout.write(self.style.SUCCESS(f"Created Part & Stocked: {part.sku}"))

        # 7. Service Contracts & Preventive Maintenance
        import datetime
        from apps.contracts.models import ServiceContract, ContractStatus, ServiceFrequency

        primary_loc = customer.service_locations.filter(is_primary=True).first()
        hvac_service = ServiceType.objects.filter(category__code="HVAC").first()

        if primary_loc:
            contract, c_created = ServiceContract.objects.get_or_create(
                contract_number="CNT-2026-APEX-01",
                defaults={
                    "title": "Annual Central Chiller & HVAC Maintenance (AMC)",
                    "customer": customer,
                    "service_location": primary_loc,
                    "start_date": datetime.date(2026, 1, 1),
                    "end_date": datetime.date(2026, 12, 31),
                    "status": ContractStatus.ACTIVE,
                    "service_frequency": ServiceFrequency.QUARTERLY,
                    "total_visits_allowed": 4,
                    "visits_used": 1,
                    "contract_value": Decimal("75000.00"),
                    "sla_response_hours": 12,
                    "next_scheduled_date": datetime.date(2026, 10, 1),
                    "created_by": admin_user,
                    "terms_and_conditions": "Includes 4 periodic quarterly preventive checks and 12-hour breakdown response.",
                },
            )
            if c_created and hvac_service:
                contract.covered_services.add(hvac_service)
                self.stdout.write(self.style.SUCCESS("Created Active Service Contract: CNT-2026-APEX-01"))

        self.stdout.write(self.style.SUCCESS("Seeding completed successfully!"))


