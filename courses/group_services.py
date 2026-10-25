from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from notifications.services import send_notification

from .models import (
    MAX_TEAM_MEMBERS,
    Enrollment,
    Team,
    TeamChat,
    TeamChatMessage,
    TeamInvitation,
    TeamMembership,
)


class GroupError(Exception):
    """Raised with a user-facing Thai message."""


def _require_enrolled_student(user, course):
    enrolled = Enrollment.objects.filter(
        user=user,
        course=course,
        role=Enrollment.Role.STUDENT,
    ).exists()
    if user.role != User.Role.STUDENT or not enrolled:
        raise GroupError("เฉพาะนักศึกษาที่ได้รับอนุมัติให้ลงทะเบียนวิชานี้เท่านั้น")


@transaction.atomic
def create_team(*, user, course, name):
    _require_enrolled_student(user, course)
    if TeamMembership.objects.filter(user=user, course=course).exists():
        raise GroupError("คุณมีกลุ่มในรายวิชานี้แล้ว")

    name = name.strip()
    if not name:
        raise GroupError("กรุณาระบุชื่อกลุ่ม")
    if len(name) > 100:
        raise GroupError("ชื่อกลุ่มต้องมีความยาวไม่เกิน 100 ตัวอักษร")

    try:
        team = Team.objects.create(course=course, name=name, created_by=user)
        TeamMembership.objects.create(team=team, course=course, user=user)
    except IntegrityError as error:
        raise GroupError("คุณมีกลุ่มในรายวิชานี้แล้ว") from error
    return team


@transaction.atomic
def invite_students(*, inviter, team, invitee_ids):
    team = Team.objects.select_for_update().get(pk=team.pk)
    if not TeamMembership.objects.filter(team=team, user=inviter).exists():
        raise GroupError("คุณต้องเป็นสมาชิกกลุ่มก่อนจึงจะเชิญเพื่อนได้")

    try:
        invitee_ids = list(dict.fromkeys(int(invitee_id) for invitee_id in invitee_ids))
    except (TypeError, ValueError) as error:
        raise GroupError("รายชื่อเพื่อนที่เลือกไม่ถูกต้อง") from error
    if not invitee_ids:
        raise GroupError("เลือกเพื่อนที่ต้องการเชิญอย่างน้อยหนึ่งคน")

    candidates = list(
        User.objects.filter(
            id__in=invitee_ids,
            role=User.Role.STUDENT,
            enrollments__course=team.course,
            enrollments__role=Enrollment.Role.STUDENT,
        ).distinct()
    )
    if len(candidates) != len(invitee_ids):
        raise GroupError("เลือกได้เฉพาะนักศึกษาที่ลงทะเบียนวิชานี้และได้รับอนุมัติแล้ว")

    for candidate in candidates:
        if candidate == inviter:
            raise GroupError("ไม่สามารถเชิญตัวเองเข้ากลุ่มได้")
        if TeamMembership.objects.filter(user=candidate, course=team.course).exists():
            raise GroupError(f"{candidate.full_name} มีกลุ่มในรายวิชานี้แล้ว")
        if TeamInvitation.objects.filter(
            team=team,
            invitee=candidate,
            status=TeamInvitation.Status.PENDING,
        ).exists():
            raise GroupError(f"คำเชิญถึง {candidate.full_name} ยังรอการตอบรับอยู่")

    pending_count = TeamInvitation.objects.filter(
        team=team,
        status=TeamInvitation.Status.PENDING,
    ).count()
    available_slots = MAX_TEAM_MEMBERS - team.memberships.count() - pending_count
    if len(candidates) > available_slots:
        raise GroupError(f"กลุ่มเชิญสมาชิกเพิ่มได้อีกไม่เกิน {max(0, available_slots)} คน")

    invitations = []
    for candidate in candidates:
        invitation = TeamInvitation.objects.create(
            team=team,
            inviter=inviter,
            invitee=candidate,
        )
        send_notification(
            recipient=candidate,
            actor=inviter,
            title="คำเชิญเข้ากลุ่มทำงาน",
            message=f"{inviter.full_name} เชิญคุณเข้ากลุ่ม {team.name} ในวิชา {team.course.code}",
            notification_type=Notification.Type.TEAM_INVITATION,
            target_url=f"/courses/{team.course_id}/groups/",
        )
        invitations.append(invitation)
    return invitations


