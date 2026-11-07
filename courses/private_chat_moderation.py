"""UC8 report review: confirm/reject reports, warnings and 24-hour send suspensions.

Every decision is a compare-and-set on the row's status inside a transaction, so a
double submit or two moderators acting at once cannot issue a second penalty.
"""

from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from notifications.services import send_notification

from .models import (
    PrivateChat,
    PrivateChatIncident,
    PrivateChatModerationLog,
    PrivateChatSuspension,
    PrivateMessageReport,
)
from .private_chat_services import PrivateChatError, format_local

REVIEW_PERMISSION = "courses.review_privatemessagereport"
# Confirmed incidents 1..WARNING_LIMIT get a warning; every one after that a suspension.
WARNING_LIMIT = 3
SUSPENSION_DURATION = timedelta(hours=24)
MAX_NOTE_LENGTH = 1000

Status = PrivateMessageReport.Status
LogAction = PrivateChatModerationLog.Action


def can_review(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
        and user.has_perm(REVIEW_PERMISSION)
    )


def _require_reviewer(user):
    if not can_review(user):
        raise PermissionDenied("ไม่มีสิทธิ์พิจารณารายงานข้อความส่วนตัว")


def _clean_note(note, *, required=False, label="หมายเหตุ"):
    note = note.strip() if isinstance(note, str) else ""
    if required and not note:
        raise PrivateChatError(f"กรุณากรอก{label}")
    if len(note) > MAX_NOTE_LENGTH:
        raise PrivateChatError(f"{label}ต้องมีความยาวไม่เกิน 1,000 ตัวอักษร")
    return note


def _broadcast(chat_ids, event):
    """Push an event to open private chat pages once the decision is committed."""
    chat_ids = list(chat_ids)

    def send():
        channel_layer = get_channel_layer()
        for chat_id in chat_ids:
            async_to_sync(channel_layer.group_send)(f"private_chat_{chat_id}", event)

    transaction.on_commit(send)


def _pair_chat_ids(user, other):
    return PrivateChat.objects.filter(
        Q(user_low=user, user_high=other) | Q(user_low=other, user_high=user)
    ).values_list("id", flat=True)


def decide_report(*, report_id, reviewer, decision, note=""):
    """Confirm or reject one pending report and apply the resulting penalty, if any."""
    _require_reviewer(reviewer)
    if decision not in (Status.CONFIRMED, Status.REJECTED):
        raise PrivateChatError("กรุณาเลือกผลการพิจารณา")
    note = _clean_note(note, label="หมายเหตุการตัดสิน")

    with transaction.atomic():
        now = timezone.now()
        claimed = PrivateMessageReport.objects.filter(
            pk=report_id, status=Status.PENDING
        ).update(
            status=decision, reviewed_by=reviewer, reviewed_at=now, review_note=note
        )
        if not claimed:
            raise PrivateChatError("รายงานนี้ได้รับการพิจารณาไปแล้ว")
        report = PrivateMessageReport.objects.select_related(
            "message__chat__course", "message__sender", "reporter", "course"
        ).get(pk=report_id)

        if decision == Status.REJECTED:
            _log(
                LogAction.REPORT_REJECTED,
                reviewer,
                report.reported_user,
                report=report,
                note=note,
            )
            _notify_reporter(report, confirmed=False)
            return report

        message = report.message
        if message is None:
            raise PrivateChatError("ไม่พบข้อความต้นฉบับแล้ว จึงยืนยันรายงานนี้ไม่ได้")
        incident = _get_or_create_incident(message, reviewer, now)
        report.incident = incident
        report.save(update_fields=["incident"])
        _log(
            LogAction.REPORT_CONFIRMED,
            reviewer,
            report.reported_user,
            report=report,
            incident=incident,
            note=note,
        )
        _notify_reporter(report, confirmed=True)
        return report


def _get_or_create_incident(message, reviewer, now):
    """One incident per message; a second confirmed report of it reuses the first."""
    existing = PrivateChatIncident.objects.filter(message=message).first()
    if existing:
        return existing

    offender = message.sender
    # Serialises sequence numbers per sender where row locks exist (PostgreSQL);
    # the unique (offender, sequence) constraint is the backstop everywhere else.
    User.objects.select_for_update().filter(pk=offender.pk).first()
    sequence = PrivateChatIncident.objects.filter(offender=offender).count() + 1
    action = (
        PrivateChatIncident.Action.WARNING
        if sequence <= WARNING_LIMIT
        else PrivateChatIncident.Action.SUSPENSION
    )
    try:
        with transaction.atomic():
            incident = PrivateChatIncident.objects.create(
                message=message,
                offender=offender,
                course=message.chat.course,
                message_body=message.body,
                sequence=sequence,
                action=action,
                confirmed_by=reviewer,
                confirmed_at=now,
            )
    except IntegrityError as error:
        existing = PrivateChatIncident.objects.filter(message=message).first()
        if existing:
            return existing
        raise PrivateChatError(
            "มีการยืนยันรายงานของผู้ใช้นี้พร้อมกัน กรุณาลองอีกครั้ง"
        ) from error

    message.hidden_at = now
    message.save(update_fields=["hidden_at"])
    _broadcast(
        [message.chat_id], {"type": "chat.message_hidden", "message_id": message.id}
    )

    if action == PrivateChatIncident.Action.WARNING:
        _log(LogAction.WARNING_ISSUED, reviewer, offender, incident=incident)
        _notify_offender_warning(incident, message)
    else:
        counterpart = message.chat.other_participant(offender)
        suspension = PrivateChatSuspension.objects.create(
            incident=incident,
            user=offender,
            counterpart=counterpart,
            starts_at=now,
            ends_at=now + SUSPENSION_DURATION,
        )
        _log(
            LogAction.SUSPENDED,
            reviewer,
            offender,
            incident=incident,
            suspension=suspension,
        )
        _notify_offender_suspended(suspension, message)
        _broadcast(_pair_chat_ids(offender, counterpart), {"type": "chat.block_state"})
    return incident


