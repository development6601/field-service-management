from django.db.models import Q
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.permissions import IsAdmin, IsDispatcher, IsAdminOrManager
from .models import User, UserRole
from .serializers import (
    CustomTokenObtainPairSerializer,
    UserSerializer,
    ChangePasswordSerializer,
    LogoutSerializer,
    CustomerRegistrationSerializer,
    UserCreateByAdminSerializer,
    UserAdminUpdateSerializer,
    TechnicianRosterSerializer,
)


class LoginView(TokenObtainPairView):
    """
    Login endpoint: Exchange email & password for JWT Access and Refresh tokens.
    Returns user identity and embedded role claims.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = CustomTokenObtainPairSerializer


class RefreshTokenView(TokenRefreshView):
    """
    Token Refresh endpoint: Submit valid refresh token to obtain a fresh access token.
    Rotates refresh token for continuous security.
    """

    permission_classes = [permissions.AllowAny]


class LogoutView(APIView):
    """
    Secure Logout endpoint: Blacklists the provided refresh token so it cannot be used again.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": "Successfully logged out. Token has been blacklisted."},
            status=status.HTTP_200_OK,
        )


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Current user profile endpoint.
    GET: Returns details of the currently authenticated user.
    PATCH / PUT: Update contact details (first_name, last_name, phone_number).
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """
    Change password endpoint for authenticated users.
    Validates current password and updates to new password.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        return Response(
            {"detail": "Password has been successfully updated."},
            status=status.HTTP_200_OK,
        )


class CustomerRegistrationView(generics.CreateAPIView):
    """
    Public self-registration API for clients and customers.
    Enforces role=CUSTOMER and provisions customer record.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = CustomerRegistrationSerializer


class UserManagementViewSet(viewsets.ModelViewSet):
    """
    Administrative user management viewset.
    List & Retrieve: accessible by Admins and Managers.
    Create, Update & Delete: strictly restricted to Admins.
    """

    queryset = User.objects.all().select_related("technician_profile")

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdmin()]
        return [IsAdminOrManager()]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateByAdminSerializer
        elif self.action in ["update", "partial_update"]:
            return UserAdminUpdateSerializer
        return UserSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtering by role (e.g. ?role=TECHNICIAN)
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role.upper())

        # Filtering by active status (e.g. ?is_active=true)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            active_bool = is_active.lower() in ("true", "1", "t")
            qs = qs.filter(is_active=active_bool)

        # Search by email, name, or phone
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone_number__icontains=search)
            )

        return qs

    def perform_destroy(self, instance):
        # Edge case protection: Prevent an Admin from deleting their own account
        if instance == self.request.user:
            raise ValidationError("You cannot delete your own administrative account.")
        instance.delete()


class TechnicianRosterView(generics.ListAPIView):
    """
    Operational roster view for Dispatchers and Admins.
    Lists active technicians with filtering by availability and required skills.
    """

    permission_classes = [IsDispatcher]
    serializer_class = TechnicianRosterSerializer

    def get_queryset(self):
        qs = User.objects.technicians().filter(is_active=True).select_related("technician_profile")

        # Filter by real-time availability (e.g. ?available=true)
        available = self.request.query_params.get("available")
        if available is not None:
            avail_bool = available.lower() in ("true", "1", "t")
            qs = qs.filter(technician_profile__is_available=avail_bool)

        # Filter by skill (e.g. ?skill=HVAC)
        skill = self.request.query_params.get("skill")
        if skill:
            qs = qs.filter(technician_profile__skills__icontains=skill)

        return qs
