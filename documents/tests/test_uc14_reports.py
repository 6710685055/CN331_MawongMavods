from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from courses.models import Enrollment
from notifications.models import Notification

from ..constants import moderation as texts
from ..models import Document, DocumentReport, DocumentReportDecision
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    close_reports_for_owner_deletion,
    get_reported_queue,
    replace_document_file,
    report_document,
    resolve_reports,
    upload_document,
    verify_document,
    withdraw_report,
)
from .base import BaseDocumentTestCase, make_file

Resolution = DocumentReport.Resolution
SPAM = DocumentReport.Reason.SPAM
INCORRECT = DocumentReport.Reason.INCORRECT


@override_settings(DOCUMENT_REPORT_HIDE_THRESHOLD=2)
class UC14ReviewReportedDocumentsTests(BaseDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.student3 = self._make_student("student3@example.com", "สมศรี")
        self.student4 = self._make_student("student4@example.com", "สมปอง")

        # Owner: student. Reported by two students -> hidden (threshold 2).
        self.doc = self._upload(
            self.student, "ชีทสรุปที่ถูกซ่อน", Document.DocType.SUMMARY
        )
        report_document(user=self.student2, document=self.doc, reason=SPAM)
        report_document(
            user=self.student3, document=self.doc, reason=INCORRECT, detail="สูตรผิด"
        )

        # Reported once -> still visible.
        self.doc_visible = self._upload(
            self.student2, "การบ้านที่ถูก Report", Document.DocType.HOMEWORK
        )
        report_document(user=self.student3, document=self.doc_visible, reason=SPAM)

        # Uploaded by TA1 and reported.
        self.doc_by_ta = self._upload(self.ta, "ชีทของ TA1", Document.DocType.EXAM)
        report_document(user=self.student, document=self.doc_by_ta, reason=SPAM)

        self.doc.refresh_from_db()

    # --- helpers ---------------------------------------------------------

    def _make_student(self, email, first_name):
        user = User.objects.create_user(
            email=email,
            password="Password123!",
            first_name=first_name,
            last_name="ทดสอบ",
            role=User.Role.STUDENT,
            email_verified=True,
        )
        Enrollment.objects.create(
            user=user, course=self.course, role=Enrollment.Role.STUDENT
        )
        return user

    def _upload(self, user, title, doc_type):
        return upload_document(
            user=user,
            course=self.course,
            title=title,
            doc_type=doc_type,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file(f"{doc_type}-{user.pk}.pdf"),
            confirm_past_deadline=True,
        )

    def _url(self, name, doc=None):
        doc = doc or self.doc
        return reverse(f"documents:{name}", args=[self.course.id, doc.id])

    def _resolve(self, outcome, reviewer=None, doc=None, **kwargs):
        doc = doc or self.doc
        with self.captureOnCommitCallbacks(execute=True):
            decision = resolve_reports(
                reviewer=reviewer or self.ta2, document=doc, outcome=outcome, **kwargs
            )
        doc.refresh_from_db()
        return decision

    def _notifications(self, notification_type):
        return Notification.objects.filter(notification_type=notification_type)

    # --- Access ------------------------------------------------------------

    def test_only_approved_staff_can_access_queue_and_actions(self):
        queue_url = reverse("documents:reported_queue", args=[self.course.id])
        for user in (self.student4, self.ta_pending, self.outsider):
            self.client.force_login(user)
            self.assertEqual(self.client.get(queue_url).status_code, 403)
            self.assertEqual(
                self.client.get(self._url("report_review")).status_code, 403
            )
            response = self.client.post(
                self._url("resolve_reports"), {"outcome": Resolution.DISMISSED}
            )
            self.assertEqual(response.status_code, 403)
            with self.assertRaises(DocumentPermissionError):
                resolve_reports(
                    reviewer=user, document=self.doc, outcome=Resolution.DISMISSED
                )

        self.assertEqual(DocumentReportDecision.objects.count(), 0)

        for user in (self.ta, self.teacher):
            self.client.force_login(user)
            self.assertEqual(self.client.get(queue_url).status_code, 200)

    def test_queue_order_counts_reasons_and_excludes_own_uploads(self):
        queue = list(get_reported_queue(reviewer=self.teacher, course=self.course))
        self.assertEqual(queue[0], self.doc)  # hidden first
        self.assertEqual(queue[0].open_report_count, 2)
        self.assertEqual(
            {d.id for d in queue}, {self.doc.id, self.doc_visible.id, self.doc_by_ta.id}
        )

        # TA1 does not see (and cannot judge) the document they uploaded
        ta1_queue = get_reported_queue(reviewer=self.ta, course=self.course)
        self.assertNotIn(self.doc_by_ta, ta1_queue)
        with self.assertRaisesMessage(
            DocumentPermissionError, texts.CANNOT_MODERATE_OWN
        ):
            resolve_reports(
                reviewer=self.ta, document=self.doc_by_ta, outcome=Resolution.DISMISSED
            )

        self.client.force_login(self.teacher)
        page = self.client.get(
            reverse("documents:reported_queue", args=[self.course.id])
        )
        self.assertContains(page, DocumentReport.Reason.SPAM.label)
        self.assertContains(page, DocumentReport.Reason.INCORRECT.label)
        self.assertContains(page, "ซ่อนชั่วคราว")

    def test_reviewer_sees_reporter_names_but_owner_cannot(self):
        self.client.force_login(self.ta2)
        page = self.client.get(self._url("report_review"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.student2.full_name)
        self.assertContains(page, "สูตรผิด")

        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self._url("report_review")).status_code, 403)
        detail = self.client.get(self._url("detail"))
        self.assertNotContains(detail, self.student2.full_name)
        self.assertNotContains(detail, self.student3.full_name)

    # --- Outcomes ----------------------------------------------------------

    def test_dismiss_unhides_keeps_badge_and_resets_count(self):
        Document.objects.filter(pk=self.doc.pk).update(is_hidden=False)
        verify_document(reviewer=self.teacher, document=self.doc)
        Document.objects.filter(pk=self.doc.pk).update(is_hidden=True)

        decision = self._resolve(Resolution.DISMISSED)

        self.assertFalse(self.doc.is_hidden)
        self.assertTrue(self.doc.has_active_verified_badge)
        self.assertFalse(
            DocumentReport.objects.filter(
                document=self.doc, status=DocumentReport.Status.OPEN
            ).exists()
        )
        self.assertEqual(decision.report_count, 2)
        self.assertEqual(
            set(
                DocumentReport.objects.filter(document=self.doc).values_list(
                    "resolution", flat=True
                )
            ),
            {Resolution.DISMISSED},
        )
        # Dismissed reporters cannot re-report the same version (UC10 rule)
        with self.assertRaises(DocumentServiceError):
            report_document(user=self.student2, document=self.doc, reason=SPAM)

    def test_revision_requires_reason_drops_badge_and_returns_to_pending_after_fix(
        self,
    ):
        with self.assertRaisesMessage(
            DocumentServiceError,
            texts.REASON_REQUIRED.format(outcome=Resolution.REVISION.label),
        ):
            resolve_reports(
                reviewer=self.ta2, document=self.doc, outcome=Resolution.REVISION
            )

        Document.objects.filter(pk=self.doc.pk).update(is_hidden=False)
        verify_document(reviewer=self.teacher, document=self.doc)
        Document.objects.filter(pk=self.doc.pk).update(is_hidden=True)

        self._resolve(Resolution.REVISION, reason="แก้สูตรบทที่ 2")
        self.assertEqual(self.doc.verify_status, Document.VerifyStatus.NEEDS_REVISION)
        self.assertFalse(self.doc.has_active_verified_badge)
        self.assertTrue(self.doc.is_hidden)
        self.assertEqual(self.doc.latest_review_comment, "แก้สูตรบทที่ 2")

        replace_document_file(
            user=self.student, document=self.doc, new_file=make_file("fixed.pdf")
        )
        self.assertEqual(self.doc.verify_status, Document.VerifyStatus.PENDING)
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.is_hidden)
        self.assertIsNone(self.doc.hidden_at)

    def test_revision_hides_from_other_students_until_owner_replaces_file(self):
        # doc_visible: uploaded by student2, reported once by student3, not hidden yet.
        self._resolve(Resolution.REVISION, doc=self.doc_visible, reason="ไฟล์ผิดบท")
        self.assertTrue(self.doc_visible.is_hidden)

        library_url = reverse("documents:library", args=[self.course.id])
        self.client.force_login(self.student3)
        self.assertEqual(
            self.client.get(self._url("detail", self.doc_visible)).status_code, 404
        )
        self.assertEqual(
            self.client.get(self._url("download", self.doc_visible)).status_code, 404
        )
        self.assertNotContains(self.client.get(library_url), self.doc_visible.title)

        for user in (self.student2, self.ta2):  # owner and course staff
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(self._url("download", self.doc_visible)).status_code,
                200,
            )
        self.client.force_login(self.student2)
        self.assertContains(
            self.client.get(self._url("detail", self.doc_visible)),
            "จนกว่าเจ้าของจะอัปโหลดไฟล์ใหม่",
        )

        replace_document_file(
            user=self.student2, document=self.doc_visible, new_file=make_file("hw2.pdf")
        )
        self.client.force_login(self.student3)
        self.assertEqual(
            self.client.get(self._url("download", self.doc_visible)).status_code, 200
        )
        self.assertContains(self.client.get(library_url), self.doc_visible.title)

    def test_replacing_file_keeps_threshold_hidden_document_hidden(self):
        # self.doc is hidden by open reports and still waits for a reviewer.
        replace_document_file(
            user=self.student, document=self.doc, new_file=make_file("new.pdf")
        )
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.is_hidden)

        self.client.force_login(self.student4)
        self.assertEqual(self.client.get(self._url("download")).status_code, 404)

    def test_revision_of_homework_resets_after_owner_replaces_file(self):
        self._resolve(Resolution.REVISION, doc=self.doc_visible, reason="ไฟล์ผิดบท")
        self.assertEqual(
            self.doc_visible.verify_status, Document.VerifyStatus.NEEDS_REVISION
        )

        replace_document_file(
            user=self.student2, document=self.doc_visible, new_file=make_file("hw2.pdf")
        )
        self.assertEqual(self.doc_visible.verify_status, Document.VerifyStatus.NONE)

    def test_remove_requires_reason_and_confirmation_and_hides_everywhere(self):
        with self.assertRaises(DocumentServiceError):
            resolve_reports(
                reviewer=self.ta2,
                document=self.doc,
                outcome=Resolution.REMOVED,
                confirmed=True,
            )
        with self.assertRaisesMessage(
            DocumentServiceError, texts.REMOVE_CONFIRM_REQUIRED
        ):
            resolve_reports(
                reviewer=self.ta2,
                document=self.doc,
                outcome=Resolution.REMOVED,
                reason="ละเมิดลิขสิทธิ์",
            )

        # A Verified badge does not protect the document from removal
        Document.objects.filter(pk=self.doc.pk).update(is_hidden=False)
        verify_document(reviewer=self.teacher, document=self.doc)
        file_name = self.doc.file.name
        self.assertTrue(default_storage.exists(file_name))

        self._resolve(Resolution.REMOVED, reason="ละเมิดลิขสิทธิ์", confirmed=True)

        self.assertTrue(self.doc.is_removed)
        self.assertEqual(self.doc.removed_by, self.ta2)
        self.assertFalse(Document.objects.filter(pk=self.doc.pk).exists())
        self.assertTrue(Document.all_objects.filter(pk=self.doc.pk).exists())
        self.assertFalse(default_storage.exists(file_name))

        for user in (self.student4, self.ta, self.teacher):
            self.client.force_login(user)
            library = self.client.get(
                reverse("documents:library", args=[self.course.id])
            )
            self.assertNotContains(library, self.doc.title)
            self.assertEqual(self.client.get(self._url("detail")).status_code, 404)
            self.assertEqual(self.client.get(self._url("download")).status_code, 404)

    def test_remove_via_http_requires_confirm_checkbox(self):
        self.client.force_login(self.teacher)
        self.client.post(
            self._url("resolve_reports"),
            {"outcome": Resolution.REMOVED, "reason": "สแปม"},
        )
        self.assertFalse(Document.all_objects.get(pk=self.doc.pk).is_removed)

        response = self.client.post(
            self._url("resolve_reports"),
            {"outcome": Resolution.REMOVED, "reason": "สแปม", "confirm_remove": "on"},
        )
        self.assertRedirects(
            response, reverse("documents:reported_queue", args=[self.course.id])
        )
        self.assertTrue(Document.all_objects.get(pk=self.doc.pk).is_removed)

    # --- Record keeping and notifications ---------------------------------

    def test_decision_closes_all_reports_and_records_who_what_why_when(self):
        decision = self._resolve(Resolution.REVISION, reason="เนื้อหาผิด")

        reports = DocumentReport.objects.filter(document=self.doc)
        self.assertTrue(
            all(r.status == DocumentReport.Status.RESOLVED for r in reports)
        )
        self.assertTrue(
            all(r.decision_id == decision.id and r.closed_at for r in reports)
        )

        self.assertEqual(decision.reviewer, self.ta2)
        self.assertEqual(decision.reviewer_name_snapshot, self.ta2.full_name)
        self.assertEqual(decision.reviewer_role_snapshot, Document.VerifierRole.TA)
        self.assertEqual(decision.outcome, Resolution.REVISION)
        self.assertEqual(decision.reason, "เนื้อหาผิด")
        self.assertIsNotNone(decision.created_at)

    def test_owner_and_all_reporters_notified_for_every_outcome(self):
        cases = (
            (
                self.doc,
                self.student,
                {"outcome": Resolution.REVISION, "reason": "แก้หน้า 3"},
                Notification.Type.DOCUMENT_NEEDS_REVISION,
                {self.student2, self.student3},
            ),
            (
                self.doc_visible,
                self.student2,
                {"outcome": Resolution.DISMISSED},
                Notification.Type.DOCUMENT_REPORT_DISMISSED,
                {self.student3},
            ),
            (
                self.doc_by_ta,
                self.ta,
                {"outcome": Resolution.REMOVED, "reason": "สแปม", "confirmed": True},
                Notification.Type.DOCUMENT_REMOVED,
                {self.student},
            ),
        )
        for doc, owner, kwargs, owner_type, reporters in cases:
            with self.subTest(outcome=kwargs["outcome"]):
                outcome = kwargs.pop("outcome")
                self._resolve(outcome, reviewer=self.teacher, doc=doc, **kwargs)

                owner_note = self._notifications(owner_type).get(recipient=owner)
                if kwargs.get("reason"):
                    self.assertIn(kwargs["reason"], owner_note.message)
                for reporter in reporters:
                    self.assertNotIn(
                        reporter.full_name, owner_note.title + owner_note.message
                    )

                resolved = self._notifications(
                    Notification.Type.DOCUMENT_REPORT_RESOLVED
                ).filter(title__contains=doc.title)
                self.assertEqual(set(n.recipient for n in resolved), reporters)

    def test_second_concurrent_decision_is_rejected_and_not_recorded(self):
        self._resolve(Resolution.DISMISSED, reviewer=self.ta2)
        notes_before = Notification.objects.count()

        with self.assertRaisesMessage(DocumentServiceError, texts.ALREADY_HANDLED):
            self._resolve(
                Resolution.REMOVED, reviewer=self.teacher, reason="x", confirmed=True
            )

        self.assertEqual(
            DocumentReportDecision.objects.filter(document=self.doc).count(), 1
        )
        self.assertEqual(Notification.objects.count(), notes_before)
        self.assertFalse(self.doc.is_removed)

        # Via HTTP the second reviewer is told it was already handled
        report_document(user=self.student4, document=self.doc, reason=SPAM)
        self._resolve(Resolution.DISMISSED, reviewer=self.ta2)
        self.client.force_login(self.teacher)
        response = self.client.post(
            self._url("resolve_reports"), {"outcome": Resolution.DISMISSED}, follow=True
        )
        self.assertContains(response, texts.ALREADY_HANDLED)

    def test_owner_deletion_hook_closes_reports_and_notifies_reporters(self):
        with self.assertRaises(DocumentPermissionError):
            close_reports_for_owner_deletion(document=self.doc, owner=self.student2)

        with self.captureOnCommitCallbacks(execute=True):
            decision = close_reports_for_owner_deletion(
                document=self.doc, owner=self.student
            )

        self.assertEqual(decision.outcome, Resolution.OWNER_DELETED)
        self.assertFalse(
            DocumentReport.objects.filter(
                document=self.doc, status=DocumentReport.Status.OPEN
            ).exists()
        )
        notified = set(
            self._notifications(Notification.Type.DOCUMENT_REPORT_RESOLVED).values_list(
                "recipient_id", flat=True
            )
        )
        self.assertEqual(notified, {self.student2.id, self.student3.id})
        # Nothing left to close
        self.assertIsNone(
            close_reports_for_owner_deletion(document=self.doc, owner=self.student)
        )

    # --- Owner deletes via US12 (hard delete) ------------------------------

    def test_owner_delete_via_us12_notifies_reporters_and_links_to_library(self):
        doc_id = self.doc.id
        self.client.force_login(self.student)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._url("delete"))

        library_url = reverse("documents:library", args=[self.course.id])
        self.assertRedirects(response, library_url)
        self.assertFalse(Document.all_objects.filter(pk=doc_id).exists())

        resolved = self._notifications(Notification.Type.DOCUMENT_REPORT_RESOLVED)
        self.assertEqual(
            sorted(resolved.values_list("recipient_id", flat=True)),
            sorted([self.student2.id, self.student3.id]),
        )
        for notification in resolved:
            # The detail page is a 404 now, so the link points to the course library.
            self.assertEqual(notification.target_url, library_url)

        # The owner acted themselves: no decision notification for them,
        # and nothing they receive names the reporters.
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.student,
                notification_type__in=[
                    Notification.Type.DOCUMENT_REPORT_DISMISSED,
                    Notification.Type.DOCUMENT_NEEDS_REVISION,
                    Notification.Type.DOCUMENT_REMOVED,
                    Notification.Type.DOCUMENT_REPORT_RESOLVED,
                ],
            ).exists()
        )
        for notification in Notification.objects.filter(recipient=self.student):
            for reporter in (self.student2, self.student3):
                self.assertNotIn(
                    reporter.full_name, notification.title + notification.message
                )

    def test_owner_delete_without_open_reports_sends_no_report_notifications(self):
        withdraw_report(user=self.student3, document=self.doc_visible)
        self.client.force_login(self.student2)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._url("delete", doc=self.doc_visible))

        self.assertRedirects(
            response, reverse("documents:library", args=[self.course.id])
        )
        self.assertFalse(Document.all_objects.filter(pk=self.doc_visible.pk).exists())
        self.assertFalse(
            self._notifications(Notification.Type.DOCUMENT_REPORT_RESOLVED).exists()
        )
