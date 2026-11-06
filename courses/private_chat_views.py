from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.models import User

from .models import Course, PrivateChat, PrivateChatMessage, PrivateMessageReport, UserBlock
from .private_chat_services import (
    PrivateChatError,
    block_state_for,
    block_user,
    can_access_chat,
    chat_classmates,
    get_or_create_private_chat,
    is_chat_eligible,
    message_page,
    post_private_message,
    report_message,
    serialize_private_message,
    unblock_user,
    visible_messages,
)

NOT_ELIGIBLE_MESSAGE = "แชทส่วนตัวเปิดให้เฉพาะนักศึกษาและ TA ที่ได้รับอนุมัติในรายวิชานี้"


def _get_accessible_chat(user, course_id, chat_id):
    """Return the room only to its two participants while both are enrolled; 404 otherwise."""
    chat = get_object_or_404(
        PrivateChat.objects.select_related("course", "user_low", "user_high"),
        Q(user_low=user) | Q(user_high=user),
        pk=chat_id,
        course_id=course_id,
    )
    if not can_access_chat(user, chat):
        raise Http404("ไม่พบห้องแชท")
    return chat


def _wants_json(request):
    return request.headers.get("Accept") == "application/json"


def _reported_ids(user, chat_messages):
    return set(
        PrivateMessageReport.objects.filter(
            reporter=user,
            message__in=chat_messages,
        ).values_list("message_id", flat=True)
    )


def _broadcast_block_state(chat):
    # Each connected consumer re-reads the block rows for its own user, so both
    # pages get the real current state (including when both sides blocked).
    async_to_sync(get_channel_layer().group_send)(
        f"private_chat_{chat.id}",
        {"type": "chat.block_state"},
    )


