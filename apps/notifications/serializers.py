from rest_framework import serializers
from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """
    Standard read serializer for notifications in user inbox feeds.
    """

    recipient_email = serializers.EmailField(source="recipient.email", read_only=True)
    recipient_name = serializers.CharField(source="recipient.get_full_name", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "recipient",
            "recipient_email",
            "recipient_name",
            "title",
            "message",
            "notification_type",
            "priority",
            "is_read",
            "read_at",
            "related_entity_type",
            "related_entity_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class UnreadCountSerializer(serializers.Serializer):
    """
    Count response for app header/notification badge counter.
    """

    unread_count = serializers.IntegerField()


class MarkAllReadSerializer(serializers.Serializer):
    """
    Response format when marking all user notifications as read.
    """

    marked_count = serializers.IntegerField()
    detail = serializers.CharField()
