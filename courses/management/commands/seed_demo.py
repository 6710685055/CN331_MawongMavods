import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.models import (
    Course,
    Enrollment,
    PrivateChat,
    PrivateChatMessage,
    PrivateMessageReport,
    Team,
    TeamChat,
    TeamChatMessage,
    TeamInvitation,
    TeamMembership,
)
from documents.models import Document, DocumentReport, DocumentReviewLog, DocumentVote
from meetings.models import Meeting
from notifications.models import Notification


def make_minimal_pdf(title_ascii: str) -> bytes:
    """สร้างไฟล์ PDF 1 หน้าที่เปิดอ่านในเบราว์เซอร์ได้จริงโดยไม่ต้องลงไลบรารีเพิ่ม"""
    safe = title_ascii.encode("ascii", "replace").decode("ascii")
    safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 16 Tf 50 740 Td ({safe}) Tj ET".encode("ascii")
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        ),
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objs:
        offsets.append(len(buf))
        buf.extend(obj)
    xref = len(buf)
    buf.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(buf)


def load_demo_pdf(filename: str, fallback_label: str) -> bytes:
    """ใช้ไฟล์ PDF ภาษาไทยจาก media/demo_files/ ถ้ามี ไม่งั้นสร้าง PDF ขั้นต่ำให้"""
    demo_path = Path(settings.MEDIA_ROOT) / "demo_files" / filename
    if demo_path.is_file():
        return demo_path.read_bytes()
    return make_minimal_pdf(fallback_label)


