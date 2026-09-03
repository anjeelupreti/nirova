"""Arriving, triaging, treating and dispositioning in the emergency department.

Three rules.

**Nothing requires knowing who the patient is.** An unconscious arrival gets a
real patient record with a generated identifier, flagged unidentified. Every
subsequent action — triage, drugs, imaging, charges — attaches to it normally.
When somebody finally names them, the provisional record merges into the real
one through the merge machinery that already exists, and nothing written
against it is lost.

**Triage appends, never overwrites.** The denormalised category on the
arrival is a cache of the latest assessment; the assessments themselves are
the record, and a deterioration is a fact a mortality review will look for.

**Every clock starts at arrival.** Not at triage, not at activation of a
pathway. A stroke recognised forty minutes late has already spent forty
minutes of its window, and a target measured from recognition would hide
exactly the delay that matters.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: an emergency presentation is the most litigated episode in a
# hospital. Who triaged, when, to what -- and who changed it -- all matter.
from apps.audit.services import record
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.emergency.models import (
    CLOSED_DISPOSITIONS,
    PATHWAY_TARGET_MINUTES,
    TARGET_MINUTES,
    AlertPathway,
    Arrival,
    ArrivalMode,
    CriticalAlert,
    Disposition,
    ResuscitationEvent,
    TriageAssessment,
)
from apps.encounters.models import (
    Encounter,
    EncounterStatus,
    EncounterType,
    TriageCategory,
)
from apps.entitlements.services import require_module
from apps.patients.models import Gender, Patient
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.emergency")

ZERO = Decimal("0.00")

#: Placeholder surname for an unidentified arrival.
#:
#: A real value rather than an empty string, because every screen in the
#: system prints `full_name` and a blank there reads as a broken record. It is
#: never matched on: `Arrival.is_unidentified` is the flag anything should
#: branch on.
UNKNOWN_SURNAME = "Unidentified"


class EmergencyError(DomainError):
    code = "emergency_operation_failed"


class ArrivalClosed(EmergencyError):
    code = "arrival_closed"
    status_code = 409


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def _next_reference() -> str:
    stem = f"ED{timezone.localdate():%y%m%d}"
    last = (
        Arrival.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    serial = int(last[len(stem):]) + 1 if last else 1
    return f"{stem}{serial:03d}"


# ---------------------------------------------------------------------------
# Arriving
# ---------------------------------------------------------------------------


@tenant_atomic_method
def register_unidentified(
    organization,
    facility,
    actor=None,
    description: str = "",
    apparent_gender: str = "",
    apparent_age=None,
) -> Patient:
    """Create a patient record for somebody nobody can name yet.

    A real record, not a placeholder: it has an MRN, it accepts charges,
    prescriptions and results, and it merges cleanly into the identified
    record when one turns up.

    The alternative — refusing to register — means everything that happens in
    the next hour is written nowhere. The other alternative, letting staff
    type "Unknown Male" into the name field, produces a dozen patients with
    the same name that the duplicate detector then cheerfully merges into each
    other.

    `description` is what staff will actually call them. "Male, ~40, blue
    shirt, tattoo left forearm" beats "Unknown 3" when two of them are in the
    department at once — and it is what a relative arriving at the desk will
    recognise.
    """
    require_module(organization, ModuleCode.CLINIC)

    # Sequenced within the day so two unidentified arrivals are tellable
    # apart at a glance without reading the description.
    today = timezone.localdate()
    seen_today = Arrival.objects.filter(
        arrived_at__date=today, is_unidentified=True
    ).count()

    patient = Patient.objects.create(
        mrn=Patient.allocate_mrn(),
        first_name=f"Unknown {seen_today + 1}",
        last_name=UNKNOWN_SURNAME,
        gender=apparent_gender or Gender.UNKNOWN,
        notes=(
            f"Unidentified on arrival {today}. {description}".strip()
        ),
        created_by_id=getattr(actor, "uuid", None),
    )
    logger.warning(
        "UNIDENTIFIED PATIENT registered as %s at %s: %s",
        patient.mrn, facility.code, description or "no description",
    )
    record(
        AuditAction.CREATE,
        entity_type="patients.Patient",
        entity_id=patient.uuid,
        entity_label=f"{patient.mrn} — unidentified arrival",
        reason=description,
    )
    return patient


@tenant_atomic_method
def arrive(
    organization,
    facility,
    presenting_complaint: str,
    actor=None,
    patient: Patient = None,
    department=None,
    arrival_mode: str = ArrivalMode.WALK_IN,
    unidentified_description: str = "",
    apparent_gender: str = "",
    is_mlc: bool = False,
    **details,
) -> Arrival:
    """Register a presentation to the emergency department.

    With no `patient`, one is created as unidentified. That is the normal
    path for an ambulance arrival and it must be the *easy* path — a system
    where registering an unknown patient is harder than registering a known
    one gets used wrongly under pressure.
    """
    require_module(organization, ModuleCode.CLINIC)

    unidentified = patient is None
    if unidentified:
        patient = register_unidentified(
            organization, facility, actor=actor,
            description=unidentified_description,
            apparent_gender=apparent_gender,
        )
    else:
        survivor = patient.resolve()
        if survivor.pk != patient.pk:
            # Follow the merge rather than refusing. In an emergency the
            # priority is that the record attaches to *something* correct;
            # making a triage nurse resolve a merge first is the wrong
            # trade.
            patient = survivor

    open_arrival = Arrival.objects.filter(
        patient=patient, disposition=Disposition.PENDING
    ).first()
    if open_arrival is not None:
        raise EmergencyError(
            f"{patient.full_name} is already in the department under "
            f"{open_arrival.reference}.",
            detail={"arrival": open_arrival.reference},
        )

    encounter = Encounter.objects.create(
        reference=f"ENC-{_next_reference()}",
        patient=patient,
        encounter_type=EncounterType.EMERGENCY,
        status=EncounterStatus.IN_PROGRESS,
        facility=facility,
        department=department,
        chief_complaint=presenting_complaint,
        created_by_id=getattr(actor, "uuid", None),
    )

    arrival = Arrival.objects.create(
        reference=_next_reference(),
        patient=patient,
        encounter=encounter,
        facility=facility,
        department=department,
        arrival_mode=arrival_mode,
        presenting_complaint=presenting_complaint,
        is_unidentified=unidentified,
        # Both set at arrival. The first is cleared on identification; the
        # second never is, because it records what happened rather than what
        # is true now.
        arrived_unidentified=unidentified,
        provisional_description=unidentified_description,
        is_mlc=is_mlc,
        created_by_id=getattr(actor, "uuid", None),
        **details,
    )

    record(
        AuditAction.CREATE,
        entity_type="emergency.Arrival",
        entity_id=arrival.uuid,
        entity_label=f"{arrival.reference} — {patient.full_name}",
        metadata={
            "mode": arrival_mode,
            "unidentified": unidentified,
            "mlc": is_mlc,
        },
    )
    if is_mlc:
        logger.warning(
            "MEDICO-LEGAL ARRIVAL %s — police must be informed",
            arrival.reference,
        )
    return arrival


@tenant_atomic_method
def identify(
    arrival: Arrival,
    actor,
    first_name: str = "",
    last_name: str = "",
    existing_patient: Patient = None,
    **details,
) -> Arrival:
    """Put a name to an unidentified arrival.

    Two paths, and the difference matters.

    **They already have a record here.** The provisional record merges into
    it, so everything written during the resus — drugs, imaging, charges —
    lands on the chart their GP will read next month. This is why the
    provisional record had to be a real patient rather than a placeholder.

    **They are new.** The provisional record is simply named, keeping its MRN
    and everything attached to it.
    """
    if not arrival.is_unidentified:
        raise EmergencyError(f"{arrival.reference} is already identified.")

    provisional = arrival.patient

    if existing_patient is not None:
        from apps.patients.services import merge_patients

        survivor = merge_patients(
            surviving=existing_patient.resolve(),
            duplicate=provisional,
            actor=actor,
            reason=(
                f"Identified during emergency arrival {arrival.reference}."
            ),
        )
        arrival.patient = survivor
        if arrival.encounter_id:
            arrival.encounter.patient = survivor
            arrival.encounter.save(update_fields=["patient", "updated_at"])
    else:
        if not (first_name.strip() and last_name.strip()):
            raise EmergencyError(
                "Give a name, or the existing record they belong to."
            )
        provisional.first_name = first_name
        provisional.last_name = last_name
        for field, value in details.items():
            if hasattr(provisional, field) and value not in (None, ""):
                setattr(provisional, field, value)
        provisional.save()

    arrival.is_unidentified = False
    arrival.identified_at = timezone.now()
    arrival.save(
        update_fields=[
            "patient", "is_unidentified", "identified_at", "updated_at",
        ]
    )

    record(
        AuditAction.UPDATE,
        entity_type="emergency.Arrival",
        entity_id=arrival.uuid,
        entity_label=f"{arrival.reference} identified as {arrival.patient.full_name}",
        metadata={
            "merged": existing_patient is not None,
            "minutes_unidentified": arrival.minutes_unidentified,
        },
    )
    return arrival


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


@tenant_atomic_method
def triage(
    arrival: Arrival,
    category: int,
    actor,
    reason: str = "",
    **observations,
) -> TriageAssessment:
    """Assess how sick somebody is, and record that you did.

    Appends. The category on the arrival is refreshed as a cache for the
    board; the assessment is the record. A patient triaged urgent at 09:00
    and resuscitation at 09:40 has a documented deterioration, which is what
    a mortality review looks for and what an overwritten field destroys.
    """
    if not arrival.is_open:
        raise ArrivalClosed(
            f"{arrival.reference} was "
            f"{arrival.get_disposition_display().lower()}.",
            detail={"disposition": arrival.disposition},
        )

    previous = arrival.triage_category
    assessment = TriageAssessment.objects.create(
        arrival=arrival,
        category=category,
        previous_category=previous,
        assessed_by_id=getattr(actor, "uuid", None),
        assessed_by_name=getattr(actor, "full_name", "") or "",
        reason=reason,
        created_by_id=getattr(actor, "uuid", None),
        **{
            key: value for key, value in observations.items()
            if value is not None
        },
    )

    arrival.triage_category = category
    # Only the *first* triage sets the clock. A re-triage does not restart
    # the wait: somebody who has been waiting an hour has been waiting an
    # hour, whatever category they are now.
    if arrival.triaged_at is None:
        arrival.triaged_at = assessment.assessed_at
    arrival.save(
        update_fields=["triage_category", "triaged_at", "updated_at"]
    )

    if arrival.encounter_id:
        encounter = arrival.encounter
        encounter.triage_category = category
        encounter.triaged_at = encounter.triaged_at or assessment.assessed_at
        encounter.triaged_by_id = getattr(actor, "uuid", None)
        encounter.save(
            update_fields=[
                "triage_category", "triaged_at", "triaged_by_id", "updated_at",
            ]
        )

    if assessment.is_deterioration:
        logger.warning(
            "TRIAGE DETERIORATION %s: category %s -> %s (%s)",
            arrival.reference, previous, category, reason or "no reason given",
        )
    record(
        AuditAction.UPDATE,
        entity_type="emergency.Arrival",
        entity_id=arrival.uuid,
        entity_label=f"{arrival.reference} triaged {category}",
        reason=reason,
        metadata={"from": previous, "to": category},
    )
    return assessment


@tenant_atomic_method
def mark_seen(arrival: Arrival, actor, at=None) -> Arrival:
    """Record that a clinician has picked the patient up.

    The gap from arrival to here is the number the department is judged on,
    and it is only meaningful if it is recorded at the moment rather than
    inferred later from the first note somebody happened to type.
    """
    if arrival.first_seen_at is not None:
        return arrival
    arrival.first_seen_at = at or timezone.now()
    arrival.seen_by_id = getattr(actor, "uuid", None)
    arrival.seen_by_name = getattr(actor, "full_name", "") or ""
    arrival.save(
        update_fields=[
            "first_seen_at", "seen_by_id", "seen_by_name", "updated_at",
        ]
    )
    if arrival.is_breaching:
        logger.warning(
            "TRIAGE TARGET BREACHED %s: category %s seen after %d minutes "
            "against a %d minute target",
            arrival.reference, arrival.triage_category,
            arrival.waiting_minutes, arrival.target_minutes or 0,
        )
    return arrival


# ---------------------------------------------------------------------------
# Critical pathways
# ---------------------------------------------------------------------------


@tenant_atomic_method
def activate_alert(
    arrival: Arrival,
    pathway: str,
    actor,
    notes: str = "",
) -> CriticalAlert:
    """Put a patient on a time-critical pathway."""
    if not arrival.is_open:
        raise ArrivalClosed(detail={"disposition": arrival.disposition})

    alert, created = CriticalAlert.objects.get_or_create(
        arrival=arrival,
        pathway=pathway,
        defaults={
            "activated_by_id": getattr(actor, "uuid", None),
            "activated_by_name": getattr(actor, "full_name", "") or "",
            "notes": notes,
            "created_by_id": getattr(actor, "uuid", None),
        },
    )
    if created:
        logger.warning(
            "CRITICAL ALERT %s on %s — recognised %d minutes after arrival, "
            "target %d minutes to intervention",
            pathway, arrival.reference, alert.recognition_minutes,
            alert.target_minutes,
        )
        record(
            AuditAction.CREATE,
            entity_type="emergency.CriticalAlert",
            entity_id=alert.uuid,
            entity_label=f"{pathway} on {arrival.reference}",
            reason=notes,
            metadata={"recognition_minutes": alert.recognition_minutes},
        )
    return alert


@tenant_atomic_method
def record_intervention(
    alert: CriticalAlert,
    actor,
    intervention: str,
    at=None,
) -> CriticalAlert:
    """Record the pathway's defining act — thrombolysis, antibiotics, theatre."""
    alert.intervention = intervention
    alert.intervention_at = at or timezone.now()
    alert.save(
        update_fields=["intervention", "intervention_at", "updated_at"]
    )
    if alert.met_target is False:
        logger.warning(
            "PATHWAY TARGET MISSED %s on %s: %d minutes against %d",
            alert.pathway, alert.arrival.reference,
            alert.door_to_intervention_minutes, alert.target_minutes,
        )
    return alert


