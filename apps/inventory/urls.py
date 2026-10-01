from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inventory.views import (
    InventoryAlertsViewSet,
    InventoryTransactionViewSet,
    PartViewSet,
    StockItemViewSet,
    StockOperationsViewSet,
    WarehouseViewSet,
)

router = DefaultRouter()
router.register(r"parts", PartViewSet, basename="part")
router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"stock", StockItemViewSet, basename="stock-item")
router.register(r"operations", StockOperationsViewSet, basename="stock-operations")
router.register(r"alerts", InventoryAlertsViewSet, basename="inventory-alerts")
router.register(r"transactions", InventoryTransactionViewSet, basename="inventory-transactions")

urlpatterns = [
    path("", include(router.urls)),
]
