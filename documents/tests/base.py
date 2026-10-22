import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from courses.models import Course, Enrollment



def make_file(filename="sheet.pdf", content=b"%PDF-1.4 sample content", size=None):
    f = SimpleUploadedFile(filename, content, content_type="application/pdf")
    if size is not None:
        f.size = size
    return f


class BaseDocumentTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self._temp_media = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._temp_media)
        self._override.enable()

        self.course = Course.objects.create(code="CN331", name="Software Engineering")
        self.other_course = Course.objects.create(code="CN321", name="Data Networks")

        self.student = User.objects.create_user(
            email="student1@example.com",
            password="Password123!",
            first_name="สมชาย",
            last_name="ใจดี",
            role=User.Role.STUDENT,
            email_verified=True,
        )
        self.student2 = User.objects.create_user(
            email="student2@example.com",
            password="Password123!",
            first_name="สมหญิง",
            last_name="รักเรียน",
            role=User.Role.STUDENT,
            email_verified=True,
        )
        self.ta_pending = User.objects.create_user(
            email="tapending@example.com",
            password="Password123!",
            first_name="ทีเอ",
            last_name="รออนุมัติ",
            role=User.Role.TA,
            email_verified=True,
        )
        self.ta = User.objects.create_user(
            email="ta1@example.com",
            password="Password123!",
            first_name="กิตติ",
            last_name="ผู้ช่วยสอน",
            role=User.Role.TA,
            email_verified=True,
        )
        self.ta2 = User.objects.create_user(
            email="ta2@example.com",
            password="Password123!",
            first_name="นภา",
            last_name="ผู้ช่วยสอนสอง",
            role=User.Role.TA,
            email_verified=True,
        )
        self.teacher = User.objects.create_user(
            email="teacher@example.com",
            password="Password123!",
            first_name="ดร.วิชัย",
            last_name="สอนดี",
            role=User.Role.TEACHER,
            teacher_status=User.TeacherStatus.APPROVED,
            email_verified=True,
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="Password123!",
            first_name="คนนอก",
            last_name="ไม่ได้ลงเรียน",
            role=User.Role.STUDENT,
            email_verified=True,
        )

        Enrollment.objects.create(
            user=self.student, course=self.course, role=Enrollment.Role.STUDENT
        )
        Enrollment.objects.create(
            user=self.student2, course=self.course, role=Enrollment.Role.STUDENT
        )
        Enrollment.objects.create(
            user=self.ta_pending, course=self.course, role=Enrollment.Role.TA_PENDING
        )
        Enrollment.objects.create(
            user=self.ta, course=self.course, role=Enrollment.Role.TA
        )
        Enrollment.objects.create(
            user=self.ta2, course=self.course, role=Enrollment.Role.TA
        )
        Enrollment.objects.create(
            user=self.teacher, course=self.course, role=Enrollment.Role.TEACHER
        )

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._temp_media, ignore_errors=True)
        super().tearDown()
