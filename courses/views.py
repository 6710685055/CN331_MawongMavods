from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import User

from .models import Course, Enrollment
from .permissions import is_course_staff
from .services import EnrollmentError, enroll


# ──────────────────────────── Index / My courses ────────────────────────────

@login_required
def my_courses(request):
    """Role-aware index page showing courses the user is involved in."""
    enrollments = list(
        Enrollment.objects.filter(user=request.user)
        .select_related("course", "course__owner")
    )
    for e in enrollments:
        e.is_staff_role = is_course_staff(request.user, e.course)

    # Teacher: also show pending enrollments for courses they own
    pending_enrollments = []
    if request.user.role == User.Role.TEACHER:
        owned_courses = Course.objects.filter(owner=request.user)
        pending_enrollments = list(
            Enrollment.objects.filter(
                course__in=owned_courses,
                role__in=[Enrollment.Role.STUDENT_PENDING, Enrollment.Role.TA_PENDING],
            ).select_related("user", "course")
        )

    return render(request, "courses/my_courses.html", {
        "enrollments": enrollments,
        "pending_enrollments": pending_enrollments,
    })


# ──────────────────────────── Course search / browse ────────────────────────

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


# ──────────────────────────── Enroll (student self-register) ────────────────

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
        elif enrollment.role == Enrollment.Role.STUDENT_PENDING:
            messages.success(
                request,
                f"ส่งคำขอลงทะเบียน {course.code} แล้ว กรุณารอให้อาจารย์ผู้สอนอนุมัติ",
            )
        else:
            messages.success(request, f"ลงทะเบียน {course.code} เรียบร้อยแล้ว")
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("courses:list")


# ──────────────────────────── Course detail (stub) ──────────────────────────

@login_required
def course_detail(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    return render(request, "courses/course_detail.html", {"course": course})


# ──────────────────────────── Teacher: create course ────────────────────────

@login_required
def create_course(request):
    if request.user.role != User.Role.TEACHER:
        messages.error(request, "เฉพาะอาจารย์เท่านั้นที่สามารถสร้างรายวิชาได้")
        return redirect("courses:my")

    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        name = request.POST.get("name", "").strip()
        if not code or not name:
            messages.error(request, "กรุณากรอกรหัสวิชาและชื่อวิชา")
            return render(request, "courses/create_course.html", {"code": code, "name": name})

        if Course.objects.filter(code=code).exists():
            messages.error(request, f"รหัสวิชา {code} ถูกใช้ไปแล้ว")
            return render(request, "courses/create_course.html", {"code": code, "name": name})

        course = Course.objects.create(code=code, name=name, owner=request.user)
        # Auto-enroll the teacher
        Enrollment.objects.create(user=request.user, course=course, role=Enrollment.Role.TEACHER)
        messages.success(request, f"สร้างรายวิชา {code} เรียบร้อยแล้ว")
        return redirect("courses:my")

    return render(request, "courses/create_course.html")


# ──────────────────────────── Teacher: delete course ────────────────────────

@login_required
@require_POST
def delete_course(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if course.owner != request.user:
        messages.error(request, "คุณไม่ใช่เจ้าของรายวิชานี้")
        return redirect("courses:my")

    course_code = course.code
    course.delete()
    messages.success(request, f"ลบรายวิชา {course_code} เรียบร้อยแล้ว")
    return redirect("courses:my")


# ──────────────────────────── Teacher: approve / reject enrollment ──────────

@login_required
@require_POST
def approve_enrollment(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id)
    course = enrollment.course

    if course.owner != request.user:
        messages.error(request, "คุณไม่มีสิทธิ์อนุมัติในรายวิชานี้")
        return redirect("courses:my")

    if enrollment.role == Enrollment.Role.STUDENT_PENDING:
        enrollment.role = Enrollment.Role.STUDENT
        enrollment.save()
        messages.success(request, f"อนุมัติ {enrollment.user.full_name} เป็นนักศึกษาในวิชา {course.code}")
    elif enrollment.role == Enrollment.Role.TA_PENDING:
        enrollment.role = Enrollment.Role.TA
        enrollment.save()
        messages.success(request, f"อนุมัติ {enrollment.user.full_name} เป็น TA ในวิชา {course.code}")
    else:
        messages.info(request, "ไม่มีคำขอที่ต้องอนุมัติ")

    return redirect("courses:my")


@login_required
@require_POST
def reject_enrollment(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id)
    course = enrollment.course

    if course.owner != request.user:
        messages.error(request, "คุณไม่มีสิทธิ์ปฏิเสธในรายวิชานี้")
        return redirect("courses:my")

    user_name = enrollment.user.full_name
    enrollment.delete()
    messages.success(request, f"ปฏิเสธคำขอของ {user_name} ในวิชา {course.code}")
    return redirect("courses:my")


# ──────────────────────────── Teacher: manage members ───────────────────────

@login_required
def course_members(request, course_id):
    """Teacher view to manage members (add TA / student, remove members)."""
    course = get_object_or_404(Course, pk=course_id)
    if course.owner != request.user:
        messages.error(request, "คุณไม่ใช่เจ้าของรายวิชานี้")
        return redirect("courses:my")

    members = Enrollment.objects.filter(course=course).select_related("user")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        member_role = request.POST.get("role", "student")
        try:
            target_user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, f"ไม่พบผู้ใช้ {email} ในระบบ")
            return redirect("courses:members", course_id=course.id)

        if Enrollment.objects.filter(user=target_user, course=course).exists():
            messages.error(request, f"{email} อยู่ในรายวิชานี้แล้ว")
            return redirect("courses:members", course_id=course.id)

        if member_role == "ta":
            role = Enrollment.Role.TA
        else:
            role = Enrollment.Role.STUDENT

        Enrollment.objects.create(user=target_user, course=course, role=role)
        messages.success(request, f"เพิ่ม {target_user.full_name} เป็น {Enrollment.Role(role).label} ในวิชา {course.code}")
        return redirect("courses:members", course_id=course.id)

    return render(request, "courses/course_members.html", {
        "course": course,
        "members": members,
    })


@login_required
@require_POST
def remove_member(request, course_id, enrollment_id):
    course = get_object_or_404(Course, pk=course_id)
    if course.owner != request.user:
        messages.error(request, "คุณไม่ใช่เจ้าของรายวิชานี้")
        return redirect("courses:my")

    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, course=course)
    if enrollment.user == request.user:
        messages.error(request, "ไม่สามารถลบตัวเองออกจากรายวิชาได้")
        return redirect("courses:members", course_id=course.id)

    user_name = enrollment.user.full_name
    enrollment.delete()
    messages.success(request, f"ลบ {user_name} ออกจากรายวิชา {course.code}")
    return redirect("courses:members", course_id=course.id)
