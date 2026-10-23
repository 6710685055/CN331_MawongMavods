from django.urls import path

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
    path("<int:course_id>/members/<int:enrollment_id>/remove/", views.remove_member, name="remove_member"),
    path("enrollment/<int:enrollment_id>/approve/", views.approve_enrollment, name="approve"),
    path("enrollment/<int:enrollment_id>/reject/", views.reject_enrollment, name="reject"),
]
