from django.urls import path
from apps.analytics.views import (
    ExecutiveOverviewView,
    InventoryAnalyticsView,
    ReportExportView,
    RevenueAnalyticsView,
    SLAComplianceView,
    TechnicianProductivityView,
)

urlpatterns = [
    path("overview/", ExecutiveOverviewView.as_view(), name="analytics-overview"),
    path("revenue/", RevenueAnalyticsView.as_view(), name="analytics-revenue"),
    path("technicians/", TechnicianProductivityView.as_view(), name="analytics-technicians"),
    path("sla/", SLAComplianceView.as_view(), name="analytics-sla"),
    path("inventory/", InventoryAnalyticsView.as_view(), name="analytics-inventory"),
    path("export/", ReportExportView.as_view(), name="analytics-export"),
]
