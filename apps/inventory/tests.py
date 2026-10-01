from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.customers.models import Customer, ServiceLocation
from apps.inventory.models import (
    InventoryTransaction,
    LocationType,
    Part,
    PartCategory,
    StockItem,
    TransactionType,
    UnitOfMeasure,
    Warehouse,
    WorkOrderPart,
    WorkOrderPartStatus,
)
from apps.inventory.services import InventoryService
from apps.work_orders.models import WorkOrder, WorkOrderStatus

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(
        email="test_admin@fsm.com",
        password="Password123!",
        first_name="Admin",
        last_name="Boss",
        role=UserRole.ADMIN,
    )
    return user


@pytest.fixture
def dispatcher_user(db):
    user = User.objects.create_user(
        email="test_disp@fsm.com",
        password="Password123!",
        first_name="Vikram",
        last_name="Malhotra",
        role=UserRole.DISPATCHER,
    )
    return user


@pytest.fixture
def technician_ramesh(db):
    user = User.objects.create_user(
        email="test_ramesh@fsm.com",
        password="Password123!",
        first_name="Ramesh",
        last_name="Sharma",
        role=UserRole.TECHNICIAN,
    )
    return user


@pytest.fixture
def technician_alice(db):
    user = User.objects.create_user(
        email="test_alice@fsm.com",
        password="Password123!",
        first_name="Alice",
        last_name="Singh",
        role=UserRole.TECHNICIAN,
    )
    return user


@pytest.fixture
def warehouse(db, admin_user):
    return Warehouse.objects.create(
        code="WH-TEST-01",
        name="Test Depot Okhla",
        city="New Delhi",
        manager=admin_user,
        is_primary=True,
    )


@pytest.fixture
def part_refrigerant(db):
    return Part.objects.create(
        sku="TEST-R410A",
        name="Refrigerant Gas R410A",
        category=PartCategory.HVAC,
        unit_of_measure=UnitOfMeasure.KG,
        cost_price=Decimal("2000.00"),
        selling_price=Decimal("3200.00"),
        reorder_threshold=5,
    )


@pytest.fixture
def customer_and_wo(db, technician_ramesh, admin_user):
    customer = Customer.objects.create(
        primary_contact_name="Mohan Lal",
        company_name="Fortis Healthcare",
        email="fortis@health.com",
        phone="+919811122233",
    )
    loc = ServiceLocation.objects.create(
        customer=customer,
        location_name="ICU Chiller Wing",
        address_line1="Okhla Road",
        city="New Delhi",
        state="Delhi",
        postal_code="110025",
        latitude=Decimal("28.560300"),
        longitude=Decimal("77.279300"),
        is_primary=True,
    )
    wo = WorkOrder.objects.create(
        customer=customer,
        service_location=loc,
        assigned_technician=technician_ramesh,
        title="Repair ICU Chiller Leakage",
        status=WorkOrderStatus.IN_PROGRESS,
        created_by=admin_user,
    )
    return customer, loc, wo


# ---------------------------------------------------------
# Test Suite 1: Parts Catalog & RBAC
# ---------------------------------------------------------
@pytest.mark.django_db
class TestPartCatalog:
    def test_admin_can_create_part(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        payload = {
            "sku": "VALVE-EXP-10",
            "name": "Expansion Valve 10T",
            "category": PartCategory.MECHANICAL,
            "unit_of_measure": UnitOfMeasure.PIECE,
            "cost_price": "1500.00",
            "selling_price": "2800.00",
            "reorder_threshold": 4,
        }
        res = api_client.post("/api/v1/inventory/parts/", payload)
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["sku"] == "VALVE-EXP-10"
        assert res.data["total_quantity_on_hand"] == 0

    def test_technician_cannot_create_part(self, api_client, technician_ramesh):
        api_client.force_authenticate(user=technician_ramesh)
        payload = {
            "sku": "ILLEGAL-PART",
            "name": "Illegal Part",
        }
        res = api_client.post("/api/v1/inventory/parts/", payload)
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_filter_and_search_parts(self, api_client, technician_ramesh, part_refrigerant):
        api_client.force_authenticate(user=technician_ramesh)
        res = api_client.get("/api/v1/inventory/parts/?category=HVAC")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data["results"]) >= 1

        res_search = api_client.get("/api/v1/inventory/parts/?search=R410A")
        assert res_search.status_code == status.HTTP_200_OK
        assert any(p["sku"] == "TEST-R410A" for p in res_search.data["results"])


