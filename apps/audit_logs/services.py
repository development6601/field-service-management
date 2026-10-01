import logging
from apps.audit_logs.middleware import get_client_ip, get_current_request, get_current_user, get_user_agent
from apps.audit_logs.models import AuditAction, AuditLog

logger = logging.getLogger(__name__)


class AuditLogService:
    """
    Core domain service orchestrating system event logging, diff generation,
    actor resolution, and immutable audit persistence.
    """

    @classmethod
    def record(
        cls,
        *,
        action: str,
        entity_type: str,
        entity_id,
        entity_repr: str = "",
        changes: dict = None,
        description: str = "",
        actor=None,
        request=None,
    ) -> AuditLog:
        """
        Creates and stores an immutable audit log record.
        Safely catches exceptions so audit glitches never break core business transactions.
        """
        req = request or get_current_request()
        effective_actor = actor or get_current_user()

        actor_email = effective_actor.email if effective_actor else "system@fsm.local"
        actor_role = getattr(effective_actor, "role", "SYSTEM") if effective_actor else "SYSTEM"
        ip_addr = get_client_ip(req)
        user_agent_str = get_user_agent(req)

        try:
            log_entry = AuditLog.objects.create(
                actor=effective_actor if getattr(effective_actor, "is_authenticated", False) else None,
                actor_email=actor_email,
                actor_role=actor_role,
                action=action,
                description=description or f"{action} on {entity_type} {entity_repr}",
                entity_type=entity_type,
                entity_id=entity_id,
                entity_repr=entity_repr or str(entity_id),
                changes=changes or {},
                ip_address=ip_addr,
                user_agent=user_agent_str,
            )
            return log_entry
        except Exception as e:
            logger.error(f"Failed to record audit log for {action} on {entity_type}:{entity_id}: {e}", exc_info=True)
            return None

    @classmethod
    def log_work_order_created(cls, work_order, actor=None):
        return cls.record(
            action=AuditAction.WORK_ORDER_CREATED,
            entity_type="work_order",
            entity_id=work_order.id,
            entity_repr=work_order.work_order_number,
            description=f"Work Order {work_order.work_order_number} created with title '{work_order.title}'.",
            changes={
                "status": {"old": None, "new": work_order.status},
                "priority": {"old": None, "new": work_order.priority},
                "assigned_technician": {
                    "old": None,
                    "new": work_order.assigned_technician.get_full_name() if work_order.assigned_technician else None,
                },
            },
            actor=actor,
        )

    @classmethod
    def log_work_order_assigned(cls, work_order, old_technician, new_technician, actor=None):
        old_name = old_technician.get_full_name() if old_technician else "Unassigned"
        new_name = new_technician.get_full_name() if new_technician else "Unassigned"
        return cls.record(
            action=AuditAction.WORK_ORDER_ASSIGNED,
            entity_type="work_order",
            entity_id=work_order.id,
            entity_repr=work_order.work_order_number,
            description=f"Technician reassigned from '{old_name}' to '{new_name}'.",
            changes={
                "assigned_technician": {
                    "old": str(old_technician.id) if old_technician else None,
                    "new": str(new_technician.id) if new_technician else None,
                    "old_name": old_name,
                    "new_name": new_name,
                }
            },
            actor=actor,
        )

    @classmethod
    def log_work_order_status_change(cls, work_order, old_status: str, new_status: str, actor=None):
        return cls.record(
            action=AuditAction.WORK_ORDER_STATUS_CHANGED,
            entity_type="work_order",
            entity_id=work_order.id,
            entity_repr=work_order.work_order_number,
            description=f"Work Order status transitioned from '{old_status}' to '{new_status}'.",
            changes={
                "status": {"old": old_status, "new": new_status}
            },
            actor=actor,
        )

    @classmethod
    def log_invoice_issued(cls, invoice, actor=None):
        return cls.record(
            action=AuditAction.INVOICE_ISSUED,
            entity_type="invoice",
            entity_id=invoice.id,
            entity_repr=invoice.invoice_number,
            description=f"Invoice {invoice.invoice_number} issued for amount ₹{invoice.total_amount}.",
            changes={
                "status": {"old": "DRAFT", "new": invoice.status},
                "total_amount": {"old": None, "new": str(invoice.total_amount)},
            },
            actor=actor,
        )

    @classmethod
    def log_payment_recorded(cls, payment, actor=None):
        return cls.record(
            action=AuditAction.PAYMENT_RECORDED,
            entity_type="payment",
            entity_id=payment.id,
            entity_repr=payment.payment_number,
            description=f"Payment {payment.payment_number} of ₹{payment.amount} recorded via {payment.payment_method}.",
            changes={
                "amount": {"old": None, "new": str(payment.amount)},
                "payment_method": {"old": None, "new": payment.payment_method},
                "transaction_reference": {"old": None, "new": payment.transaction_reference},
            },
            actor=actor,
        )

    @classmethod
    def log_service_request_created(cls, service_request, actor=None):
        return cls.record(
            action=AuditAction.SERVICE_REQUEST_CREATED,
            entity_type="service_request",
            entity_id=service_request.id,
            entity_repr=service_request.request_number,
            description=f"Service request {service_request.request_number} raised by '{service_request.customer.company_name}'.",
            changes={
                "priority": {"old": None, "new": service_request.priority},
                "status": {"old": None, "new": service_request.status},
            },
            actor=actor,
        )
