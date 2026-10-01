import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.scheduling.broadcaster import broadcast_dispatcher_event
from apps.service_requests.models import RequestPriority, ServiceRequest
from apps.work_orders.models import WorkOrder

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=WorkOrder)
def work_order_pre_save_realtime(sender, instance, **kwargs):
    """Caches prior state to detect field transitions on update."""
    if instance.pk:
        try:
            old = WorkOrder.objects.only("status", "assigned_technician_id").get(pk=instance.pk)
            instance._realtime_old_status = old.status
            instance._realtime_old_tech_id = old.assigned_technician_id
        except WorkOrder.DoesNotExist:
            instance._realtime_old_status = None
            instance._realtime_old_tech_id = None
    else:
        instance._realtime_old_status = None
        instance._realtime_old_tech_id = None


@receiver(post_save, sender=WorkOrder)
def work_order_post_save_realtime(sender, instance, created, **kwargs):
    """
    Broadcasts real-time events to the Dispatcher Board on Work Order creation,
    technician assignment, and status transitions.
    """
    if created:
        customer_name = getattr(instance.customer, "company_name", "N/A") if instance.customer else "N/A"
        tech_name = instance.assigned_technician.get_full_name() if instance.assigned_technician else None

        broadcast_dispatcher_event(
            "WORK_ORDER_CREATED",
            {
                "work_order_id": str(instance.id),
                "work_order_number": instance.work_order_number,
                "customer": customer_name,
                "priority": instance.priority,
                "status": instance.status,
                "assigned_technician": tech_name,
                "scheduled_start": (
                    instance.scheduled_start.isoformat()
                    if instance.scheduled_start
                    else None
                ),
            },
        )
        return

    # 1. Assignment broadcast
    old_tech_id = getattr(instance, "_realtime_old_tech_id", None)
    new_tech_id = instance.assigned_technician_id
    if (old_tech_id != new_tech_id) and new_tech_id:
        tech_name = instance.assigned_technician.get_full_name() if instance.assigned_technician else "Unassigned"
        broadcast_dispatcher_event(
            "WORK_ORDER_ASSIGNED",
            {
                "work_order_id": str(instance.id),
                "work_order_number": instance.work_order_number,
                "technician_id": str(new_tech_id),
                "technician_name": tech_name,
                "status": instance.status,
            },
        )

    # 2. Status transition broadcast
    old_status = getattr(instance, "_realtime_old_status", None)
    new_status = instance.status
    if old_status and (old_status != new_status):
        tech_name = instance.assigned_technician.get_full_name() if instance.assigned_technician else None
        broadcast_dispatcher_event(
            "WORK_ORDER_STATUS_CHANGED",
            {
                "work_order_id": str(instance.id),
                "work_order_number": instance.work_order_number,
                "old_status": old_status,
                "new_status": new_status,
                "technician": tech_name,
            },
        )


@receiver(post_save, sender=ServiceRequest)
def service_request_post_save_realtime(sender, instance, created, **kwargs):
    """
    Broadcasts instant emergency alerts to the Dispatcher Board when high-priority
    breakdown tickets are raised.
    """
    if created and instance.priority in [RequestPriority.CRITICAL, RequestPriority.HIGH]:
        customer_name = getattr(instance.customer, "company_name", "N/A") if instance.customer else "N/A"
        broadcast_dispatcher_event(
            "EMERGENCY_REQUEST_ALERT",
            {
                "request_id": str(instance.id),
                "request_number": instance.request_number,
                "title": instance.title,
                "customer": customer_name,
                "priority": instance.priority,
                "sla_response_due_at": (
                    instance.sla_response_due_at.isoformat()
                    if instance.sla_response_due_at
                    else None
                ),
            },
        )
