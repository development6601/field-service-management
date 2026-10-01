from django.urls import path
from apps.core.views import CeleryHealthView, HealthCheckView, TaskTriggerView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("health/celery/", CeleryHealthView.as_view(), name="celery-health"),
    path("tasks/trigger/", TaskTriggerView.as_view(), name="task-trigger"),
]
