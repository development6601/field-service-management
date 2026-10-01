from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.contracts.views import ServiceContractViewSet

router = DefaultRouter()
router.register(r"", ServiceContractViewSet, basename="contract")

urlpatterns = [
    path("", include(router.urls)),
]