@transaction.atomic
def respond_to_invitation(*, invitation_id, user, accept):
    invitation = (
        TeamInvitation.objects.select_for_update()
        .select_related("team", "team__course", "inviter")
        .get(pk=invitation_id, invitee=user)
    )
    if invitation.status != TeamInvitation.Status.PENDING:
        raise GroupError("คำเชิญนี้ได้รับการตอบกลับไปแล้ว")

    team = Team.objects.select_for_update().get(pk=invitation.team_id)
    if not accept:
        invitation.status = TeamInvitation.Status.DECLINED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
        send_notification(
            recipient=invitation.inviter,
            actor=user,
            title="ปฏิเสธคำเชิญเข้ากลุ่ม",
            message=f"{user.full_name} ปฏิเสธคำเชิญเข้ากลุ่ม {team.name}",
            notification_type=Notification.Type.TEAM_INVITATION_RESPONSE,
            target_url=f"/courses/{team.course_id}/groups/",
        )
        return invitation

    _require_enrolled_student(user, team.course)
    existing_membership = TeamMembership.objects.filter(
        user=user,
        course=team.course,
    ).first()
    if existing_membership:
        invitation.status = TeamInvitation.Status.CANCELLED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
        return invitation

    if team.memberships.count() >= MAX_TEAM_MEMBERS:
        invitation.status = TeamInvitation.Status.CANCELLED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
        return invitation

    invitation.status = TeamInvitation.Status.ACCEPTED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    try:
        TeamMembership.objects.create(team=team, course=team.course, user=user)
    except IntegrityError as error:
        raise GroupError("คุณมีกลุ่มในรายวิชานี้แล้ว จึงรับคำเชิญนี้ไม่ได้") from error

    TeamInvitation.objects.filter(
        invitee=user,
        team__course=team.course,
        status=TeamInvitation.Status.PENDING,
    ).exclude(pk=invitation.pk).update(
        status=TeamInvitation.Status.CANCELLED,
        responded_at=timezone.now(),
    )

    if team.memberships.count() >= 2:
        TeamChat.objects.get_or_create(team=team)

    send_notification(
        recipient=invitation.inviter,
        actor=user,
        title="ตอบรับคำเชิญเข้ากลุ่ม",
        message=f"{user.full_name} ตอบรับเข้ากลุ่ม {team.name}",
        notification_type=Notification.Type.TEAM_INVITATION_RESPONSE,
        target_url=f"/courses/{team.course_id}/groups/",
    )
    return invitation


