"""The import pipeline: parse, map, validate, preview, commit, report.

Knows about files, mappings, duplicates, savepoints and reports. Knows nothing
about patients or medicines -- those live in `kinds.py`, one importer each. The
separation is what lets §124's remaining kinds be added without this file
growing a switch statement.

**The order is the whole design.** Parse reads the file and writes rows.
Validate normalises and detects duplicates, writing only to `ImportRow`.
Preview reads. Commit creates. Nothing before commit touches a patient, a
product or a ledger, which is what makes the preview trustworthy: what it says
will happen is what happens.
"""

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

# `tenant_atomic` opens a transaction on the *tenant's* database -- a bare
# `transaction.atomic()` would open one on the control plane and silently
# give up atomicity (see apps/tenancy/db.py). The method form decorates a
# whole service; the context-manager form is the per-row savepoint in
# `commit_batch`, where nesting inside an open transaction is exactly what
# is wanted.
from apps.tenancy.db import tenant_atomic, tenant_atomic_method
from apps.dataimport.kinds import importer_for
from apps.dataimport.models import (
    BatchStatus,
    ImportBatch,
    ImportRow,
    RowDecision,
    RowStatus,
)

logger = logging.getLogger(__name__)

#: Most rows one upload may contain.
#:
#: Not a performance limit -- it is a limit on how much can go wrong at once.
#: A file of 200,000 rows is not a migration somebody is reviewing, it is a
#: migration somebody is hoping about, and the right answer is to split it by
#: facility or by year so that each piece can be read before it is committed.
#: Generous enough for any single practice's patient list.
MAX_ROWS = 50_000

#: How many sample values to show per column when suggesting a mapping. Three
#: is enough to tell a date column from a text one by eye, which is the
#: question a reviewer is actually answering.
SAMPLE_VALUES = 3


