from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError


def get_allowed_extensions() -> tuple[str, ...]:
    return tuple(
        ext.lower() for ext in getattr(settings, "DOCUMENT_ALLOWED_EXTENSIONS", ())
    )


def get_allowed_extensions_display() -> str:
    return ", ".join(ext.lstrip(".").upper() for ext in get_allowed_extensions())


def get_max_file_size_mb() -> int:
    return int(getattr(settings, "DOCUMENT_MAX_FILE_SIZE_MB", 50))


def get_max_file_size_bytes() -> int:
    return int(
        getattr(
            settings,
            "DOCUMENT_MAX_FILE_SIZE_BYTES",
            get_max_file_size_mb() * 1024 * 1024,
        )
    )


def validate_document_file(uploaded_file) -> None:
    """Validate uploaded document extension and file size based on project settings."""
    if not uploaded_file:
        raise ValidationError("กรุณาแนบไฟล์เอกสาร")

    ext = Path(uploaded_file.name).suffix.lower()
    allowed_exts = get_allowed_extensions()
    if not ext or ext not in allowed_exts:
        raise ValidationError(
            f"ชนิดไฟล์ไม่รองรับ ({ext or 'ไม่มีนามสกุล'}) ระบบรองรับเฉพาะไฟล์ {get_allowed_extensions_display()} เท่านั้น"
        )

    size = getattr(uploaded_file, "size", 0) or 0
    if size <= 0:
        raise ValidationError("ไฟล์ที่อัปโหลดว่างเปล่า กรุณาเลือกไฟล์ที่ถูกต้อง")

    max_bytes = get_max_file_size_bytes()
    if size > max_bytes:
        raise ValidationError(
            f"ขนาดไฟล์เกินกำหนด (สูงสุดไม่เกิน {get_max_file_size_mb()}MB)"
        )
