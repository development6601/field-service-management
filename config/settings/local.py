"""
Development settings for Field Service Management (FSM).
Intended for local developer workstations.
"""

import os
from .base import *  # noqa: F403, F401
from .base import BASE_DIR

DEBUG = True

# Database Configuration
# Defaults to SQLite for effortless local development.
# Set USE_SQLITE=False in .env to connect to PostgreSQL.
USE_SQLITE = os.getenv("USE_SQLITE", "True").lower() in ("true", "1", "t")

if USE_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DATABASE_NAME", "fsm_db"),
            "USER": os.getenv("DATABASE_USER", "postgres"),
            "PASSWORD": os.getenv("DATABASE_PASSWORD", "postgres"),
            "HOST": os.getenv("DATABASE_HOST", "localhost"),
            "PORT": os.getenv("DATABASE_PORT", "5432"),
        }
    }

# CORS settings for development (allow local frontend dev servers)
CORS_ALLOW_ALL_ORIGINS = True

# Console email backend for testing notifications locally without SMTP server
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = ["https://*.ngrok-free.app"]