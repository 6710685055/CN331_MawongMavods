"""UC4: Verify Document."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from courses.models import Enrollment
from notifications.models import Notification

from ..models import Document, DocumentReviewLog
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    get_verification_queue,
    replace_document_file,
    request_document_revision,
    revoke_document_verification,
    upload_document,
    verify_document,
)
from .base import BaseDocumentTestCase, make_file


class UC4VerifyDocumentTests(BaseDocumentTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.doc_older = upload_document(
            user=self.student,
            course=self.course,
            title="ชีทสรุปเก่าสุด",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("old.pdf"),
        )
        Document.objects.filter(pk=self.doc_older.pk).update(
            created_at=now - timedelta(hours=3)
        )

        self.doc_newer = upload_document(
            user=self.student2,
            course=self.course,
            title="แนวข้อสอบใหม่กว่า",
            doc_type=Document.DocType.EXAM,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("new.pdf"),
        )
        Document.objects.filter(pk=self.doc_newer.pk).update(
            created_at=now - timedelta(hours=1)
        )

        self.doc_by_ta = upload_document(
            user=self.ta,
            course=self.course,
            title="ชีทที่ TA1 อัปโหลดเอง",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("ta_own.pdf"),
        )
        Document.objects.filter(pk=self.doc_by_ta.pk).update(
            created_at=now - timedelta(hours=2)
        )

        self.doc_homework = upload_document(
            user=self.student,
            course=self.course,
            title="การบ้านท้ายบท",
            doc_type=Document.DocType.HOMEWORK,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("hw.pdf"),
            confirm_past_deadline=True,
        )

    def test_queue_access_and_fifo_order_and_exclusions(self):
        # Student and TA_PENDING cannot access review queue
        for unauthorized in (self.student, self.ta_pending, self.outsider):
            self.client.force_login(unauthorized)
            res = self.client.get(
                reverse("documents:review_queue", args=[self.course.id])
            )
            self.assertEqual(res.status_code, 403)

        # Approved TA sees only SUMMARY and EXAM in PENDING status, oldest first, excluding own upload
        ta_queue = list(get_verification_queue(reviewer=self.ta, course=self.course))
        self.assertEqual(
            [d.id for d in ta_queue],
            [self.doc_older.id, self.doc_newer.id],
        )

        # Another TA (ta2) or Teacher sees doc_by_ta in the queue as well, in oldest-first order
        teacher_queue = list(
            get_verification_queue(reviewer=self.teacher, course=self.course)
        )
        self.assertEqual(
            [d.id for d in teacher_queue],
            [self.doc_older.id, self.doc_by_ta.id, self.doc_newer.id],
        )

    def test_verify_by_ta_and_teacher_creates_badge_and_notification(self):
        # Verified by TA
        verify_document(reviewer=self.ta, document=self.doc_older)
        self.doc_older.refresh_from_db()
        self.assertTrue(self.doc_older.has_active_verified_badge)
        self.assertEqual(self.doc_older.verified_badge_label, "Verified by TA")
        self.assertEqual(self.doc_older.verified_by_name, self.ta.full_name)
        self.assertEqual(self.doc_older.verified_version, 1)
        self.assertIsNotNone(self.doc_older.verified_at)

        noti = Notification.objects.filter(
            recipient=self.student,
            notification_type=Notification.Type.DOCUMENT_VERIFIED,
        ).first()
        self.assertIsNotNone(noti)
        self.assertIn("Verified by TA", noti.title)

        # Verified by Teacher
        verify_document(reviewer=self.teacher, document=self.doc_newer)
        self.doc_newer.refresh_from_db()
        self.assertTrue(self.doc_newer.has_active_verified_badge)
        self.assertEqual(self.doc_newer.verified_badge_label, "Verified by Teacher")
        self.assertEqual(self.doc_newer.verified_by_name, self.teacher.full_name)

    def test_cannot_verify_own_document_or_homework_or_without_permission(self):
        # TA cannot verify own document
        with self.assertRaises(DocumentPermissionError):
            verify_document(reviewer=self.ta, document=self.doc_by_ta)

        self.client.force_login(self.ta)
        res_own = self.client.post(
            reverse("documents:verify", args=[self.course.id, self.doc_by_ta.id])
        )
        self.assertEqual(res_own.status_code, 403)

        # Homework cannot be verified
        with self.assertRaises(DocumentServiceError):
            verify_document(reviewer=self.teacher, document=self.doc_homework)

        # Student calling verify API directly gets 403
        self.client.force_login(self.student2)
        res_stu = self.client.post(
            reverse("documents:verify", args=[self.course.id, self.doc_older.id])
        )
        self.assertEqual(res_stu.status_code, 403)

    def test_badge_persists_when_ta_role_revoked_later(self):
        verify_document(reviewer=self.ta, document=self.doc_older)
        # Simulate UC16 revoking TA rights back to STUDENT
        Enrollment.objects.filter(user=self.ta, course=self.course).update(
            role=Enrollment.Role.STUDENT
        )
        self.doc_older.refresh_from_db()
        self.assertTrue(self.doc_older.has_active_verified_badge)
        self.assertEqual(self.doc_older.verified_badge_label, "Verified by TA")
        self.assertEqual(self.doc_older.verified_by_name, "กิตติ ผู้ช่วยสอน")

    def test_request_revision_and_strict_visibility_of_status_and_comments(self):
        # Empty comment is rejected
        with self.assertRaises(DocumentServiceError):
            request_document_revision(
                reviewer=self.ta, document=self.doc_older, comment="   "
            )

        # Valid revision request updates status to NEEDS_REVISION and notifies owner
        comment_text = "สูตรในหน้า 3 ผิด กรุณาแก้แล้วอัปโหลดใหม่"
        request_document_revision(
            reviewer=self.ta, document=self.doc_older, comment=comment_text
        )
        self.doc_older.refresh_from_db()
        self.assertEqual(
            self.doc_older.verify_status, Document.VerifyStatus.NEEDS_REVISION
        )
        self.assertEqual(self.doc_older.latest_review_comment, comment_text)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student,
                notification_type=Notification.Type.DOCUMENT_NEEDS_REVISION,
            ).exists()
        )

        # Owner, TA, and Teacher see the "ต้องแก้ไข" status and reviewer comment
        for privileged_viewer in (self.student, self.ta, self.teacher):
            self.client.force_login(privileged_viewer)
            res = self.client.get(
                reverse(
                    "documents:detail", args=[self.course.id, self.doc_older.id]
                )
            )
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, "ต้องแก้ไข")
            self.assertContains(res, comment_text)

        # Other student in the same course (student2) does NOT see "ต้องแก้ไข", "รอตรวจ", or the comment
        self.client.force_login(self.student2)
        res_other_detail = self.client.get(
            reverse("documents:detail", args=[self.course.id, self.doc_older.id])
        )
        self.assertEqual(res_other_detail.status_code, 200)
        self.assertNotContains(res_other_detail, "สถานะ: ต้องแก้ไข")
        self.assertNotContains(res_other_detail, comment_text)

        # Also check on a PENDING document (doc_by_ta) that student2 does NOT see "สถานะ: รอตรวจ"
        res_pending_detail = self.client.get(
            reverse("documents:detail", args=[self.course.id, self.doc_by_ta.id])
        )
        self.assertNotContains(res_pending_detail, "สถานะ: รอตรวจ")

    def test_revoke_verification_requires_reason_and_notifies_owner(self):
        verify_document(reviewer=self.ta, document=self.doc_older)
        self.assertTrue(self.doc_older.has_active_verified_badge)

        # Empty reason is rejected
        with self.assertRaises(DocumentServiceError):
            revoke_document_verification(
                reviewer=self.teacher, document=self.doc_older, reason=""
            )

        # Valid revoke removes badge, sets status to NEEDS_REVISION, and notifies owner
        revoke_document_verification(
            reviewer=self.teacher,
            document=self.doc_older,
            reason="พบว่าโจทย์ข้อ 5 เฉลยสลับข้อ",
        )
        self.doc_older.refresh_from_db()
        self.assertFalse(self.doc_older.has_active_verified_badge)
        self.assertEqual(
            self.doc_older.verify_status, Document.VerifyStatus.NEEDS_REVISION
        )
        self.assertEqual(
            self.doc_older.latest_review_comment, "พบว่าโจทย์ข้อ 5 เฉลยสลับข้อ"
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student,
                notification_type=Notification.Type.DOCUMENT_VERIFY_REVOKED,
            ).exists()
        )
        self.assertEqual(
            DocumentReviewLog.objects.filter(
                document=self.doc_older,
                action=DocumentReviewLog.Action.REVOKE_VERIFY,
            ).count(),
            1,
        )

    def test_version_binding_when_owner_replaces_file(self):
        verify_document(reviewer=self.ta, document=self.doc_older)
        self.assertTrue(self.doc_older.has_active_verified_badge)
        self.assertEqual(self.doc_older.version, 1)

        # Owner uploads new file version -> badge is dropped, version becomes 2, re-enters PENDING queue
        replace_document_file(
            user=self.student,
            document=self.doc_older,
            new_file=make_file("old_v2.pdf"),
        )
        self.doc_older.refresh_from_db()
        self.assertEqual(self.doc_older.version, 2)
        self.assertFalse(self.doc_older.has_active_verified_badge)
        self.assertEqual(self.doc_older.verify_status, Document.VerifyStatus.PENDING)

        queue_ids = [
            d.id for d in get_verification_queue(reviewer=self.ta, course=self.course)
        ]
        self.assertIn(self.doc_older.id, queue_ids)