class ImportError_(Exception):
    """A problem with the batch as a whole, as opposed to with one row."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_upload(uploaded, filename: str = "") -> tuple[list, list]:
    """Read a CSV, TSV or XLSX upload into headers and row dicts.

    Returns `(headers, rows)` where each row is `{header: value}` using the
    file's own header names. Mapping to fields happens later and separately,
    because a reviewer must be able to see the file as it is before deciding
    what its columns mean.
    """
    name = (filename or getattr(uploaded, "name", "") or "").lower()
    raw = uploaded.read() if hasattr(uploaded, "read") else uploaded

    if name.endswith((".xlsx", ".xlsm")):
        return _parse_xlsx(raw)
    return _parse_delimited(raw, name)


def _parse_delimited(raw: bytes, name: str) -> tuple[list, list]:
    """CSV or TSV, with the encoding and delimiter worked out rather than assumed.

    **UTF-8 with a BOM is the normal case, not the exception.** Excel on
    Windows writes it by default, and reading it as plain UTF-8 leaves a
    zero-width character glued to the first header -- so `"Name"` becomes
    `"\\ufeffName"`, matches no alias, and the first column silently fails to
    map. `utf-8-sig` strips it.

    The fallback to cp1252 is for files saved from older Excel installs, which
    are common in exactly the practices most likely to be migrating off paper
    and spreadsheets.
    """
    if isinstance(raw, str):
        text = raw
    else:
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ImportError_(
                "This file is not text in any encoding this can read. If it is "
                "a spreadsheet, save it as .xlsx or as CSV (UTF-8)."
            )

    if not text.strip():
        raise ImportError_("The file is empty.")

    # Sniff the delimiter rather than assuming a comma: a Nepali or European
    # Excel writes semicolons, and a file of semicolons read as CSV parses as
    # one enormous column with no error at all.
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
        if name.endswith(".tsv"):
            dialect = csv.excel_tab

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    if not headers:
        raise ImportError_("The first row has no column names.")

    rows = []
    for row in reader:
        # `None` keys appear when a data row has more cells than the header.
        # Worth keeping the row and reporting the mismatch rather than dropping
        # it: a trailing comma on one line should not lose a patient.
        rows.append({
            key.strip(): value
            for key, value in row.items()
            if key and key.strip()
        })
        if len(rows) > MAX_ROWS:
            raise ImportError_(
                f"This file has more than {MAX_ROWS:,} rows. Split it -- by "
                "facility, or by year -- so that each part can be reviewed "
                "before it is imported."
            )
    return headers, rows


def _parse_xlsx(raw: bytes) -> tuple[list, list]:
    """The first worksheet of an Excel file.

    `data_only=True` reads the cached value of a formula rather than the
    formula text. A migration file is full of `=CONCATENATE(...)` columns, and
    importing the formula source as a patient's name is the kind of mistake
    that is obvious afterwards and invisible at the time.

    Only the first sheet. A workbook with the real data on sheet three is a
    file somebody should fix before importing, and silently picking a sheet
    would make "which one did it use?" an unanswerable question later.
    """
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - declared in requirements
        raise ImportError_(
            "Excel support is not installed on this server. Save the file as "
            "CSV (UTF-8) instead."
        ) from None

    try:
        book = load_workbook(
            io.BytesIO(raw) if isinstance(raw, bytes) else raw,
            data_only=True, read_only=True,
        )
    except Exception as error:  # noqa: BLE001 - openpyxl raises many shapes
        raise ImportError_(f"This is not a readable Excel file: {error}") from None

    sheet = book.worksheets[0]
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise ImportError_("The first worksheet is empty.") from None

    headers, seen = [], {}
    for index, value in enumerate(header_row):
        name = str(value).strip() if value is not None else ""
        if not name:
            # An unnamed column is kept positionally rather than dropped, so
            # the row dicts stay aligned with the file.
            name = f"Column {index + 1}"
        # Excel files routinely have two columns called "Remarks". Left as-is,
        # the second would overwrite the first in a dict and data would vanish.
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        headers.append(name)

    rows = []
    for values in rows_iter:
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue  # a blank separator row, of which spreadsheets have many
        rows.append({
            headers[i]: values[i] if i < len(values) else None
            for i in range(len(headers))
        })
        if len(rows) > MAX_ROWS:
            raise ImportError_(
                f"This sheet has more than {MAX_ROWS:,} rows. Split it so that "
                "each part can be reviewed before it is imported."
            )
    book.close()
    return headers, rows


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    """Normalise a header for comparison: lowercase, alphanumeric only."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def suggest_mapping(kind: str, headers: list) -> dict:
    """Guess `{field: header}` from the header names.

    Exact field name first, then the declared aliases, then a containment
    match. Each step is more generous than the last and the first hit wins, so
    a file with both "name" and "first name" maps `first_name` to the more
    specific one.

    **A suggestion, never a decision.** The mapping is stored and editable, and
    `validate_batch` works from the stored mapping rather than re-suggesting --
    otherwise a reviewer's correction would be silently undone on the next
    request, which is the worst kind of interface bug because the screen looks
    right.
    """
    importer = importer_for(kind)
    by_slug = {_slug(h): h for h in headers}
    mapping, taken = {}, set()

    def claim(field: str, header: str) -> None:
        mapping[field] = header
        taken.add(header)

    for column in importer.columns:
        if column.field in mapping:
            continue
        # 1. The field name itself.
        hit = by_slug.get(_slug(column.field))
        if hit and hit not in taken:
            claim(column.field, hit)
            continue
        # 2. A declared alias, in the order they are declared -- earlier
        #    aliases are the more common spellings.
        for alias in column.aliases:
            hit = by_slug.get(_slug(alias))
            if hit and hit not in taken:
                claim(column.field, hit)
                break
        if column.field in mapping:
            continue
        # 3. Containment, which catches "Patient First Name" and "DOB (AD)".
        #    Last because it is the step that can be wrong: "name" is inside
        #    "name of guardian".
        candidates = [_slug(column.field), *(_slug(a) for a in column.aliases)]
        for slug, header in by_slug.items():
            if header in taken:
                continue
            if any(c and c in slug for c in candidates):
                claim(column.field, header)
                break

    return mapping


