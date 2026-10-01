from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.portal.views import (
    PortalContractViewSet,
    PortalDashboardView,
    PortalInvoiceViewSet,
    PortalServiceRequestViewSet,
    PortalWorkOrderViewSet,
)

router = DefaultRouter()
router.register(r"requests", PortalServiceRequestViewSet, basename="portal-request")
router.register(r"work-orders", PortalWorkOrderViewSet, basename="portal-work-order")
router.register(r"contracts", PortalContractViewSet, basename="portal-contract")
router.register(r"invoices", PortalInvoiceViewSet, basename="portal-invoice")

urlpatterns = [
    path("dashboard/", PortalDashboardView.as_view(), name="portal-dashboard"),
    path("", include(router.urls)),
]