@tenant_atomic_method
def stand_down(alert: CriticalAlert, actor, reason: str) -> CriticalAlert:
    """Cancel a pathway that turned out not to apply.

    Recorded rather than deleted. A stroke call that stood down is a real
    event — it consumed a CT slot and a team — and a department that deleted
    them would under-count its own activity and never notice it was
    over-activating.
    """
    if not reason.strip():
        raise EmergencyError("Standing down a pathway must say why.")
    alert.stood_down_at = timezone.now()
    alert.stood_down_reason = reason
    alert.save(
        update_fields=["stood_down_at", "stood_down_reason", "updated_at"]
    )
    return alert


# ---------------------------------------------------------------------------
# Resuscitation
# ---------------------------------------------------------------------------


@tenant_atomic_method
def log_resus(
    arrival: Arrival,
    event_type: str,
    actor,
    detail: str = "",
    at=None,
    **fields,
) -> ResuscitationEvent:
    """Add one timed entry to a resuscitation record.

    Timestamped on creation and never edited. A resus written afterwards from
    memory is not good enough for the thing a coroner reads, and a record that
    can be edited is a record that will be.
    """
    return ResuscitationEvent.objects.create(
        arrival=arrival,
        occurred_at=at or timezone.now(),
        event_type=event_type,
        detail=detail,
        recorded_by_id=getattr(actor, "uuid", None),
        recorded_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
        **{key: value for key, value in fields.items() if value not in (None, "")},
    )


