import logging
from celery import shared_task
from django.contrib.auth import get_user_model

from apps.notifications.services import NotificationService

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(
    bind=True,
    name="apps.notifications.tasks.dispatch_async_notification",
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def dispatch_async_notification(
    self,
    recipient_id,
    title: str,
    message: str,
    notification_type: str = "GENERAL",
    priority: str = "NORMAL",
    related_entity_type: str = "",
    related_entity_id=None,
):
    """
    Asynchronous notification worker.
    Decouples in-app notification creation and third-party push/email from the HTTP cycle.
    Equipped with automatic exponential backoff retries on network failures.
    """
    try:
        recipient = User.objects.get(id=recipient_id)
        notification = NotificationService.send(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        return {
            "status": "SUCCESS",
            "notification_id": str(notification.id) if notification else None,
            "recipient_email": recipient.email,
        }
    except User.DoesNotExist:
        logger.error(f"Cannot dispatch notification. Recipient User {recipient_id} not found.")
        return {"status": "FAILED", "error": "User not found"}
    except Exception as exc:
        logger.warning(
            f"Failed to dispatch async notification to {recipient_id}. Attempt {self.request.retries + 1}/3: {exc}"
        )
        raise self.retry(exc=exc)
