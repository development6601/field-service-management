from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.audit_logs.models import AuditLog
from apps.audit_logs.serializers import AuditLogSerializer, AuditLogTimelineSerializer
from apps.core.permissions import IsAdminOrManager


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only endpoint for querying system audit logs and event timelines.
    Only ADMIN and MANAGER roles are permitted to access audit records.
    Modifications, creations, or deletions are strictly prohibited.
    """

    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrManager]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        entity_type = params.get("entity_type")
        if entity_type:
            queryset = queryset.filter(entity_type__iexact=entity_type)

        entity_id = params.get("entity_id")
        if entity_id:
            queryset = queryset.filter(entity_id=entity_id)

        action_name = params.get("action")
        if action_name:
            queryset = queryset.filter(action=action_name)

        actor_id = params.get("actor")
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)

        start_date = params.get("start_date")
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)

        end_date = params.get("end_date")
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="entity_type",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Target entity type: 'work_order', 'service_request', or 'invoice'",
            ),
            OpenApiParameter(
                name="entity_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Target entity UUID",
            ),
        ],
        responses={200: AuditLogTimelineSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="timeline")
    def timeline(self, request):
        """
        Retrieves a chronological event timeline for a specific entity.
        Query parameters:
          - entity_type (required): e.g., 'work_order', 'service_request', 'invoice'
          - entity_id (required): UUID of the target entity
        """
        entity_type = request.query_params.get("entity_type")
        entity_id = request.query_params.get("entity_id")

        if not entity_type or not entity_id:
            return Response(
                {
                    "error": "Both 'entity_type' and 'entity_id' query parameters are required for timeline."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logs = (
            AuditLog.objects.filter(
                entity_type__iexact=entity_type,
                entity_id=entity_id,
            )
            .order_by("created_at")
        )

        serializer = AuditLogTimelineSerializer(logs, many=True)
        return Response(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "total_events": logs.count(),
                "timeline": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
