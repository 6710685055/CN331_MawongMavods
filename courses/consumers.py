from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.shortcuts import get_object_or_404

from .group_services import GroupError, post_chat_message, serialize_chat_message
from .models import TeamChat, TeamMembership


class TeamChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return

        self.course_id = self.scope["url_route"]["kwargs"]["course_id"]
        self.team_id = self.scope["url_route"]["kwargs"]["team_id"]
        self.group_name = f"team_chat_{self.team_id}"
        self.chat_id = await self.get_member_chat_id(user.id)
        if self.chat_id is None:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "message": "รูปแบบข้อความไม่ถูกต้อง"})
            return
        if content.get("type") != "message.send":
            await self.send_json({"type": "error", "message": "รูปแบบข้อความไม่ถูกต้อง"})
            return

        try:
            message = await self.create_message(content.get("body", ""))
        except GroupError as error:
            await self.send_json({"type": "error", "message": str(error)})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {"type": "chat.message", "message": message},
        )

    async def chat_message(self, event):
        if not await self.is_member(self.scope["user"].id):
            await self.close(code=4403)
            return
        await self.send_json({"type": "message.new", "message": event["message"]})

    @database_sync_to_async
    def get_member_chat_id(self, user_id):
        chat = (
            TeamChat.objects.filter(
                team_id=self.team_id,
                team__course_id=self.course_id,
                team__memberships__user_id=user_id,
            )
            .values_list("id", flat=True)
            .first()
        )
        return chat

    @database_sync_to_async
    def is_member(self, user_id):
        return TeamMembership.objects.filter(
            team_id=self.team_id,
            course_id=self.course_id,
            user_id=user_id,
        ).exists()

    @database_sync_to_async
    def create_message(self, body):
        chat = get_object_or_404(TeamChat, pk=self.chat_id)
        message = post_chat_message(chat=chat, sender=self.scope["user"], body=body)
        return serialize_chat_message(message)