# ---------------------------------------------------------
# Test Suite 2: Inward Stock Procurement & Warehouse
# ---------------------------------------------------------
@pytest.mark.django_db
class TestStockProcurement:
    def test_receive_purchase_stock(self, api_client, dispatcher_user, warehouse, part_refrigerant):
        api_client.force_authenticate(user=dispatcher_user)
        payload = {
            "warehouse_id": str(warehouse.id),
            "part_id": str(part_refrigerant.id),
            "quantity": 25,
            "notes": "Bulk shipment PO-9912",
        }
        res = api_client.post("/api/v1/inventory/operations/receive/", payload)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["quantity_on_hand"] == 25

        # Verify audit transaction created
        tx = InventoryTransaction.objects.filter(
            part=part_refrigerant, transaction_type=TransactionType.PURCHASE_RECEIPT
        ).first()
        assert tx is not None
        assert tx.quantity == 25
        assert tx.to_warehouse == warehouse
        assert tx.performed_by == dispatcher_user


# ---------------------------------------------------------
# Test Suite 3: Van Transfers & Safety Checks
# ---------------------------------------------------------
@pytest.mark.django_db
class TestVanTransferWorkflow:
    def test_transfer_to_van_and_insufficient_stock(
        self, api_client, dispatcher_user, warehouse, part_refrigerant, technician_ramesh
    ):
        # 1. First inward 10 units to warehouse
        InventoryService.receive_purchase_stock(
            warehouse=warehouse,
            part=part_refrigerant,
            quantity=10,
            performed_by=dispatcher_user,
        )

        api_client.force_authenticate(user=dispatcher_user)

        # 2. Transfer 4 units to Ramesh's van
        transfer_payload = {
            "warehouse_id": str(warehouse.id),
            "technician_id": str(technician_ramesh.id),
            "part_id": str(part_refrigerant.id),
            "quantity": 4,
            "notes": "Morning field run stock",
        }
        res = api_client.post("/api/v1/inventory/operations/transfer-to-van/", transfer_payload)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["warehouse_stock"]["quantity_on_hand"] == 6
        assert res.data["van_stock"]["quantity_on_hand"] == 4

        # 3. Attempt to transfer 10 more (only 6 left) -> should fail
        transfer_payload["quantity"] = 10
        res_fail = api_client.post("/api/v1/inventory/operations/transfer-to-van/", transfer_payload)
        assert res_fail.status_code == status.HTTP_400_BAD_REQUEST
        assert "Insufficient available stock" in str(res_fail.data)

    def test_technician_my_van_endpoint(
        self, api_client, warehouse, part_refrigerant, technician_ramesh, technician_alice
    ):
        # Allocate 5 to Ramesh, 2 to Alice
        InventoryService.receive_purchase_stock(
            warehouse=warehouse, part=part_refrigerant, quantity=20
        )
        InventoryService.transfer_to_van(
            warehouse=warehouse, technician=technician_ramesh, part=part_refrigerant, quantity=5
        )
        InventoryService.transfer_to_van(
            warehouse=warehouse, technician=technician_alice, part=part_refrigerant, quantity=2
        )

        # Ramesh calls /my-van/
        api_client.force_authenticate(user=technician_ramesh)
        res_ramesh = api_client.get("/api/v1/inventory/stock/my-van/")
        assert res_ramesh.status_code == status.HTTP_200_OK
        assert len(res_ramesh.data) == 1
        assert res_ramesh.data[0]["quantity_on_hand"] == 5

        # Alice calls /my-van/
        api_client.force_authenticate(user=technician_alice)
        res_alice = api_client.get("/api/v1/inventory/stock/my-van/")
        assert res_alice.status_code == status.HTTP_200_OK
        assert len(res_alice.data) == 1
        assert res_alice.data[0]["quantity_on_hand"] == 2


