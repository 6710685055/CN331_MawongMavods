from django.urls import path

from . import group_views
from . import private_chat_views
from . import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list, name="list"),
    path("mine/", views.my_courses, name="my"),
    path("create/", views.create_course, name="create"),
    path("<int:course_id>/", views.course_detail, name="detail"),
    path("<int:course_id>/enroll/", views.enroll_course, name="enroll"),
    path("<int:course_id>/delete/", views.delete_course, name="delete"),
    path("<int:course_id>/members/", views.course_members, name="members"),
    path("<int:course_id>/groups/", group_views.group_dashboard, name="groups"),
    path(
        "<int:course_id>/groups/manage/",
        group_views.manage_unassigned_students,
        name="manage_unassigned_students",
    ),
    path(
        "<int:course_id>/groups/manage/assign/",
        group_views.ta_assign_student,
        name="ta_assign_student",
    ),
    path(
        "<int:course_id>/groups/manage/create-team/",
        group_views.ta_create_and_assign_team,
        name="ta_create_and_assign_team",
    ),
    path(
        "<int:course_id>/groups/manage/auto-assign/",
        group_views.ta_auto_assign,
        name="ta_auto_assign",
    ),
    path(
        "<int:course_id>/groups/create/",
        group_views.create_course_team,
        name="create_team",
    ),
    path(
        "<int:course_id>/groups/<int:team_id>/invite/",
        group_views.invite_to_team,
        name="invite_to_team",
    ),
    path(
        "<int:course_id>/groups/<int:team_id>/leave/",
        group_views.leave_team,
        name="leave_team",
    ),
    path(
        "<int:course_id>/groups/invitations/<int:invitation_id>/respond/",
        group_views.respond_to_team_invitation,
        name="respond_to_team_invitation",
    ),
    path(
        "<int:course_id>/groups/<int:team_id>/chat/",
        group_views.team_chat,
        name="team_chat",
    ),
    path(
        "<int:course_id>/groups/<int:team_id>/chat/attachments/<int:message_id>/",
        group_views.download_chat_attachment,
        name="download_chat_attachment",
    ),
    path(
        "<int:course_id>/chats/",
        private_chat_views.private_chat_list,
        name="private_chats",
    ),
    path(
        "<int:course_id>/chats/start/<int:user_id>/",
        private_chat_views.start_private_chat,
        name="start_private_chat",
    ),
    path(
        "<int:course_id>/chats/<int:chat_id>/",
        private_chat_views.private_chat,
        name="private_chat",
    ),
    path(
        "<int:course_id>/chats/<int:chat_id>/messages/",
        private_chat_views.private_chat_history,
        name="private_chat_history",
    ),
    path(
        "<int:course_id>/chats/<int:chat_id>/block/",
        private_chat_views.block_private_chat_user,
        name="block_private_chat_user",
    ),
    path(
        "<int:course_id>/chats/<int:chat_id>/unblock/",
        private_chat_views.unblock_private_chat_user,
        name="unblock_private_chat_user",
    ),
    path(
        "<int:course_id>/chats/<int:chat_id>/messages/<int:message_id>/report/",
        private_chat_views.report_private_message,
        name="report_private_message",
    ),
    path(
        "<int:course_id>/members/<int:enrollment_id>/remove/",
        views.remove_member,
        name="remove_member",
    ),
    path(
        "enrollment/<int:enrollment_id>/approve/",
        views.approve_enrollment,
        name="approve",
    ),
    path(
        "enrollment/<int:enrollment_id>/reject/", views.reject_enrollment, name="reject"
    ),
]