@login_required
def private_chat_list(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not is_chat_eligible(request.user, course):
        messages.error(request, NOT_ELIGIBLE_MESSAGE)
        return redirect("courses:detail", course_id=course.id)

    # Only rooms whose other participant is still an active student/TA of the course,
    # the same rule the chat page enforces; other rooms stay in the database, unlisted.
    eligible_ids = chat_classmates(request.user, course).order_by().values("pk")
    chats = list(
        PrivateChat.objects.filter(course=course)
        .filter(
            Q(user_low=request.user, user_high__in=eligible_ids)
            | Q(user_high=request.user, user_low__in=eligible_ids)
        )
        .select_related("course", "user_low", "user_high")
    )
    chat_by_other_id = {}
    for chat in chats:
        chat.other_user = chat.other_participant(request.user)
        chat.last_message = visible_messages(chat).order_by("-created_at", "-id").first()
        chat_by_other_id[chat.other_user.id] = chat
    chats.sort(
        key=lambda chat: chat.last_message.created_at if chat.last_message else chat.created_at,
        reverse=True,
    )

    blocked_ids = set(
        UserBlock.objects.filter(blocker=request.user).values_list("blocked_id", flat=True)
    )
    classmates = list(chat_classmates(request.user, course))
    roles = dict(
        course.enrollments.filter(user__in=classmates).values_list("user_id", "role")
    )
    for classmate in classmates:
        classmate.course_role = roles.get(classmate.id)
        classmate.private_chat = chat_by_other_id.get(classmate.id)
        classmate.is_blocked_by_me = classmate.id in blocked_ids

    return render(
        request,
        "courses/private_chat_list.html",
        {"course": course, "chats": chats, "classmates": classmates},
    )


@login_required
@require_POST
def start_private_chat(request, course_id, user_id):
    course = get_object_or_404(Course, pk=course_id)
    other = get_object_or_404(User, pk=user_id)
    try:
        chat, _created = get_or_create_private_chat(course=course, user=request.user, other=other)
    except PrivateChatError as error:
        messages.error(request, str(error))
        if is_chat_eligible(request.user, course):
            return redirect("courses:private_chats", course_id=course.id)
        return redirect("courses:detail", course_id=course.id)
    return redirect("courses:private_chat", course_id=course.id, chat_id=chat.id)


@login_required
def private_chat(request, course_id, chat_id):
    chat = _get_accessible_chat(request.user, course_id, chat_id)
    other = chat.other_participant(request.user)

    if request.method == "POST":
        try:
            chat_message = post_private_message(
                chat=chat,
                sender=request.user,
                body=request.POST.get("body", ""),
            )
        except PrivateChatError as error:
            if _wants_json(request):
                return JsonResponse({"error": str(error)}, status=400)
            messages.error(request, str(error))
            return redirect("courses:private_chat", course_id=course_id, chat_id=chat.id)

        serialized_message = serialize_private_message(chat_message)
        async_to_sync(get_channel_layer().group_send)(
            f"private_chat_{chat.id}",
            {"type": "chat.message", "message": serialized_message},
        )
        if _wants_json(request):
            return JsonResponse({"message": serialized_message}, status=201)
        return redirect("courses:private_chat", course_id=course_id, chat_id=chat.id)

    chat_messages, has_more = message_page(chat)
    return render(
        request,
        "courses/private_chat.html",
        {
            "chat": chat,
            "course": chat.course,
            "other_user": other,
            "chat_messages": chat_messages,
            "has_older_messages": has_more,
            "reported_ids": _reported_ids(request.user, chat_messages),
            **block_state_for(chat, request.user),
            "report_reasons": PrivateMessageReport.Reason.choices,
            "chat_ws_path": f"/ws/courses/{course_id}/chats/{chat.id}/",
        },
    )


@login_required
@require_GET
def private_chat_history(request, course_id, chat_id):
    """JSON page of messages older than ?before=<message_id>, oldest first."""
    chat = _get_accessible_chat(request.user, course_id, chat_id)
    try:
        before_id = int(request.GET.get("before", ""))
    except ValueError:
        return JsonResponse({"error": "ไม่สามารถโหลดข้อความเก่าได้ กรุณารีเฟรชหน้าแล้วลองอีกครั้ง"}, status=400)
    before = chat.messages.filter(pk=before_id).first()
    if before is None:
        return JsonResponse({"error": "ไม่สามารถโหลดข้อความเก่าได้ กรุณารีเฟรชหน้าแล้วลองอีกครั้ง"}, status=400)

    chat_messages, has_more = message_page(chat, before=before)
    reported_ids = _reported_ids(request.user, chat_messages)
    return JsonResponse(
        {
            "messages": [
                serialize_private_message(message, reported=message.id in reported_ids)
                for message in chat_messages
            ],
            "has_more": has_more,
        }
    )


@login_required
@require_POST
def block_private_chat_user(request, course_id, chat_id):
    chat = _get_accessible_chat(request.user, course_id, chat_id)
    try:
        other = block_user(chat=chat, user=request.user)
    except PrivateChatError as error:
        messages.error(request, str(error))
    else:
        _broadcast_block_state(chat)
        messages.success(request, f"บล็อก {other.full_name} แล้ว ทั้งสองฝ่ายจะส่งข้อความถึงกันไม่ได้")
    return redirect("courses:private_chat", course_id=course_id, chat_id=chat.id)


@login_required
@require_POST
def unblock_private_chat_user(request, course_id, chat_id):
    chat = _get_accessible_chat(request.user, course_id, chat_id)
    try:
        other = unblock_user(chat=chat, user=request.user)
    except PrivateChatError as error:
        messages.error(request, str(error))
    else:
        _broadcast_block_state(chat)
        messages.success(request, f"ยกเลิกการบล็อก {other.full_name} แล้ว")
    return redirect("courses:private_chat", course_id=course_id, chat_id=chat.id)


@login_required
@require_POST
def report_private_message(request, course_id, chat_id, message_id):
    chat = _get_accessible_chat(request.user, course_id, chat_id)
    message = get_object_or_404(
        PrivateChatMessage.objects.select_related("chat__course", "sender"),
        pk=message_id,
        chat=chat,
    )
    try:
        report_message(
            message=message,
            reporter=request.user,
            reason=request.POST.get("reason", ""),
            details=request.POST.get("details", ""),
        )
    except PrivateChatError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            "ส่งรายงานข้อความแล้ว สถานะ: รอตรวจสอบ คุณจะได้รับแจ้งเตือนเมื่อผู้ดูแลระบบพิจารณาเสร็จ",
        )
    return redirect("courses:private_chat", course_id=course_id, chat_id=chat.id)
