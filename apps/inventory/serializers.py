from rest_framework import serializers

from apps.accounts.models import User, UserRole
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


class PartSerializer(serializers.ModelSerializer):
    """
    CRUD serializer for catalog parts with real-time aggregated stock stats.
    """

    total_quantity_on_hand = serializers.IntegerField(read_only=True)
    total_quantity_reserved = serializers.IntegerField(read_only=True)
    total_available_quantity = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Part
        fields = [
            "id",
            "sku",
            "name",
            "description",
            "category",
            "unit_of_measure",
            "cost_price",
            "selling_price",
            "reorder_threshold",
            "is_active",
            "total_quantity_on_hand",
            "total_quantity_reserved",
            "total_available_quantity",
            "is_low_stock",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "total_quantity_on_hand",
            "total_quantity_reserved",
            "total_available_quantity",
            "is_low_stock",
            "created_at",
            "updated_at",
        ]


class WarehouseSerializer(serializers.ModelSerializer):
    """
    Serializer for storage warehouses and depots.
    """

    manager_name = serializers.CharField(source="manager.get_full_name", read_only=True)
    stock_items_count = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "code",
            "name",
            "address",
            "city",
            "manager",
            "manager_name",
            "is_primary",
            "is_active",
            "stock_items_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "stock_items_count", "created_at", "updated_at"]

    def get_stock_items_count(self, obj) -> int:
        return obj.stock_items.filter(quantity_on_hand__gt=0).count()


class StockItemSerializer(serializers.ModelSerializer):
    """
    Serializer representing stock levels of a part at a warehouse or technician van.
    """

    part_sku = serializers.CharField(source="part.sku", read_only=True)
    part_name = serializers.CharField(source="part.name", read_only=True)
    part_unit = serializers.CharField(source="part.unit_of_measure", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    technician_name = serializers.CharField(source="technician.get_full_name", read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockItem
        fields = [
            "id",
            "part",
            "part_sku",
            "part_name",
            "part_unit",
            "location_type",
            "warehouse",
            "warehouse_code",
            "warehouse_name",
            "technician",
            "technician_name",
            "quantity_on_hand",
            "quantity_reserved",
            "available_quantity",
            "is_low_stock",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "part_sku",
            "part_name",
            "part_unit",
            "warehouse_code",
            "warehouse_name",
            "technician_name",
            "available_quantity",
            "is_low_stock",
            "updated_at",
        ]


class WorkOrderPartSerializer(serializers.ModelSerializer):
    """
    Serializer representing parts consumed or reserved on a WorkOrder.
    """

    part_sku = serializers.CharField(source="part.sku", read_only=True)
    part_name = serializers.CharField(source="part.name", read_only=True)
    part_unit = serializers.CharField(source="part.unit_of_measure", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    technician_name = serializers.CharField(source="technician.get_full_name", read_only=True)
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = WorkOrderPart
        fields = [
            "id",
            "work_order",
            "part",
            "part_sku",
            "part_name",
            "part_unit",
            "source_location_type",
            "warehouse",
            "warehouse_code",
            "technician",
            "technician_name",
            "quantity",
            "unit_price",
            "total_price",
            "status",
            "notes",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "work_order",
            "part_sku",
            "part_name",
            "part_unit",
            "warehouse_code",
            "technician_name",
            "unit_price",
            "total_price",
            "status",
            "created_at",
        ]


class ConsumeWorkOrderPartSerializer(serializers.Serializer):
    """
    Input payload for adding/consuming a part on a work order.
    """

    part_id = serializers.UUIDField(help_text="UUID of the catalog Part to consume")
    quantity = serializers.IntegerField(min_value=1, default=1, help_text="Quantity consumed")
    source_location_type = serializers.ChoiceField(
        choices=LocationType.choices,
        default=LocationType.TECHNICIAN_VAN,
        help_text="TECHNICIAN_VAN or WAREHOUSE",
    )
    warehouse_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Required if source_location_type is WAREHOUSE",
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ReceiveStockSerializer(serializers.Serializer):
    """
    Input payload for inward stock procurement into a warehouse depot.
    """

    warehouse_id = serializers.UUIDField()
    part_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class TransferToVanSerializer(serializers.Serializer):
    """
    Input payload for transferring parts from warehouse depot to technician mobile van.
    """

    warehouse_id = serializers.UUIDField()
    technician_id = serializers.UUIDField()
    part_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class TransferToWarehouseSerializer(serializers.Serializer):
    """
    Input payload for returning parts from technician mobile van to warehouse depot.
    """

    technician_id = serializers.UUIDField()
    warehouse_id = serializers.UUIDField()
    part_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AdjustStockSerializer(serializers.Serializer):
    """
    Input payload for manual inventory count adjustments and reconciliations.
    """

    stock_item_id = serializers.UUIDField()
    new_quantity_on_hand = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(min_length=5, help_text="Mandatory audit adjustment reason")


class InventoryTransactionSerializer(serializers.ModelSerializer):
    """
    Immutable audit log entry serializer.
    """

    part_sku = serializers.CharField(source="part.sku", read_only=True)
    part_name = serializers.CharField(source="part.name", read_only=True)
    work_order_number = serializers.CharField(source="work_order.work_order_number", read_only=True)
    performed_by_name = serializers.CharField(source="performed_by.get_full_name", read_only=True)

    class Meta:
        model = InventoryTransaction
        fields = [
            "id",
            "transaction_type",
            "part",
            "part_sku",
            "part_name",
            "quantity",
            "from_location",
            "to_location",
            "work_order",
            "work_order_number",
            "performed_by",
            "performed_by_name",
            "notes",
            "created_at",
        ]
        read_only_fields = fields
