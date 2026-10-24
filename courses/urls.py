from django.urls import path

from . import group_views
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
    path("<int:course_id>/groups/create/", group_views.create_course_team, name="create_team"),
    path(
        "<int:course_id>/groups/<int:team_id>/invite/",
        group_views.invite_to_team,
        name="invite_to_team",
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
    path("<int:course_id>/members/<int:enrollment_id>/remove/", views.remove_member, name="remove_member"),
    path("enrollment/<int:enrollment_id>/approve/", views.approve_enrollment, name="approve"),
    path("enrollment/<int:enrollment_id>/reject/", views.reject_enrollment, name="reject"),
]
