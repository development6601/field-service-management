import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.audit_logs.services import AuditLogService
from apps.billing.models import Invoice, InvoiceStatus, Payment
from apps.service_requests.models import ServiceRequest
from apps.work_orders.models import WorkOrder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Work Orders
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=WorkOrder)
def work_order_pre_save_audit(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = WorkOrder.objects.select_related("assigned_technician").get(pk=instance.pk)
            instance._audit_old_status = old.status
            instance._audit_old_tech = old.assigned_technician
        except WorkOrder.DoesNotExist:
            instance._audit_old_status = None
            instance._audit_old_tech = None
    else:
        instance._audit_old_status = None
        instance._audit_old_tech = None


@receiver(post_save, sender=WorkOrder)
def work_order_post_save_audit(sender, instance, created, **kwargs):
    if created:
        AuditLogService.log_work_order_created(instance)
        return

    old_tech = getattr(instance, "_audit_old_tech", None)
    new_tech = instance.assigned_technician
    if (old_tech != new_tech) and (old_tech or new_tech):
        AuditLogService.log_work_order_assigned(instance, old_tech, new_tech)

    old_status = getattr(instance, "_audit_old_status", None)
    new_status = instance.status
    if old_status and old_status != new_status:
        AuditLogService.log_work_order_status_change(instance, old_status, new_status)


# ---------------------------------------------------------------------------
# 2. Service Requests
# ---------------------------------------------------------------------------
@receiver(post_save, sender=ServiceRequest)
def service_request_post_save_audit(sender, instance, created, **kwargs):
    if created:
        AuditLogService.log_service_request_created(instance)


# ---------------------------------------------------------------------------
# 3. Invoices
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=Invoice)
def invoice_pre_save_audit(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = Invoice.objects.get(pk=instance.pk)
            instance._audit_old_status = old.status
        except Invoice.DoesNotExist:
            instance._audit_old_status = None
    else:
        instance._audit_old_status = None


@receiver(post_save, sender=Invoice)
def invoice_post_save_audit(sender, instance, created, **kwargs):
    old_status = getattr(instance, "_audit_old_status", None)
    if instance.status == InvoiceStatus.ISSUED and (created or old_status != InvoiceStatus.ISSUED):
        AuditLogService.log_invoice_issued(instance)


# ---------------------------------------------------------------------------
# 4. Payments
# ---------------------------------------------------------------------------
@receiver(post_save, sender=Payment)
def payment_post_save_audit(sender, instance, created, **kwargs):
    if created:
        AuditLogService.log_payment_recorded(instance)
