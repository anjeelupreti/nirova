"""Recording what left the building.

§102's last outstanding line, and a gap with a particular shape: `EXPORT`,
`PRINT` and `DOWNLOAD` have been in `AuditAction` since the audit log was
written, with severities already assigned -- and **nothing has ever recorded
one**. Three actions defined and never used is worse than three actions absent,
because the log looks like it covers exports and does not.

**An export is not a read, and recording it as one loses the thing that
matters.** A read shows one record to one person on one screen, inside a system
that can still refuse them tomorrow. An export makes a copy that leaves, and
after that no permission in this system governs it. That is why `EXPORT` and
`DOWNLOAD` are `SENSITIVE` by default while `VIEW` is `INFO`: the question
asked after a leak is not "who looked?" but "who took a copy?", and those are
different queries against different rows.

**Record what was in it, not merely that something happened.** The report and
its parameters, how many rows, which section -- enough to answer "what was in
that file?" a year later without having kept the file, which nobody does and
nobody should.

**And claim no more than is known.** A payslip rendered as HTML is a printable;
whether anybody pressed print is not observable over HTTP. It is recorded as a
*printable produced*, which is true, rather than as a print, which would be a
guess written into an append-only log.
"""

from apps.audit.models import AuditAction
from apps.audit.services import record


def record_export(
    what: str,
    *,
    label: str = "",
    rows: int | None = None,
    fmt: str = "csv",
    parameters: dict | None = None,
    entity_type: str = "export",
) -> None:
    """A file of many records was produced and handed over.

    `what` is the thing exported -- a report code, a list name. `parameters`
    is how it was narrowed, which is the difference between an export of one
    ward and an export of the hospital.
    """
    record(
        action=AuditAction.EXPORT,
        entity_type=entity_type,
        entity_id=what,
        entity_label=label or what,
        metadata={
            "what": what,
            "format": fmt,
            # `None` rather than 0 when unknown. A count of zero is a claim
            # that the file was empty, and this log should not make claims it
            # cannot support.
            "rows": rows,
            "parameters": parameters or {},
        },
    )


def record_download(
    entity_type: str,
    entity_id,
    label: str,
    *,
    size_bytes: int | None = None,
    content_type: str = "",
) -> None:
    """One stored file was handed over.

    Separate from `record_export` because they answer different questions. A
    download is "somebody took *this* document"; an export is "somebody took a
    copy of a slice of the database". Collapsing them makes both harder to
    read.
    """
    record(
        action=AuditAction.DOWNLOAD,
        entity_type=entity_type,
        entity_id=str(entity_id),
        entity_label=label,
        metadata={"size_bytes": size_bytes, "content_type": content_type},
    )


def record_printable(
    entity_type: str,
    entity_id,
    label: str,
    *,
    kind: str = "",
) -> None:
    """A printable rendering was produced.

    Deliberately not called "printed". Whether the person pressed print, saved
    a PDF, or closed the tab is invisible from here, and an append-only log
    that says "printed" when it means "asked for something printable" is a
    record that will be quoted back as fact in an investigation.
    """
    record(
        action=AuditAction.PRINT,
        entity_type=entity_type,
        entity_id=str(entity_id),
        entity_label=label,
        metadata={"kind": kind, "note": "a printable was produced, not "
                                        "necessarily printed"},
    )
