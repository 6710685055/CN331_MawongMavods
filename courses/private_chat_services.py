from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from notifications.services import send_notification

from .models import (
    Enrollment,
    PrivateChat,
    PrivateChatMessage,
    PrivateChatSuspension,
    PrivateMessageReport,
    UserBlock,
)

PRIVATE_CHAT_ROLES = (Enrollment.Role.STUDENT, Enrollment.Role.TA)
MAX_PRIVATE_MESSAGE_LENGTH = 4000
MAX_REPORT_DETAILS_LENGTH = 1000
# Messages per page: the chat page shows the newest page, older pages load on demand.
PRIVATE_CHAT_PAGE_SIZE = 100
# Neighbouring messages copied on each side of a reported one, for the moderator only.
REPORT_CONTEXT_SIZE = 3


class PrivateChatError(Exception):
    """Raised with a user-facing Thai message."""


def is_chat_eligible(user, course):
    """UC8 actors are approved students and TAs of the course."""
    if not user or not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    return Enrollment.objects.filter(
        user=user,
        course=course,
        role__in=PRIVATE_CHAT_ROLES,
    ).exists()


def chat_classmates(user, course):
    """Users the given user may start a private chat with in this course."""
    return (
        User.objects.filter(
            is_active=True,
            enrollments__course=course,
            enrollments__role__in=PRIVATE_CHAT_ROLES,
        )
        .exclude(pk=user.pk)
        .distinct()
        .order_by("first_name", "last_name", "email")
    )


def can_access_chat(user, chat):
    """Participants may read a room only while both are still enrolled in its course."""
    return (
        chat.has_participant(user)
        and is_chat_eligible(chat.user_low, chat.course)
        and is_chat_eligible(chat.user_high, chat.course)
    )


def is_blocked_between(user, other):
    return UserBlock.objects.filter(
        Q(blocker=user, blocked=other) | Q(blocker=other, blocked=user)
    ).exists()