def mapping_report(kind: str, headers: list, rows: list, mapping: dict) -> dict:
    """What the mapping covers, what it misses, and a sample of each column.

    The three things a reviewer needs before committing to a mapping: which
    required fields are still unmapped (the file cannot be imported until they
    are), which of the file's columns will be ignored (usually fine, sometimes
    a mapping mistake), and what the values actually look like.
    """
    importer = importer_for(kind)
    mapped_headers = set(mapping.values())
    missing_required = [
        {"field": c.field, "label": c.label}
        for c in importer.columns
        if c.required and not mapping.get(c.field)
    ]
    samples = {}
    for header in headers:
        values = []
        for row in rows[:50]:
            value = row.get(header)
            if value is None or str(value).strip() == "":
                continue
            values.append(_jsonable(value))
            if len(values) >= SAMPLE_VALUES:
                break
        samples[header] = values
    return {
        "mapping": mapping,
        "missing_required": missing_required,
        "ignored_columns": [h for h in headers if h not in mapped_headers],
        "samples": samples,
        "columns": [
            {
                "field": c.field, "label": c.label, "required": c.required,
                "help_text": c.help_text,
                "mapped_to": mapping.get(c.field, ""),
            }
            for c in importer.columns
        ],
    }


# ---------------------------------------------------------------------------
# Creating a batch
# ---------------------------------------------------------------------------


def _jsonable(value):
    """Make a cell storable in a JSONField without losing what it was.

    openpyxl returns real `datetime` and `Decimal` objects, which `JSONField`
    cannot serialise. Converting to ISO text keeps the value readable in the
    stored row -- and the stored row is the audit trail, so it has to hold what
    the file said rather than a repr.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _next_reference() -> str:
    """`IMP-000123`, sequential within the tenant.

    Readable aloud, because the first thing anybody does with a failed import
    is read its reference down a telephone.
    """
    last = ImportBatch.objects.order_by("-id").values_list("reference", flat=True).first()
    number = 1
    if last and last.startswith("IMP-"):
        try:
            number = int(last.split("-", 1)[1]) + 1
        except ValueError:
            number = ImportBatch.objects.count() + 1
    return f"IMP-{number:06d}"


@tenant_atomic_method
def create_batch(
    *, kind: str, filename: str, headers: list, rows: list, actor=None,
) -> ImportBatch:
    """Store an uploaded file as a batch of rows, with a suggested mapping.

    Writes the rows immediately rather than holding the file in a session or a
    temporary directory. A migration is reviewed over minutes or hours, often by
    somebody other than whoever uploaded it, and a file that expired with the
    session would have to be uploaded again -- which is how a batch gets
    imported twice.
    """
    importer = importer_for(kind)
    if not rows:
        raise ImportError_("The file has column names but no rows.")

    batch = ImportBatch.objects.create(
        reference=_next_reference(),
        kind=importer.kind,
        filename=filename[:255],
        headers=headers,
        column_map=suggest_mapping(kind, headers),
        total_rows=len(rows),
        uploaded_by_id=getattr(actor, "uuid", None),
        uploaded_by_name=getattr(actor, "full_name", "") or getattr(actor, "email", ""),
        created_by_id=getattr(actor, "uuid", None),
    )

    ImportRow.objects.bulk_create(
        [
            ImportRow(
                batch=batch,
                # +2, not +1: the header is row 1 in the user's spreadsheet, so
                # the first data row is row 2. Getting this wrong makes every
                # error message point at the line above the problem, which is
                # maddening to debug from the other end of a telephone.
                row_number=index + 2,
                raw={key: _jsonable(value) for key, value in row.items()},
                created_by_id=getattr(actor, "uuid", None),
            )
            for index, row in enumerate(rows)
        ],
        batch_size=1000,
    )
    logger.info(
        "IMPORT BATCH %s created: %s, %d rows from %s",
        batch.reference, batch.kind, len(rows), filename,
    )
    return batch


@tenant_atomic_method
def set_mapping(batch: ImportBatch, mapping: dict) -> ImportBatch:
    """Replace the column mapping, rejecting it if a required field is unmapped.

    Refused outright once the batch has been imported: the mapping is the
    record of how the committed rows were interpreted, and rewriting it
    afterwards would make the audit trail describe an import that never
    happened.
    """
    if batch.is_committed:
        raise ImportError_(
            f"{batch.reference} has already been imported. Its mapping is part "
            "of the record of what was imported and cannot be changed."
        )
    importer = importer_for(batch.kind)
    known = {c.field for c in importer.columns}
    unknown = set(mapping) - known
    if unknown:
        raise ImportError_(
            f"{importer.label} has no field called {', '.join(sorted(unknown))}."
        )

    batch.column_map = {f: h for f, h in mapping.items() if h}
    batch.status = BatchStatus.MAPPED
    batch.save(update_fields=["column_map", "status", "updated_at"])
    return batch


# ---------------------------------------------------------------------------
# Validating
# ---------------------------------------------------------------------------


def _mapped_values(row: ImportRow, column_map: dict) -> dict:
    """`{field: raw value}` for one row, through the batch's mapping."""
    return {field: row.raw.get(header) for field, header in column_map.items()}


