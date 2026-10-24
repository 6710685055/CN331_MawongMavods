from django.urls import path

from .consumers import TeamChatConsumer

websocket_urlpatterns = [
    path(
        "ws/courses/<int:course_id>/groups/<int:team_id>/chat/",
        TeamChatConsumer.as_asgi(),
    ),
]
