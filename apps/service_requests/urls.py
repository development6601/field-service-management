from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ServiceRequestViewSet

router = DefaultRouter()
router.register("requests", ServiceRequestViewSet, basename="service-request")

urlpatterns = [
    path("", include(router.urls)),
]
