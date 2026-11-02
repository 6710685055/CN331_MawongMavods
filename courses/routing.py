from django.urls import path

from .consumers import PrivateChatConsumer, TeamChatConsumer

websocket_urlpatterns = [
    path(
        "ws/courses/<int:course_id>/groups/<int:team_id>/chat/",
        TeamChatConsumer.as_asgi(),
    ),
    path(
        "ws/courses/<int:course_id>/chats/<int:chat_id>/",
        PrivateChatConsumer.as_asgi(),
    ),
]
