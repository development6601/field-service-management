import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from apps.accounts.models import UserRole
from apps.core.models import BaseModel


class PartCategory(models.TextChoices):
    ELECTRICAL = "ELECTRICAL", "Electrical"
    MECHANICAL = "MECHANICAL", "Mechanical"
    HVAC = "HVAC", "HVAC & Refrigeration"
    PLUMBING = "PLUMBING", "Plumbing"
    CONSUMABLE = "CONSUMABLE", "Consumables & Fasteners"
    TOOLS = "TOOLS", "Tools & Equipment"
    OTHER = "OTHER", "Other"


class UnitOfMeasure(models.TextChoices):
    PIECE = "PIECE", "Piece / Unit"
    KG = "KG", "Kilogram (kg)"
    METER = "METER", "Meter (m)"
    LITER = "LITER", "Liter (L)"
    SET = "SET", "Set"
    BOX = "BOX", "Box / Pack"
    ROLL = "ROLL", "Roll"


class Part(BaseModel):
    """
    Catalog of parts, spare components, and consumables used in field service jobs.
    """

    sku = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Unique Stock Keeping Unit (e.g., COMP-R410A-10KG)",
    )
    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Display name of the part",
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed technical specs or usage instructions",
    )
    category = models.CharField(
        max_length=32,
        choices=PartCategory.choices,
        default=PartCategory.OTHER,
        db_index=True,
        help_text="Domain classification for parts catalog",
    )
    unit_of_measure = models.CharField(
        max_length=20,
        choices=UnitOfMeasure.choices,
        default=UnitOfMeasure.PIECE,
        help_text="Inventory measurement unit",
    )
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Internal procurement / cost price",
    )
    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Standard customer billing unit price",
    )
    reorder_threshold = models.PositiveIntegerField(
        default=5,
        help_text="Minimum aggregate stock level before triggering low-stock alerts",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this part is available for active dispatch & requisition",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Part"
        verbose_name_plural = "Parts"
        ordering = ["sku"]

    def __str__(self):
        return f"{self.sku} - {self.name}"

    @property
    def total_quantity_on_hand(self) -> int:
        """Aggregate physical stock across all warehouses and mobile vans."""
        total = self.stock_items.aggregate(total=Sum("quantity_on_hand"))["total"]
        return total or 0

    @property
    def total_quantity_reserved(self) -> int:
        """Aggregate reserved stock across all warehouses and vans."""
        total = self.stock_items.aggregate(total=Sum("quantity_reserved"))["total"]
        return total or 0

    @property
    def total_available_quantity(self) -> int:
        """Aggregate available unreserved stock across all locations."""
        return max(0, self.total_quantity_on_hand - self.total_quantity_reserved)

    @property
    def is_low_stock(self) -> bool:
        """True if total quantity on hand is at or below the reorder threshold."""
        return self.total_quantity_on_hand <= self.reorder_threshold


class Warehouse(BaseModel):
    """
    Physical storage facility or central depot housing spare parts.
    """

    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Unique warehouse code (e.g. WH-DEL-01)",
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable facility name (e.g., Delhi Central Hub)",
    )
    address = models.TextField(
        blank=True,
        help_text="Street address / location of the facility",
    )
    city = models.CharField(
        max_length=100,
        db_index=True,
        help_text="City / operational hub",
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_warehouses",
        help_text="Facility manager or supervisor",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Flag indicating the primary regional distribution depot",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Flag indicating if the facility is operational",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name} ({self.city})"


class LocationType(models.TextChoices):
    WAREHOUSE = "WAREHOUSE", "Warehouse Depot"
    TECHNICIAN_VAN = "TECHNICIAN_VAN", "Technician Mobile Van"


