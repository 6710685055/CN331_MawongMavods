from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from courses.models import Enrollment
from notifications.models import Notification

from ..constants import feedback as texts
from ..models import Document, DocumentReport, DocumentVote
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    replace_document_file,
    report_document,
    upload_document,
    vote_document,
    withdraw_report,
)
from ..services.feedback import _hide_if_threshold_reached
from .base import BaseDocumentTestCase, make_file

UP = DocumentVote.Value.UP
DOWN = DocumentVote.Value.DOWN
OTHER = DocumentReport.Reason.OTHER
SPAM = DocumentReport.Reason.SPAM


class UC10FeedbackTests(BaseDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.doc = upload_document(
            user=self.student,
            course=self.course,
            title="ชีทสรุปบทที่ 1",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("ch1.pdf"),
        )
        self.student3 = User.objects.create_user(
            email="student3@example.com",
            password="Password123!",
            first_name="สมศรี",
            last_name="ขยันดี",
            role=User.Role.STUDENT,
            email_verified=True,
        )
        Enrollment.objects.create(
            user=self.student3, course=self.course, role=Enrollment.Role.STUDENT
        )

    def _url(self, name):
        return reverse(f"documents:{name}", args=[self.course.id, self.doc.id])

    def _refresh(self):
        self.doc.refresh_from_db()
        return self.doc

    # --- Permissions -------------------------------------------------------

    def test_outsider_and_owner_cannot_vote_or_report(self):
        for user, message in (
            (self.outsider, texts.NOT_COURSE_MEMBER),
            (self.student, texts.OWNER_CANNOT_INTERACT),
        ):
            with self.assertRaisesMessage(DocumentPermissionError, message):
                vote_document(user=user, document=self.doc, value=UP)
            with self.assertRaisesMessage(DocumentPermissionError, message):
                report_document(user=user, document=self.doc, reason=SPAM)

        # Server-side check on the HTTP endpoints too
        self.client.force_login(self.outsider)
        response = self.client.post(
            self._url("vote"), {"value": "up"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(self._url("report"), {"reason": SPAM}).status_code, 403)
        self.assertFalse(DocumentVote.objects.exists())
        self.assertFalse(DocumentReport.objects.exists())

    def test_owner_does_not_see_vote_or_report_buttons(self):
        self.client.force_login(self.student)
        response = self.client.get(self._url("detail"))
        self.assertNotContains(response, "data-vote-button")
        self.assertNotContains(response, self._url("report"))

        self.client.force_login(self.student2)
        response = self.client.get(self._url("detail"))
        self.assertContains(response, "data-vote-button")
        self.assertContains(response, self._url("report"))

    # --- Voting -----------------------------------------------------------

    def test_vote_toggle_switch_and_net_score(self):
        self.assertEqual(vote_document(user=self.student2, document=self.doc, value=UP), (1, UP))
        self.assertEqual(vote_document(user=self.student3, document=self.doc, value=DOWN), (0, DOWN))

        # Switching does not add a second vote
        self.assertEqual(vote_document(user=self.student2, document=self.doc, value=DOWN), (-2, DOWN))
        self.assertEqual(DocumentVote.objects.filter(document=self.doc).count(), 2)

        # Same button again cancels
        self.assertEqual(vote_document(user=self.student2, document=self.doc, value=DOWN), (-1, None))
        self.assertEqual(self._refresh().vote_score, -1)

    def test_vote_endpoint_returns_json_and_shows_user_vote(self):
        self.client.force_login(self.student2)
        response = self.client.post(
            self._url("vote"), {"value": "up"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"score": 1, "my_vote": "up"})

        invalid = self.client.post(
            self._url("vote"), {"value": "sideways"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(invalid.status_code, 400)

        detail = self.client.get(self._url("detail"))
        self.assertContains(detail, 'class="vote-btn active"')

    def test_duplicate_vote_blocked_by_database(self):
        DocumentVote.objects.create(document=self.doc, user=self.student2, value=UP)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentVote.objects.create(document=self.doc, user=self.student2, value=DOWN)

    # --- Reporting --------------------------------------------------------

    def test_report_requires_reason_and_detail_for_other(self):
        with self.assertRaisesMessage(DocumentServiceError, texts.REPORT_REASON_REQUIRED):
            report_document(user=self.student2, document=self.doc, reason="")
        with self.assertRaises(DocumentServiceError):
            report_document(user=self.student2, document=self.doc, reason=OTHER, detail="  ")

        report = report_document(
            user=self.student2, document=self.doc, reason=OTHER, detail="ไฟล์เปิดไม่ได้"
        )
        self.assertEqual(report.status, DocumentReport.Status.OPEN)
        self.assertEqual(report.document_version, self.doc.version)

        # The form layer rejects it as well
        self.client.force_login(self.student3)
        self.client.post(self._url("report"), {"reason": OTHER, "detail": ""})
        self.assertFalse(DocumentReport.objects.filter(reporter=self.student3).exists())

    def test_duplicate_open_report_rejected_and_db_constraint(self):
        report_document(user=self.student2, document=self.doc, reason=SPAM)
        with self.assertRaisesMessage(DocumentServiceError, texts.REPORT_DUPLICATE):
            report_document(user=self.student2, document=self.doc, reason=SPAM)

        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentReport.objects.create(
                document=self.doc,
                reporter=self.student2,
                reason=SPAM,
                document_version=self.doc.version,
            )

    def test_report_endpoint_marks_document_as_reported(self):
        self.client.force_login(self.student2)
        self.client.post(self._url("report"), {"reason": SPAM})
        detail = self.client.get(self._url("detail"))
        self.assertContains(detail, "Report แล้ว")
        self.assertContains(detail, self._url("withdraw_report"))

    def test_withdraw_report(self):
        report_document(user=self.student2, document=self.doc, reason=SPAM)
        withdraw_report(user=self.student2, document=self.doc)
        self.assertEqual(
            DocumentReport.objects.get(reporter=self.student2).status,
            DocumentReport.Status.WITHDRAWN,
        )
        with self.assertRaisesMessage(DocumentServiceError, texts.REPORT_NOTHING_TO_WITHDRAW):
            withdraw_report(user=self.student2, document=self.doc)

        # Can report again after withdrawing
        report_document(user=self.student2, document=self.doc, reason=SPAM)

    # --- Hide threshold (threshold comes from settings, not hardcoded) ----

    @override_settings(DOCUMENT_REPORT_HIDE_THRESHOLD=2)
    def test_threshold_hides_document_and_notifies_once(self):
        report_document(user=self.student2, document=self.doc, reason=SPAM)
        self.assertFalse(self._refresh().is_hidden)

        report_document(user=self.student3, document=self.doc, reason=SPAM)
        self.assertTrue(self._refresh().is_hidden)
        self.assertIsNotNone(self.doc.hidden_at)

        hidden_notes = Notification.objects.filter(
            notification_type=Notification.Type.DOCUMENT_HIDDEN
        )
        self.assertEqual(
            set(hidden_notes.values_list("recipient_id", flat=True)),
            {self.student.id, self.ta.id, self.ta2.id, self.teacher.id},
        )
        self.assertEqual(hidden_notes.count(), 4)  # TA_PENDING is not staff

        owner_note = hidden_notes.get(recipient=self.student)
        for reporter in (self.student2, self.student3):
            self.assertNotIn(reporter.first_name, owner_note.title + owner_note.message)

        # Re-running the threshold check (e.g. a concurrent report) does not notify again
        self.assertFalse(_hide_if_threshold_reached(self.doc))
        self.assertEqual(hidden_notes.count(), 4)

    @override_settings(DOCUMENT_REPORT_HIDE_THRESHOLD=1)
    def test_hidden_document_visibility_and_no_voting(self):
        report_document(user=self.student2, document=self.doc, reason=SPAM)
        self.assertTrue(self._refresh().is_hidden)

        # Other students: not in library, detail/download 404, cannot vote
        self.client.force_login(self.student3)
        library = self.client.get(reverse("documents:library", args=[self.course.id]))
        self.assertNotContains(library, self.doc.title)
        self.assertEqual(self.client.get(self._url("detail")).status_code, 404)
        self.assertEqual(self.client.get(self._url("download")).status_code, 404)
        with self.assertRaisesMessage(DocumentPermissionError, texts.DOCUMENT_HIDDEN_NO_INTERACT):
            vote_document(user=self.student3, document=self.doc, value=UP)

        # Owner, TA and Teacher still see it
        for user in (self.student, self.ta, self.teacher):
            self.client.force_login(user)
            library = self.client.get(reverse("documents:library", args=[self.course.id]))
            self.assertContains(library, self.doc.title)
            detail = self.client.get(self._url("detail"))
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, "ซ่อนชั่วคราว")
            self.assertNotContains(detail, self.student2.full_name)

    @override_settings(DOCUMENT_REPORT_HIDE_THRESHOLD=2)
    def test_withdraw_keeps_hidden_until_no_open_reports_remain(self):
        report_document(user=self.student2, document=self.doc, reason=SPAM)
        report_document(user=self.student3, document=self.doc, reason=SPAM)
        self.assertTrue(self._refresh().is_hidden)

        withdraw_report(user=self.student2, document=self.doc)
        self.assertTrue(self._refresh().is_hidden)

        withdraw_report(user=self.student3, document=self.doc)
        self.assertFalse(self._refresh().is_hidden)
        self.assertIsNone(self.doc.hidden_at)

    @override_settings(DOCUMENT_REPORT_HIDE_THRESHOLD=1)
    def test_reporter_redirected_to_library_when_their_report_hides_document(self):
        self.client.force_login(self.student2)
        response = self.client.post(self._url("report"), {"reason": SPAM})
        self.assertRedirects(response, reverse("documents:library", args=[self.course.id]))

    # --- Dismissed reports (resolution set by UC14) -------------------------

    def test_dismissed_report_blocks_rereport_until_new_version(self):
        report = report_document(user=self.student2, document=self.doc, reason=SPAM)
        DocumentReport.objects.filter(pk=report.pk).update(
            status=DocumentReport.Status.RESOLVED,
            resolution=DocumentReport.Resolution.DISMISSED,
        )
        with self.assertRaisesMessage(DocumentServiceError, texts.REPORT_ALREADY_DISMISSED):
            report_document(user=self.student2, document=self.doc, reason=SPAM)

        replace_document_file(user=self.student, document=self.doc, new_file=make_file("ch1_v2.pdf"))
        new_report = report_document(user=self.student2, document=self.doc, reason=SPAM)
        self.assertEqual(new_report.document_version, 2)