@tenant_atomic_method
def validate_batch(batch: ImportBatch, actor=None) -> ImportBatch:
    """Normalise every row, find duplicates, and record what would happen.

    Writes only to `ImportRow` and the batch's counters. Nothing a clinician or
    an accountant would recognise is touched, which is the property that makes
    the preview worth reading.

    Re-runnable before a commit -- a reviewer fixes the mapping and validates
    again -- and refused after one, because the row statuses are the record of
    what was imported.
    """
    if batch.is_committed:
        raise ImportError_(
            f"{batch.reference} has already been imported; its rows record what "
            "happened and re-validating would overwrite that."
        )

    importer = importer_for(batch.kind)
    missing = [f for f in importer.required_fields() if not batch.column_map.get(f)]
    if missing:
        labels = {c.field: c.label for c in importer.columns}
        raise ImportError_(
            "These required columns are not mapped: "
            + ", ".join(labels.get(f, f) for f in missing)
            + ". Map them before validating."
        )

    counts = {status: 0 for status in RowStatus.values}
    error_summary: dict[str, int] = {}

    #: Rows seen so far, by the importer's same-file key. This is the check no
    #: database lookup can do -- at validation time neither row exists yet --
    #: and it is the duplicate that every naive importer misses, because the
    #: spreadsheet a practice has kept for a decade has the same person in it
    #: three or four times.
    seen_keys: dict = {}

    updates = []
    for row in batch.rows.all().iterator(chunk_size=500):
        values = _mapped_values(row, batch.column_map)
        normalised, errors = importer.normalise(values)

        row.normalised = {k: _jsonable(v) for k, v in normalised.items()}
        row.errors = errors
        row.duplicate_of_uuid = None
        row.duplicate_of_label = ""
        row.duplicate_score = 0
        row.duplicate_matched_on = []
        row.duplicate_of_row = None

        if errors:
            row.status = RowStatus.INVALID
            for error in errors:
                key = error.get("field", "row")
                error_summary[key] = error_summary.get(key, 0) + 1
        else:
            key = importer.same_file_key(normalised)
            earlier = seen_keys.get(key) if key is not None else None
            if earlier is not None:
                row.status = RowStatus.DUPLICATE
                row.duplicate_of_row = earlier
                row.duplicate_matched_on = ["same file"]
                row.duplicate_score = 100
                row.duplicate_of_label = f"row {earlier} of this file"
            else:
                if key is not None:
                    seen_keys[key] = row.row_number
                existing = importer.find_existing(normalised)
                if existing:
                    uuid, label, score, matched_on = existing
                    row.status = RowStatus.DUPLICATE
                    row.duplicate_of_uuid = uuid
                    row.duplicate_of_label = label[:255]
                    row.duplicate_score = min(score, 32767)
                    row.duplicate_matched_on = matched_on
                else:
                    row.status = RowStatus.VALID

        # A decision made on a previous validation is kept. Somebody who has
        # reviewed four hundred duplicates and then fixed one mapping column
        # should not lose four hundred decisions.
        counts[row.status] += 1
        updates.append(row)
        if len(updates) >= 500:
            _save_rows(updates)
            updates = []
    if updates:
        _save_rows(updates)

    # A duplicate already decided "import anyway" counts as ready, because that
    # is what the commit will do with it. A counter that disagreed with the
    # commit would make the preview a lie.
    decided_in = batch.rows.filter(
        status=RowStatus.DUPLICATE, decision=RowDecision.IMPORT
    ).count()

    batch.valid_rows = counts[RowStatus.VALID] + decided_in
    batch.invalid_rows = counts[RowStatus.INVALID]
    batch.duplicate_rows = counts[RowStatus.DUPLICATE]
    batch.error_summary = dict(
        sorted(error_summary.items(), key=lambda kv: kv[1], reverse=True)
    )
    batch.status = BatchStatus.VALIDATED
    batch.validated_at = timezone.now()
    batch.save(update_fields=[
        "valid_rows", "invalid_rows", "duplicate_rows", "error_summary",
        "status", "validated_at", "updated_at",
    ])
    logger.info(
        "IMPORT BATCH %s validated: %d ready, %d invalid, %d duplicate",
        batch.reference, batch.valid_rows, batch.invalid_rows,
        batch.duplicate_rows,
    )
    return batch


