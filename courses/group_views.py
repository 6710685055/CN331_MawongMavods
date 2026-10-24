from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User

from .group_services import (
    GroupError,
    create_team,
    invite_students,
    post_chat_message,
    respond_to_invitation,
)
from .models import Course, Enrollment, Team, TeamChat, TeamInvitation, TeamMembership


def _student_enrollment(user, course):
    return Enrollment.objects.filter(
        user=user,
        course=course,
        role=Enrollment.Role.STUDENT,
    ).exists() and user.role == User.Role.STUDENT


@login_required
def group_dashboard(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not _student_enrollment(request.user, course):
        messages.error(request, "ระบบจัดกลุ่มเปิดให้เฉพาะนักศึกษาที่ได้รับอนุมัติในรายวิชานี้")
        return redirect("courses:detail", course_id=course.id)

    memberships = list(
        TeamMembership.objects.filter(course=course).select_related("user", "team")
    )
    membership_by_user = {membership.user_id: membership for membership in memberships}
    students = list(
        Enrollment.objects.filter(course=course, role=Enrollment.Role.STUDENT)
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__email")
    )
    for enrollment in students:
        enrollment.team_membership = membership_by_user.get(enrollment.user_id)

    team_membership = membership_by_user.get(request.user.id)
    team = team_membership.team if team_membership else None
    groups = (
        Team.objects.filter(course=course)
        .prefetch_related("memberships__user")
        .order_by("name", "id")
    )
    pending_invitations = TeamInvitation.objects.filter(
        invitee=request.user,
        team__course=course,
        status=TeamInvitation.Status.PENDING,
    ).select_related("team", "inviter")
    sent_invitations = (
        TeamInvitation.objects.filter(team=team, status=TeamInvitation.Status.PENDING)
        .select_related("invitee")
        if team
        else TeamInvitation.objects.none()
    )
    invited_ids = set(sent_invitations.values_list("invitee_id", flat=True))
    ungrouped_students = [
        enrollment
        for enrollment in students
        if enrollment.team_membership is None and enrollment.user_id != request.user.id
    ]
    chat = TeamChat.objects.filter(team=team).first() if team else None

    return render(
        request,
        "courses/group_dashboard.html",
        {
            "course": course,
            "students": students,
            "groups": groups,
            "team": team,
            "chat": chat,
            "pending_invitations": pending_invitations,
            "sent_invitations": sent_invitations,
            "invited_ids": invited_ids,
            "ungrouped_students": ungrouped_students,
        },
    )


@login_required
@require_POST
def create_course_team(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not _student_enrollment(request.user, course):
        messages.error(request, "ระบบจัดกลุ่มเปิดให้เฉพาะนักศึกษาที่ได้รับอนุมัติในรายวิชานี้")
        return redirect("courses:detail", course_id=course.id)
    try:
        team = create_team(user=request.user, course=course, name=request.POST.get("name", ""))
    except GroupError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"สร้างกลุ่ม {team.name} แล้ว เชิญเพื่อนที่ยังไม่มีกลุ่มได้เลย")
    return redirect("courses:groups", course_id=course.id)


@login_required
@require_POST
def invite_to_team(request, course_id, team_id):
    team = get_object_or_404(Team, pk=team_id, course_id=course_id)
    invitee_ids = request.POST.getlist("invitee_ids")
    try:
        invitations = invite_students(
            inviter=request.user,
            team=team,
            invitee_ids=invitee_ids,
        )
    except GroupError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"ส่งคำเชิญแล้ว {len(invitations)} คน")
    return redirect("courses:groups", course_id=course_id)


@login_required
@require_POST
def respond_to_team_invitation(request, course_id, invitation_id):
    invitation = get_object_or_404(
        TeamInvitation,
        pk=invitation_id,
        invitee=request.user,
        team__course_id=course_id,
    )
    action = request.POST.get("action")
    if action not in {"accept", "decline"}:
        messages.error(request, "ไม่พบการตอบกลับคำเชิญที่ถูกต้อง")
        return redirect("courses:groups", course_id=course_id)
    accept = action == "accept"
    try:
        result = respond_to_invitation(
            invitation_id=invitation.id,
            user=request.user,
            accept=accept,
        )
    except GroupError as error:
        messages.error(request, str(error))
    else:
        if result.status == TeamInvitation.Status.ACCEPTED:
            messages.success(request, f"เข้าร่วมกลุ่ม {result.team.name} แล้ว")
        elif result.status == TeamInvitation.Status.DECLINED:
            messages.info(request, f"ปฏิเสธคำเชิญเข้ากลุ่ม {result.team.name} แล้ว")
        elif result.status == TeamInvitation.Status.CANCELLED:
            messages.info(request, "คำเชิญนี้ใช้ไม่ได้แล้ว เนื่องจากคุณมีกลุ่มแล้วหรือกลุ่มเต็ม")
    return redirect("courses:groups", course_id=course_id)


@login_required
def team_chat(request, course_id, team_id):
    chat = get_object_or_404(
        TeamChat.objects.select_related("team", "team__course"),
        team_id=team_id,
        team__course_id=course_id,
        team__memberships__user=request.user,
    )
    if request.method == "POST":
        try:
            post_chat_message(
                chat=chat,
                sender=request.user,
                body=request.POST.get("body", ""),
            )
        except GroupError as error:
            messages.error(request, str(error))
        return redirect("courses:team_chat", course_id=course_id, team_id=team_id)

    chat_messages = list(
        chat.messages.select_related("sender").order_by("-created_at", "-id")[:100]
    )
    return render(
        request,
        "courses/team_chat.html",
        {
            "chat": chat,
            "team": chat.team,
            "chat_messages": reversed(chat_messages),
        },
    )
