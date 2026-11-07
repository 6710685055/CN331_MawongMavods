"""US-12: owner edit and delete document flows."""

from pathlib import Path

from django.core.files.storage import default_storage
from django.urls import reverse

from ..models import Document, DocumentReport, DocumentReviewLog, DocumentVote
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    delete_document,
    update_document_metadata,
    upload_document,
    verify_document,
)
from .base import BaseDocumentTestCase, make_file


class US12DocumentManagementTests(BaseDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.document = upload_document(
            user=self.student,
            course=self.course,
            title="ชีทสรุปเดิม",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2568,
            semester=Document.Semester.FIRST,
            related_chapter="บทที่ 1",
            description="คำอธิบายเดิม",
            uploaded_file=make_file("us12-document.pdf"),
        )

    def _url(self, name):
        return reverse(f"documents:{name}", args=[self.course.id, self.document.id])

    def _metadata(self, **overrides):
        metadata = {
            "title": "ชีทสรุปใหม่",
            "doc_type": Document.DocType.SUMMARY,
            "academic_year": 2569,
            "semester": Document.Semester.SECOND,
            "related_chapter": "บทที่ 2-3",
            "description": "คำอธิบายใหม่",
        }
        metadata.update(overrides)
        return metadata

    def test_owner_can_edit_metadata_without_replacing_file(self):
        old_file_name = self.document.file.name

        updated = update_document_metadata(
            user=self.student,
            document=self.document,
            **self._metadata(title="  ชีทสรุปใหม่  ", description="  คำอธิบายใหม่  "),
        )

        self.assertEqual(updated.title, "ชีทสรุปใหม่")
        self.assertEqual(updated.doc_type, Document.DocType.SUMMARY)
        self.assertEqual(updated.academic_year, 2569)
        self.assertEqual(updated.semester, Document.Semester.SECOND)
        self.assertEqual(updated.related_chapter, "บทที่ 2-3")
        self.assertEqual(updated.description, "คำอธิบายใหม่")
        self.assertEqual(updated.version, 1)
        self.assertEqual(updated.file.name, old_file_name)

    def test_changing_document_type_resets_verification_and_requires_homework_confirmation(
        self,
    ):
        verify_document(reviewer=self.ta, document=self.document)
        self.document.refresh_from_db()
        self.assertTrue(self.document.has_active_verified_badge)

        with self.assertRaises(DocumentServiceError):
            update_document_metadata(
                user=self.student,
                document=self.document,
                **self._metadata(doc_type=Document.DocType.HOMEWORK),
            )

        updated = update_document_metadata(
            user=self.student,
            document=self.document,
            confirm_past_deadline=True,
            **self._metadata(doc_type=Document.DocType.HOMEWORK),
        )
        self.assertEqual(updated.verify_status, Document.VerifyStatus.NONE)
        self.assertFalse(updated.has_active_verified_badge)
        self.assertIsNone(updated.verified_by_id)
        self.assertIsNone(updated.verified_version)

        updated = update_document_metadata(
            user=self.student,
            document=updated,
            **self._metadata(doc_type=Document.DocType.EXAM),
        )
        self.assertEqual(updated.verify_status, Document.VerifyStatus.PENDING)

    def test_edit_form_rejects_invalid_year_and_requires_homework_confirmation(self):
        self.client.force_login(self.student)
        invalid_year = self.client.post(
            self._url("edit"),
            self._metadata(academic_year=2400),
        )
        self.assertEqual(invalid_year.status_code, 200)
        self.assertContains(invalid_year, "กรุณาระบุปีการศึกษาเป็น พ.ศ. ที่ถูกต้อง")

        missing_confirmation = self.client.post(
            self._url("edit"),
            self._metadata(doc_type=Document.DocType.HOMEWORK),
        )
        self.assertEqual(missing_confirmation.status_code, 200)
        self.assertContains(
            missing_confirmation, "กรุณายืนยันว่าการบ้านชิ้นนี้หมดกำหนดส่งแล้ว"
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.doc_type, Document.DocType.SUMMARY)

    def test_only_owner_can_open_edit_page_or_update_or_delete_document(self):
        self.client.force_login(self.student)
        detail = self.client.get(self._url("detail"))
        self.assertContains(detail, self._url("edit"))
        self.assertContains(detail, self._url("delete"))
        self.assertEqual(self.client.get(self._url("edit")).status_code, 200)
        edit_response = self.client.post(self._url("edit"), self._metadata())
        self.assertRedirects(edit_response, self._url("detail"))
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "ชีทสรุปใหม่")

        self.client.force_login(self.student2)
        self.assertEqual(self.client.get(self._url("edit")).status_code, 403)
        self.assertEqual(
            self.client.post(self._url("edit"), self._metadata()).status_code,
            403,
        )
        self.assertEqual(self.client.post(self._url("delete")).status_code, 403)

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self._url("edit")).status_code, 403)
        with self.assertRaises(DocumentPermissionError):
            update_document_metadata(
                user=self.student2,
                document=self.document,
                **self._metadata(),
            )
        with self.assertRaises(DocumentPermissionError):
            delete_document(user=self.student2, document=self.document)

    def test_delete_is_post_only_and_removes_file_and_cascaded_document_data(self):
        vote = DocumentVote.objects.create(
            document=self.document,
            user=self.student2,
            value=DocumentVote.Value.UP,
        )
        report = DocumentReport.objects.create(
            document=self.document,
            reporter=self.student2,
            reason=DocumentReport.Reason.SPAM,
            document_version=self.document.version,
        )
        review_log = DocumentReviewLog.objects.create(
            document=self.document,
            reviewer=self.ta,
            reviewer_name_snapshot=self.ta.full_name,
            reviewer_role_snapshot=Document.VerifierRole.TA,
            action=DocumentReviewLog.Action.VERIFY,
            document_version=self.document.version,
        )
        file_name = self.document.file.name
        file_path = Path(self.document.file.path)
        self.assertTrue(file_path.exists())
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self._url("delete")).status_code, 405)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._url("delete"))

        self.assertRedirects(
            response, reverse("documents:library", args=[self.course.id])
        )
        self.assertFalse(Document.objects.filter(pk=self.document.pk).exists())
        self.assertFalse(DocumentVote.objects.filter(pk=vote.pk).exists())
        self.assertFalse(DocumentReport.objects.filter(pk=report.pk).exists())
        self.assertFalse(DocumentReviewLog.objects.filter(pk=review_log.pk).exists())
        self.assertFalse(default_storage.exists(file_name))