def _save_rows(rows: list) -> None:
    ImportRow.objects.bulk_update(
        rows,
        [
            "normalised", "errors", "status", "duplicate_of_uuid",
            "duplicate_of_label", "duplicate_score", "duplicate_matched_on",
            "duplicate_of_row",
        ],
        batch_size=500,
    )


@tenant_atomic_method
def decide_rows(batch: ImportBatch, decisions: dict) -> ImportBatch:
    """Record what to do with duplicate rows: `{row_number: "import"|"skip"}`.

    Only duplicates take a decision. A valid row needs none, and an invalid row
    cannot be rescued by one -- the file has to be corrected.
    """
    if batch.is_committed:
        raise ImportError_(f"{batch.reference} has already been imported.")

    allowed = set(RowDecision.values)
    bad = {v for v in decisions.values() if v not in allowed}
    if bad:
        raise ImportError_(
            f"{', '.join(sorted(bad))} is not a decision. Use "
            f"{' or '.join(sorted(allowed - {RowDecision.UNDECIDED}))}."
        )

    rows = {
        row.row_number: row
        for row in batch.rows.filter(
            row_number__in=[int(n) for n in decisions], status=RowStatus.DUPLICATE
        )
    }
    changed = []
    for number, decision in decisions.items():
        row = rows.get(int(number))
        if row is None:
            continue  # not a duplicate, or not in this batch: nothing to decide
        row.decision = decision
        changed.append(row)
    if changed:
        ImportRow.objects.bulk_update(changed, ["decision"], batch_size=500)

    batch.valid_rows = (
        batch.rows.filter(status=RowStatus.VALID).count()
        + batch.rows.filter(
            status=RowStatus.DUPLICATE, decision=RowDecision.IMPORT
        ).count()
    )
    batch.save(update_fields=["valid_rows", "updated_at"])
    return batch


# ---------------------------------------------------------------------------
# Previewing and committing
# ---------------------------------------------------------------------------


def preview_batch(batch: ImportBatch, limit: int = 25) -> dict:
    """What a commit would do, in the terms the reviewer decides in."""
    importer = importer_for(batch.kind)
    pending_decisions = batch.rows.filter(
        status=RowStatus.DUPLICATE, decision=RowDecision.UNDECIDED
    ).count()
    return {
        "reference": batch.reference,
        "kind": batch.kind,
        "noun": importer.noun,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "will_create": batch.valid_rows,
        "will_skip": batch.total_rows - batch.valid_rows,
        "invalid_rows": batch.invalid_rows,
        "duplicate_rows": batch.duplicate_rows,
        "awaiting_decision": pending_decisions,
        "error_summary": batch.error_summary,
        "sample": [
            {
                "row_number": row.row_number,
                "status": row.status,
                "normalised": row.normalised,
                "errors": row.errors,
                "duplicate_of_label": row.duplicate_of_label,
                "duplicate_matched_on": row.duplicate_matched_on,
                # Which *row of this file* it duplicates, when that is the
                # match. The reviewer's next action is to look at that row, so
                # leaving it out of the preview means going to find it by hand.
                "duplicate_of_row": row.duplicate_of_row,
                "duplicate_score": row.duplicate_score,
                "decision": row.decision,
            }
            for row in batch.rows.exclude(status=RowStatus.VALID)[:limit]
        ],
    }


def commit_batch(batch: ImportBatch, *, organization, actor=None, facility=None) -> ImportBatch:
    """Create the records. One savepoint per row, idempotent, quota checked once.

    **Not wrapped in a single transaction, deliberately.** Each row commits in
    its own savepoint so that row 4,312 failing on a value nobody anticipated
    does not roll back the 4,311 before it. One transaction for the file means
    an eight-thousand-row import fails entirely on its worst row, and whoever
    is migrating spends their week bisecting a spreadsheet.

    **Idempotent at both levels.** A batch already committed is refused -- the
    likeliest way a migration creates duplicates is a slow request and a second
    click. Within a batch, a row that already has a `created_uuid` is skipped,
    so a commit interrupted halfway can be run again and will finish rather
    than double.
    """
    if batch.is_committed:
        raise ImportError_(
            f"{batch.reference} was imported on "
            f"{batch.imported_at:%Y-%m-%d %H:%M} and cannot be imported again. "
            "Upload the file again if you genuinely need a second import."
        )
    if batch.status != BatchStatus.VALIDATED:
        raise ImportError_(
            f"{batch.reference} has not been validated. Validate it so that "
            "what will happen can be read before it happens."
        )

    awaiting = batch.rows.filter(
        status=RowStatus.DUPLICATE, decision=RowDecision.UNDECIDED
    ).count()
    if awaiting:
        raise ImportError_(
            f"{awaiting} row(s) match an existing record and have no decision. "
            "Choose import or skip for each -- a duplicate resolved by default "
            "is a duplicate nobody chose."
        )

    importer = importer_for(batch.kind)

    # **The quota is checked once, for the whole batch, before anything is
    # created.** Per-row checking would let an import stop halfway through with
    # four thousand patients in and four thousand out, which is the worst
    # possible state: the customer is over their plan *and* their migration is
    # half done. `register_patient` still checks per row, and that is fine -- it
    # is the backstop, not the gate.
    if importer.quota_key:
        from apps.entitlements.services import check_quota

        decision = check_quota(
            organization, importer.quota_key, requested=batch.valid_rows
        )
        decision.raise_if_blocked()

    rows = list(
        batch.rows.filter(created_uuid__isnull=True).exclude(
            status__in=[RowStatus.INVALID, RowStatus.SKIPPED]
        ).order_by("row_number")
    )

    imported = failed = skipped = 0
    for row in rows:
        if row.status == RowStatus.DUPLICATE and row.decision != RowDecision.IMPORT:
            row.status = RowStatus.SKIPPED
            row.save(update_fields=["status", "updated_at"])
            skipped += 1
            continue

        normalised = _rehydrate(importer, row)
        try:
            # `tenant_atomic` opens a savepoint when a transaction is already
            # open and a transaction when one is not, so this is the row-level
            # boundary whichever way the caller arrived.
            with tenant_atomic():
                created = importer.create(organization, normalised, actor, facility)
            row.created_uuid = getattr(created, "uuid", None)
            row.created_label = str(created)[:255]
            row.status = RowStatus.IMPORTED
            row.failure_reason = ""
            imported += 1
        except Exception as error:  # noqa: BLE001 - one bad row must not stop the file
            row.status = RowStatus.FAILED
            # The message a person has to act on, so it is the exception's own
            # text rather than a class name. Truncated because a database error
            # can be a page long and the column is not the place for it -- the
            # full text is in the log, which the reference points at.
            row.failure_reason = f"{type(error).__name__}: {error}"[:512]
            failed += 1
            logger.warning(
                "IMPORT %s row %d failed: %s",
                batch.reference, row.row_number, error,
            )
        row.save(update_fields=[
            "created_uuid", "created_label", "status", "failure_reason",
            "updated_at",
        ])

    batch.imported_rows = batch.rows.filter(status=RowStatus.IMPORTED).count()
    batch.failed_rows = batch.rows.filter(status=RowStatus.FAILED).count()
    batch.skipped_rows = batch.rows.filter(status=RowStatus.SKIPPED).count()
    batch.status = BatchStatus.PARTIAL if failed else BatchStatus.IMPORTED
    batch.imported_at = timezone.now()
    batch.imported_by_name = (
        getattr(actor, "full_name", "") or getattr(actor, "email", "")
    )
    batch.save(update_fields=[
        "imported_rows", "failed_rows", "skipped_rows", "status",
        "imported_at", "imported_by_name", "updated_at",
    ])

    _record_audit(batch, importer, imported, failed, skipped)
    logger.info(
        "IMPORT BATCH %s committed: %d created, %d failed, %d skipped",
        batch.reference, imported, failed, skipped,
    )
    return batch


