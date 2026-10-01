"""
Base settings for Field Service Management (FSM) platform.
Shared across all environments (local, testing, production).
"""

import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# config/settings/base.py -> parent.parent.parent is the workspace root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env file from root
load_dotenv(BASE_DIR / ".env")

# Core Security
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-default-dev-key")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in ("true", "1", "t")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

# Application definition
DJANGO_APPS = [
    "daphne",  # Must be first for ASGI runserver
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.customers.apps.CustomersConfig",
    "apps.services.apps.ServicesConfig",
    "apps.service_requests.apps.ServiceRequestsConfig",
    "apps.work_orders.apps.WorkOrdersConfig",
    "apps.scheduling.apps.SchedulingConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.contracts.apps.ContractsConfig",
    "apps.billing.apps.BillingConfig",
    "apps.portal.apps.PortalConfig",
    "apps.notifications.apps.NotificationsConfig",
    "apps.attachments.apps.AttachmentsConfig",
    "apps.audit_logs.apps.AuditLogsConfig",
    "apps.analytics.apps.AnalyticsConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ASGI Application definition for Channels & WebSockets (Phase 19)
ASGI_APPLICATION = "config.asgi.application"

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # Must be as high as possible
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit_logs.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # Indian Standard Time (IST, UTC+05:30)
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (uploaded photos, completion signatures, docs)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ",
}

# OpenAPI & Swagger UI Configuration (drf-spectacular)
SPECTACULAR_SETTINGS = {
    "TITLE": "Field Service Management (FSM) API",
    "DESCRIPTION": (
        "Enterprise real-time Field Service Management & Workforce Automation API.\n\n"
        "Features: RBAC, Customer Portal, Work Order State Machine, Scheduling, "
        "Inventory Stock Control, Billing & Invoicing, Celery Asynchronous Tasks, "
        "and WebSockets Real-Time Live Feeds."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "displayOperationId": False,
    },
}

# SimpleJWT Configuration
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "apps.accounts.serializers.CustomTokenObtainPairSerializer",
}

# Celery Configuration (Phase 18)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "True").lower() in ("true", "1", "t")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_IMPORTS = [
    "apps.service_requests.tasks",
    "apps.billing.tasks",
    "apps.inventory.tasks",
    "apps.notifications.tasks",
]

# Celery Beat Scheduled Periodic Tasks
CELERY_BEAT_SCHEDULE = {
    "check-sla-breaches-every-15-mins": {
        "task": "apps.service_requests.tasks.check_and_escalate_sla_breaches",
        "schedule": 900.0,  # Every 15 minutes
    },
    "send-overdue-invoice-reminders-daily": {
        "task": "apps.billing.tasks.send_overdue_invoice_reminders",
        "schedule": 86400.0,  # Daily
    },
    "check-low-stock-thresholds-hourly": {
        "task": "apps.inventory.tasks.check_low_stock_thresholds",
        "schedule": 3600.0,  # Hourly
    },
}

# Channel Layers Configuration (Phase 19)
# Uses InMemoryChannelLayer for dev/tests, and Redis for distributed production
CHANNEL_LAYER_BACKEND = os.getenv("CHANNEL_LAYER_BACKEND", "in_memory")
if CHANNEL_LAYER_BACKEND == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1")],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }
