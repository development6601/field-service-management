import logging
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.notifications.models import (
    Notification,
    NotificationPriority,
    NotificationType,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class NotificationService:
    """
    Central business domain service managing notification event dispatches,
    audience resolution, formatting, and database persistence.
    """

    @staticmethod
    def send(
        *,
        recipient,
        title: str,
        message: str,
        notification_type: str = NotificationType.GENERAL,
        priority: str = NotificationPriority.NORMAL,
        related_entity_type: str = "",
        related_entity_id=None,
    ) -> Notification:
        """
        Creates and stores an in-app notification record for the specified user.
        Safely catches exceptions so notification glitches never crash core business operations.
        """
        if not recipient:
            return None

        try:
            notification = Notification.objects.create(
                recipient=recipient,
                title=title,
                message=message,
                notification_type=notification_type,
                priority=priority,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
            )
            return notification
        except Exception as e:
            logger.error(
                f"Failed to generate notification for user {getattr(recipient, 'id', None)}: {e}",
                exc_info=True,
            )
            return None

    @classmethod
    def notify_work_order_assigned(cls, work_order):
        """Notifies the assigned technician when a work order is assigned to them."""
        technician = work_order.assigned_technician
        if not technician:
            return None

        location_name = (
            work_order.service_location.location_name
            if work_order.service_location
            else "Customer Location"
        )
        return cls.send(
            recipient=technician,
            title=f"New Job Assigned: {work_order.work_order_number}",
            message=f"You have been assigned to work order '{work_order.title}' at {location_name}.",
            notification_type=NotificationType.WORK_ORDER_ASSIGNED,
            priority=NotificationPriority.HIGH,
            related_entity_type="work_order",
            related_entity_id=work_order.id,
        )

    @classmethod
    def notify_work_order_status_change(cls, work_order, old_status: str = None):
        """Notifies customer of key lifecycle updates (TRAVELING, ARRIVED, COMPLETED)."""
        customer_user = getattr(work_order.customer, "user", None)
        if not customer_user:
            return None

        from apps.work_orders.models import WorkOrderStatus

        location_name = (
            work_order.service_location.location_name
            if work_order.service_location
            else "your site"
        )
        tech_name = (
            work_order.assigned_technician.get_full_name()
            if work_order.assigned_technician
            else "Technician"
        )

        if work_order.status == WorkOrderStatus.TRAVELING:
            return cls.send(
                recipient=customer_user,
                title=f"Technician On The Way: {work_order.work_order_number}",
                message=f"{tech_name} has started traveling towards {location_name}.",
                notification_type=NotificationType.WORK_ORDER_STATUS_CHANGED,
                priority=NotificationPriority.HIGH,
                related_entity_type="work_order",
                related_entity_id=work_order.id,
            )
        elif work_order.status == WorkOrderStatus.ARRIVED:
            return cls.send(
                recipient=customer_user,
                title=f"Technician Arrived On-Site: {work_order.work_order_number}",
                message=f"{tech_name} has arrived at {location_name} and will begin service shortly.",
                notification_type=NotificationType.WORK_ORDER_STATUS_CHANGED,
                priority=NotificationPriority.HIGH,
                related_entity_type="work_order",
                related_entity_id=work_order.id,
            )
        elif work_order.status == WorkOrderStatus.COMPLETED:
            return cls.send(
                recipient=customer_user,
                title=f"Service Completed: {work_order.work_order_number}",
                message=f"Work order '{work_order.title}' has been successfully completed. Please share your rating & feedback.",
                notification_type=NotificationType.WORK_ORDER_COMPLETED,
                priority=NotificationPriority.NORMAL,
                related_entity_type="work_order",
                related_entity_id=work_order.id,
            )

        return None

    @classmethod
    def notify_service_request_created(cls, service_request):
        """
        Notifies customer of request receipt and alerts operational dispatchers.
        """
        notifications = []
        # 1. Customer confirmation
        customer_user = getattr(service_request.customer, "user", None)
        if customer_user:
            n_cust = cls.send(
                recipient=customer_user,
                title=f"Request Received: {service_request.request_number}",
                message=f"Your service request '{service_request.title}' has been logged and is under dispatcher review.",
                notification_type=NotificationType.SERVICE_REQUEST_CREATED,
                priority=NotificationPriority.NORMAL,
                related_entity_type="service_request",
                related_entity_id=service_request.id,
            )
            if n_cust:
                notifications.append(n_cust)

        # 2. Dispatchers / Admin alert
        dispatchers = User.objects.filter(
            role__in=[UserRole.DISPATCHER, UserRole.ADMIN, UserRole.MANAGER],
            is_active=True,
        )
        priority = (
            NotificationPriority.URGENT
            if service_request.priority in ["HIGH", "CRITICAL"]
            else NotificationPriority.NORMAL
        )
        for staff in dispatchers:
            n_staff = cls.send(
                recipient=staff,
                title=f"New Service Request: {service_request.request_number}",
                message=f"Customer '{service_request.customer.company_name}' raised '{service_request.title}' ({service_request.priority} priority).",
                notification_type=NotificationType.SERVICE_REQUEST_CREATED,
                priority=priority,
                related_entity_type="service_request",
                related_entity_id=service_request.id,
            )
            if n_staff:
                notifications.append(n_staff)

        return notifications

    @classmethod
    def notify_invoice_generated(cls, invoice):
        """Notifies customer when a new bill/invoice is issued."""
        customer_user = getattr(invoice.customer, "user", None)
        if not customer_user:
            return None

        wo_title = invoice.work_order.title if invoice.work_order else "Completed Service"
        return cls.send(
            recipient=customer_user,
            title=f"New Invoice Issued: {invoice.invoice_number}",
            message=f"Invoice {invoice.invoice_number} of ₹{invoice.total_amount} has been issued for '{wo_title}'.",
            notification_type=NotificationType.INVOICE_GENERATED,
            priority=NotificationPriority.HIGH,
            related_entity_type="invoice",
            related_entity_id=invoice.id,
        )

    @classmethod
    def notify_payment_received(cls, payment):
        """Notifies customer when payment is successfully recorded."""
        invoice = payment.invoice
        customer_user = getattr(invoice.customer, "user", None)
        if not customer_user:
            return None

        return cls.send(
            recipient=customer_user,
            title=f"Payment Received: {payment.payment_number}",
            message=f"Your payment of ₹{payment.amount} for invoice {invoice.invoice_number} was successfully recorded via {payment.payment_method}.",
            notification_type=NotificationType.PAYMENT_RECEIVED,
            priority=NotificationPriority.NORMAL,
            related_entity_type="payment",
            related_entity_id=payment.id,
        )

    @classmethod
    def notify_low_stock(cls, stock_item):
        """Notifies dispatchers and managers when stock falls to or below reorder threshold."""
        staff_users = User.objects.filter(
            role__in=[UserRole.DISPATCHER, UserRole.ADMIN, UserRole.MANAGER],
            is_active=True,
        )
        location_desc = (
            stock_item.warehouse.name
            if stock_item.warehouse
            else (
                f"{stock_item.technician.get_full_name()}'s Van"
                if stock_item.technician
                else "Storage Location"
            )
        )
        notifications = []
        for staff in staff_users:
            n = cls.send(
                recipient=staff,
                title=f"Low Stock Alert: {stock_item.part.name}",
                message=(
                    f"Stock for '{stock_item.part.name}' at {location_desc} "
                    f"is down to {stock_item.quantity_on_hand} {stock_item.part.unit_of_measure} "
                    f"(Reorder threshold: {stock_item.part.reorder_threshold})."
                ),
                notification_type=NotificationType.LOW_STOCK_ALERT,
                priority=NotificationPriority.URGENT,
                related_entity_type="stock_item",
                related_entity_id=stock_item.id,
            )
            if n:
                notifications.append(n)
        return notifications
