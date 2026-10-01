from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.billing.views import InvoiceViewSet, PaymentViewSet

router = DefaultRouter()
router.register(r"invoices", InvoiceViewSet, basename="invoice")
router.register(r"payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path("", include(router.urls)),
]
