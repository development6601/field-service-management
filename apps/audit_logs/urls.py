from rest_framework.routers import DefaultRouter
from apps.audit_logs.views import AuditLogViewSet

router = DefaultRouter()
router.register(r"", AuditLogViewSet, basename="audit-log")

urlpatterns = router.urls
