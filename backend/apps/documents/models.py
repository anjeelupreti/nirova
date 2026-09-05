"""Documents: the files a hospital accumulates, and who may open them.

§122. Nothing in this system has ever stored a file, which blocks discharge
summaries, scanned insurance cards, radiology images, employee certificates and
a patient photographing a rash. The gap has been listed as outstanding since
the checklist was written.

The decisions, in the order they matter.

**A document is attached to something, and inherits that thing's access.** This
is the whole design. A file about a patient is as sensitive as the patient's
record, so it is governed by the same care relationship rather than by a second
permission model that would drift out of step within a month. `subject_type`
and `subject_uuid` name what it is about; the access check reads them and asks
the module that owns that thing.

**Stored by checksum, not by filename.** Two people uploading the same scan
should not produce two copies, a filename is attacker-controlled input, and a
checksum makes tampering detectable. The original name is kept for display and
never used as a path.

**Never deleted, archived.** A discharge summary somebody removed is a fact
worth being able to discover. `archived_at` hides it; nothing removes the row,
and the file stays until a retention rule that does not exist yet says
otherwise.

**Versions supersede rather than overwrite.** The same reasoning as
prescriptions and clinical notes: a corrected report is a new document pointing
at the old one, because "what did this say when the decision was made?" is a
question somebody eventually asks.

**Nothing here scans for malware**, and that is stated rather than assumed. A
hospital that lets patients upload files needs scanning before it lets those
files be downloaded by staff, and this module is not it. Recorded on the
checklist as a blocker for patient upload specifically.
"""

import hashlib

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Facility


class DocumentCategory(models.TextChoices):
    """What kind of document, which decides retention and who expects it.

    Deliberately coarse. A finer taxonomy is a customer's to configure, and
    guessing it here produces categories nobody uses next to a `misc` that
    everything ends up in.
    """

    CLINICAL = "clinical", "Clinical record"
    RESULT = "result", "Diagnostic result"
    IMAGING = "imaging", "Image or scan"
    DISCHARGE = "discharge", "Discharge summary"
    CONSENT = "consent", "Consent form"
    IDENTITY = "identity", "Identity or insurance"
    EMPLOYEE = "employee", "Employee record"
    FINANCE = "finance", "Invoice or receipt"
    OTHER = "other", "Other"


#: Categories whose documents are about a patient, and therefore inherit the
#: patient's access rules rather than a facility's.
PATIENT_CATEGORIES = frozenset({
    DocumentCategory.CLINICAL,
    DocumentCategory.RESULT,
    DocumentCategory.IMAGING,
    DocumentCategory.DISCHARGE,
    DocumentCategory.CONSENT,
    DocumentCategory.IDENTITY,
})


def upload_path(instance, filename: str) -> str:
    """Where the bytes go: category, then checksum.

    Never the uploaded filename. It is attacker-controlled, it collides, and it
    leaks — a file called `ram-bahadur-hiv-result.pdf` sitting on disk is a
    disclosure to anybody who can list a directory, quite apart from whether
    they can open it.
    """
    digest = instance.checksum or "unknown"
    return f"documents/{instance.category}/{digest[:2]}/{digest}"


class Document(BaseModel):
    """One stored file, and what it is about."""

    category = models.CharField(
        max_length=16, choices=DocumentCategory.choices, db_index=True,
    )
    title = models.CharField(max_length=255)
    description = models.CharField(max_length=512, blank=True)

    #: What this document concerns, in the loosest terms — a type name and a
    #: UUID, the same shape the notification centre uses. Deliberately not a
    #: foreign key: a document about a merged patient or a cancelled order must
    #: outlive the row, and a cascade would delete the evidence.
    subject_type = models.CharField(max_length=48, db_index=True)
    subject_uuid = models.UUIDField(db_index=True)

    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="documents",
    )

    file = models.FileField(upload_to=upload_path, max_length=255)
    #: The name the uploader gave it. For display only — never a path.
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    #: SHA-256. Identity, deduplication and tamper detection in one field.
    checksum = models.CharField(max_length=64, db_index=True)

    uploaded_by_id = models.UUIDField(null=True, blank=True, db_index=True)
    uploaded_by_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)

    #: A corrected document points at what it replaces. The old one stays
    #: readable and is marked superseded, because "what did this say when the
    #: decision was made?" is a question somebody eventually asks.
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="superseded_by",
    )

    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "document"
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["subject_type", "subject_uuid", "-uploaded_at"]),
            models.Index(fields=["category", "-uploaded_at"]),
        ]
        constraints = [
            # The same bytes attached to the same thing twice is one document.
            # Partial, so an archived one does not block re-uploading a file
            # somebody removed by mistake.
            models.UniqueConstraint(
                fields=["subject_type", "subject_uuid", "checksum"],
                condition=models.Q(archived_at__isnull=True,
                                   deleted_at__isnull=True),
                name="uniq_live_document_per_subject_and_content",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.original_name})"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def is_about_a_patient(self) -> bool:
        """Whether this inherits a patient's access rules.

        Read from the subject rather than the category, because the category is
        a label somebody chose and the subject is what the document is actually
        attached to. A mislabelled employee certificate attached to a patient
        should still be governed as the patient's.
        """
        return self.subject_type == "patients.Patient"


def checksum_of(handle) -> str:
    """SHA-256 of an uploaded file, read in chunks.

    Chunked because a radiology image is not small, and reading a scan into
    memory to hash it is how an upload endpoint becomes a way to exhaust the
    server.
    """
    digest = hashlib.sha256()
    for chunk in handle.chunks():
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()