def resuscitation_record(arrival: Arrival) -> dict:
    """The whole resus, in order, with elapsed times.

    Elapsed from the first entry rather than from arrival: a resus that starts
    twenty minutes into an attendance is still a resus that ran for eleven
    minutes, and that is the number the debrief needs.
    """
    events = list(arrival.resuscitation.order_by("occurred_at"))
    if not events:
        return {"arrival": arrival.reference, "events": [], "duration_minutes": 0}

    start = events[0].occurred_at
    rows = [
        {
            "at": event.occurred_at,
            "elapsed_minutes": int(
                (event.occurred_at - start).total_seconds() // 60
            ),
            "event_type": event.event_type,
            "detail": event.detail,
            "drug": event.drug,
            "dose": event.dose,
            "route": event.route,
            "joules": event.joules,
            "rhythm": event.rhythm,
            "recorded_by": event.recorded_by_name,
        }
        for event in events
    ]
    return {
        "arrival": arrival.reference,
        "started_at": start,
        "duration_minutes": rows[-1]["elapsed_minutes"],
        "shocks": sum(1 for row in rows if row["event_type"] == "shock"),
        "drugs": sum(1 for row in rows if row["event_type"] == "drug"),
        "rosc": any(row["event_type"] == "rosc" for row in rows),
        "events": rows,
    }


