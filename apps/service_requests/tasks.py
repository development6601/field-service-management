import logging
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.audit_logs.models import AuditAction
from apps.audit_logs.services import AuditLogService
from apps.notifications.models import NotificationPriority, NotificationType
from apps.notifications.services import NotificationService
from apps.service_requests.models import RequestStatus, ServiceRequest

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(name="apps.service_requests.tasks.check_and_escalate_sla_breaches")
def check_and_escalate_sla_breaches():
    """
    Periodic task scanning for resolution and response SLA violations.
    Dispatches automated escalation notifications to managers and dispatchers.
    """
    now = timezone.now()
    active_statuses = [
        RequestStatus.NEW,
        RequestStatus.REVIEWED,
        RequestStatus.SCHEDULED,
        RequestStatus.ASSIGNED,
        RequestStatus.IN_PROGRESS,
    ]

    breached_requests = ServiceRequest.objects.filter(
        status__in=active_statuses,
        sla_resolution_due_at__isnull=False,
        sla_resolution_due_at__lt=now,
    ).select_related("customer", "service_type")

    breached_count = breached_requests.count()
    escalated_ids = []

    if breached_count > 0:
        dispatchers_and_managers = User.objects.filter(
            role__in=[UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER],
            is_active=True,
        )

        for sr in breached_requests:
            escalated_ids.append(str(sr.id))
            title = f"CRITICAL: SLA Breached on {sr.request_number}"
            message = (
                f"Service Request {sr.request_number} for customer '{sr.customer.company_name}' "
                f"has breached its resolution target ({sr.sla_resolution_due_at.strftime('%Y-%m-%d %H:%M')}). "
                f"Immediate dispatcher intervention required."
            )

            # Send in-app notification to all supervisory staff
            for staff in dispatchers_and_managers:
                NotificationService.send(
                    recipient=staff,
                    title=title,
                    message=message,
                    notification_type=NotificationType.GENERAL,
                    priority=NotificationPriority.URGENT,
                    related_entity_type="service_request",
                    related_entity_id=sr.id,
                )

            # Broadcast real-time alert to live Dispatcher Board
            try:
                from apps.scheduling.broadcaster import broadcast_dispatcher_event
                broadcast_dispatcher_event(
                    "SLA_BREACH_ALERT",
                    {
                        "request_id": str(sr.id),
                        "request_number": sr.request_number,
                        "customer": sr.customer.company_name,
                        "priority": sr.priority,
                        "escalation_level": sr.escalation_level,
                        "resolution_due_at": sr.sla_resolution_due_at.isoformat() if sr.sla_resolution_due_at else None,
                    },
                )
            except Exception:
                pass

            # Record in immutable audit ledger
            AuditLogService.record(
                action=AuditAction.GENERAL_ACTION,
                entity_type="service_request",
                entity_id=sr.id,
                entity_repr=sr.request_number,
                description=f"Automated SLA breach escalation triggered. Target deadline {sr.sla_resolution_due_at} was exceeded.",
                changes={
                    "sla_status": {"old": "ACTIVE", "new": "BREACHED"},
                    "breached_at": {"old": None, "new": str(now)},
                },
            )

    logger.info(
        f"SLA Breach check completed at {now}. Processed {breached_count} breached tickets."
    )
    return {
        "timestamp": str(now),
        "breached_count": breached_count,
        "escalated_ids": escalated_ids,
    }
