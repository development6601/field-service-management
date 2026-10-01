from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ScheduleOverrideLogViewSet,
    SchedulingViewSet,
    TechnicianLeaveViewSet,
)

app_name = "scheduling"

router = DefaultRouter()
router.register(r"leaves", TechnicianLeaveViewSet, basename="technician-leave")
router.register(r"overrides", ScheduleOverrideLogViewSet, basename="schedule-override")
router.register(r"", SchedulingViewSet, basename="scheduling")

urlpatterns = [
    path("", include(router.urls)),
]
