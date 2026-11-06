from django.urls import path

from . import views

app_name = "meetings"

urlpatterns = [
    path("", views.meeting_index, name="index"),
    path("teams/<int:team_id>/", views.group_meetings, name="group"),
    path("teams/<int:team_id>/create/", views.meeting_create, name="create"),
    path("<int:meeting_id>/edit/", views.meeting_edit, name="edit"),
]
