import os
from celery import Celery

# Set default Django settings module for 'celery' program
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("fsm")

# Read configuration from Django settings with 'CELERY_' prefix
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py across all installed apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Simple diagnostic task to verify worker execution."""
    print(f"Request: {self.request!r}")
