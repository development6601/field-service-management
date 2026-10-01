from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User, UserRole
from apps.core.permissions import (
    IsAdmin,
    IsAdminOrManager,
    IsDispatcher,
    IsTechnician,
)
from apps.inventory.models import (
    InventoryTransaction,
    LocationType,
    Part,
    StockItem,
    Warehouse,
    WorkOrderPart,
)
from apps.inventory.serializers import (
    AdjustStockSerializer,
    InventoryTransactionSerializer,
    PartSerializer,
    ReceiveStockSerializer,
    StockItemSerializer,
    TransferToVanSerializer,
    TransferToWarehouseSerializer,
    WarehouseSerializer,
    WorkOrderPartSerializer,
)
from apps.inventory.services import InventoryService
from drf_spectacular.utils import extend_schema


class PartViewSet(viewsets.ModelViewSet):
    """
    Manage catalog parts, spare components, and consumables.
    - Admins: Full CRUD
    - Managers/Dispatchers/Technicians: Read-only access
    """

    queryset = Part.objects.all()
    serializer_class = PartSerializer

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(sku__icontains=search) | Q(name__icontains=search))

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")

        return qs


class WarehouseViewSet(viewsets.ModelViewSet):
    """
    Manage storage warehouses and central regional depots.
    - Admins/Managers: Full CRUD
    - Dispatchers/Staff: Read-only access
    """

    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdminOrManager()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        city = self.request.query_params.get("city")
        if city:
            qs = qs.filter(city__icontains=city)

        is_primary = self.request.query_params.get("is_primary")
        if is_primary is not None:
            qs = qs.filter(is_primary=is_primary.lower() == "true")

        return qs


class StockItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    View inventory stock levels across warehouses and technician mobile vans.
    Includes dedicated `my-van` endpoint for technicians.
    """

    queryset = StockItem.objects.select_related("part", "warehouse", "technician").all()
    serializer_class = StockItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Technicians default to seeing only their own van stock unless explicitly filtering or admin
        if user.role == UserRole.TECHNICIAN and self.action != "retrieve":
            # Check if query specifically asks for a warehouse or another tech
            tech_id = self.request.query_params.get("technician")
            wh_id = self.request.query_params.get("warehouse")
            if not tech_id and not wh_id:
                qs = qs.filter(technician=user)

        part_id = self.request.query_params.get("part")
        if part_id:
            qs = qs.filter(part_id=part_id)

        warehouse_id = self.request.query_params.get("warehouse")
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        technician_id = self.request.query_params.get("technician")
        if technician_id:
            qs = qs.filter(technician_id=technician_id)

        location_type = self.request.query_params.get("location_type")
        if location_type:
            qs = qs.filter(location_type=location_type)

        low_stock = self.request.query_params.get("low_stock")
        if low_stock and low_stock.lower() == "true":
            # Stock items where on-hand is <= reorder threshold of part
            qs = [item for item in qs if item.is_low_stock]

        return qs

    @action(detail=False, methods=["get"], url_path="my-van")
    def my_van(self, request):
        """
        Dedicated mobile endpoint: Technicians view parts currently on their van.
        """
        if request.user.role != UserRole.TECHNICIAN:
            return Response(
                {"detail": "Only field technicians have mobile van inventory."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        van_stock = StockItem.objects.filter(
            technician=request.user,
            location_type=LocationType.TECHNICIAN_VAN,
        ).select_related("part")

        serializer = self.get_serializer(van_stock, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class StockOperationsViewSet(viewsets.ViewSet):
    """
    Atomic inventory movement and management operations:
    - Receive inward stock into warehouse
    - Transfer warehouse <-> technician van
    - Stock count adjustments
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=ReceiveStockSerializer, responses={200: StockItemSerializer})
    @action(detail=False, methods=["post"], url_path="receive")
    def receive_stock(self, request):
        """
        Record procurement stock receipt into a warehouse depot.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ReceiveStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        warehouse = get_object_or_404(Warehouse, id=data["warehouse_id"])
        part = get_object_or_404(Part, id=data["part_id"])

        try:
            stock_item = InventoryService.receive_purchase_stock(
                warehouse=warehouse,
                part=part,
                quantity=data["quantity"],
                performed_by=request.user,
                notes=data.get("notes", ""),
            )
        except ValidationError as e:
            return Response({"detail": str(e.message_dict if hasattr(e, "message_dict") else e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(StockItemSerializer(stock_item).data, status=status.HTTP_200_OK)

    @extend_schema(request=TransferToVanSerializer)
    @action(detail=False, methods=["post"], url_path="transfer-to-van")
    def transfer_to_van(self, request):
        """
        Transfer parts from warehouse depot to technician mobile van.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        serializer = TransferToVanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        warehouse = get_object_or_404(Warehouse, id=data["warehouse_id"])
        technician = get_object_or_404(User, id=data["technician_id"], role=UserRole.TECHNICIAN)
        part = get_object_or_404(Part, id=data["part_id"])

        try:
            wh_stock, van_stock = InventoryService.transfer_to_van(
                warehouse=warehouse,
                technician=technician,
                part=part,
                quantity=data["quantity"],
                performed_by=request.user,
                notes=data.get("notes", ""),
            )
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "message": f"Successfully transferred {data['quantity']} units to {technician.get_full_name()}'s van.",
                "warehouse_stock": StockItemSerializer(wh_stock).data,
                "van_stock": StockItemSerializer(van_stock).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=TransferToWarehouseSerializer)
    @action(detail=False, methods=["post"], url_path="transfer-to-warehouse")
    def transfer_to_warehouse(self, request):
        """
        Return parts from technician van back to warehouse depot.
        """
        serializer = TransferToWarehouseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        technician = get_object_or_404(User, id=data["technician_id"])
        # Technicians can only return from their own van
        if request.user.role == UserRole.TECHNICIAN and request.user.id != technician.id:
            return Response({"detail": "Cannot transfer stock from another technician's van."}, status=status.HTTP_403_FORBIDDEN)

        warehouse = get_object_or_404(Warehouse, id=data["warehouse_id"])
        part = get_object_or_404(Part, id=data["part_id"])

        try:
            van_stock, wh_stock = InventoryService.transfer_to_warehouse(
                technician=technician,
                warehouse=warehouse,
                part=part,
                quantity=data["quantity"],
                performed_by=request.user,
                notes=data.get("notes", ""),
            )
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "message": f"Successfully returned {data['quantity']} units to warehouse {warehouse.code}.",
                "van_stock": StockItemSerializer(van_stock).data,
                "warehouse_stock": StockItemSerializer(wh_stock).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=AdjustStockSerializer, responses={200: StockItemSerializer})
    @action(detail=False, methods=["post"], url_path="adjust")
    def adjust_stock(self, request):
        """
        Stock count adjustment for auditing and reconciliation.
        """
        if request.user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            return Response({"detail": "Only Admins and Managers can adjust stock counts."}, status=status.HTTP_403_FORBIDDEN)

        serializer = AdjustStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        stock_item = get_object_or_404(StockItem, id=data["stock_item_id"])

        try:
            updated_stock = InventoryService.adjust_stock(
                stock_item=stock_item,
                new_quantity_on_hand=data["new_quantity_on_hand"],
                reason=data["reason"],
                performed_by=request.user,
            )
        except ValidationError as e:
            msg = e.message_dict if hasattr(e, "message_dict") else e.messages
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(StockItemSerializer(updated_stock).data, status=status.HTTP_200_OK)


class InventoryAlertsViewSet(viewsets.ViewSet):
    """
    Real-time inventory alerts, including low-stock thresholds.
    """

    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        """
        Returns parts whose aggregate stock is at or below reorder threshold.
        """
        parts = Part.objects.filter(is_active=True)
        low_stock_parts = [p for p in parts if p.is_low_stock]
        serializer = PartSerializer(low_stock_parts, many=True)
        return Response(
            {
                "count": len(low_stock_parts),
                "low_stock_items": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class InventoryTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Immutable audit ledger of all inventory movements.
    """

    queryset = InventoryTransaction.objects.select_related("part", "work_order", "performed_by").all()
    serializer_class = InventoryTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        part_id = self.request.query_params.get("part")
        if part_id:
            qs = qs.filter(part_id=part_id)

        tx_type = self.request.query_params.get("transaction_type")
        if tx_type:
            qs = qs.filter(transaction_type=tx_type)

        work_order_id = self.request.query_params.get("work_order")
        if work_order_id:
            qs = qs.filter(work_order_id=work_order_id)

        return qs
