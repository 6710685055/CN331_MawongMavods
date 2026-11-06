from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string

from notifications.models import Notification
from notifications.services import send_notification

from .models import Meeting
from .selectors import group_content_type

# Meeting times in notification text are always shown in Thai time.
MEETING_TIME_ZONE = ZoneInfo("Asia/Bangkok")


def get_group_access():
    adapter_path = getattr(
        settings,
        "MEETINGS_GROUP_ACCESS_ADAPTER",
        "meetings.group_access.TeamAccess",
    )
    return import_string(adapter_path)


def format_meeting_time(value):
    return timezone.localtime(value, MEETING_TIME_ZONE).strftime("%d/%m/%Y %H:%M")


def _group_url(group_id):
    return reverse("meetings:group", args=[group_id])


def _notify_members(group, *, exclude, **notification):
    for recipient in get_group_access().members(group):
        if exclude is not None and recipient.pk == exclude.pk:
            continue
        send_notification(recipient=recipient, **notification)


@transaction.atomic
def create_meeting(*, group, actor, title, meeting_url, starts_at):
    meeting = Meeting.objects.create(
        group_content_type=group_content_type(group),
        group_object_id=group.pk,
        created_by=actor,
        title=title,
        meeting_url=meeting_url,
        starts_at=starts_at,
    )
    # The creator is not told about their own meeting; they get the reminder later.
    _notify_members(
        group,
        exclude=actor,
        actor=actor,
        title="มีนัดหมายประชุมใหม่",
        message=f"{actor.full_name} นัดประชุม {title} เวลา {format_meeting_time(starts_at)}",
        notification_type=Notification.Type.MEETING_CREATED,
        target_url=_group_url(group.pk),
    )
    return meeting


@transaction.atomic
def reschedule_meeting(*, meeting, actor, title, meeting_url, starts_at):
    # ModelForm validation copies submitted values onto its `instance` before
    # this service is called. Reload the persisted row so change detection
    # compares the submitted values with what was actually saved before.
    meeting = Meeting.objects.select_for_update().get(pk=meeting.pk)
    time_changed = meeting.starts_at != starts_at
    changed = any(
        (
            meeting.title != title,
            meeting.meeting_url != meeting_url,
            meeting.starts_at != starts_at,
        )
    )
    if not changed:
        return False

    meeting.title = title
    meeting.meeting_url = meeting_url
    meeting.starts_at = starts_at
    update_fields = ["title", "meeting_url", "starts_at", "updated_at"]
    if time_changed:
        # A new start time gets its own reminder, even if the old one was sent.
        meeting.reminder_sent_at = None
        update_fields.append("reminder_sent_at")
    meeting.save(update_fields=update_fields)

    if time_changed:
        message = f"{title} ถูกเลื่อนเป็นเวลา {format_meeting_time(starts_at)}"
    else:
        message = f"{title} มีการแก้ไขรายละเอียด เวลาเดิม {format_meeting_time(starts_at)}"
    _notify_members(
        meeting.group,
        exclude=actor,
        actor=actor,
        title="มีการเปลี่ยนแปลงนัดหมายประชุม",
        message=message,
        notification_type=Notification.Type.MEETING_UPDATED,
        target_url=_group_url(meeting.group_object_id),
    )
    return True


@transaction.atomic
def send_due_reminders(*, now=None, reminder_minutes=None):
    """Remind every member (creator included) once per start time.

    `reminder_sent_at` records the reminder; rescheduling clears it. Only meetings
    linked to the active adapter's group model are processed.
    """
    now = now or timezone.now()
    reminder_minutes = reminder_minutes or getattr(settings, "MEETING_REMINDER_MINUTES", 15)
    window_end = now + timedelta(minutes=reminder_minutes)
    group_access = get_group_access()
    due = (
        Meeting.objects.select_for_update()
        .filter(
            group_content_type=group_content_type(group_access.model),
            starts_at__gt=now,
            starts_at__lte=window_end,
            reminder_sent_at__isnull=True,
        )
        .order_by("starts_at", "pk")
    )
    sent = 0
    for meeting in due:
        group = meeting.group
        if group is None:
            # The team was dissolved; there is nobody left to remind.
            continue
        _notify_members(
            group,
            exclude=None,
            actor=meeting.created_by,
            title="ใกล้ถึงเวลาประชุมกลุ่ม",
            message=f"{meeting.title} จะเริ่มเวลา {format_meeting_time(meeting.starts_at)}",
            notification_type=Notification.Type.MEETING_REMINDER,
            target_url=_group_url(meeting.group_object_id),
        )
        meeting.reminder_sent_at = now
        meeting.save(update_fields=["reminder_sent_at"])
        sent += 1
    return sent