# ---------------------------------------------------------
# Test Suite 4: Work Order Consumption, Price Lock & Returns
# ---------------------------------------------------------
@pytest.mark.django_db
class TestWorkOrderPartsLifecycle:
    def test_consume_part_and_price_lock(
        self, api_client, warehouse, part_refrigerant, technician_ramesh, technician_alice, customer_and_wo
    ):
        _, _, wo = customer_and_wo

        # Stock Ramesh's van with 4 units @ selling_price 3200.00
        InventoryService.receive_purchase_stock(
            warehouse=warehouse, part=part_refrigerant, quantity=10
        )
        InventoryService.transfer_to_van(
            warehouse=warehouse, technician=technician_ramesh, part=part_refrigerant, quantity=4
        )

        api_client.force_authenticate(user=technician_ramesh)

        # Ramesh consumes 2 units on his work order
        consume_payload = {
            "part_id": str(part_refrigerant.id),
            "quantity": 2,
            "source_location_type": LocationType.TECHNICIAN_VAN,
            "notes": "Topped up refrigerant in compressor A",
        }
        res = api_client.post(f"/api/v1/work-orders/{wo.id}/parts/", consume_payload)
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["quantity"] == 2
        assert Decimal(res.data["unit_price"]) == Decimal("3200.00")
        assert Decimal(res.data["total_price"]) == Decimal("6400.00")
        assert res.data["status"] == WorkOrderPartStatus.CONSUMED

        # Verify Ramesh's van stock is now 2
        van_stock = StockItem.objects.get(
            part=part_refrigerant, technician=technician_ramesh, location_type=LocationType.TECHNICIAN_VAN
        )
        assert van_stock.quantity_on_hand == 2

        # Check work order detail includes parts and parts_total_cost
        res_detail = api_client.get(f"/api/v1/work-orders/{wo.id}/")
        assert res_detail.status_code == status.HTTP_200_OK
        assert len(res_detail.data["parts_used"]) == 1
        assert Decimal(res_detail.data["parts_total_cost"]) == Decimal("6400.00")

    def test_consume_exceeding_van_stock_fails(
        self, api_client, warehouse, part_refrigerant, technician_ramesh, customer_and_wo
    ):
        _, _, wo = customer_and_wo

        # Put 2 units on van
        InventoryService.receive_purchase_stock(
            warehouse=warehouse, part=part_refrigerant, quantity=5
        )
        InventoryService.transfer_to_van(
            warehouse=warehouse, technician=technician_ramesh, part=part_refrigerant, quantity=2
        )

        api_client.force_authenticate(user=technician_ramesh)

        # Attempt to consume 5 units
        consume_payload = {
            "part_id": str(part_refrigerant.id),
            "quantity": 5,
        }
        res = api_client.post(f"/api/v1/work-orders/{wo.id}/parts/", consume_payload)
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Insufficient stock" in str(res.data)

    def test_unassigned_technician_cannot_consume_parts(
        self, api_client, warehouse, part_refrigerant, technician_ramesh, technician_alice, customer_and_wo
    ):
        _, _, wo = customer_and_wo  # wo is assigned to Ramesh

        # Alice attempts to add parts to Ramesh's work order
        api_client.force_authenticate(user=technician_alice)
        consume_payload = {
            "part_id": str(part_refrigerant.id),
            "quantity": 1,
        }
        res = api_client.post(f"/api/v1/work-orders/{wo.id}/parts/", consume_payload)
        assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]

    def test_return_unused_part_from_work_order(
        self, api_client, warehouse, part_refrigerant, technician_ramesh, customer_and_wo
    ):
        _, _, wo = customer_and_wo

        # Inward and transfer 3 units
        InventoryService.receive_purchase_stock(
            warehouse=warehouse, part=part_refrigerant, quantity=10
        )
        InventoryService.transfer_to_van(
            warehouse=warehouse, technician=technician_ramesh, part=part_refrigerant, quantity=3
        )

        # Consume 2 units
        wo_part = InventoryService.consume_part_on_work_order(
            work_order=wo,
            part=part_refrigerant,
            quantity=2,
            technician=technician_ramesh,
            performed_by=technician_ramesh,
        )
        # Van stock is now 1
        assert StockItem.objects.get(technician=technician_ramesh, part=part_refrigerant).quantity_on_hand == 1

        api_client.force_authenticate(user=technician_ramesh)

        # Return the 2 consumed units back to van
        res_return = api_client.post(
            f"/api/v1/work-orders/{wo.id}/return-part/",
            {"work_order_part_id": str(wo_part.id), "notes": "Customer cancelled component replacement"},
        )
        assert res_return.status_code == status.HTTP_200_OK
        assert res_return.data["status"] == WorkOrderPartStatus.RETURNED

        # Van stock restored to 3
        van_stock = StockItem.objects.get(technician=technician_ramesh, part=part_refrigerant)
        assert van_stock.quantity_on_hand == 3

        # Transaction ledger has RETURNED_FROM_JOB entry
        tx = InventoryTransaction.objects.filter(
            transaction_type=TransactionType.RETURNED_FROM_JOB, part=part_refrigerant
        ).first()
        assert tx is not None
        assert tx.quantity == 2