def _rehydrate(importer, row: ImportRow) -> dict:
    """Re-normalise from the stored raw row rather than trusting the JSON.

    `normalised` was written through `_jsonable`, so a date is a string and a
    decimal is a string by the time it is stored. Handing those to a service
    expecting a `date` works by accident in Django and fails in other places,
    so the row is normalised again from `raw` -- which is pure, cheap, and
    guaranteed to agree with what validation decided because it is the same
    function over the same input.
    """
    values = _mapped_values(row, row.batch.column_map)
    normalised, _ = importer.normalise(values)
    return normalised


def _record_audit(batch, importer, imported: int, failed: int, skipped: int) -> None:
    """One audit event for the batch, not one per row.

    Each created record already writes its own audit event through its
    creation service. This is the event that says *why* eight thousand patients
    appeared on a Tuesday, which is the question an auditor actually asks.
    """
    from apps.audit.models import AuditAction
    from apps.audit.services import record

    record(
        AuditAction.CREATE,
        entity_type="dataimport.ImportBatch",
        entity_id=batch.uuid,
        entity_label=f"{batch.reference}: {importer.label} from {batch.filename}",
        metadata={
            "kind": batch.kind,
            "filename": batch.filename,
            "total_rows": batch.total_rows,
            "imported": imported,
            "failed": failed,
            "skipped": skipped,
            "duplicates_found": batch.duplicate_rows,
        },
    )


# ---------------------------------------------------------------------------
# The error report
# ---------------------------------------------------------------------------


def error_report_csv(batch: ImportBatch) -> str:
    """Every row that did not import, as a CSV with the original columns.

    **Shaped to be corrected and re-uploaded, not merely read.** The original
    columns come first, in the file's own order and with the file's own
    headers, so the reviewer can fix the cells in place; the row number and the
    problem are appended at the end. A report that listed only row numbers and
    messages would have to be read side by side with the original file, which
    for four hundred rows nobody does.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([*batch.headers, "Row", "Outcome", "Problem"])

    failures = batch.rows.filter(
        status__in=[RowStatus.INVALID, RowStatus.FAILED, RowStatus.DUPLICATE]
    ).order_by("row_number")
    for row in failures.iterator(chunk_size=500):
        if row.status == RowStatus.INVALID:
            problem = "; ".join(
                f"{error.get('field', 'row')} {error.get('message', '')}".strip()
                for error in row.errors
            )
        elif row.status == RowStatus.FAILED:
            problem = row.failure_reason
        else:
            matched = ", ".join(row.duplicate_matched_on) or "unknown"
            problem = f"matches {row.duplicate_of_label} on {matched}"
        writer.writerow([
            *[row.raw.get(header, "") for header in batch.headers],
            row.row_number,
            row.get_status_display(),
            problem,
        ])
    return buffer.getvalue()
