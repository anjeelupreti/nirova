"""Who has been reading records, and which of it looks wrong.

Phase 3 of `docs/ACCESS_DESIGN.md`. Phases 1 and 2 made access loggable and
narrowable; this makes it *visible*. A log nobody reads is a log that only
matters after somebody complains, and by then the question is always the same:
who looked at this record, and why.

Three reports, and they answer three different questions.

**Who looked at one patient.** The question a complaint opens with, and the one
the patient themselves is entitled to ask. It has to be answerable in one query
and without interpretation.

**Which reads had no care relationship behind them.** The interesting one. Every
access is logged, but a log of thousands of legitimate reads hides the handful
that are not. Recomputing the relationship as it stands *now* is imperfect --
somebody may have had one at the time and not today -- so this is presented as
*worth looking at* rather than as a finding.

**Who reads far more than their peers.** Volume is the crudest signal and
sometimes the only one. A receptionist who opens six hundred records in a week
when their colleagues open eighty is not necessarily doing anything wrong, and
is worth a conversation. Reported against the median of the same role, because
comparing a ward nurse to a records clerk says nothing.
"""

from collections import defaultdict
from datetime import timedelta
from statistics import median

from django.db.models import Count
from django.utils import timezone

from apps.audit.models import AuditAction, AuditEvent


def _window(days: int):
    return timezone.now() - timedelta(days=days)


def who_looked_at(patient, days: int = 365) -> list:
    """Every recorded read of one patient's record.

    Returned newest first and unaggregated. A summary would be easier to read
    and is the wrong shape: somebody asking this question wants the individual
    lines, including the two minutes on a Tuesday that they remember.
    """
    events = (
        AuditEvent.objects.filter(
            entity_type="patients.Patient",
            entity_id=str(patient.uuid),
            action=AuditAction.VIEW_SENSITIVE,
            occurred_at__gte=_window(days),
        )
        .order_by("-occurred_at")
    )
    return [
        {
            "at": event.occurred_at,
            "who": event.actor_email or "the system",
            "role": event.actor_role,
            "facility": event.facility_code,
            "reason": event.reason,
            "severity": event.severity,
        }
        for event in events
    ]


def reads_without_a_relationship(days: int = 30, limit: int = 200) -> dict:
    """Reads whose reader has no care relationship with that patient *now*.

    Deliberately hedged. The relationship is recomputed at report time, and a
    clinician who saw somebody in March legitimately has none in July -- so
    these are candidates for a look, not accusations. Presenting them as
    findings would train whoever reads this to dismiss the whole report.

    Break-glass reads are excluded: they have their own queue, they are
    already reviewed one by one, and leaving them here would fill this report
    with the cases somebody has already looked at.
    """
    from apps.patients.models import Patient
    from apps.rbac.relationships import has_care_relationship

    events = (
        AuditEvent.objects.filter(
            entity_type="patients.Patient",
            action=AuditAction.VIEW_SENSITIVE,
            occurred_at__gte=_window(days),
        )
        .exclude(actor_id__isnull=True)
        .order_by("-occurred_at")[:2000]
    )

    patients = {
        str(patient.uuid): patient
        for patient in Patient.objects.filter(
            uuid__in={event.entity_id for event in events if event.entity_id}
        )
    }

    flagged = []
    checked = 0
    for event in events:
        patient = patients.get(event.entity_id)
        if patient is None:
            continue
        # A grant is its own record and its own queue; counting it here would
        # bury the reads nobody has looked at under the ones somebody has.
        if "break_glass" in (event.metadata or {}):
            continue
        checked += 1
        if has_care_relationship(event.actor_id, patient) is None:
            flagged.append({
                "at": event.occurred_at,
                "who": event.actor_email,
                "role": event.actor_role,
                "patient": event.entity_label,
                "reason": event.reason,
            })
        if len(flagged) >= limit:
            break

    return {
        "window_days": days,
        "reads_checked": checked,
        "without_a_relationship": len(flagged),
        # The ratio is the number to read. "Forty" means one thing against
        # fifty reads and another against four thousand.
        "percent": round(len(flagged) / checked * 100, 1) if checked else 0.0,
        "note": (
            "The relationship is recomputed now, so a clinician who "
            "legitimately saw somebody months ago will appear here. These are "
            "worth a look, not findings."
        ),
        "reads": flagged,
    }


def read_volume_by_person(days: int = 30) -> dict:
    """Who reads far more records than others doing the same job.

    Compared against the median of the *same role*, because a ward clerk and a
    consultant have no business being compared. An outlier is somebody worth
    asking about, and the report says so rather than implying more.
    """
    rows = (
        AuditEvent.objects.filter(
            action=AuditAction.VIEW_SENSITIVE,
            occurred_at__gte=_window(days),
        )
        .exclude(actor_id__isnull=True)
        .values("actor_id", "actor_email", "actor_role")
        .annotate(reads=Count("id"))
        .order_by("-reads")
    )

    by_role = defaultdict(list)
    for row in rows:
        by_role[row["actor_role"] or "unknown"].append(row)

    people = []
    for role, members in by_role.items():
        counts = [member["reads"] for member in members]
        middle = median(counts) if counts else 0
        for member in members:
            # Two-and-a-half times the median, and at least twenty reads --
            # without the floor, somebody reading five records against a
            # median of one is an "outlier" and the report becomes noise.
            outlier = (
                middle > 0
                and member["reads"] >= max(20, middle * 2.5)
            )
            people.append({
                "who": member["actor_email"],
                "role": role,
                "reads": member["reads"],
                "role_median": middle,
                "is_outlier": outlier,
            })

    people.sort(key=lambda person: person["reads"], reverse=True)
    return {
        "window_days": days,
        "people": people,
        "outliers": [person for person in people if person["is_outlier"]],
        "note": (
            "Compared against the median for the same role. Volume is the "
            "crudest signal there is; an outlier is somebody to ask, not "
            "somebody to accuse."
        ),
    }
