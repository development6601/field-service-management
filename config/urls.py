"""
URL configuration for Field Service Management (FSM) project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from apps.core.views import HealthCheckView
from apps.accounts.urls import auth_urlpatterns, user_urlpatterns


@api_view(["GET"])
@permission_classes([AllowAny])
def api_root(request):
    return Response({
        "project": "Field Service Management (FSM) API",
        "status": "operational",
        "version": "v1",
        "endpoints": {
            "swagger_docs": "/api/docs/",
            "swagger_alt": "/swagger/",
            "redoc_docs": "/api/redoc/",
            "openapi_schema": "/api/schema/",
            "health_check": "/api/v1/health/",
            "admin": "/admin/",
            "auth": {
                "register": "/api/v1/auth/register/",
                "login": "/api/v1/auth/login/",
                "refresh": "/api/v1/auth/refresh/",
                "logout": "/api/v1/auth/logout/",
                "me": "/api/v1/auth/me/",
                "change_password": "/api/v1/auth/change-password/",
            },
            "users": {
                "users_list_and_crud": "/api/v1/users/",
                "technicians_roster": "/api/v1/users/technicians/roster/",
            },
            "customers": {
                "customers_list_and_crud": "/api/v1/customers/",
                "service_locations_crud": "/api/v1/locations/",
            },
            "service_requests": {
                "requests_list_and_create": "/api/v1/requests/",
                "request_review": "/api/v1/requests/<id>/review/",
                "request_cancel": "/api/v1/requests/<id>/cancel/",
                "request_attachments": "/api/v1/requests/<id>/attachments/",
            },
            "work_orders": {
                "work_orders_list_and_create": "/api/v1/work-orders/",
                "convert_from_request": "/api/v1/work-orders/convert/",
                "assign_technician": "/api/v1/work-orders/<id>/assign/",
                "update_status": "/api/v1/work-orders/<id>/status/",
                "my_jobs": "/api/v1/work-orders/my-jobs/",
                "accept_job": "/api/v1/work-orders/<id>/accept/",
                "reject_job": "/api/v1/work-orders/<id>/reject/",
                "start_travel": "/api/v1/work-orders/<id>/start-travel/",
                "arrive_on_site": "/api/v1/work-orders/<id>/arrive/",
                "start_work": "/api/v1/work-orders/<id>/start-work/",
                "complete_job": "/api/v1/work-orders/<id>/complete/",
                "parts": "/api/v1/work-orders/<id>/parts/",
                "return_part": "/api/v1/work-orders/<id>/return-part/",
            },
            "scheduling": {
                "timeline": "/api/v1/scheduling/timeline/?date=YYYY-MM-DD",
                "check_availability": "/api/v1/scheduling/check/",
                "leaves": "/api/v1/scheduling/leaves/",
                "overrides": "/api/v1/scheduling/overrides/",
            },
            "inventory": {
                "parts_catalog": "/api/v1/inventory/parts/",
                "warehouses": "/api/v1/inventory/warehouses/",
                "stock_levels": "/api/v1/inventory/stock/",
                "my_van_stock": "/api/v1/inventory/stock/my-van/",
                "receive_stock": "/api/v1/inventory/operations/receive/",
                "transfer_to_van": "/api/v1/inventory/operations/transfer-to-van/",
                "transfer_to_warehouse": "/api/v1/inventory/operations/transfer-to-warehouse/",
                "adjust_stock": "/api/v1/inventory/operations/adjust/",
                "low_stock_alerts": "/api/v1/inventory/alerts/low-stock/",
                "transaction_ledger": "/api/v1/inventory/transactions/",
            },
            "contracts": {
                "contracts_list_and_create": "/api/v1/contracts/",
                "activate_contract": "/api/v1/contracts/<id>/activate/",
                "generate_work_order": "/api/v1/contracts/<id>/generate-work-order/",
                "terminate_contract": "/api/v1/contracts/<id>/terminate/",
            },
            "billing": {
                "invoices_list": "/api/v1/billing/invoices/",
                "generate_invoice": "/api/v1/billing/invoices/generate/",
                "invoice_detail": "/api/v1/billing/invoices/<id>/",
                "issue_invoice": "/api/v1/billing/invoices/<id>/issue/",
                "record_payment": "/api/v1/billing/invoices/<id>/payments/",
                "cancel_invoice": "/api/v1/billing/invoices/<id>/cancel/",
                "payments_history": "/api/v1/billing/payments/",
            },
            "portal": {
                "dashboard": "/api/v1/portal/dashboard/",
                "requests": "/api/v1/portal/requests/",
                "work_orders": "/api/v1/portal/work-orders/",
                "track_job": "/api/v1/portal/work-orders/<id>/track/",
                "submit_feedback": "/api/v1/portal/work-orders/<id>/feedback/",
                "contracts": "/api/v1/portal/contracts/",
                "invoices": "/api/v1/portal/invoices/",
                "pay_invoice": "/api/v1/portal/invoices/<id>/pay/",
            },
            "notifications": {
                "inbox": "/api/v1/notifications/",
                "unread_count": "/api/v1/notifications/unread-count/",
                "mark_read": "/api/v1/notifications/<id>/mark-read/",
                "mark_all_read": "/api/v1/notifications/mark-all-read/",
            },
            "attachments": {
                "upload_and_list": "/api/v1/attachments/",
                "detail": "/api/v1/attachments/<id>/",
                "download": "/api/v1/attachments/<id>/download/",
            },
            "audit_logs": {
                "logs_list": "/api/v1/audit-logs/",
                "log_detail": "/api/v1/audit-logs/<id>/",
                "timeline": "/api/v1/audit-logs/timeline/?entity_type=...&entity_id=...",
            },
            "analytics": {
                "executive_overview": "/api/v1/analytics/overview/",
                "revenue_analytics": "/api/v1/analytics/revenue/",
                "technician_productivity": "/api/v1/analytics/technicians/",
                "sla_compliance": "/api/v1/analytics/sla/",
                "inventory_analytics": "/api/v1/analytics/inventory/",
                "report_export": "/api/v1/analytics/export/?report_type=...&start_date=...&end_date=...",
            },
            "celery_tasks": {
                "health": "/api/v1/health/celery/",
                "trigger_task": "/api/v1/tasks/trigger/",
            },
        }
    })


urlpatterns = [
    path("", api_root, name="api-root"),
    path("admin/", admin.site.urls),
    # Core API & Celery Health/Trigger endpoints
    path("api/v1/", include("apps.core.urls")),
    # Authentication API endpoints
    path("api/v1/auth/", include((auth_urlpatterns, "auth"))),
    # User Management and Roster endpoints
    path("api/v1/users/", include((user_urlpatterns, "users"))),
    # Customer & Service Location endpoints
    path("api/v1/", include("apps.customers.urls")),
    # Service Requests & Ticketing Engine
    path("api/v1/", include("apps.service_requests.urls")),
    # Work Orders & Job Execution
    path("api/v1/work-orders/", include("apps.work_orders.urls")),
    # Scheduling & Dispatch Engine
    path("api/v1/scheduling/", include("apps.scheduling.urls")),
    # Inventory & Parts Management
    path("api/v1/inventory/", include("apps.inventory.urls")),
    # Service Contracts & Preventive Maintenance
    path("api/v1/contracts/", include("apps.contracts.urls")),
    # Billing & Payments
    path("api/v1/billing/", include("apps.billing.urls")),
    # Customer Self-Service Portal
    path("api/v1/portal/", include("apps.portal.urls")),
    # Event Notifications Engine
    path("api/v1/notifications/", include("apps.notifications.urls")),
    # Files & Document Attachments Management
    path("api/v1/attachments/", include("apps.attachments.urls")),
    # Audit & Activity Logs Engine
    path("api/v1/audit-logs/", include("apps.audit_logs.urls")),
    # Reports & Executive Analytics Engine
    path("api/v1/analytics/", include("apps.analytics.urls")),
    # OpenAPI 3 Schema & Interactive Swagger UI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui-alt"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

