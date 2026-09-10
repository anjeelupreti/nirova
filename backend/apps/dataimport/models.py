"""Bringing a practice's existing records in, one reviewable batch at a time.

A hospital does not adopt a system empty. It arrives with eight thousand
patients in a spreadsheet somebody has maintained since 2014, a medicine list
with three spellings of paracetamol, and an opening stock count taken last
Thursday. §124 is therefore not a convenience feature: it is the thing that
decides whether a customer can start at all.

**Why this is a batch with rows and not a function that takes a file.** A naive
importer is worse than none. It inserts what it is given, and the damage is
permanent in a way that no other kind of bug is: two records for the same
patient split a clinical history, and by the time anybody notices there are
encounters, prescriptions and invoices hanging off both. Undoing that is the
`merge_patients` service, done by hand, per person. So every import here is a
*reviewable object*: uploaded, mapped, validated, previewed, and only then
committed, with every row's fate recorded against the row number in the
original file.

**Nothing is written until commit.** Validation is pure -- it reads to detect
duplicates and writes only to `ImportRow`. That is what makes the preview
trustworthy: what the preview says will happen is what the commit does.

**Commit goes through the real creation services, never the models.**
`register_patient` allocates the MRN, checks the entitlement quota, writes the
audit event and meters the record. An importer calling `Patient.objects.create`
would bypass all four, and the first symptom would be two patients with the same
MRN a month later. The import is a caller like any other; it gets no shortcut.

**A row is the unit of failure.** Each row commits in its own savepoint, so row
4,312 failing on a bad date does not roll back the 4,311 before it. The
alternative -- one transaction for the file -- means an eight-thousand-row
import fails entirely on its worst row, and whoever is doing the migration
spends their week bisecting a spreadsheet.
"""

from django.db import models

from apps.common.models import BaseModel


class ImportKind(models.TextChoices):
    """What a batch is importing.

    Each value has an `Importer` in `kinds.py` declaring its columns, how to
    normalise a row, how to recognise a duplicate and which service creates
    the record. Adding a kind means adding an importer, not editing this
    pipeline.
    """

    PATIENTS = "patients", "Patients"
    EMPLOYEES = "employees", "Employees"
    MEDICINES = "medicines", "Medicines and products"
    SUPPLIERS = "suppliers", "Suppliers"
    SERVICES = "services", "Services and prices"


class BatchStatus(models.TextChoices):
    """Where a batch is in the pipeline.

    The order is the pipeline, and the transitions are one-way. A batch that
    has been imported cannot be validated again: re-validating would rewrite
    the row decisions that the import was based on, and the record of what was
    imported is the only thing that makes an import auditable afterwards.
    """

    UPLOADED = "uploaded", "Uploaded, not yet mapped"
    MAPPED = "mapped", "Columns mapped"
    VALIDATED = "validated", "Validated, ready to preview"
    IMPORTED = "imported", "Imported"
    PARTIAL = "partial", "Imported with failures"
    CANCELLED = "cancelled", "Cancelled"


class RowStatus(models.TextChoices):
    """What happened, or will happen, to one row of the file.

    `DUPLICATE` is deliberately not a failure. It is the most common and most
    important outcome of a real migration -- a spreadsheet maintained for a
    decade has the same person in it four times -- and the right response is to
    show the match and let a person decide, not to refuse the file.
    """

    PENDING = "pending", "Not yet validated"
    VALID = "valid", "Ready to import"
    INVALID = "invalid", "Cannot be imported"
    DUPLICATE = "duplicate", "Matches an existing record"
    IMPORTED = "imported", "Imported"
    SKIPPED = "skipped", "Deliberately not imported"
    FAILED = "failed", "Import was attempted and failed"


class RowDecision(models.TextChoices):
    """What a reviewer decided to do with a row that needs a decision.

    Only meaningful for a `DUPLICATE` row. `IMPORT` creates a second record
    anyway, which is occasionally right -- twins, a shared phone, a common name
    -- and is recorded as a deliberate act rather than an accident.
    """

    UNDECIDED = "undecided", "Awaiting a decision"
    IMPORT = "import", "Import anyway"
    SKIP = "skip", "Skip this row"


