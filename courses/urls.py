from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list, name="list"),
    path("mine/", views.my_courses, name="my"),
    path("<int:course_id>/enroll/", views.enroll_course, name="enroll"),
]
