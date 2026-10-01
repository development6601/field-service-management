from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LoginView,
    RefreshTokenView,
    LogoutView,
    UserProfileView,
    ChangePasswordView,
    CustomerRegistrationView,
    UserManagementViewSet,
    TechnicianRosterView,
)

# Authentication endpoints (/api/v1/auth/...)
auth_urlpatterns = [
    path("register/", CustomerRegistrationView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshTokenView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", UserProfileView.as_view(), name="auth-me"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
]

# User management router (/api/v1/users/...)
user_router = DefaultRouter()
user_router.register("", UserManagementViewSet, basename="user")

user_urlpatterns = [
    path("technicians/roster/", TechnicianRosterView.as_view(), name="technician-roster"),
    path("", include(user_router.urls)),
]

urlpatterns = auth_urlpatterns