# ---------------------------------------------------------
# Test Suite 5: Low-Stock Alerts & Adjustments
# ---------------------------------------------------------
@pytest.mark.django_db
class TestAlertsAndAdjustments:
    def test_low_stock_alert_endpoint(self, api_client, admin_user, warehouse, part_refrigerant):
        # part_refrigerant has reorder_threshold = 5, initial stock = 0 -> should be low stock
        api_client.force_authenticate(user=admin_user)
        res = api_client.get("/api/v1/inventory/alerts/low-stock/")
        assert res.status_code == status.HTTP_200_OK
        assert any(item["sku"] == part_refrigerant.sku for item in res.data["low_stock_items"])

        # Receive 10 units -> stock = 10 (> threshold 5) -> no longer low stock
        InventoryService.receive_purchase_stock(
            warehouse=warehouse, part=part_refrigerant, quantity=10, performed_by=admin_user
        )
        res_after = api_client.get("/api/v1/inventory/alerts/low-stock/")
        assert not any(item["sku"] == part_refrigerant.sku for item in res_after.data["low_stock_items"])

    def test_admin_stock_adjustment(self, api_client, admin_user, warehouse, part_refrigerant):
        stock_item = InventoryService.receive_purchase_stock(
            warehouse=warehouse, part=part_refrigerant, quantity=10, performed_by=admin_user
        )

        api_client.force_authenticate(user=admin_user)
        payload = {
            "stock_item_id": str(stock_item.id),
            "new_quantity_on_hand": 8,
            "reason": "Physical count revealed 2 damaged cylinders during audit",
        }
        res = api_client.post("/api/v1/inventory/operations/adjust/", payload)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["quantity_on_hand"] == 8

        # Verify ADJUSTMENT transaction
        tx = InventoryTransaction.objects.filter(
            transaction_type=TransactionType.ADJUSTMENT, part=part_refrigerant
        ).first()
        assert tx is not None
        assert tx.quantity == 2
        assert "damaged cylinders" in tx.notes
