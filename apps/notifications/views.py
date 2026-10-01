from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.notifications.models import Notification
from apps.notifications.serializers import (
    MarkAllReadSerializer,
    NotificationSerializer,
    UnreadCountSerializer,
)


class NotificationViewSet(viewsets.ModelViewSet):
    """
    Authenticated user inbox endpoint.
    Users can inspect alerts, check unread counts, and acknowledge notifications.
    Strictly isolated: users can never see or modify other users' notifications.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        """Returns only notifications belonging to the logged-in user."""
        if not self.request.user or not self.request.user.is_authenticated:
            return Notification.objects.none()

        qs = Notification.objects.filter(recipient=self.request.user).order_by("-created_at")

        is_read_param = self.request.query_params.get("is_read")
        if is_read_param is not None:
            if is_read_param.lower() in ["true", "1"]:
                qs = qs.filter(is_read=True)
            elif is_read_param.lower() in ["false", "0"]:
                qs = qs.filter(is_read=False)

        type_param = self.request.query_params.get("type")
        if type_param:
            qs = qs.filter(notification_type__iexact=type_param)

        priority_param = self.request.query_params.get("priority")
        if priority_param:
            qs = qs.filter(priority__iexact=priority_param)

        return qs

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        """
        Marks a specific notification as read.
        """
        notification = self.get_object()
        notification.mark_as_read()
        return Response(NotificationSerializer(notification).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        """
        Marks all unread notifications for the current user as read in bulk.
        """
        unread_qs = Notification.objects.filter(recipient=request.user, is_read=False)
        count = unread_qs.count()
        now = timezone.now()
        unread_qs.update(is_read=True, read_at=now, updated_at=now)

        data = {
            "marked_count": count,
            "detail": f"Successfully marked {count} notification(s) as read.",
        }
        return Response(MarkAllReadSerializer(data).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """
        Returns the number of unread notifications for the active user (for badge UI).
        """
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response(UnreadCountSerializer({"unread_count": count}).data, status=status.HTTP_200_OK)