class StockItem(BaseModel):
    """
    Polymorphic stock level record tracking quantities of a Part at a specific location
    (either a central Warehouse depot or a field Technician's mobile van).
    """

    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name="stock_items",
        help_text="Catalog part being stocked",
    )
    location_type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        db_index=True,
        help_text="Type of storage location",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stock_items",
        help_text="Warehouse facility (if location_type == WAREHOUSE)",
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="van_stock_items",
        help_text="Technician holding this van stock (if location_type == TECHNICIAN_VAN)",
    )
    quantity_on_hand = models.IntegerField(
        default=0,
        help_text="Physical count of items currently in this location",
    )
    quantity_reserved = models.IntegerField(
        default=0,
        help_text="Count of items reserved for upcoming scheduled work orders",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Stock Item"
        verbose_name_plural = "Stock Items"
        constraints = [
            models.UniqueConstraint(
                fields=["part", "warehouse"],
                condition=models.Q(warehouse__isnull=False),
                name="unique_part_warehouse_stock",
            ),
            models.UniqueConstraint(
                fields=["part", "technician"],
                condition=models.Q(technician__isnull=False),
                name="unique_part_technician_stock",
            ),
        ]
        ordering = ["part__sku"]

    def __str__(self):
        loc = self.warehouse.code if self.warehouse else (f"Van: {self.technician.get_full_name()}" if self.technician else "Unknown")
        return f"{self.part.sku} @ {loc}: {self.quantity_on_hand} on hand ({self.available_quantity} avail)"

    def clean(self):
        super().clean()
        if self.location_type == LocationType.WAREHOUSE:
            if not self.warehouse:
                raise ValidationError({"warehouse": "Warehouse must be set when location_type is WAREHOUSE."})
            if self.technician:
                raise ValidationError({"technician": "Technician must be null when location_type is WAREHOUSE."})
        elif self.location_type == LocationType.TECHNICIAN_VAN:
            if not self.technician:
                raise ValidationError({"technician": "Technician must be set when location_type is TECHNICIAN_VAN."})
            if self.warehouse:
                raise ValidationError({"warehouse": "Warehouse must be null when location_type is TECHNICIAN_VAN."})
            if hasattr(self.technician, "role") and self.technician.role != UserRole.TECHNICIAN:
                raise ValidationError({"technician": "Assigned user for van stock must have the TECHNICIAN role."})

        if self.quantity_on_hand < 0:
            raise ValidationError({"quantity_on_hand": "Quantity on hand cannot be negative."})
        if self.quantity_reserved < 0:
            raise ValidationError({"quantity_reserved": "Quantity reserved cannot be negative."})
        if self.quantity_reserved > self.quantity_on_hand:
            raise ValidationError({"quantity_reserved": "Quantity reserved cannot exceed quantity on hand."})

    @property
    def available_quantity(self) -> int:
        """Physical stock minus quantity reserved for other jobs."""
        return max(0, self.quantity_on_hand - self.quantity_reserved)

    @property
    def is_low_stock(self) -> bool:
        """True if on-hand quantity at this location is at or below the part's reorder threshold."""
        return self.quantity_on_hand <= self.part.reorder_threshold


class WorkOrderPartStatus(models.TextChoices):
    RESERVED = "RESERVED", "Reserved"
    CONSUMED = "CONSUMED", "Consumed"
    RETURNED = "RETURNED", "Returned"


class WorkOrderPart(BaseModel):
    """
    Billable parts or materials attached to a WorkOrder job card.
    Locks the unit selling price at consumption time for audit and billing calculations.
    """

    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.CASCADE,
        related_name="parts_used",
        help_text="Work order where the part was used",
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.PROTECT,
        related_name="work_order_usages",
        help_text="Part consumed or reserved",
    )
    source_location_type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.TECHNICIAN_VAN,
        help_text="Source inventory location where the part was deducted from",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Source warehouse (if deducted directly from warehouse)",
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Technician van where the part was deducted from",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        help_text="Quantity consumed or reserved on the job",
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Locked billing unit price at the time of consumption",
    )
    status = models.CharField(
        max_length=20,
        choices=WorkOrderPartStatus.choices,
        default=WorkOrderPartStatus.CONSUMED,
        db_index=True,
        help_text="Consumption status",
    )
    notes = models.TextField(
        blank=True,
        help_text="Field notes or installation remarks",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Work Order Part"
        verbose_name_plural = "Work Order Parts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.quantity}x {self.part.name} on {self.work_order.work_order_number} ({self.status})"

    @property
    def total_price(self) -> Decimal:
        """Total billing charge for this part item."""
        return Decimal(self.quantity) * self.unit_price


class TransactionType(models.TextChoices):
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT", "Purchase Receipt (Stock Inward)"
    TRANSFER_TO_VAN = "TRANSFER_TO_VAN", "Transfer to Technician Van"
    RETURN_TO_WAREHOUSE = "RETURN_TO_WAREHOUSE", "Return to Warehouse"
    RESERVED_FOR_JOB = "RESERVED_FOR_JOB", "Reserved for Work Order"
    RELEASED_FROM_JOB = "RELEASED_FROM_JOB", "Reservation Released"
    CONSUMED_ON_JOB = "CONSUMED_ON_JOB", "Consumed on Work Order"
    RETURNED_FROM_JOB = "RETURNED_FROM_JOB", "Returned from Work Order"
    ADJUSTMENT = "ADJUSTMENT", "Inventory Adjustment / Reconciliation"


class InventoryTransaction(BaseModel):
    """
    Immutable double-entry audit ledger recording every movement, transfer, consumption,
    and adjustment across the inventory lifecycle.
    """

    transaction_type = models.CharField(
        max_length=32,
        choices=TransactionType.choices,
        db_index=True,
        help_text="Classification of the inventory movement",
    )
    part = models.ForeignKey(
        Part,
        on_delete=models.PROTECT,
        related_name="inventory_transactions",
        help_text="Part affected by this transaction",
    )
    quantity = models.PositiveIntegerField(
        help_text="Number of units moved, consumed, or adjusted",
    )
    from_location = models.CharField(
        max_length=100,
        blank=True,
        help_text="Source description (e.g. 'Warehouse: WH-DEL-01' or 'Technician Van: Ramesh')",
    )
    to_location = models.CharField(
        max_length=100,
        blank=True,
        help_text="Destination description (e.g. 'Work Order: WO-20260924-62B1E0')",
    )
    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outward_transactions",
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inward_transactions",
    )
    from_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="van_outward_transactions",
    )
    to_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="van_inward_transactions",
    )
    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_transactions",
        help_text="Associated work order (if consumed or reserved on a job)",
    )
    notes = models.TextField(
        blank=True,
        help_text="Reason, purchase order reference, or audit notes",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_inventory_transactions",
        help_text="User who initiated or authorized this stock operation",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Inventory Transaction"
        verbose_name_plural = "Inventory Transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.transaction_type}: {self.quantity}x {self.part.sku} ({self.from_location} -> {self.to_location})"
