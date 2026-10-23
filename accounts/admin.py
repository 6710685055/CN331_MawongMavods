from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .forms import AdminUserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Minimal Admin tooling so teacher accounts can be approved (full flow = UC15)."""

    add_form = AdminUserCreationForm
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "role", "teacher_status", "email_verified")
    list_filter = ("role", "teacher_status", "email_verified")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("ข้อมูลส่วนตัว", {"fields": ("first_name", "last_name")}),
        ("บทบาท", {"fields": ("role", "teacher_status", "email_verified")}),
        ("สิทธิ์", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("วันที่", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "first_name", "last_name", "role", "password1", "password2")}),
    )
    actions = ["approve_teachers", "reject_teachers"]

    @admin.action(description="อนุมัติบัญชีอาจารย์ที่เลือก")
    def approve_teachers(self, request, queryset):
        n = queryset.filter(role=User.Role.TEACHER).update(teacher_status=User.TeacherStatus.APPROVED)
        self.message_user(request, f"อนุมัติ {n} บัญชี", messages.SUCCESS)

    @admin.action(description="ปฏิเสธบัญชีอาจารย์ที่เลือก")
    def reject_teachers(self, request, queryset):
        n = queryset.filter(role=User.Role.TEACHER).update(teacher_status=User.TeacherStatus.REJECTED)
        self.message_user(request, f"ปฏิเสธ {n} บัญชี", messages.WARNING)
