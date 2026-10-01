import logging
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.scheduling.broadcaster import (
    DISPATCHER_BOARD_GROUP,
    TECHNICIAN_TRACKING_GROUP,
    broadcast_dispatcher_event,
)

logger = logging.getLogger(__name__)


class DispatcherBoardConsumer(AsyncJsonWebsocketConsumer):
    """
    Real-time WebSocket consumer for the live Dispatcher Board.
    Broadcasts work order transitions, technician assignments, emergency tickets,
    and SLA breach alerts to online dispatchers without page refresh.
    
    URL: ws/dispatcher/board/
    Permissions: ADMIN, MANAGER, DISPATCHER only
    """

    group_name = DISPATCHER_BOARD_GROUP

    async def connect(self):
        self.user = self.scope.get("user")

        # 1. RBAC Guard: Authenticated and authorized internal roles only
        if not self.user or not self.user.is_authenticated:
            logger.warning("Unauthenticated WebSocket connection attempted on Dispatcher Board.")
            await self.close(code=4003)
            return

        allowed_roles = [UserRole.ADMIN, UserRole.MANAGER, UserRole.DISPATCHER]
        if self.user.role not in allowed_roles:
            logger.warning(
                f"Forbidden WebSocket connection by {self.user.email} (Role: {self.user.role})."
            )
            await self.close(code=4003)
            return

        # 2. Join the shared dispatcher board channel group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # 3. Send initial connection confirmation handshake
        await self.send_json(
            {
                "event": "CONNECTED",
                "room": "dispatcher_board",
                "user": self.user.email,
                "role": self.user.role,
                "timestamp": timezone.now().isoformat(),
                "message": "Connected to real-time Dispatcher Board feed.",
            }
        )
        logger.info(f"Dispatcher {self.user.email} connected to {self.group_name}.")

    async def disconnect(self, close_code):
        # Discard channel from group on disconnect
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WebSocket client disconnected with code: {close_code}")

    async def receive_json(self, content):
        """
        Handles incoming messages from connected dispatchers (e.g. heartbeat ping or query).
        """
        msg_type = content.get("type", "")

        if msg_type == "ping":
            await self.send_json(
                {
                    "event": "PONG",
                    "timestamp": timezone.now().isoformat(),
                }
            )
        else:
            await self.send_json(
                {
                    "event": "ACK",
                    "received_type": msg_type,
                    "timestamp": timezone.now().isoformat(),
                }
            )

    async def board_event(self, event):
        """
        Handler invoked when a group message is broadcasted to 'dispatcher_board'.
        Forwards the event payload as JSON directly to the WebSocket client.
        """
        await self.send_json(event["content"])


class TechnicianTrackingConsumer(AsyncJsonWebsocketConsumer):
    """
    Real-time WebSocket consumer for field technicians to stream GPS coordinates
    and presence availability pings. Automatically updates database and broadcasts
    to the Dispatcher Board.

    URL: ws/technician/tracking/
    Permissions: TECHNICIAN, ADMIN, DISPATCHER
    """

    group_name = TECHNICIAN_TRACKING_GROUP

    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4003)
            return

        allowed_roles = [UserRole.TECHNICIAN, UserRole.ADMIN, UserRole.DISPATCHER]
        if self.user.role not in allowed_roles:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.send_json(
            {
                "event": "CONNECTED",
                "room": "technician_tracking",
                "user": self.user.email,
                "role": self.user.role,
                "timestamp": timezone.now().isoformat(),
            }
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content):
        """
        Accepts location pings from the technician mobile client:
        Payload:
        {
            "type": "location_ping",
            "latitude": 19.0760,
            "longitude": 72.8777,
            "is_available": true
        }
        """
        msg_type = content.get("type", "")

        if msg_type == "location_ping":
            lat = content.get("latitude")
            lon = content.get("longitude")
            is_avail = content.get("is_available")

            profile_data = await self.update_technician_profile(lat, lon, is_avail)

            # Broadcast updated location to all dispatchers
            if self.channel_layer:
                await self.channel_layer.group_send(
                    DISPATCHER_BOARD_GROUP,
                    {
                        "type": "board_event",
                        "content": {
                            "event": "TECHNICIAN_LOCATION_UPDATED",
                            "timestamp": timezone.now().isoformat(),
                            "data": {
                                "technician_id": str(self.user.id),
                                "technician_name": self.user.get_full_name(),
                                "email": self.user.email,
                                "latitude": lat,
                                "longitude": lon,
                                "is_available": is_avail if is_avail is not None else True,
                            },
                        },
                    },
                )

            await self.send_json(
                {
                    "event": "LOCATION_ACK",
                    "status": "RECORDED",
                    "timestamp": timezone.now().isoformat(),
                    "data": profile_data,
                }
            )
        elif msg_type == "ping":
            await self.send_json({"event": "PONG", "timestamp": timezone.now().isoformat()})
        else:
            await self.send_json({"error": "Unknown message type."})

    @database_sync_to_async
    def update_technician_profile(self, lat, lon, is_available):
        """Asynchronously persists technician GPS telemetry in database."""
        try:
            if hasattr(self.user, "technician_profile"):
                profile = self.user.technician_profile
                fields_to_update = ["updated_at"]
                if lat is not None:
                    profile.current_latitude = lat
                    fields_to_update.append("current_latitude")
                if lon is not None:
                    profile.current_longitude = lon
                    fields_to_update.append("current_longitude")
                if is_available is not None:
                    profile.is_available = is_available
                    fields_to_update.append("is_available")
                profile.save(update_fields=fields_to_update)
                return {
                    "technician_id": str(self.user.id),
                    "latitude": float(profile.current_latitude) if profile.current_latitude else None,
                    "longitude": float(profile.current_longitude) if profile.current_longitude else None,
                    "is_available": profile.is_available,
                }
        except Exception as e:
            logger.error(f"Error updating technician location: {e}")
        return None
