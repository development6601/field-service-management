from django.urls import re_path

from apps.scheduling.consumers import (
    DispatcherBoardConsumer,
    TechnicianTrackingConsumer,
)

websocket_urlpatterns = [
    re_path(r"^ws/dispatcher/board/$", DispatcherBoardConsumer.as_asgi()),
    re_path(r"^ws/technician/tracking/$", TechnicianTrackingConsumer.as_asgi()),
]
