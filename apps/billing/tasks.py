import logging
from decimal import Decimal
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.audit_logs.models import AuditAction
from apps.audit_logs.services import AuditLogService
from apps.billing.models import Invoice, InvoiceStatus
from apps.notifications.models import NotificationPriority, NotificationType
from apps.notifications.services import NotificationService

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(name="apps.billing.tasks.send_overdue_invoice_reminders")
def send_overdue_invoice_reminders():
    """
    Daily scheduled task identifying overdue customer invoices.
    Sends payment dunning notifications to customer contacts and alerts the finance team.
    """
    today = timezone.localdate()
    overdue_invoices = Invoice.objects.filter(
        status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID],
        due_date__isnull=False,
        due_date__lt=today,
    ).select_related("customer", "customer__user", "work_order")

    overdue_count = overdue_invoices.count()
    total_overdue_amount = Decimal("0.00")
    processed_invoices = []

    if overdue_count > 0:
        finance_staff = User.objects.filter(
            role__in=[UserRole.ADMIN, UserRole.MANAGER],
            is_active=True,
        )

        for inv in overdue_invoices:
            balance = inv.balance_due
            total_overdue_amount += balance
            processed_invoices.append(inv.invoice_number)

            title = f"PAYMENT OVERDUE: Invoice {inv.invoice_number}"
            message = (
                f"Dear {inv.customer.company_name}, payment for Invoice {inv.invoice_number} "
                f"of ₹{balance} was due on {inv.due_date}. Please settle immediately to maintain uninterrupted service."
            )

            # 1. Notify Customer User account (if portal access is provisioned)
            if inv.customer.user:
                NotificationService.send(
                    recipient=inv.customer.user,
                    title=title,
                    message=message,
                    notification_type=NotificationType.INVOICE_GENERATED,
                    priority=NotificationPriority.URGENT,
                    related_entity_type="invoice",
                    related_entity_id=inv.id,
                )

            # 2. Alert Finance Managers
            for staff in finance_staff:
                NotificationService.send(
                    recipient=staff,
                    title=f"Dunning Alert: {inv.invoice_number} Overdue",
                    message=f"Invoice {inv.invoice_number} for customer '{inv.customer.company_name}' is overdue by {(today - inv.due_date).days} days. Outstanding: ₹{balance}.",
                    notification_type=NotificationType.INVOICE_GENERATED,
                    priority=NotificationPriority.NORMAL,
                    related_entity_type="invoice",
                    related_entity_id=inv.id,
                )

            # 3. Record Audit Log
            AuditLogService.record(
                action=AuditAction.GENERAL_ACTION,
                entity_type="invoice",
                entity_id=inv.id,
                entity_repr=inv.invoice_number,
                description=f"Automated overdue payment reminder dispatched. Outstanding balance: ₹{balance}, Due date: {inv.due_date}.",
                changes={
                    "overdue_days": {"old": 0, "new": (today - inv.due_date).days},
                    "balance_due": {"old": None, "new": str(balance)},
                },
            )

    logger.info(
        f"Overdue invoice reminder job finished at {today}. Processed {overdue_count} invoices totaling ₹{total_overdue_amount}."
    )
    return {
        "date": str(today),
        "overdue_count": overdue_count,
        "total_overdue_amount": float(total_overdue_amount),
        "processed_invoices": processed_invoices,
    }
