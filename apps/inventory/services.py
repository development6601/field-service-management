from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction

from apps.accounts.models import UserRole
from apps.inventory.models import (
    InventoryTransaction,
    LocationType,
    Part,
    StockItem,
    TransactionType,
    Warehouse,
    WorkOrderPart,
    WorkOrderPartStatus,
)


class InventoryService:
    """
    Domain service handling atomic inventory operations, stock movements,
    concurrency locks, and immutable double-entry ledger auditing.
    """

    @staticmethod
    @db_transaction.atomic
    def receive_purchase_stock(
        *,
        warehouse: Warehouse,
        part: Part,
        quantity: int,
        performed_by=None,
        notes: str = "",
    ) -> StockItem:
        """
        Record newly procured stock inward into a warehouse depot.
        """
        if quantity <= 0:
            raise ValidationError({"quantity": "Received quantity must be greater than zero."})

        stock_item, _ = StockItem.objects.select_for_update().get_or_create(
            part=part,
            location_type=LocationType.WAREHOUSE,
            warehouse=warehouse,
            defaults={"quantity_on_hand": 0, "quantity_reserved": 0},
        )

        stock_item.quantity_on_hand += quantity
        stock_item.save(update_fields=["quantity_on_hand", "updated_at"])

        InventoryTransaction.objects.create(
            transaction_type=TransactionType.PURCHASE_RECEIPT,
            part=part,
            quantity=quantity,
            from_location="Vendor / Supplier Procurement",
            to_location=f"Warehouse: {warehouse.code} ({warehouse.name})",
            to_warehouse=warehouse,
            performed_by=performed_by,
            notes=notes or f"Stock inward: +{quantity} units received",
        )

        return stock_item

    @staticmethod
    @db_transaction.atomic
    def transfer_to_van(
        *,
        warehouse: Warehouse,
        technician,
        part: Part,
        quantity: int,
        performed_by=None,
        notes: str = "",
    ) -> tuple[StockItem, StockItem]:
        """
        Atomically transfer spare parts from a warehouse depot to a technician's mobile van.
        """
        if quantity <= 0:
            raise ValidationError({"quantity": "Transfer quantity must be greater than zero."})

        if technician.role != UserRole.TECHNICIAN:
            raise ValidationError({"technician": "Recipient must have the TECHNICIAN role."})

        try:
            wh_stock = StockItem.objects.select_for_update().get(
                part=part,
                location_type=LocationType.WAREHOUSE,
                warehouse=warehouse,
            )
        except StockItem.DoesNotExist:
            raise ValidationError(
                {"quantity": f"Part '{part.sku}' is not stocked in warehouse '{warehouse.code}'."}
            )

        if wh_stock.available_quantity < quantity:
            raise ValidationError(
                {
                    "quantity": (
                        f"Insufficient available stock at warehouse '{warehouse.code}' for part '{part.sku}'. "
                        f"Available: {wh_stock.available_quantity}, Requested: {quantity}."
                    )
                }
            )

        # Deduct from warehouse
        wh_stock.quantity_on_hand -= quantity
        wh_stock.save(update_fields=["quantity_on_hand", "updated_at"])

        # Add to technician van
        van_stock, _ = StockItem.objects.select_for_update().get_or_create(
            part=part,
            location_type=LocationType.TECHNICIAN_VAN,
            technician=technician,
            defaults={"quantity_on_hand": 0, "quantity_reserved": 0},
        )
        van_stock.quantity_on_hand += quantity
        van_stock.save(update_fields=["quantity_on_hand", "updated_at"])

        # Audit Ledger
        InventoryTransaction.objects.create(
            transaction_type=TransactionType.TRANSFER_TO_VAN,
            part=part,
            quantity=quantity,
            from_location=f"Warehouse: {warehouse.code}",
            to_location=f"Technician Van: {technician.get_full_name()} ({technician.email})",
            from_warehouse=warehouse,
            to_technician=technician,
            performed_by=performed_by,
            notes=notes or f"Transferred {quantity} units to technician van",
        )

        return wh_stock, van_stock

    @staticmethod
    @db_transaction.atomic
    def transfer_to_warehouse(
        *,
        technician,
        warehouse: Warehouse,
        part: Part,
        quantity: int,
        performed_by=None,
        notes: str = "",
    ) -> tuple[StockItem, StockItem]:
        """
        Atomically return parts from a technician's mobile van to a central warehouse.
        """
        if quantity <= 0:
            raise ValidationError({"quantity": "Return quantity must be greater than zero."})

        try:
            van_stock = StockItem.objects.select_for_update().get(
                part=part,
                location_type=LocationType.TECHNICIAN_VAN,
                technician=technician,
            )
        except StockItem.DoesNotExist:
            raise ValidationError(
                {"quantity": f"Part '{part.sku}' is not present in technician {technician.get_full_name()}'s van."}
            )

        if van_stock.available_quantity < quantity:
            raise ValidationError(
                {
                    "quantity": (
                        f"Insufficient stock in technician's van for part '{part.sku}'. "
                        f"Available: {van_stock.available_quantity}, Requested: {quantity}."
                    )
                }
            )

        # Deduct from van
        van_stock.quantity_on_hand -= quantity
        van_stock.save(update_fields=["quantity_on_hand", "updated_at"])

        # Add to warehouse
        wh_stock, _ = StockItem.objects.select_for_update().get_or_create(
            part=part,
            location_type=LocationType.WAREHOUSE,
            warehouse=warehouse,
            defaults={"quantity_on_hand": 0, "quantity_reserved": 0},
        )
        wh_stock.quantity_on_hand += quantity
        wh_stock.save(update_fields=["quantity_on_hand", "updated_at"])

        # Audit Ledger
        InventoryTransaction.objects.create(
            transaction_type=TransactionType.RETURN_TO_WAREHOUSE,
            part=part,
            quantity=quantity,
            from_location=f"Technician Van: {technician.get_full_name()}",
            to_location=f"Warehouse: {warehouse.code}",
            from_technician=technician,
            to_warehouse=warehouse,
            performed_by=performed_by,
            notes=notes or f"Returned {quantity} units to warehouse from van",
        )

        return van_stock, wh_stock

    @staticmethod
    @db_transaction.atomic
    def consume_part_on_work_order(
        *,
        work_order,
        part: Part,
        quantity: int = 1,
        source_location_type: str = LocationType.TECHNICIAN_VAN,
        warehouse: Warehouse = None,
        technician=None,
        performed_by=None,
        notes: str = "",
    ) -> WorkOrderPart:
        """
        Deduct part stock and record billable line-item on a WorkOrder.
        Automatically locks selling unit_price at time of consumption.
        """
        if quantity <= 0:
            raise ValidationError({"quantity": "Consumed quantity must be greater than zero."})

        if not part.is_active:
            raise ValidationError({"part": f"Part '{part.sku}' is inactive and cannot be consumed."})

        # Resolve location
        if source_location_type == LocationType.TECHNICIAN_VAN:
            tech = technician or work_order.assigned_technician
            if not tech:
                raise ValidationError({"technician": "No technician assigned to deduct van stock from."})

            try:
                stock_item = StockItem.objects.select_for_update().get(
                    part=part,
                    location_type=LocationType.TECHNICIAN_VAN,
                    technician=tech,
                )
            except StockItem.DoesNotExist:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Insufficient stock: Part '{part.name}' ({part.sku}) is not stocked "
                            f"in technician {tech.get_full_name()}'s van."
                        )
                    }
                )

            if stock_item.available_quantity < quantity:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Insufficient stock: Technician {tech.get_full_name()} only has "
                            f"{stock_item.available_quantity} available, but {quantity} were requested."
                        )
                    }
                )

            stock_item.quantity_on_hand -= quantity
            stock_item.save(update_fields=["quantity_on_hand", "updated_at"])

            from_loc_str = f"Technician Van: {tech.get_full_name()}"
            src_tech = tech
            src_wh = None

        elif source_location_type == LocationType.WAREHOUSE:
            if not warehouse:
                raise ValidationError({"warehouse": "Warehouse must be specified when deducting from warehouse."})

            try:
                stock_item = StockItem.objects.select_for_update().get(
                    part=part,
                    location_type=LocationType.WAREHOUSE,
                    warehouse=warehouse,
                )
            except StockItem.DoesNotExist:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Insufficient stock: Part '{part.name}' ({part.sku}) is not stocked "
                            f"in warehouse '{warehouse.code}'."
                        )
                    }
                )

            if stock_item.available_quantity < quantity:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Insufficient stock: Warehouse '{warehouse.code}' only has "
                            f"{stock_item.available_quantity} available, but {quantity} were requested."
                        )
                    }
                )

            stock_item.quantity_on_hand -= quantity
            stock_item.save(update_fields=["quantity_on_hand", "updated_at"])

            from_loc_str = f"Warehouse: {warehouse.code}"
            src_wh = warehouse
            src_tech = None
        else:
            raise ValidationError({"source_location_type": "Invalid source location type."})

        # Lock selling price at consumption time
        wo_part = WorkOrderPart.objects.create(
            work_order=work_order,
            part=part,
            source_location_type=source_location_type,
            warehouse=src_wh,
            technician=src_tech,
            quantity=quantity,
            unit_price=part.selling_price,
            status=WorkOrderPartStatus.CONSUMED,
            notes=notes,
        )

        # Audit ledger
        InventoryTransaction.objects.create(
            transaction_type=TransactionType.CONSUMED_ON_JOB,
            part=part,
            quantity=quantity,
            from_location=from_loc_str,
            to_location=f"Work Order: {work_order.work_order_number} ({work_order.title})",
            from_warehouse=src_wh,
            from_technician=src_tech,
            work_order=work_order,
            performed_by=performed_by,
            notes=notes or f"Consumed on {work_order.work_order_number} @ {part.selling_price} each",
        )

        return wo_part

    @staticmethod
    @db_transaction.atomic
    def return_part_from_work_order(
        *,
        work_order_part: WorkOrderPart,
        performed_by=None,
        notes: str = "",
    ) -> WorkOrderPart:
        """
        Return an unused or incorrectly issued part back to its original inventory source
        (technician van or warehouse).
        """
        if work_order_part.status != WorkOrderPartStatus.CONSUMED:
            raise ValidationError({"status": f"Cannot return part with status '{work_order_part.status}'."})

        part = work_order_part.part
        qty = work_order_part.quantity

        if work_order_part.source_location_type == LocationType.TECHNICIAN_VAN:
            tech = work_order_part.technician or work_order_part.work_order.assigned_technician
            van_stock, _ = StockItem.objects.select_for_update().get_or_create(
                part=part,
                location_type=LocationType.TECHNICIAN_VAN,
                technician=tech,
                defaults={"quantity_on_hand": 0, "quantity_reserved": 0},
            )
            van_stock.quantity_on_hand += qty
            van_stock.save(update_fields=["quantity_on_hand", "updated_at"])

            to_loc_str = f"Technician Van: {tech.get_full_name()}"
            to_tech = tech
            to_wh = None

        elif work_order_part.source_location_type == LocationType.WAREHOUSE:
            wh = work_order_part.warehouse
            wh_stock, _ = StockItem.objects.select_for_update().get_or_create(
                part=part,
                location_type=LocationType.WAREHOUSE,
                warehouse=wh,
                defaults={"quantity_on_hand": 0, "quantity_reserved": 0},
            )
            wh_stock.quantity_on_hand += qty
            wh_stock.save(update_fields=["quantity_on_hand", "updated_at"])

            to_loc_str = f"Warehouse: {wh.code}"
            to_wh = wh
            to_tech = None
        else:
            raise ValidationError({"source_location_type": "Unknown original source location."})

        # Mark status as RETURNED
        work_order_part.status = WorkOrderPartStatus.RETURNED
        if notes:
            work_order_part.notes = f"{work_order_part.notes} [Returned: {notes}]".strip()
        work_order_part.save(update_fields=["status", "notes", "updated_at"])

        # Audit Ledger
        InventoryTransaction.objects.create(
            transaction_type=TransactionType.RETURNED_FROM_JOB,
            part=part,
            quantity=qty,
            from_location=f"Work Order: {work_order_part.work_order.work_order_number}",
            to_location=to_loc_str,
            to_warehouse=to_wh,
            to_technician=to_tech,
            work_order=work_order_part.work_order,
            performed_by=performed_by,
            notes=notes or f"Returned unused from {work_order_part.work_order.work_order_number}",
        )

        return work_order_part

    @staticmethod
    @db_transaction.atomic
    def adjust_stock(
        *,
        stock_item: StockItem,
        new_quantity_on_hand: int,
        reason: str,
        performed_by=None,
    ) -> StockItem:
        """
        Manually adjust physical stock counts during audit or reconciliation.
        """
        if new_quantity_on_hand < 0:
            raise ValidationError({"new_quantity_on_hand": "Stock count cannot be negative."})
        if not reason:
            raise ValidationError({"reason": "Audit adjustment reason is required."})

        old_quantity = stock_item.quantity_on_hand
        difference = new_quantity_on_hand - old_quantity

        stock_item.quantity_on_hand = new_quantity_on_hand
        stock_item.save(update_fields=["quantity_on_hand", "updated_at"])

        loc_str = stock_item.warehouse.code if stock_item.warehouse else f"Technician Van: {stock_item.technician.get_full_name()}"

        InventoryTransaction.objects.create(
            transaction_type=TransactionType.ADJUSTMENT,
            part=stock_item.part,
            quantity=abs(difference),
            from_location=loc_str,
            to_location=loc_str,
            from_warehouse=stock_item.warehouse,
            to_warehouse=stock_item.warehouse,
            from_technician=stock_item.technician,
            to_technician=stock_item.technician,
            performed_by=performed_by,
            notes=f"Stock count adjusted from {old_quantity} to {new_quantity_on_hand} (diff: {difference:+d}). Reason: {reason}",
        )

        return stock_item
