import logging
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdminOrManager

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """
    Service health check endpoint to verify API and database connectivity.
    Endpoint: /api/v1/health/
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        db_status = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"

        payload = {
            "status": "healthy" if db_status == "ok" else "degraded",
            "service": "field-service-management-api",
            "version": "1.0.0",
            "timezone": "Asia/Kolkata (IST)",
            "timestamp": timezone.localtime().isoformat(),
            "database": db_status,
        }

        http_status = (
            status.HTTP_200_OK if db_status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return Response(payload, status=http_status)


class CeleryHealthView(APIView):
    """
    Diagnostic endpoint to inspect Celery task queue, broker configuration,
    and registered periodic schedules.
    Endpoint: /api/v1/health/celery/
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        from config.celery import app as celery_app

        celery_app.loader.import_default_modules()

        broker_url = getattr(settings, "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
        is_eager = getattr(settings, "CELERY_TASK_ALWAYS_EAGER", True)
        beat_schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})

        # Mask sensitive broker password if present
        safe_broker = broker_url.split("@")[-1] if "@" in broker_url else broker_url

        registered_tasks = [
            task for task in sorted(celery_app.tasks.keys())
            if not task.startswith("celery.")
        ]

        return Response(
            {
                "status": "operational",
                "celery_version": getattr(celery_app, "version", "5.x"),
                "broker": safe_broker,
                "eager_mode_active": is_eager,
                "registered_tasks": registered_tasks,
                "scheduled_beat_jobs": list(beat_schedule.keys()),
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class TaskTriggerView(APIView):
    """
    Administrative endpoint to trigger and test background tasks on demand.
    Endpoint: POST /api/v1/tasks/trigger/
    Body:
      {
        "task_name": "check_sla_breaches" | "send_overdue_reminders" | "check_low_stock"
      }
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get(self, request):
        """Returns the list of triggerable background tasks."""
        return Response(
            {
                "available_tasks": [
                    "check_sla_breaches",
                    "send_overdue_reminders",
                    "check_low_stock",
                ],
                "description": "Send POST with {'task_name': '...'} to trigger immediate execution.",
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        task_name = request.data.get("task_name")
        valid_tasks = {
            "check_sla_breaches": "apps.service_requests.tasks.check_and_escalate_sla_breaches",
            "send_overdue_reminders": "apps.billing.tasks.send_overdue_invoice_reminders",
            "check_low_stock": "apps.inventory.tasks.check_low_stock_thresholds",
        }

        if not task_name or task_name not in valid_tasks:
            return Response(
                {
                    "error": f"Invalid task_name. Allowed tasks are: {', '.join(valid_tasks.keys())}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.billing.tasks import send_overdue_invoice_reminders
        from apps.inventory.tasks import check_low_stock_thresholds
        from apps.service_requests.tasks import check_and_escalate_sla_breaches

        task_map = {
            "check_sla_breaches": check_and_escalate_sla_breaches,
            "send_overdue_reminders": send_overdue_invoice_reminders,
            "check_low_stock": check_low_stock_thresholds,
        }

        task_func = task_map[task_name]
        # Dispatch task via Celery delay()
        async_result = task_func.delay()

        # In eager mode, result is immediately available
        result_data = async_result.result if hasattr(async_result, "result") else "Queued"

        return Response(
            {
                "status": "EXECUTED",
                "task_name": task_name,
                "task_id": str(async_result.id) if hasattr(async_result, "id") else None,
                "execution_result": result_data,
                "triggered_by": request.user.email,
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )
