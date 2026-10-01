import logging
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.inventory.models import Part
from apps.notifications.models import NotificationPriority, NotificationType
from apps.notifications.services import NotificationService

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(name="apps.inventory.tasks.check_low_stock_thresholds")
def check_low_stock_thresholds():
    """
    Hourly scheduled task scanning spare parts inventory levels.
    Identifies parts below their reorder threshold and dispatches replenishment alerts.
    """
    now = timezone.now()
    active_parts = Part.objects.filter(is_active=True).prefetch_related("stock_items")

    low_stock_items = []

    for part in active_parts:
        qty_on_hand = part.total_quantity_on_hand
        if qty_on_hand <= part.reorder_threshold:
            low_stock_items.append({
                "part_id": str(part.id),
                "sku": part.sku,
                "name": part.name,
                "current_stock": qty_on_hand,
                "reorder_threshold": part.reorder_threshold,
            })

    if low_stock_items:
        procurement_staff = User.objects.filter(
            role__in=[UserRole.ADMIN, UserRole.MANAGER],
            is_active=True,
        )

        for item in low_stock_items:
            title = f"INVENTORY ALERT: Low Stock for {item['sku']}"
            message = (
                f"Part '{item['name']}' ({item['sku']}) is below its safety threshold. "
                f"Current on-hand: {item['current_stock']}, Minimum threshold: {item['reorder_threshold']}. "
                f"Please initiate purchase inward."
            )

            for staff in procurement_staff:
                NotificationService.send(
                    recipient=staff,
                    title=title,
                    message=message,
                    notification_type=NotificationType.LOW_STOCK_ALERT,
                    priority=NotificationPriority.HIGH,
                    related_entity_type="part",
                    related_entity_id=item["part_id"],
                )

    logger.info(
        f"Inventory threshold scan completed at {now}. Found {len(low_stock_items)} low-stock parts."
    )
    return {
        "timestamp": str(now),
        "low_stock_count": len(low_stock_items),
        "low_stock_parts": low_stock_items,
    }