class ImportBatch(BaseModel):
    """One uploaded file, its mapping, and what became of it."""

    reference = models.CharField(max_length=32, db_index=True, unique=True)
    kind = models.CharField(max_length=24, choices=ImportKind.choices, db_index=True)
    filename = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=BatchStatus.choices,
        default=BatchStatus.UPLOADED, db_index=True,
    )

    #: The file's own header row, in file order. Kept so the mapping can be
    #: re-edited and so an error report can name the column the user saw rather
    #: than the field the system wanted.
    headers = models.JSONField(default=list)

    #: `{field_name: header_name}`. Stored rather than recomputed because a
    #: reviewer may correct a suggestion, and a mapping that silently
    #: re-suggested itself on the next request would discard that correction.
    column_map = models.JSONField(default=dict)

    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    invalid_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)

    #: `{column_or_field: count}` -- which problems this file has most of.
    #: A migration is fixed by correcting the spreadsheet, and the useful
    #: question is "what is wrong with it" rather than "which rows are wrong".
    error_summary = models.JSONField(default=dict)

    uploaded_by_id = models.UUIDField(null=True, blank=True)
    uploaded_by_name = models.CharField(max_length=255, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    imported_by_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "dataimport_batch"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["kind", "status"])]

    def __str__(self):
        return f"{self.reference} ({self.get_kind_display()}, {self.status})"

    @property
    def is_committed(self) -> bool:
        """Whether this batch has already been through a commit.

        The guard against importing the same file twice, which is the single
        most likely way a migration creates duplicates: somebody clicks import,
        the request is slow, they click again.
        """
        return self.status in {BatchStatus.IMPORTED, BatchStatus.PARTIAL}

    @property
    def ready_to_import(self) -> int:
        """How many rows a commit would actually create."""
        return self.valid_rows


class ImportRow(BaseModel):
    """One row of the file, and its fate.

    Kept after the import rather than discarded. An import is a bulk write of
    somebody's historical records, and the question asked three months later is
    always "where did this patient come from?" -- answerable only if the row
    that produced them still exists, with its original spelling.
    """

    batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="rows"
    )
    #: 1-based, counting the header as row 1, so it matches what the user sees
    #: in their spreadsheet. An off-by-one here makes every error message wrong
    #: in a way that is maddening to debug from the other end of a phone call.
    row_number = models.PositiveIntegerField()

    #: The row exactly as it came out of the file, by the file's own headers.
    raw = models.JSONField(default=dict)
    #: The row after mapping and type coercion, by field name. This is what
    #: `create` is handed, so storing it makes the import reproducible.
    normalised = models.JSONField(default=dict)

    status = models.CharField(
        max_length=12, choices=RowStatus.choices,
        default=RowStatus.PENDING, db_index=True,
    )
    decision = models.CharField(
        max_length=12, choices=RowDecision.choices,
        default=RowDecision.UNDECIDED,
    )

    #: `[{"field": "phone", "message": "..."}]`. A list because a row usually
    #: has more than one thing wrong with it, and reporting only the first
    #: means the user fixes their file one error per upload.
    errors = models.JSONField(default=list)

    #: The existing record this row looks like, if any.
    duplicate_of_uuid = models.UUIDField(null=True, blank=True)
    duplicate_of_label = models.CharField(max_length=255, blank=True)
    duplicate_score = models.PositiveSmallIntegerField(default=0)
    #: Which signals matched -- phone, exact name, name and date of birth, a
    #: document number. A score alone is not reviewable; "same phone" is.
    duplicate_matched_on = models.JSONField(default=list)

    #: Set when another row *in the same file* is the same person. A database
    #: lookup cannot find this, because neither row exists yet -- which is why
    #: it is the duplicate every importer misses.
    duplicate_of_row = models.PositiveIntegerField(null=True, blank=True)

    created_uuid = models.UUIDField(null=True, blank=True)
    created_label = models.CharField(max_length=255, blank=True)
    failure_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "dataimport_row"
        ordering = ["batch_id", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_number"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_import_row_per_batch",
            )
        ]
        indexes = [models.Index(fields=["batch", "status"])]

    def __str__(self):
        return f"{self.batch.reference} row {self.row_number} ({self.status})"
