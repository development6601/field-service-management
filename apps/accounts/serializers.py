from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers, exceptions
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from .models import TechnicianProfile

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT serializer that embeds user roles and profile details into
    both the token claims and the JSON response payload.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Inject custom claims directly into the encrypted JWT payload
        token["user_id"] = str(user.id)
        token["email"] = user.email
        token["role"] = user.role
        token["full_name"] = user.full_name
        return token

    def validate(self, attrs):
        # Authenticate standard credentials
        data = super().validate(attrs)

        # Edge case protection: Prevent login if account is soft-deleted
        if getattr(self.user, "is_deleted", False):
            raise exceptions.AuthenticationFailed("Account has been deactivated. Please contact administrator.")

        if not self.user.is_active:
            raise exceptions.AuthenticationFailed("Account is disabled.")

        # Embed convenient user metadata in the login response
        data["user"] = {
            "id": str(self.user.id),
            "email": self.user.email,
            "full_name": self.user.full_name,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "phone_number": self.user.phone_number,
            "role": self.user.role,
        }

        # Include technician info if applicable
        if hasattr(self.user, "technician_profile"):
            data["user"]["skills"] = self.user.technician_profile.skills
            data["user"]["is_available"] = self.user.technician_profile.is_available

        return data


class TechnicianProfileSerializer(serializers.ModelSerializer):
    """Serializer for field technician profile details."""

    class Meta:
        model = TechnicianProfile
        fields = [
            "id",
            "skills",
            "is_available",
            "working_hours_start",
            "working_hours_end",
            "current_latitude",
            "current_longitude",
            "emergency_contact",
            "notes",
        ]
        read_only_fields = ["id"]


class UserSerializer(serializers.ModelSerializer):
    """Detailed serializer for User profile view and update."""

    technician_profile = TechnicianProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "role",
            "is_active",
            "technician_profile",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "role", "is_active", "created_at", "updated_at"]


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer to securely change an authenticated user's password."""

    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is not correct.")
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        validate_password(value, user)
        return value


class LogoutSerializer(serializers.Serializer):
    """Serializer to invalidate refresh tokens on logout."""

    refresh = serializers.CharField(required=True)

    def validate(self, attrs):
        self.token = attrs["refresh"]
        return attrs

    def save(self, **kwargs):
        try:
            token = RefreshToken(self.token)
            token.blacklist()
        except TokenError as e:
            raise serializers.ValidationError({"refresh": f"Invalid or expired token: {str(e)}"})


class CustomerRegistrationSerializer(serializers.ModelSerializer):
    """
    Public self-registration serializer for customers.
    Strictly forces role to CUSTOMER to prevent privilege escalation attacks.
    """

    password = serializers.CharField(write_only=True, required=True)
    company_name = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "password",
            "first_name",
            "last_name",
            "phone_number",
            "company_name",
            "role",
        ]
        read_only_fields = ["id", "role"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        from apps.customers.models import Customer

        company_name = validated_data.pop("company_name", "")
        # Enforce role CUSTOMER regardless of what was submitted
        validated_data["role"] = "CUSTOMER"

        user = User.objects.create_user(**validated_data)

        # Automatically provision linked Customer profile
        Customer.objects.create(
            user=user,
            company_name=company_name,
            primary_contact_name=user.full_name or user.email,
            email=user.email,
            phone=user.phone_number,
        )
        return user


class TechnicianProfileInputSerializer(serializers.ModelSerializer):
    """Nested serializer for creating/updating technician profile details."""

    class Meta:
        model = TechnicianProfile
        fields = [
            "skills",
            "is_available",
            "working_hours_start",
            "working_hours_end",
            "current_latitude",
            "current_longitude",
            "emergency_contact",
            "notes",
        ]


class UserCreateByAdminSerializer(serializers.ModelSerializer):
    """
    Admin-only serializer for creating internal employees
    (Admin, Dispatcher, Technician, Manager) with optional technician profiles.
    """

    password = serializers.CharField(write_only=True, required=True)
    technician_profile = TechnicianProfileInputSerializer(required=False, write_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "password",
            "first_name",
            "last_name",
            "phone_number",
            "role",
            "is_active",
            "technician_profile",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        tech_profile_data = validated_data.pop("technician_profile", None)
        user = User.objects.create_user(**validated_data)

        # If user is a technician, create their profile
        if user.role == "TECHNICIAN":
            profile_kwargs = tech_profile_data or {}
            TechnicianProfile.objects.create(user=user, **profile_kwargs)

        return user


class UserAdminUpdateSerializer(serializers.ModelSerializer):
    """Admin-only serializer for updating existing user roles, status, and technician details."""

    technician_profile = TechnicianProfileInputSerializer(required=False)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "role",
            "is_active",
            "technician_profile",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "updated_at"]

    def update(self, instance, validated_data):
        tech_profile_data = validated_data.pop("technician_profile", None)

        # Update core user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update or create technician profile if user is TECHNICIAN
        if instance.role == "TECHNICIAN" and tech_profile_data is not None:
            profile, _ = TechnicianProfile.objects.get_or_create(user=instance)
            for attr, value in tech_profile_data.items():
                setattr(profile, attr, value)
            profile.save()

        return instance


class TechnicianRosterSerializer(serializers.ModelSerializer):
    """Optimized representation of available field technicians for Dispatchers."""

    full_name = serializers.CharField(read_only=True)
    skills = serializers.JSONField(source="technician_profile.skills", read_only=True, default=list)
    is_available = serializers.BooleanField(source="technician_profile.is_available", read_only=True, default=False)
    working_hours_start = serializers.TimeField(source="technician_profile.working_hours_start", read_only=True, default=None)
    working_hours_end = serializers.TimeField(source="technician_profile.working_hours_end", read_only=True, default=None)
    current_latitude = serializers.DecimalField(max_digits=9, decimal_places=6, source="technician_profile.current_latitude", read_only=True, default=None)
    current_longitude = serializers.DecimalField(max_digits=9, decimal_places=6, source="technician_profile.current_longitude", read_only=True, default=None)
    emergency_contact = serializers.CharField(source="technician_profile.emergency_contact", read_only=True, default="")

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone_number",
            "skills",
            "is_available",
            "working_hours_start",
            "working_hours_end",
            "current_latitude",
            "current_longitude",
            "emergency_contact",
        ]