# ---------------------------------------------------------------------------
# Leaving
# ---------------------------------------------------------------------------


@tenant_atomic_method
def dispose(
    arrival: Arrival,
    disposition: str,
    actor,
    notes: str = "",
    admission_reference: str = "",
    referred_to: str = "",
) -> Arrival:
    """Close the episode.

    `LWBS` is available and deliberately prominent. A patient who gives up
    waiting and goes home is a fact about the department, and one that only
    exists if somebody records it — otherwise the encounter simply goes quiet
    and the department's own numbers flatter it.
    """
    if disposition not in CLOSED_DISPOSITIONS:
        raise EmergencyError(f"'{disposition}' is not a way an attendance ends.")
    if not arrival.is_open:
        raise ArrivalClosed(
            f"{arrival.reference} was already "
            f"{arrival.get_disposition_display().lower()}.",
            detail={"disposition": arrival.disposition},
        )
    if disposition == Disposition.REFERRED and not referred_to.strip():
        raise EmergencyError("A referral must say where to.")
    if disposition == Disposition.ADMITTED and not admission_reference.strip():
        raise EmergencyError(
            "Admit the patient first, then record the admission reference — "
            "an attendance marked admitted with no admission is a patient "
            "nobody is looking after."
        )

    arrival.disposition = disposition
    arrival.disposition_at = timezone.now()
    arrival.disposition_notes = notes
    arrival.admission_reference = admission_reference
    arrival.referred_to = referred_to
    arrival.save()

    if arrival.encounter_id:
        encounter = arrival.encounter
        encounter.status = EncounterStatus.COMPLETED
        encounter.ended_at = arrival.disposition_at
        encounter.save(update_fields=["status", "ended_at", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="emergency.Arrival",
        entity_id=arrival.uuid,
        entity_label=f"{arrival.reference} {disposition}",
        reason=notes,
        metadata={
            "minutes_in_department": arrival.total_minutes,
            "waited_minutes": arrival.waiting_minutes,
            "breached": arrival.is_breaching,
        },
    )
    if disposition == Disposition.LWBS:
        logger.warning(
            "LEFT WITHOUT BEING SEEN %s after %d minutes at category %s",
            arrival.reference, arrival.waiting_minutes,
            arrival.triage_category,
        )
    return arrival


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------


def board(facility) -> list:
    """Everyone currently in the department, sickest and longest-waiting first.

    The ordering is the whole point: triage category, then arrival time. A
    board sorted by arrival alone is a first-come-first-served queue, which is
    precisely what triage exists to override.
    """
    rows = (
        Arrival.objects.filter(
            facility=facility, disposition=Disposition.PENDING
        )
        .select_related("patient")
        .prefetch_related("alerts")
        # Nulls last: an untriaged patient is not "category zero", they are
        # somebody nobody has assessed, and they belong at the top of the
        # *untriaged* group rather than ahead of a resuscitation call.
        .order_by(models.F("triage_category").asc(nulls_last=True), "arrived_at")
    )
    return [
        {
            "reference": arrival.reference,
            "patient": arrival.patient.full_name,
            "mrn": arrival.patient.mrn,
            "is_unidentified": arrival.is_unidentified,
            "minutes_unidentified": arrival.minutes_unidentified,
            "description": arrival.provisional_description,
            "complaint": arrival.presenting_complaint,
            "arrival_mode": arrival.arrival_mode,
            "arrived_at": arrival.arrived_at,
            "triage_category": arrival.triage_category,
            "waiting_minutes": arrival.waiting_minutes,
            "target_minutes": arrival.target_minutes,
            "minutes_to_breach": arrival.minutes_to_breach,
            "is_breaching": arrival.is_breaching,
            "seen": arrival.first_seen_at is not None,
            "seen_by": arrival.seen_by_name,
            "is_mlc": arrival.is_mlc,
            "alerts": [
                {
                    "pathway": alert.pathway,
                    "target_minutes": alert.target_minutes,
                    "elapsed": alert.door_to_intervention_minutes,
                    "met_target": alert.met_target,
                    "stood_down": alert.stood_down_at is not None,
                }
                for alert in arrival.alerts.all()
            ],
        }
        for arrival in rows
    ]


def department_summary(facility, since=None) -> dict:
    """How the department is performing.

    Every figure here is one a department is externally judged on, so each is
    computed rather than stored and each says what it measures.
    """
    since = since or (timezone.localdate() - timedelta(days=7))
    arrivals = Arrival.objects.filter(
        facility=facility, arrived_at__date__gte=since
    )
    closed = arrivals.exclude(disposition=Disposition.PENDING)

    by_disposition = dict(
        closed.values_list("disposition")
        .annotate(n=models.Count("id"))
        .values_list("disposition", "n")
    )
    by_category = dict(
        arrivals.exclude(triage_category__isnull=True)
        .values_list("triage_category")
        .annotate(n=models.Count("id"))
        .values_list("triage_category", "n")
    )
    by_mode = dict(
        arrivals.values_list("arrival_mode")
        .annotate(n=models.Count("id"))
        .values_list("arrival_mode", "n")
    )

    seen = [row for row in arrivals if row.first_seen_at]
    waits = [row.waiting_minutes for row in seen]
    breaches = [row for row in seen if row.is_breaching]

    total = closed.count() or 1
    lwbs = by_disposition.get(Disposition.LWBS, 0)

    # Breach rate per category, because an aggregate hides the thing that
    # matters: a department can breach 5% overall while missing every single
    # category-2 target.
    per_category = {}
    for row in seen:
        if row.triage_category is None:
            continue
        bucket = per_category.setdefault(
            row.triage_category, {"seen": 0, "breached": 0}
        )
        bucket["seen"] += 1
        if row.is_breaching:
            bucket["breached"] += 1
    for bucket in per_category.values():
        bucket["breach_percent"] = round(
            bucket["breached"] / bucket["seen"] * 100, 1
        )

    return {
        "since": since,
        "arrivals": arrivals.count(),
        "in_department": arrivals.filter(
            disposition=Disposition.PENDING
        ).count(),
        "by_disposition": by_disposition,
        "by_triage_category": by_category,
        "by_arrival_mode": by_mode,
        "median_wait_minutes": (
            sorted(waits)[len(waits) // 2] if waits else 0
        ),
        "longest_wait_minutes": max(waits) if waits else 0,
        "breaches": len(breaches),
        "breach_percent": (
            round(len(breaches) / len(seen) * 100, 1) if seen else 0.0
        ),
        "breach_by_category": per_category,
        # The number a department is most tempted not to look at.
        "left_without_being_seen": lwbs,
        "lwbs_percent": round(lwbs / total * 100, 1),
        # Counted on the arrival fact, not the current state. Counting
        # `is_unidentified` reports zero for everybody eventually identified,
        # which is to say for almost everybody.
        "arrived_unidentified": arrivals.filter(
            arrived_unidentified=True
        ).count(),
        "still_unidentified": arrivals.filter(is_unidentified=True).count(),
        "medico_legal": arrivals.filter(is_mlc=True).count(),
    }


def pathway_performance(facility, since=None) -> list:
    """Door-to-intervention against target, per pathway.

    Recognition time is reported separately from intervention time, because
    they have different fixes: a slow recognition is a triage problem, a slow
    intervention is a resource problem, and a single door-to-needle figure
    cannot tell a department which it has.
    """
    since = since or (timezone.localdate() - timedelta(days=90))
    alerts = CriticalAlert.objects.filter(
        arrival__facility=facility, activated_at__date__gte=since
    ).select_related("arrival")

    grouped = {}
    for alert in alerts:
        bucket = grouped.setdefault(
            alert.pathway,
            {
                "pathway": alert.pathway,
                "target_minutes": alert.target_minutes,
                "activations": 0,
                "stood_down": 0,
                "with_intervention": 0,
                "met_target": 0,
                "recognition": [],
                "door_to_intervention": [],
            },
        )
        bucket["activations"] += 1
        if alert.stood_down_at:
            bucket["stood_down"] += 1
            continue
        bucket["recognition"].append(alert.recognition_minutes)
        elapsed = alert.door_to_intervention_minutes
        if elapsed is not None:
            bucket["with_intervention"] += 1
            bucket["door_to_intervention"].append(elapsed)
            if alert.met_target:
                bucket["met_target"] += 1

    def average(values):
        return round(sum(values) / len(values), 1) if values else None

    return [
        {
            "pathway": bucket["pathway"],
            "target_minutes": bucket["target_minutes"],
            "activations": bucket["activations"],
            "stood_down": bucket["stood_down"],
            "with_intervention": bucket["with_intervention"],
            "met_target": bucket["met_target"],
            "met_target_percent": (
                round(
                    bucket["met_target"] / bucket["with_intervention"] * 100, 1
                )
                if bucket["with_intervention"] else None
            ),
            "average_recognition_minutes": average(bucket["recognition"]),
            "average_door_to_intervention_minutes": average(
                bucket["door_to_intervention"]
            ),
        }
        for bucket in sorted(grouped.values(), key=lambda row: row["pathway"])
    ]
