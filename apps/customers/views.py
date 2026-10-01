from django.db import transaction
from django.db.models import Q
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.response import Response

from apps.accounts.models import UserRole
from apps.core.permissions import IsDispatcher
from .models import Customer, ServiceLocation
from .serializers import (
    CustomerSerializer,
    CustomerCreateUpdateSerializer,
    ServiceLocationSerializer,
)


class CustomerViewSet(viewsets.ModelViewSet):
    """
    CRUD API for customer accounts.
    - Admins, Managers, and Dispatchers have full operational access across all clients.
    - Customer users are strictly isolated to viewing and updating their own profile.
    """

    permission_classes = [permissions.IsAuthenticated]
    queryset = Customer.objects.all().prefetch_related("service_locations")

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return CustomerCreateUpdateSerializer
        return CustomerSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Tenant isolation: Customers can only see their own company/profile
        if user.role == UserRole.CUSTOMER:
            return qs.filter(user=user)

        # Search across company name, contact, email, phone, and tax ID
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(company_name__icontains=search)
                | Q(primary_contact_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(tax_id__icontains=search)
            )

        # Filter by city of service location (e.g. ?city=Bengaluru)
        city = self.request.query_params.get("city")
        if city:
            qs = qs.filter(service_locations__city__iexact=city).distinct()

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        # Regular customer users cannot arbitrarily create new customer records via this endpoint
        if user.role == UserRole.CUSTOMER:
            raise PermissionDenied("Customer accounts must be created through registration or by administrators.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            raise PermissionDenied("Only Administrators and Managers can delete customer records.")
        instance.delete()


class ServiceLocationViewSet(viewsets.ModelViewSet):
    """
    CRUD API for physical service sites and branch locations.
    Supports both direct access (/api/v1/locations/) and nested access (/api/v1/customers/<id>/locations/).
    Enforces atomic primary site switching.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ServiceLocationSerializer
    queryset = ServiceLocation.objects.all().select_related("customer")

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        # Handle nested customer URL: /api/v1/customers/<customer_pk>/locations/
        customer_pk = self.kwargs.get("customer_pk")
        if customer_pk:
            qs = qs.filter(customer_id=customer_pk)

        # Tenant isolation: Customer users only see their own physical locations
        if user.role == UserRole.CUSTOMER:
            qs = qs.filter(customer__user=user)

        # Filter by primary status (e.g. ?is_primary=true)
        is_primary = self.request.query_params.get("is_primary")
        if is_primary is not None:
            primary_bool = is_primary.lower() in ("true", "1", "t")
            qs = qs.filter(is_primary=primary_bool)

        # Filter by city (e.g. ?city=Bengaluru)
        city = self.request.query_params.get("city")
        if city:
            qs = qs.filter(city__iexact=city)

        return qs

    def _resolve_customer(self, serializer):
        customer_pk = self.kwargs.get("customer_pk")
        user = self.request.user

        if customer_pk:
            try:
                customer = Customer.objects.get(id=customer_pk)
            except Customer.DoesNotExist:
                raise NotFound("Target customer not found.")
        else:
            customer = serializer.validated_data.get("customer")
            if not customer:
                # If customer role, auto-assign their own customer profile
                if user.role == UserRole.CUSTOMER and hasattr(user, "customer_profile"):
                    customer = user.customer_profile
                else:
                    raise PermissionDenied("You must specify a valid customer for this location.")

        # Ensure Customer user cannot add location to another customer's account
        if user.role == UserRole.CUSTOMER and customer.user != user:
            raise PermissionDenied("You cannot add or modify locations for other customers.")

        return customer

    def perform_create(self, serializer):
        with transaction.atomic():
            customer = self._resolve_customer(serializer)
            is_primary = serializer.validated_data.get("is_primary", False)

            # Atomic Primary Switch: If this is marked primary, demote all other locations of this customer
            if is_primary:
                ServiceLocation.objects.filter(customer=customer).update(is_primary=False)

            serializer.save(customer=customer)

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = serializer.instance
            user = self.request.user

            # Tenant check
            if user.role == UserRole.CUSTOMER and instance.customer.user != user:
                raise PermissionDenied("You do not have permission to update this location.")

            is_primary = serializer.validated_data.get("is_primary", False)

            # Atomic Primary Switch on update
            if is_primary:
                ServiceLocation.objects.filter(customer=instance.customer).exclude(id=instance.id).update(is_primary=False)

            serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if user.role == UserRole.CUSTOMER and instance.customer.user != user:
            raise PermissionDenied("You cannot delete locations belonging to other customers.")
        instance.delete()
