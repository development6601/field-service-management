from rest_framework import permissions
from apps.accounts.models import UserRole


class IsAdmin(permissions.BasePermission):
    """Allows access only to authenticated users with ADMIN role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.ADMIN
        )


class IsManager(permissions.BasePermission):
    """Allows access to users with MANAGER or ADMIN role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (UserRole.MANAGER, UserRole.ADMIN)
        )


class IsDispatcher(permissions.BasePermission):
    """Allows access to users with DISPATCHER, MANAGER, or ADMIN role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (UserRole.DISPATCHER, UserRole.MANAGER, UserRole.ADMIN)
        )


class IsTechnician(permissions.BasePermission):
    """Allows access only to field TECHNICIANS."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.TECHNICIAN
        )


class IsCustomer(permissions.BasePermission):
    """Allows access only to CUSTOMER users."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.CUSTOMER
        )


class IsAdminOrManager(permissions.BasePermission):
    """Allows read/write to Admin, and read/supervise to Manager."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (UserRole.ADMIN, UserRole.MANAGER)
        )


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Object-level permission allowing users to view/modify only their own objects,
    while permitting Admins full operational access.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.role == UserRole.ADMIN:
            return True

        # If obj is User itself
        if hasattr(obj, "id") and obj.id == request.user.id:
            return True

        # If obj has a direct 'user' foreign key
        if hasattr(obj, "user") and obj.user == request.user:
            return True

        # If obj belongs to a Customer linked to request.user
        if hasattr(obj, "customer") and getattr(obj.customer, "user", None) == request.user:
            return True

        return False