class Command(BaseCommand):
    help = "สร้างข้อมูลจำลองครบทุก Use Case สำหรับทดสอบและพรีเซนต์งาน"

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("SEED_DEMO_PASSWORD", "Demo@CN331-2026!")
        now = timezone.now()

        # 1. สร้างรายวิชามาตรฐาน (CN331 ฯลฯ)
        call_command("seed_courses", stdout=self.stdout)
        cn331 = Course.objects.get(code="CN331")

        # 2. สร้างบัญชีผู้ใช้ครบทุกบทบาท (UC7)
        teacher = self._ensure_user(
            "teacher@cn331.demo",
            "สมชาย",
            "สอนดี",
            User.Role.TEACHER,
            password,
            teacher_status=User.TeacherStatus.APPROVED,
        )
        self._ensure_user(
            "teacher_pending@cn331.demo",
            "วิชัย",
            "รออนุมัติ",
            User.Role.TEACHER,
            password,
            teacher_status=User.TeacherStatus.PENDING,
        )
        ta = self._ensure_user(
            "ta@cn331.demo", "พิมพ์ชนก", "ผู้ช่วยสอน", User.Role.TA, password
        )
        ta_pending = self._ensure_user(
            "ta_pending@cn331.demo", "ธนพล", "สมัครผู้ช่วย", User.Role.TA, password
        )

        student_specs = [
            ("stu1@cn331.demo", "กิตติภพ", "ใจดี"),
            ("stu2@cn331.demo", "ณัฐธิดา", "ขยันเรียน"),
            ("stu3@cn331.demo", "ปวริศ", "รักโค้ด"),
            ("stu4@cn331.demo", "ชลธิชา", "หาทีม"),
            ("stu5@cn331.demo", "ศุภกร", "ไร้กลุ่ม"),
        ]
        students = [
            self._ensure_user(email, fn, ln, User.Role.STUDENT, password)
            for email, fn, ln in student_specs
        ]
        stu1, stu2, stu3, stu4, stu5 = students
        stu_pending = self._ensure_user(
            "stu_pending@cn331.demo",
            "อภิญญา",
            "รอเข้าวิชา",
            User.Role.STUDENT,
            password,
        )

        # ตั้งเจ้าของวิชา CN331 และลงทะเบียนเข้าวิชา
        if cn331.owner_id != teacher.id:
            cn331.owner = teacher
            cn331.save(update_fields=["owner"])

        enrollments = [
            (teacher, Enrollment.Role.TEACHER),
            (ta, Enrollment.Role.TA),
            (ta_pending, Enrollment.Role.TA_PENDING),
            (stu_pending, Enrollment.Role.STUDENT_PENDING),
            *((s, Enrollment.Role.STUDENT) for s in students),
        ]
        for user, role in enrollments:
            Enrollment.objects.update_or_create(
                user=user, course=cn331, defaults={"role": role}
            )

        # 3. จัดกลุ่ม + คำเชิญ + แชทกลุ่มพร้อมไฟล์แนบ (UC1, US-05, UC9, UC11)
        # stu4 และ stu5 ยังไม่มีกลุ่ม เพื่อใช้เดโม US-05 จัดการนักศึกษาไร้กลุ่มได้ทันที
        team, _ = Team.objects.get_or_create(
            course=cn331,
            name="กลุ่ม 1 - MawongDev",
            defaults={"created_by": stu1},
        )
        for member in (stu1, stu2, stu3):
            if not TeamMembership.objects.filter(user=member, course=cn331).exists():
                TeamMembership.objects.create(team=team, course=cn331, user=member)

        if (
            not TeamMembership.objects.filter(user=stu4, course=cn331).exists()
            and not TeamInvitation.objects.filter(
                team=team, invitee=stu4, status=TeamInvitation.Status.PENDING
            ).exists()
        ):
            TeamInvitation.objects.create(
                team=team,
                inviter=stu1,
                invitee=stu4,
                status=TeamInvitation.Status.PENDING,
            )

        tchat, _ = TeamChat.objects.get_or_create(team=team)
        if not tchat.messages.exists():
            TeamChatMessage.objects.create(
                chat=tchat,
                sender=stu1,
                body="สวัสดีทุกคน เปิดห้องแชทกลุ่มสำหรับโปรเจกต์ CN331 แล้วนะครับ",
            )
            TeamChatMessage.objects.create(
                chat=tchat,
                sender=stu2,
                body="รับทราบค่ะ เดี๋ยวอัปเดต ERD กับแผนแบ่งงานไว้ให้นะคะ",
            )
            msg_att = TeamChatMessage(
                chat=tchat,
                sender=stu3,
                body="แนบไฟล์สรุปหัวข้อ Sprint รอบนี้ไว้ให้ครับ",
            )
            msg_att.attachment.save(
                "sprint_plan.pdf",
                ContentFile(load_demo_pdf("sprint_plan.pdf", "CN331 Team Sprint Plan")),
                save=True,
            )
        else:
            for m in tchat.messages.exclude(attachment=""):
                if not m.attachment.storage.exists(m.attachment.name):
                    m.attachment.save(
                        "sprint_plan.pdf",
                        ContentFile(
                            load_demo_pdf("sprint_plan.pdf", "CN331 Team Sprint Plan")
                        ),
                        save=True,
                    )

        # 4. นัดหมายประชุมกลุ่ม (US-02)
        team_ct = ContentType.objects.get_for_model(Team)
        Meeting.objects.get_or_create(
            group_content_type=team_ct,
            group_object_id=team.pk,
            title="Sprint Review & ซ้อมพรีเซนต์ CN331",
            defaults={
                "meeting_url": "https://meet.google.com/abc-defg-hij",
                "starts_at": now + timedelta(days=2),
                "created_by": stu1,
            },
        )
        Meeting.objects.get_or_create(
            group_content_type=team_ct,
            group_object_id=team.pk,
            title="นัดเช็กความเรียบร้อยก่อนส่งงาน",
            defaults={
                "meeting_url": "https://meet.google.com/xyz-uvwx-rst",
                "starts_at": now + timedelta(hours=3),
                "created_by": stu2,
            },
        )

        # 5. คลังเอกสาร + Verify + Pin + โหวต + Report (UC3, UC4, UC10, UC14, US-12)
        doc_verified = self._ensure_doc(
            course=cn331,
            uploader=stu1,
            title="สรุปเนื้อหา Midterm — Software Process & Agile",
            doc_type=Document.DocType.SUMMARY,
            filename="cn331_midterm_agile.pdf",
            pdf_label="CN331 Midterm Summary - Software Process & Agile",
            description="สรุป Scrum, Kanban และ User Story พร้อมตัวอย่างข้อสอบเก่า",
            chapter="บทที่ 1-4",
            defaults={
                "verify_status": Document.VerifyStatus.VERIFIED,
                "verified_by": ta,
                "verified_by_name": ta.full_name,
                "verified_by_role": Document.VerifierRole.TA,
                "verified_at": now,
                "verified_version": 1,
                "latest_review_comment": "เนื้อหาครบถ้วน อ่านเข้าใจง่ายครับ",
                "is_pinned": True,
                "pinned_by": teacher,
                "pinned_at": now,
            },
        )
        if not doc_verified.review_logs.exists():
            DocumentReviewLog.objects.create(
                document=doc_verified,
                reviewer=ta,
                reviewer_name_snapshot=ta.full_name,
                reviewer_role_snapshot=Document.VerifierRole.TA,
                action=DocumentReviewLog.Action.VERIFY,
                document_version=1,
                comment="เนื้อหาครบถ้วน อ่านเข้าใจง่ายครับ",
            )

        doc_pending = self._ensure_doc(
            course=cn331,
            uploader=stu2,
            title="แนวข้อสอบ Final — Testing, CI/CD & Clean Code",
            doc_type=Document.DocType.EXAM,
            filename="cn331_final_practice.pdf",
            pdf_label="CN331 Final Practice Exam - Testing & CI/CD",
            description="รวมโจทย์ซ้อมมือเรื่อง Unit Test, Coverage และ Code Review",
            chapter="บทที่ 5-8",
            defaults={"verify_status": Document.VerifyStatus.PENDING},
        )

        doc_revision = self._ensure_doc(
            course=cn331,
            uploader=stu1,
            title="สรุป Design Patterns & SOLID Principles",
            doc_type=Document.DocType.SUMMARY,
            filename="cn331_design_patterns.pdf",
            pdf_label="CN331 Design Patterns & SOLID Draft",
            description="สรุปหลักการ SOLID และตัวอย่าง Strategy / Observer",
            chapter="บทที่ 6",
            defaults={
                "verify_status": Document.VerifyStatus.NEEDS_REVISION,
                "latest_review_comment": (
                    "ช่วยเพิ่มแผนภาพ UML ในหัวข้อ Observer อีกนิดครับ"
                ),
            },
        )
        if not doc_revision.review_logs.exists():
            DocumentReviewLog.objects.create(
                document=doc_revision,
                reviewer=teacher,
                reviewer_name_snapshot=teacher.full_name,
                reviewer_role_snapshot=Document.VerifierRole.TEACHER,
                action=DocumentReviewLog.Action.REQUEST_REVISION,
                document_version=1,
                comment="ช่วยเพิ่มแผนภาพ UML ในหัวข้อ Observer อีกนิดครับ",
            )

        doc_reported = self._ensure_doc(
            course=cn331,
            uploader=stu3,
            title="ตัวอย่างการบ้าน Git Branching & Pull Request",
            doc_type=Document.DocType.HOMEWORK,
            filename="cn331_git_homework.pdf",
            pdf_label="CN331 Git Branching Homework Sample",
            description="ตัวอย่างขั้นตอนการแตก branch และแก้ merge conflict",
            chapter="ปฏิบัติการที่ 2",
            defaults={"verify_status": Document.VerifyStatus.NONE},
        )

        # โหวตเอกสาร (UC10)
        for voter in (stu2, stu3, stu4):
            DocumentVote.objects.update_or_create(
                document=doc_verified,
                user=voter,
                defaults={"value": DocumentVote.Value.UP},
            )
        DocumentVote.objects.update_or_create(
            document=doc_pending,
            user=stu1,
            defaults={"value": DocumentVote.Value.UP},
        )
        for d in (doc_verified, doc_pending):
            score = d.votes.aggregate(total=Sum("value"))["total"] or 0
            if d.vote_score != score:
                d.vote_score = score
                d.save(update_fields=["vote_score"])

        # Report เอกสารค้างในคิวให้ TA/อาจารย์กดตัดสินโชว์ตอนเดโม (UC10 & UC14)
        report_specs = [
            (
                stu1,
                DocumentReport.Reason.INCORRECT,
                "คำสั่ง git reset ในหน้าแรกคลาดเคลื่อน",
            ),
            (stu2, DocumentReport.Reason.WRONG_COURSE, "มีเนื้อหาวิชาอื่นปนมาบางส่วน"),
        ]
        for reporter, reason, detail in report_specs:
            if not DocumentReport.objects.filter(
                document=doc_reported,
                reporter=reporter,
                status=DocumentReport.Status.OPEN,
            ).exists():
                DocumentReport.objects.create(
                    document=doc_reported,
                    reporter=reporter,
                    reason=reason,
                    detail=detail,
                    document_version=doc_reported.version,
                    status=DocumentReport.Status.OPEN,
                )

        # 6. แชทส่วนตัว + รายงานข้อความค้างใน Admin (UC8)
        pchat_ok = self._ensure_private_chat(cn331, stu1, stu2)
        if not pchat_ok.messages.exists():
            PrivateChatMessage.objects.create(
                chat=pchat_ok,
                sender=stu1,
                body="สวัสดีครับ ขอดูตัวอย่างการเขียนเทสของพาร์ทเอกสารหน่อยได้ไหมครับ",
            )
            PrivateChatMessage.objects.create(
                chat=pchat_ok,
                sender=stu2,
                body="ได้เลยค่ะ ดูไฟล์ในคลังเอกสารที่ปักหมุดไว้ประกอบได้เลยนะคะ",
            )

        pchat_mod = self._ensure_private_chat(cn331, stu3, stu4)
        if not pchat_mod.messages.exists():
            PrivateChatMessage.objects.create(
                chat=pchat_mod,
                sender=stu3,
                body="สวัสดีครับ สนใจเข้ากลุ่มโปรเจกต์ด้วยกันไหมครับ",
            )
            spam_msg = PrivateChatMessage.objects.create(
                chat=pchat_mod,
                sender=stu4,
                body="รับจ้างทำการบ้านทุกวิชา ทักไลน์ @spam-demo-999 ราคาถูก!",
            )
            PrivateMessageReport.objects.get_or_create(
                message=spam_msg,
                reporter=stu3,
                defaults={
                    "reported_user": stu4,
                    "course": cn331,
                    "reason": PrivateMessageReport.Reason.SPAM,
                    "details": "ส่งข้อความโฆษณารับจ้างทำการบ้านในแชทส่วนตัว",
                    "message_body": spam_msg.body,
                    "message_sent_at": spam_msg.created_at,
                    "context_snapshot": [
                        {
                            "sender_name": stu4.full_name,
                            "sent_at": timezone.localtime(spam_msg.created_at).strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            "body": spam_msg.body,
                            "reported": True,
                        }
                    ],
                },
            )

        # 7. แจ้งเตือนตัวอย่างในกระดิ่ง (Notifications)
        if not Notification.objects.filter(recipient=stu4).exists():
            Notification.objects.create(
                recipient=stu4,
                actor=stu1,
                notification_type=Notification.Type.TEAM_INVITATION,
                title="คำเชิญเข้ากลุ่ม 1 - MawongDev",
                message=f"{stu1.full_name} เชิญคุณเข้าร่วมกลุ่มในวิชา CN331",
                target_url=reverse("courses:groups", args=[cn331.id]),
            )
        if not Notification.objects.filter(recipient=ta).exists():
            Notification.objects.create(
                recipient=ta,
                actor=stu1,
                notification_type=Notification.Type.GENERAL,
                title="มีเอกสารรอตรวจและ Report ค้างในวิชา CN331",
                message="สามารถเข้าตรวจเอกสารได้ที่คิวตรวจสอบและคิว Report",
                target_url=reverse("documents:reported_queue", args=[cn331.id]),
            )

        self.stdout.write(
            self.style.SUCCESS("\n=== สร้างข้อมูลจำลองสำเร็จครบทุก Use Case ===")
        )
        self.stdout.write(f"รหัสผ่านกลางของทุกบัญชีจำลอง: {password}")
        self.stdout.write("  - อาจารย์ (เจ้าของวิชา CN331): teacher@cn331.demo")
        self.stdout.write("  - อาจารย์รออนุมัติใน /admin/:  teacher_pending@cn331.demo")
        self.stdout.write("  - TA ประจำวิชา CN331:          ta@cn331.demo")
        self.stdout.write("  - TA รออาจารย์อนุมัติเข้าวิชา:   ta_pending@cn331.demo")
        self.stdout.write("  - นักศึกษาในกลุ่ม 1:           stu1..stu3@cn331.demo")
        self.stdout.write(
            "  - นักศึกษาถูกเชิญ/ยังไร้กลุ่ม:   stu4@cn331.demo, stu5@cn331.demo"
        )
        self.stdout.write("  - นักศึกษารออนุมัติเข้าวิชา:     stu_pending@cn331.demo\n")

    def _ensure_user(
        self,
        email: str,
        first_name: str,
        last_name: str,
        role: str,
        password: str,
        teacher_status: str = User.TeacherStatus.NONE,
    ) -> User:
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "teacher_status": teacher_status,
                "email_verified": True,
            },
        )
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user

    def _ensure_private_chat(self, course: Course, u1: User, u2: User) -> PrivateChat:
        u_low, u_high = (u1, u2) if u1.pk < u2.pk else (u2, u1)
        chat, _ = PrivateChat.objects.get_or_create(
            course=course, user_low=u_low, user_high=u_high
        )
        return chat

    def _ensure_doc(
        self,
        *,
        course: Course,
        uploader: User,
        title: str,
        doc_type: str,
        filename: str,
        pdf_label: str,
        description: str,
        chapter: str,
        defaults: dict,
    ) -> Document:
        pdf_bytes = load_demo_pdf(filename, pdf_label)
        doc = Document.objects.filter(course=course, title=title).first()
        if doc is None:
            doc = Document(
                course=course,
                uploader=uploader,
                title=title,
                doc_type=doc_type,
                academic_year=2569,
                semester=Document.Semester.FIRST,
                description=description,
                related_chapter=chapter,
                original_filename=filename,
                file_size=len(pdf_bytes),
                **defaults,
            )
            doc.file.save(filename, ContentFile(pdf_bytes), save=True)
        elif not doc.file or not doc.file.storage.exists(doc.file.name):
            # ถ้าไฟล์บน storage ยังไม่มี จะอัปโหลดไฟล์ PDF คืนให้ทันที
            doc.file.save(filename, ContentFile(pdf_bytes), save=True)
        return doc
