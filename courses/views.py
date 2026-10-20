from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Course, Enrollment
from .services import EnrollmentError, enroll


@login_required
def course_list(request):
    q = request.GET.get("q", "").strip()
    courses = Course.objects.all()
    if q:
        courses = courses.filter(Q(code__icontains=q) | Q(name__icontains=q))
    enrolled_ids = set(
        Enrollment.objects.filter(user=request.user).values_list("course_id", flat=True)
    )
    return render(
        request,
        "courses/course_list.html",
        {"courses": courses, "q": q, "enrolled_ids": enrolled_ids},
    )


@login_required
@require_POST
def enroll_course(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    try:
        enrollment = enroll(request.user, course)
    except EnrollmentError as e:
        messages.error(request, str(e))
    else:
        if enrollment.role == Enrollment.Role.TA_PENDING:
            messages.success(
                request,
                f"ลงทะเบียน {course.code} แล้ว สิทธิ์ TA จะใช้ได้เมื่ออาจารย์ผู้สอนอนุมัติ",
            )
        else:
            messages.success(request, f"ลงทะเบียน {course.code} เรียบร้อยแล้ว")
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("courses:list")


@login_required
def my_courses(request):
    enrollments = Enrollment.objects.filter(user=request.user).select_related("course")
    return render(request, "courses/my_courses.html", {"enrollments": enrollments})
