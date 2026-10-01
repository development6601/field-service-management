from rest_framework import serializers
from apps.audit_logs.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for inspecting system audit events and diff snapshots.
    """

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "actor_email",
            "actor_role",
            "action",
            "description",
            "entity_type",
            "entity_id",
            "entity_repr",
            "changes",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        read_only_fields = fields


class AuditLogTimelineSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for rendering visual event timelines.
    """

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "description",
            "actor_email",
            "actor_role",
            "changes",
            "created_at",
        ]
        read_only_fields = fields