@transaction.atomic
def leave_team(*, team_id, user):
    team = Team.objects.select_for_update().select_related("course").get(pk=team_id)
    membership = (
        TeamMembership.objects.select_for_update()
        .filter(team=team, user=user)
        .first()
    )
    if membership is None:
        raise GroupError("คุณไม่ได้เป็นสมาชิกของกลุ่มนี้")

    team_name = team.name
    course_id = team.course_id
    was_leader = team.created_by_id == user.id
    membership.delete()

    remaining_memberships = list(
        TeamMembership.objects.filter(team=team)
        .select_related("user")
        .order_by("joined_at", "id")
    )
    if not remaining_memberships:
        attachment_names = list(
            TeamChatMessage.objects.filter(chat__team=team)
            .exclude(attachment="")
            .values_list("attachment", flat=True)
        )
        team.delete()
        for attachment_name in attachment_names:
            transaction.on_commit(
                lambda name=attachment_name: default_storage.delete(name)
            )
        return {
            "team_id": team_id,
            "team_name": team_name,
            "course_id": course_id,
            "dissolved": True,
            "was_leader": was_leader,
            "new_leader": None,
        }

    new_leader = None
    if was_leader:
        new_leader = remaining_memberships[0].user
        team.created_by = new_leader
        team.save(update_fields=["created_by"])

    chat_url = reverse("courses:groups", args=[course_id])
    for remaining in remaining_memberships:
        send_notification(
            recipient=remaining.user,
            actor=user,
            title=f"สมาชิกออกจากกลุ่ม {team_name}",
            message=f"{user.full_name} ออกจากกลุ่มทำงาน"
            + (
                f" และ {new_leader.full_name} เป็นหัวหน้ากลุ่มคนใหม่"
                if new_leader
                else ""
            ),
            notification_type=Notification.Type.TEAM_MEMBERSHIP,
            target_url=chat_url,
        )

    return {
        "team_id": team_id,
        "team_name": team_name,
        "course_id": course_id,
        "dissolved": False,
        "was_leader": was_leader,
        "new_leader": new_leader,
    }


@transaction.atomic
def post_chat_message(*, chat, sender, body, attachment=None):
    if not TeamMembership.objects.filter(team=chat.team, user=sender).exists():
        raise GroupError("คุณไม่มีสิทธิ์ส่งข้อความในห้องแชทนี้")
    if not isinstance(body, str):
        raise GroupError("รูปแบบข้อความไม่ถูกต้อง")
    body = body.strip()
    if not body and attachment is None:
        raise GroupError("กรุณาพิมพ์ข้อความหรือแนบไฟล์ก่อนส่ง")
    if len(body) > 4000:
        raise GroupError("ข้อความต้องมีความยาวไม่เกิน 4,000 ตัวอักษร")
    if attachment is not None:
        extension = PurePosixPath(attachment.name).suffix.lower()
        if extension not in settings.TEAM_CHAT_ALLOWED_EXTENSIONS:
            allowed = ", ".join(settings.TEAM_CHAT_ALLOWED_EXTENSIONS)
            raise GroupError(f"ชนิดไฟล์นี้ไม่รองรับ กรุณาใช้ไฟล์: {allowed}")
        if attachment.size > settings.TEAM_CHAT_MAX_FILE_SIZE_BYTES:
            max_size_mb = settings.TEAM_CHAT_MAX_FILE_SIZE_BYTES // (1024 * 1024)
            raise GroupError(f"ไฟล์แนบต้องมีขนาดไม่เกิน {max_size_mb} MB")

    message = TeamChatMessage.objects.create(
        chat=chat,
        sender=sender,
        body=body,
        attachment=attachment,
    )
    for membership in TeamMembership.objects.filter(team=chat.team).exclude(user=sender):
        send_notification(
            recipient=membership.user,
            actor=sender,
            title=f"ข้อความใหม่ในกลุ่ม {chat.team.name}",
            message=f"{sender.full_name} ส่งข้อความในแชทกลุ่ม",
            notification_type=Notification.Type.TEAM_CHAT_MESSAGE,
            target_url=reverse(
                "courses:team_chat",
                args=[chat.team.course_id, chat.team_id],
            ),
        )
    return message


def serialize_chat_message(message):
    return {
        "id": message.id,
        "sender_id": message.sender_id,
        "sender_name": message.sender.full_name,
        "sender_is_leader": message.sender_id == message.chat.team.created_by_id,
        "body": message.body,
        "created_at": timezone.localtime(message.created_at).strftime("%d/%m/%Y %H:%M"),
        "attachment_name": PurePosixPath(message.attachment.name).name
        if message.attachment
        else "",
        "attachment_url": reverse(
            "courses:download_chat_attachment",
            args=[
                message.chat.team.course_id,
                message.chat.team_id,
                message.id,
            ],
        )
        if message.attachment
        else "",
    }
