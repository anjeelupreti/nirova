"""Storing a file, and deciding who may open it.

The access rule is the whole module and it is one sentence: **a document
inherits the access rules of the thing it is attached to.** A file about a
patient is exactly as sensitive as that patient's record, so it is governed by
the same care relationship rather than by a second permission model that would
drift out of step with the first within a month.

Everything else here is bookkeeping around that.
"""

import logging

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditAction, AuditSeverity
# record: a document is often the most sensitive single object in a record --
# a scan, a consent form, a photograph. Who uploaded it and who opened it are
# both worth keeping.
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.documents.models import Document, DocumentCategory, checksum_of

logger = logging.getLogger("nirova.documents")


class DocumentError(DomainError):
    code = "document_error"


#: What may be uploaded. An allow-list rather than a deny-list, because a
#: deny-list of dangerous types is a list somebody has to keep up to date and
#: will not.
ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "application/dicom",
    "text/plain",
    "text/csv",
}

#: 50 MB. Large enough for a scanned discharge summary or a chest film, small
#: enough that an upload endpoint is not a way to fill a disk.
MAX_BYTES = 50 * 1024 * 1024


def store(
    handle,
    *,
    category: str,
    title: str,
    subject_type: str,
    subject_uuid,
    actor=None,
    facility=None,
    description: str = "",
    supersedes: Document = None,
) -> Document:
    """Store one file against one subject.

    Refuses before writing anything, so a rejected upload leaves nothing behind
    to explain.
    """
    if category not in DocumentCategory.values:
        raise DocumentError(f"'{category}' is not a document category.")

    size = getattr(handle, "size", 0)
    if size <= 0:
        raise DocumentError("That file is empty.")
    if size > MAX_BYTES:
        raise DocumentError(
            f"That file is {size // (1024 * 1024)} MB. The limit is "
            f"{MAX_BYTES // (1024 * 1024)} MB.",
            detail={"size_bytes": size, "limit_bytes": MAX_BYTES},
        )

    content_type = getattr(handle, "content_type", "") or ""
    if content_type not in ALLOWED_TYPES:
        raise DocumentError(
            f"{content_type or 'That kind of file'} cannot be stored here. "
            "Allowed: PDF, JPEG, PNG, TIFF, DICOM, plain text and CSV.",
            detail={"allowed": sorted(ALLOWED_TYPES)},
        )

    digest = checksum_of(handle)

    # The same bytes against the same subject is one document. Returning the
    # existing row rather than refusing: somebody who uploads twice has made a
    # mistake, not committed an error, and a refusal here reads as a fault in
    # the system.
    existing = Document.objects.filter(
        subject_type=subject_type, subject_uuid=subject_uuid,
        checksum=digest, archived_at__isnull=True,
    ).first()
    if existing is not None:
        return existing

    document = Document(
        category=category,
        title=title.strip() or getattr(handle, "name", "Untitled"),
        description=description.strip(),
        subject_type=subject_type,
        subject_uuid=subject_uuid,
        facility=facility,
        original_name=(getattr(handle, "name", "") or "file")[:255],
        content_type=content_type,
        size_bytes=size,
        checksum=digest,
        uploaded_by_id=getattr(actor, "uuid", None),
        uploaded_by_name=getattr(actor, "full_name", "") or "",
        supersedes=supersedes,
    )
    # `upload_path` reads the checksum off the instance, so the field has to be
    # set before the file is attached.
    document.file = handle
    document.save()

    if supersedes is not None:
        supersedes.archived_at = timezone.now()
        supersedes.archived_reason = f"Superseded by {document.uuid}"
        supersedes.save(update_fields=[
            "archived_at", "archived_reason", "updated_at",
        ])

    record(
        AuditAction.CREATE,
        entity_type="documents.Document",
        entity_id=document.uuid,
        entity_label=f"{document.title} ({document.original_name})",
        severity=(
            AuditSeverity.SENSITIVE if document.is_about_a_patient
            else AuditSeverity.NOTABLE
        ),
        metadata={
            "category": category,
            "subject": f"{subject_type}:{subject_uuid}",
            "bytes": size,
        },
    )
    return document


def archive(document: Document, actor, reason: str) -> Document:
    """Hide a document. Never remove it.

    A discharge summary somebody took down is a fact worth being able to
    discover, and the reason is the part that matters — an archived document
    with no explanation is indistinguishable from a mistake.
    """
    if not reason.strip():
        raise DocumentError("Say why the document is being archived.")
    if document.is_archived:
        return document

    document.archived_at = timezone.now()
    document.archived_reason = reason.strip()
    document.save(update_fields=[
        "archived_at", "archived_reason", "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="documents.Document",
        entity_id=document.uuid,
        entity_label=f"Archived: {document.title}",
        reason=reason.strip(),
        severity=AuditSeverity.SENSITIVE,
    )
    return document


def documents_for(subject_type: str, subject_uuid, include_archived=False):
    """Everything attached to one thing, newest first."""
    queryset = Document.objects.filter(
        subject_type=subject_type, subject_uuid=subject_uuid,
    )
    if not include_archived:
        queryset = queryset.filter(archived_at__isnull=True)
    return queryset.order_by("-uploaded_at")
