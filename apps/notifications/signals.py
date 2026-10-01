import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.billing.models import Invoice, InvoiceStatus, Payment, PaymentStatus
from apps.inventory.models import StockItem
from apps.notifications.services import NotificationService
from apps.service_requests.models import ServiceRequest
from apps.work_orders.models import WorkOrder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Service Requests
# ---------------------------------------------------------------------------
@receiver(post_save, sender=ServiceRequest)
def service_request_notification_handler(sender, instance, created, **kwargs):
    if created:
        NotificationService.notify_service_request_created(instance)


# ---------------------------------------------------------------------------
# 2. Work Orders
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=WorkOrder)
def work_order_pre_save_snapshot(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = WorkOrder.objects.get(pk=instance.pk)
            instance._old_status = old.status
            instance._old_assigned_technician_id = old.assigned_technician_id
        except WorkOrder.DoesNotExist:
            instance._old_status = None
            instance._old_assigned_technician_id = None
    else:
        instance._old_status = None
        instance._old_assigned_technician_id = None


@receiver(post_save, sender=WorkOrder)
def work_order_notification_handler(sender, instance, created, **kwargs):
    # Assignment alert for technician
    assigned_tech_id = instance.assigned_technician_id
    old_tech_id = getattr(instance, "_old_assigned_technician_id", None)

    if assigned_tech_id and (created or assigned_tech_id != old_tech_id):
        NotificationService.notify_work_order_assigned(instance)

    # Status change alerts for customer
    old_status = getattr(instance, "_old_status", None)
    if not created and old_status and old_status != instance.status:
        NotificationService.notify_work_order_status_change(instance, old_status=old_status)


# ---------------------------------------------------------------------------
# 3. Invoices
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=Invoice)
def invoice_pre_save_snapshot(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = Invoice.objects.get(pk=instance.pk)
            instance._old_status = old.status
        except Invoice.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=Invoice)
def invoice_notification_handler(sender, instance, created, **kwargs):
    old_status = getattr(instance, "_old_status", None)
    if instance.status == InvoiceStatus.ISSUED and (created or old_status != InvoiceStatus.ISSUED):
        NotificationService.notify_invoice_generated(instance)


# ---------------------------------------------------------------------------
# 4. Payments
# ---------------------------------------------------------------------------
@receiver(post_save, sender=Payment)
def payment_notification_handler(sender, instance, created, **kwargs):
    if created and instance.payment_status == PaymentStatus.SUCCESS:
        NotificationService.notify_payment_received(instance)


# ---------------------------------------------------------------------------
# 5. Inventory Low Stock Alerts
# ---------------------------------------------------------------------------
@receiver(post_save, sender=StockItem)
def stock_item_notification_handler(sender, instance, **kwargs):
    if (
        instance.part
        and instance.part.reorder_threshold > 0
        and instance.quantity_on_hand <= instance.part.reorder_threshold
    ):
        NotificationService.notify_low_stock(instance)
