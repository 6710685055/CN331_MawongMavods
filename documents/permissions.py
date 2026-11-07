from courses.permissions import (
    is_course_member,
    is_course_staff,
    is_course_ta,
    is_course_teacher,
)

from .models import Document


def can_access_course_documents(user, course) -> bool:
    """Only users enrolled in the course may view, upload, or download documents (UC3)."""
    return is_course_member(user, course)


def can_pin_document(user, course) -> bool:
    """Only approved TAs or Teachers of the course may pin/unpin documents (UC3)."""
    return is_course_staff(user, course)


def can_access_review_queue(user, course) -> bool:
    """Only approved TAs or Teachers of the course may access the verification queue (UC4)."""
    return is_course_staff(user, course)


def get_reviewer_role_snapshot(user, course) -> str:
    """Return 'Teacher' or 'TA' snapshot string for a valid course reviewer."""
    if is_course_teacher(user, course):
        return Document.VerifierRole.TEACHER
    if is_course_ta(user, course):
        return Document.VerifierRole.TA
    return ""


def can_verify_document(user, document: Document) -> bool:
    """
    True if user is an approved TA/Teacher of the document's course,
    the document is verifiable (not homework), and user is NOT the uploader (UC4).
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if not document.is_verifiable:
        return False
    if document.uploader_id == user.id:
        return False
    return is_course_staff(user, document.course)


def can_revoke_verification(user, document: Document) -> bool:
    """True if reviewer can verify this document and it currently holds an active Verified badge."""
    return can_verify_document(user, document) and document.has_active_verified_badge


def can_see_hidden_documents(user, course) -> bool:
    """Approved TAs and Teachers of the course see documents hidden by reports (UC10)."""
    return is_course_staff(user, course)


def can_view_document(user, document: Document) -> bool:
    """
    Course members may see a document, except while it is hidden by reports (UC10):
    then only the owner and course TAs/Teachers may see it.
    """
    if document.is_removed or not can_access_course_documents(user, document.course):
        return False
    if not document.is_hidden:
        return True
    return document.uploader_id == user.id or can_see_hidden_documents(
        user, document.course
    )


def can_vote_or_report(user, document: Document) -> bool:
    """Course members may vote on / report a visible document they did not upload (UC10)."""
    return (
        can_access_course_documents(user, document.course)
        and document.uploader_id != user.id
        and not document.is_hidden
        and not document.is_removed
    )


def can_access_report_queue(user, course) -> bool:
    """Only approved TAs or Teachers of the course may open the reported-documents queue (UC14)."""
    return is_course_staff(user, course)


def can_moderate_reports(user, document: Document) -> bool:
    """Course staff may judge reports, except on a document they uploaded or one already removed (UC14)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return (
        not document.is_removed
        and document.uploader_id != user.id
        and can_access_report_queue(user, document.course)
    )


def can_view_review_details(user, document: Document) -> bool:
    """
    Only the document owner (uploader), course TAs, and course Teachers
    may see 'รอตรวจ'/'ต้องแก้ไข' statuses and reviewer comments (UC4).
    Other students in the course only see the 'Verified by ...' badge.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if document.uploader_id == user.id:
        return True
    return is_course_staff(user, document.course)
