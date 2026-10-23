"""UC3: Upload & Share Document."""

from unittest.mock import patch

from django.urls import reverse

from ..models import Document
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    list_course_documents,
    toggle_document_pin,
    upload_document,
)
from .base import BaseDocumentTestCase, make_file


class UC3UploadAndShareDocumentTests(BaseDocumentTestCase):
    def test_only_enrolled_users_can_access_upload_and_download(self):
        doc = upload_document(
            user=self.student,
            course=self.course,
            title="สรุปบทที่ 1",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("ch1.pdf"),
        )

        # Non-enrolled user is rejected on server side for library, upload, and download
        self.client.force_login(self.outsider)
        res_lib = self.client.get(reverse("documents:library", args=[self.course.id]))
        self.assertEqual(res_lib.status_code, 403)

        res_up = self.client.post(
            reverse("documents:upload", args=[self.course.id]),
            {
                "title": "แอบอัปโหลด",
                "doc_type": Document.DocType.SUMMARY,
                "academic_year": 2569,
                "semester": Document.Semester.FIRST,
                "file": make_file("hack.pdf"),
            },
        )
        self.assertEqual(res_up.status_code, 403)

        res_dl = self.client.get(
            reverse("documents:download", args=[self.course.id, doc.id])
        )
        self.assertEqual(res_dl.status_code, 403)

        # Enrolled student can access library and download
        self.client.force_login(self.student2)
        res_ok_lib = self.client.get(
            reverse("documents:library", args=[self.course.id])
        )
        self.assertEqual(res_ok_lib.status_code, 200)
        self.assertContains(res_ok_lib, "สรุปบทที่ 1")

        res_ok_dl = self.client.get(
            reverse("documents:download", args=[self.course.id, doc.id])
        )
        self.assertEqual(res_ok_dl.status_code, 200)
        res_ok_dl.close()

    def test_file_type_and_size_validation(self):
        # Supported extensions: PDF, DOCX, PPTX, PNG, JPG
        for ext in ("pdf", "docx", "pptx", "png", "jpg"):
            doc = upload_document(
                user=self.student,
                course=self.course,
                title=f"ไฟล์ {ext}",
                doc_type=Document.DocType.SUMMARY,
                academic_year=2569,
                semester=Document.Semester.FIRST,
                uploaded_file=make_file(f"sample.{ext}"),
            )
            self.assertEqual(doc.version, 1)

        # Unsupported extension -> rejected with reason
        with self.assertRaises(DocumentServiceError) as ctx_ext:
            upload_document(
                user=self.student,
                course=self.course,
                title="ไฟล์อันตราย",
                doc_type=Document.DocType.SUMMARY,
                academic_year=2569,
                semester=Document.Semester.FIRST,
                uploaded_file=make_file("malware.exe"),
            )
        self.assertIn("ชนิดไฟล์ไม่รองรับ", str(ctx_ext.exception))
        self.assertIn("PDF, DOCX, PPTX, PNG, JPG", str(ctx_ext.exception))

        # File > 50MB -> rejected with reason
        too_big = make_file("huge.pdf", size=(50 * 1024 * 1024) + 1)
        with self.assertRaises(DocumentServiceError) as ctx_size:
            upload_document(
                user=self.student,
                course=self.course,
                title="ไฟล์ใหญ่เกิน",
                doc_type=Document.DocType.SUMMARY,
                academic_year=2569,
                semester=Document.Semester.FIRST,
                uploaded_file=too_big,
            )
        self.assertIn("50MB", str(ctx_size.exception))

    def test_initial_statuses_and_homework_confirmation(self):
        # Summary and Exam start as PENDING, vote_score=0
        summary_doc = upload_document(
            user=self.student,
            course=self.course,
            title="ชีทสรุป Midterm",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("summary.pdf"),
        )
        self.assertEqual(summary_doc.verify_status, Document.VerifyStatus.PENDING)
        self.assertEqual(summary_doc.vote_score, 0)
        self.assertEqual(summary_doc.uploader, self.student)

        exam_doc = upload_document(
            user=self.student,
            course=self.course,
            title="แนวข้อสอบ Final",
            doc_type=Document.DocType.EXAM,
            academic_year=2569,
            semester=Document.Semester.SECOND,
            uploaded_file=make_file("exam.pdf"),
        )
        self.assertEqual(exam_doc.verify_status, Document.VerifyStatus.PENDING)

        # Homework without confirmation is rejected
        with self.assertRaises(DocumentServiceError) as ctx_hw:
            upload_document(
                user=self.student,
                course=self.course,
                title="การบ้านบทที่ 2",
                doc_type=Document.DocType.HOMEWORK,
                academic_year=2569,
                semester=Document.Semester.FIRST,
                uploaded_file=make_file("hw.pdf"),
                confirm_past_deadline=False,
            )
        self.assertIn("หมดกำหนดส่งแล้ว", str(ctx_hw.exception))

        # Homework with confirmation succeeds and has verify_status = NONE
        hw_doc = upload_document(
            user=self.student,
            course=self.course,
            title="การบ้านบทที่ 2",
            doc_type=Document.DocType.HOMEWORK,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("hw.pdf"),
            confirm_past_deadline=True,
        )
        self.assertEqual(hw_doc.verify_status, Document.VerifyStatus.NONE)
        self.assertFalse(hw_doc.is_verifiable)

    def test_failed_upload_leaves_no_dangling_record(self):
        before_count = Document.objects.count()
        with patch.object(Document, "save", side_effect=RuntimeError("Disk error")):
            with self.assertRaises(DocumentServiceError):
                upload_document(
                    user=self.student,
                    course=self.course,
                    title="อัปโหลดพังกลางทาง",
                    doc_type=Document.DocType.SUMMARY,
                    academic_year=2569,
                    semester=Document.Semester.FIRST,
                    uploaded_file=make_file("fail.pdf"),
                )
        self.assertEqual(Document.objects.count(), before_count)

    def test_pin_and_unpin_by_ta_and_teacher_only_and_ordering(self):
        unpinned_doc = upload_document(
            user=self.student,
            course=self.course,
            title="เอกสารทั่วไป",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("normal.pdf"),
        )
        pinned_by_ta = upload_document(
            user=self.ta,
            course=self.course,
            title="เอกสารปักหมุดโดย TA",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("pinned_ta.pdf"),
            is_pinned=True,
        )
        self.assertTrue(pinned_by_ta.is_pinned)

        # Student and TA_PENDING cannot pin during upload or via toggle_document_pin
        for non_staff in (self.student, self.ta_pending):
            with self.assertRaises(DocumentPermissionError):
                toggle_document_pin(user=non_staff, document=unpinned_doc)

            self.client.force_login(non_staff)
            res = self.client.post(
                reverse(
                    "documents:toggle_pin", args=[self.course.id, unpinned_doc.id]
                )
            )
            self.assertEqual(res.status_code, 403)

        # Teacher can pin and unpin any document in the course
        toggle_document_pin(user=self.teacher, document=unpinned_doc, pinned=True)
        unpinned_doc.refresh_from_db()
        self.assertTrue(unpinned_doc.is_pinned)

        # Pinned documents appear first in library
        newer_unpinned = upload_document(
            user=self.student2,
            course=self.course,
            title="เอกสารใหม่แต่ไม่ปักหมุด",
            doc_type=Document.DocType.SUMMARY,
            academic_year=2569,
            semester=Document.Semester.FIRST,
            uploaded_file=make_file("newer.pdf"),
        )
        docs = list(list_course_documents(user=self.student, course=self.course))
        self.assertEqual(docs[-1].id, newer_unpinned.id)
        self.assertTrue(docs[0].is_pinned)
        self.assertTrue(docs[1].is_pinned)

        # Unpinning works
        toggle_document_pin(user=self.ta, document=unpinned_doc, pinned=False)
        unpinned_doc.refresh_from_db()
        self.assertFalse(unpinned_doc.is_pinned)