def lift_suspension(*, suspension_id, actor, reason):
    """End an active suspension early; the reason is required for the audit trail."""
    _require_reviewer(actor)
    reason = _clean_note(reason, required=True, label="เหตุผลการยกเลิก")

    with transaction.atomic():
        now = timezone.now()
        lifted = PrivateChatSuspension.objects.filter(
            pk=suspension_id, lifted_at__isnull=True, ends_at__gt=now
        ).update(lifted_at=now, lifted_by=actor, lift_reason=reason)
        if not lifted:
            raise PrivateChatError("การระงับนี้สิ้นสุดหรือถูกยกเลิกไปแล้ว")
        suspension = PrivateChatSuspension.objects.select_related(
            "user", "counterpart"
        ).get(pk=suspension_id)
        _log(
            LogAction.SUSPENSION_LIFTED,
            actor,
            suspension.user,
            suspension=suspension,
            note=reason,
        )
        send_notification(
            recipient=suspension.user,
            title="ยกเลิกการระงับการส่งข้อความส่วนตัว",
            message="ผู้ดูแลระบบยกเลิกการระงับการส่งข้อความส่วนตัวของคุณแล้ว คุณส่งข้อความได้ตามปกติ",
            notification_type=Notification.Type.PRIVATE_CHAT_UNSUSPENDED,
        )
        _broadcast(
            _pair_chat_ids(suspension.user, suspension.counterpart),
            {"type": "chat.block_state"},
        )
        return suspension


def _log(action, actor, target_user, **refs):
    PrivateChatModerationLog.objects.create(
        action=action, actor=actor, target_user=target_user, **refs
    )


def _notify_reporter(report, *, confirmed):
    course_code = report.course.code if report.course else "-"
    if confirmed:
        text = (
            f"ผู้ดูแลระบบยืนยันรายงานข้อความของคุณในวิชา {course_code} แล้ว "
            "ข้อความดังกล่าวถูกซ่อนจากห้องแชท"
        )
    else:
        text = (
            f"ผู้ดูแลระบบตรวจสอบรายงานข้อความของคุณในวิชา {course_code} แล้ว "
            "ไม่พบการละเมิด ข้อความยังแสดงตามปกติ"
        )
    message = report.message
    send_notification(
        recipient=report.reporter,
        title="ผลการพิจารณารายงานข้อความ",
        message=text,
        notification_type=Notification.Type.PRIVATE_REPORT_RESULT,
        target_url=(
            reverse(
                "courses:private_chat", args=[message.chat.course_id, message.chat_id]
            )
            if message
            else ""
        ),
    )


# Notifications to the sender never name the reporter or link to the room.
def _notify_offender_warning(incident, message):
    send_notification(
        recipient=incident.offender,
        title="คำเตือนการใช้แชทส่วนตัว",
        message=(
            f"ข้อความที่คุณส่งในแชทส่วนตัววิชา {message.chat.course.code} "
            f"เมื่อ {format_local(message.created_at)} ถูกผู้ดูแลระบบยืนยันว่าไม่เหมาะสมและถูกซ่อนแล้ว "
            f"นี่คือคำเตือนครั้งที่ {incident.sequence} จาก {WARNING_LIMIT} "
            "หากถูกยืนยันอีก คุณจะถูกระงับการส่งข้อความในแชทที่เกี่ยวข้อง 24 ชั่วโมง"
        ),
        notification_type=Notification.Type.PRIVATE_CHAT_WARNING,
    )


def _notify_offender_suspended(suspension, message):
    send_notification(
        recipient=suspension.user,
        title="ระงับการส่งข้อความส่วนตัว 24 ชั่วโมง",
        message=(
            f"ข้อความที่คุณส่งในแชทส่วนตัววิชา {message.chat.course.code} "
            f"เมื่อ {format_local(message.created_at)} ถูกผู้ดูแลระบบยืนยันว่าไม่เหมาะสมและถูกซ่อนแล้ว "
            "คุณถูกระงับการส่งข้อความในแชทส่วนตัวที่เกี่ยวข้องจนถึง "
            f"{format_local(suspension.ends_at)} ยังอ่านประวัติแชทได้ตามปกติ"
        ),
        notification_type=Notification.Type.PRIVATE_CHAT_SUSPENDED,
    )