def active_suspension(user, counterpart, now=None):
    """The moderation suspension stopping `user` from messaging `counterpart`, if any.

    Read from the database on every check; expiry is just `ends_at` passing.
    """
    now = now or timezone.now()
    return (
        PrivateChatSuspension.objects.filter(
            user=user,
            counterpart=counterpart,
            lifted_at__isnull=True,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("-ends_at")
        .first()
    )


def format_local(value):
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")


def suspension_message(suspension):
    return f"คุณถูกระงับการส่งข้อความในแชทนี้จนถึง {format_local(suspension.ends_at)} (ยังอ่านประวัติได้)"


def block_state_for(chat, user):
    """Current block and suspension status from the database, as seen by one participant."""
    other = chat.other_participant(user)
    blocked_by_me = UserBlock.objects.filter(blocker=user, blocked=other).exists()
    blocked_by_other = UserBlock.objects.filter(blocker=other, blocked=user).exists()
    suspension = active_suspension(user, other)
    if blocked_by_me:
        notice = "คุณบล็อกผู้ใช้นี้อยู่ ทั้งสองฝ่ายจะส่งข้อความถึงกันไม่ได้"
    elif blocked_by_other:
        notice = "ไม่สามารถส่งข้อความในห้องนี้ได้"
    elif suspension:
        notice = suspension_message(suspension)
    else:
        notice = ""
    return {
        "blocked_by_me": blocked_by_me,
        "blocked_by_other": blocked_by_other,
        "suspended_until": format_local(suspension.ends_at) if suspension else None,
        "can_send": not (blocked_by_me or blocked_by_other or suspension),
        "send_notice": notice,
    }


def visible_messages(chat):
    """Messages participants may see: hidden (confirmed-report) messages stay as evidence only."""
    return chat.messages.filter(hidden_at__isnull=True)


def message_page(chat, *, before=None, limit=PRIVATE_CHAT_PAGE_SIZE):
    """Return (messages oldest-first, has_more) for the page just older than `before`.

    The cursor is (created_at, id) so the order is total even when two messages share
    a timestamp, and messages that arrive later never shift older pages.
    """
    queryset = visible_messages(chat).select_related("sender", "chat")
    if before is not None:
        queryset = queryset.filter(
            Q(created_at__lt=before.created_at)
            | Q(created_at=before.created_at, id__lt=before.id)
        )
    page = list(queryset.order_by("-created_at", "-id")[: limit + 1])
    has_more = len(page) > limit
    return list(reversed(page[:limit])), has_more


def get_or_create_private_chat(*, course, user, other):
    if other.pk == user.pk:
        raise PrivateChatError("ไม่สามารถเปิดแชทส่วนตัวกับตัวเองได้")
    if not is_chat_eligible(user, course):
        raise PrivateChatError(
            "แชทส่วนตัวเปิดให้เฉพาะนักศึกษาและ TA ที่ได้รับอนุมัติในรายวิชานี้"
        )
    if not is_chat_eligible(other, course):
        raise PrivateChatError("ผู้ใช้นี้ไม่ได้ลงทะเบียนอยู่ในรายวิชาเดียวกับคุณ")

    user_low, user_high = sorted((user, other), key=lambda member: member.pk)
    try:
        with transaction.atomic():
            chat, created = PrivateChat.objects.get_or_create(
                course=course,
                user_low=user_low,
                user_high=user_high,
            )
    except IntegrityError:
        # Another request created the same room between our lookup and insert.
        chat = PrivateChat.objects.get(
            course=course, user_low=user_low, user_high=user_high
        )
        created = False
    return chat, created


@transaction.atomic
def post_private_message(*, chat, sender, body):
    if not can_access_chat(sender, chat):
        raise PrivateChatError("คุณไม่มีสิทธิ์ส่งข้อความในห้องแชทนี้")
    recipient = chat.other_participant(sender)
    if is_blocked_between(sender, recipient):
        raise PrivateChatError(
            "ไม่สามารถส่งข้อความได้ เนื่องจากมีการบล็อกระหว่างคุณกับผู้ใช้นี้"
        )
    suspension = active_suspension(sender, recipient)
    if suspension:
        raise PrivateChatError(suspension_message(suspension))
    if not isinstance(body, str):
        raise PrivateChatError("รูปแบบข้อความไม่ถูกต้อง")
    body = body.strip()
    if not body:
        raise PrivateChatError("กรุณาพิมพ์ข้อความก่อนส่ง")
    if len(body) > MAX_PRIVATE_MESSAGE_LENGTH:
        raise PrivateChatError("ข้อความต้องมีความยาวไม่เกิน 4,000 ตัวอักษร")

    message = PrivateChatMessage.objects.create(chat=chat, sender=sender, body=body)
    send_notification(
        recipient=recipient,
        actor=sender,
        title="ข้อความส่วนตัวใหม่",
        message=f"{sender.full_name} ส่งข้อความส่วนตัวถึงคุณในวิชา {chat.course.code}",
        notification_type=Notification.Type.PRIVATE_CHAT_MESSAGE,
        target_url=reverse("courses:private_chat", args=[chat.course_id, chat.id]),
    )
    return message


def block_user(*, chat, user):
    if not chat.has_participant(user):
        raise PrivateChatError("คุณไม่มีสิทธิ์จัดการห้องแชทนี้")
    other = chat.other_participant(user)
    UserBlock.objects.get_or_create(blocker=user, blocked=other)
    return other


def unblock_user(*, chat, user):
    if not chat.has_participant(user):
        raise PrivateChatError("คุณไม่มีสิทธิ์จัดการห้องแชทนี้")
    other = chat.other_participant(user)
    UserBlock.objects.filter(blocker=user, blocked=other).delete()
    return other


def report_message(*, message, reporter, reason, details=""):
    chat = message.chat
    if not can_access_chat(reporter, chat):
        raise PrivateChatError("คุณไม่มีสิทธิ์รายงานข้อความนี้")
    if message.sender_id == reporter.pk:
        raise PrivateChatError("ไม่สามารถรายงานข้อความของตัวเองได้")
    if message.hidden_at is not None:
        raise PrivateChatError("ข้อความนี้ถูกซ่อนโดยผู้ดูแลระบบแล้ว")
    if reason not in PrivateMessageReport.Reason.values:
        raise PrivateChatError("กรุณาเลือกเหตุผลในการรายงาน")
    details = (details or "").strip() if isinstance(details, str) else ""
    if len(details) > MAX_REPORT_DETAILS_LENGTH:
        raise PrivateChatError("รายละเอียดต้องมีความยาวไม่เกิน 1,000 ตัวอักษร")

    try:
        with transaction.atomic():
            return PrivateMessageReport.objects.create(
                message=message,
                reporter=reporter,
                reported_user=message.sender,
                course=chat.course,
                reason=reason,
                details=details,
                message_body=message.body,
                message_sent_at=message.created_at,
                context_snapshot=report_context(message),
            )
    except IntegrityError as error:
        raise PrivateChatError("คุณรายงานข้อความนี้ไปแล้ว") from error


def report_context(message, size=REPORT_CONTEXT_SIZE):
    """Copy up to `size` messages on each side of the reported one for the moderator."""
    chat_messages = message.chat.messages.select_related("sender")
    before = chat_messages.filter(
        Q(created_at__lt=message.created_at)
        | Q(created_at=message.created_at, id__lt=message.id)
    ).order_by("-created_at", "-id")[:size]
    after = chat_messages.filter(
        Q(created_at__gt=message.created_at)
        | Q(created_at=message.created_at, id__gt=message.id)
    ).order_by("created_at", "id")[:size]
    return [
        {
            "id": item.id,
            "sender_id": item.sender_id,
            "sender_name": item.sender.full_name,
            "body": item.body,
            "sent_at": item.created_at.isoformat(),
            "reported": item.id == message.id,
        }
        for item in [*reversed(before), message, *after]
    ]


def serialize_private_message(message, *, reported=False):
    chat = message.chat
    return {
        "reported": reported,
        "id": message.id,
        "sender_id": message.sender_id,
        "sender_name": message.sender.full_name,
        "body": message.body,
        "created_at": timezone.localtime(message.created_at).strftime("%d/%m/%Y %H:%M"),
        "report_url": reverse(
            "courses:report_private_message",
            args=[chat.course_id, chat.id, message.id],
        ),
    }
