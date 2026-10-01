from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, ServiceLocationViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("locations", ServiceLocationViewSet, basename="location")

urlpatterns = [
    # Nested customer locations: /api/v1/customers/<customer_pk>/locations/
    path(
        "customers/<uuid:customer_pk>/locations/",
        ServiceLocationViewSet.as_view({"get": "list", "post": "create"}),
        name="customer-locations-list",
    ),
    path("", include(router.urls)),
]
