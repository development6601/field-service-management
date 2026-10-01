from django.contrib.auth.base_user import BaseUserManager
from apps.core.managers import SoftDeletableQuerySet


class UserQuerySet(SoftDeletableQuerySet):
    """Custom queryset for User with role filtering helpers."""

    def technicians(self):
        return self.filter(role="TECHNICIAN")

    def dispatchers(self):
        return self.filter(role="DISPATCHER")

    def managers(self):
        return self.filter(role="MANAGER")

    def customers(self):
        return self.filter(role="CUSTOMER")

    def admins(self):
        return self.filter(role="ADMIN")


class CustomUserManager(BaseUserManager.from_queryset(UserQuerySet)):
    """
    Custom user manager where email is the unique identifier
    for authentication instead of usernames.
    """

    def get_queryset(self):
        return UserQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def all_with_deleted(self):
        return UserQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return UserQuerySet(self.model, using=self._db).filter(is_deleted=True)

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a standard user with the given email and password."""
        if not email:
            raise ValueError("The Email field must be set")

        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", "ADMIN")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)
