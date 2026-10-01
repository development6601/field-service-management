import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)

DISPATCHER_BOARD_GROUP = "dispatcher_board"
TECHNICIAN_TRACKING_GROUP = "technician_tracking"


def broadcast_dispatcher_event(event_type: str, data: dict):
    """
    Broadcasts a real-time event to all connected dispatchers and managers on the dispatcher board.
    Safely catches exceptions so database transactions and HTTP requests are never broken.
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.debug("No channel layer configured; skipping broadcast.")
            return

        payload = {
            "type": "board_event",
            "content": {
                "event": event_type,
                "timestamp": timezone.now().isoformat(),
                "data": data,
            },
        }

        async_to_sync(channel_layer.group_send)(DISPATCHER_BOARD_GROUP, payload)
        logger.debug(f"Broadcasted '{event_type}' to '{DISPATCHER_BOARD_GROUP}'.")
    except Exception as e:
        logger.warning(f"Failed to broadcast WebSocket event '{event_type}': {e}")


def broadcast_technician_location(technician_id: str, data: dict):
    """
    Broadcasts live GPS coordinates or status of a technician to the dispatcher board.
    """
    broadcast_dispatcher_event(
        event_type="TECHNICIAN_LOCATION_UPDATED",
        data={
            "technician_id": str(technician_id),
            **data,
        },
    )
