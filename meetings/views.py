from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import MeetingForm
from .models import Meeting
from .permissions import can_access_group, can_access_meeting
from .selectors import upcoming_for_group, upcoming_for_user
from .services import create_meeting, get_group_access, reschedule_meeting


@login_required
def meeting_index(request):
    group_access = get_group_access()
    meetings = upcoming_for_user(request.user, group_access)
    return render(
        request,
        "meetings/index.html",
        {"meetings": meetings, "groups": group_access.groups_for_user(request.user)},
    )


@login_required
def group_meetings(request, group_id):
    group_access = get_group_access()
    group = group_access.get_group_for_user(request.user, group_id)
    if group is None or not can_access_group(request.user, group, group_access):
        return render(request, "meetings/403.html", status=403)
    return render(
        request,
        "meetings/group_meetings.html",
        {"group": group, "meetings": upcoming_for_group(group)},
    )


@login_required
@require_http_methods(["GET", "POST"])
def meeting_create(request, group_id):
    group_access = get_group_access()
    group = group_access.get_group_for_user(request.user, group_id)
    if group is None or not can_access_group(request.user, group, group_access):
        return render(request, "meetings/403.html", status=403)

    form = MeetingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        meeting = create_meeting(group=group, actor=request.user, **form.cleaned_data)
        messages.success(request, "บันทึกนัดหมายประชุมแล้ว")
        return redirect("meetings:group", group_id=group_id)
    return render(request, "meetings/meeting_form.html", {"form": form, "group": group, "is_edit": False})


@login_required
@require_http_methods(["GET", "POST"])
def meeting_edit(request, meeting_id):
    group_access = get_group_access()
    meeting = get_object_or_404(Meeting.objects.select_related("group_content_type"), pk=meeting_id)
    if not can_access_meeting(request.user, meeting, group_access):
        return render(request, "meetings/403.html", status=403)

    form = MeetingForm(request.POST or None, instance=meeting)
    if request.method == "POST" and form.is_valid():
        changed = reschedule_meeting(meeting=meeting, actor=request.user, **form.cleaned_data)
        messages.success(request, "อัปเดตนัดหมายและแจ้งสมาชิกแล้ว" if changed else "ไม่มีข้อมูลที่เปลี่ยนแปลง")
        return redirect("meetings:group", group_id=meeting.group_object_id)
    return render(
        request,
        "meetings/meeting_form.html",
        {"form": form, "group": meeting.group, "meeting": meeting, "is_edit": True},
    )
