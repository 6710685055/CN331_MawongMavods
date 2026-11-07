from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.shortcuts import get_object_or_404

from .group_services import GroupError, post_chat_message, serialize_chat_message
from .models import PrivateChat, TeamChat, TeamMembership
from .private_chat_services import (
    PrivateChatError,
    block_state_for,
    can_access_chat,
    post_private_message,
    serialize_private_message,
)


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
            await self.send_json(
                {"type": "error", "message": "รูปแบบข้อความไม่ถูกต้อง"}
            )
            return
        if content.get("type") != "message.send":
            await self.send_json(
                {"type": "error", "message": "รูปแบบข้อความไม่ถูกต้อง"}
            )
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

    async def team_member_removed(self, event):
        if event["user_id"] == self.scope["user"].id or not await self.is_member(
            self.scope["user"].id
        ):
            await self.close(code=4403)

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


class PrivateChatConsumer(AsyncJsonWebsocketConsumer):
    """UC8: realtime delivery for a private room; access is re-checked on every event."""

    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return

        self.course_id = self.scope["url_route"]["kwargs"]["course_id"]
        self.chat_id = self.scope["url_route"]["kwargs"]["chat_id"]
        if not await self.has_access():
            await self.close(code=4403)
            return

        self.group_name = f"private_chat_{self.chat_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        # Sent on every (re)connect so a page that missed events while offline catches up.
        await self.send_block_state()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("type") != "message.send":
            await self.send_json(
                {"type": "error", "message": "รูปแบบข้อความไม่ถูกต้อง"}
            )
            return

        try:
            message = await self.create_message(content.get("body", ""))
        except PrivateChatError as error:
            await self.send_json({"type": "error", "message": str(error)})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {"type": "chat.message", "message": message},
        )

    async def chat_message(self, event):
        if not await self.has_access():
            await self.close(code=4403)
            return
        await self.send_json({"type": "message.new", "message": event["message"]})

    async def chat_block_state(self, event):
        if not await self.has_access():
            await self.close(code=4403)
            return
        await self.send_block_state()

    async def chat_message_hidden(self, event):
        if not await self.has_access():
            await self.close(code=4403)
            return
        await self.send_json(
            {"type": "message.hidden", "message_id": event["message_id"]}
        )

    async def send_block_state(self):
        state = await self.get_block_state()
        await self.send_json({"type": "block.state", **state})

    def get_chat(self):
        return (
            PrivateChat.objects.select_related("course", "user_low", "user_high")
            .filter(pk=self.chat_id, course_id=self.course_id)
            .first()
        )

    @database_sync_to_async
    def has_access(self):
        chat = self.get_chat()
        return bool(chat and can_access_chat(self.scope["user"], chat))

    @database_sync_to_async
    def get_block_state(self):
        return block_state_for(self.get_chat(), self.scope["user"])

    @database_sync_to_async
    def create_message(self, body):
        chat = self.get_chat()
        if chat is None:
            raise PrivateChatError("ไม่พบห้องแชท")
        message = post_private_message(chat=chat, sender=self.scope["user"], body=body)
        return serialize_private_message(message)
