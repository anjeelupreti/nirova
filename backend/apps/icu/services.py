"""Charting, titrating, scoring and stepping down.

The rules this layer exists to keep, none of which a model can keep alone.

**Every number is derived from the ledger.** Fluid balance, volume infused,
ventilator days, line-days — all computed from the rows, never stored as
counters. A stored total and a ledger disagree the first time somebody
corrects an entry, and the ledger is always the one that is right.

**Scoring names its gaps.** `sofa` returns which organ systems had no data
alongside the number. SOFA assigns zero to a normal value, so a missing
platelet count and a healthy one score identically, and the error always runs
in the same direction: towards a patient who looks less sick than they are.

**Alerts are raised against the patient's own thresholds**, are marked when
they come from unvalidated device data, and never disappear because the number
came back. A night of self-clearing desaturations is precisely what a morning
review needs to see.

**Nothing is charted against a stay that has ended.** Not because the write
would corrupt anything, but because it almost always means the wrong patient
is selected.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: intensive care is where the notes are read afterwards -- by a
# mortality review, by a family, by a court. Who changed the noradrenaline and
# when is the substance of that reading.
from apps.audit.services import record
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.icu.models import (
    DEFAULT_THRESHOLDS,
    FASTHUG_KEYS,
    Alert,
    AlertSeverity,
    AlertThreshold,
    AdmissionRoute,
    DeviceType,
    FluidDirection,
    FluidEntry,
    FluidRoute,
    IcuOutcome,
    IcuStay,
    Infusion,
    InfusionRate,
    InfusionStatus,
    InvasiveDevice,
    Observation,
    ObservationSource,
    Round,
    SofaScore,
    VentilationMode,
    VentilationRecord,
    icu_day_of,
    validate_stay_open,
)
from apps.inpatient.models import AdmissionStatus, Bed, Ward, WardType
from apps.inpatient.services import transfer_bed
# tenant_atomic_method: transactions must open on the tenant connection. The
# router raises rather than guessing, so a bare `transaction.atomic` here
# would open on the control plane and silently protect nothing.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.icu")

#: Ward types that count as critical care. Held here rather than tested
#: inline so that adding a burns unit is one edit.
CRITICAL_CARE_WARDS = {WardType.ICU, WardType.NICU, WardType.PICU, WardType.HDU}

#: Vasopressors, for the cardiovascular component of SOFA. Matched on the
#: drug name because prescribing here is free-text: an ICU stocks what it can
#: get, and a product catalogue that lags reality would score every septic
#: patient as zero.
VASOPRESSORS = ("noradrenaline", "norepinephrine", "adrenaline",
                "epinephrine", "dopamine", "dobutamine", "vasopressin")


class IcuError(DomainError):
    """Something about this stay does not add up."""


# ---------------------------------------------------------------------------
# The stay
# ---------------------------------------------------------------------------


@tenant_atomic_method
def admit_to_icu(
    organization,
    admission,
    ward: Ward,
    bed: Bed,
    reason: str,
    actor,
    route: str = AdmissionRoute.WARD,
    consultant=None,
    at=None,
) -> IcuStay:
    """Start an ICU episode, moving the patient into the unit's bed.

    The bed move goes through `inpatient.transfer_bed` rather than being
    written here. There is one bed board in this system, and a second one that
    only the ICU knows about would make the census wrong the day somebody
    looked at both.
    """
    require_module(organization, ModuleCode.HOSPITAL)

    if admission.status != AdmissionStatus.ADMITTED:
        raise IcuError(
            f"{admission.reference} is "
            f"{admission.get_status_display().lower()} — only a patient who "
            "is currently admitted can be taken into the unit.",
            detail={"status": admission.status},
        )
    if ward.ward_type not in CRITICAL_CARE_WARDS:
        raise IcuError(
            f"{ward.name} is a {ward.get_ward_type_display().lower()}, not a "
            "critical-care area.",
            detail={"ward_type": ward.ward_type},
        )
    if bed.ward_id != ward.id:
        raise IcuError(f"{bed} is not in {ward.name}.")
    if not reason.strip():
        raise IcuError("An ICU admission must record why.")

    # An open stay already exists: the patient is in the unit. Re-admitting
    # would produce two overlapping stays and double every ventilator day.
    existing = admission.icu_stays.filter(outcome=IcuOutcome.ONGOING).first()
    if existing:
        raise IcuError(
            f"{admission.patient.full_name} has been in the unit since "
            f"{existing.admitted_at:%Y-%m-%d %H:%M}.",
            detail={"stay": str(existing.uuid)},
        )

    at = at or timezone.now()
    transfer_bed(admission, bed, actor=actor, reason=f"To ICU: {reason}")

    stay = IcuStay.objects.create(
        admission=admission,
        patient=admission.patient,
        facility=admission.facility,
        ward=ward,
        bed=bed,
        admitted_at=at,
        route=route,
        reason=reason,
        primary_diagnosis=admission.provisional_diagnosis
        or admission.admitting_diagnosis,
        consultant_id=getattr(consultant, "uuid", None),
        consultant_name=getattr(consultant, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
    )
    record(
        AuditAction.CREATE,
        entity_type="icu.IcuStay",
        entity_id=stay.uuid,
        entity_label=f"{admission.patient.full_name} into {ward.name}",
        reason=reason,
    )
    return stay


@tenant_atomic_method
def set_ceiling_of_care(
    stay: IcuStay, ceiling: str, actor, for_resuscitation: bool,
) -> IcuStay:
    """Record what this patient is, and is not, for.

    Kept explicit because it changes what an alert means. A falling blood
    pressure in a patient not for escalation is not a call for the arrest
    team, and a system that pages anyway teaches people to ignore pages.
    """
    validate_stay_open(stay)
    if not ceiling.strip():
        raise IcuError("A ceiling of care must say what it is.")

    stay.ceiling_of_care = ceiling
    stay.is_for_resuscitation = for_resuscitation
    stay.ceiling_set_by = getattr(actor, "full_name", "") or ""
    stay.ceiling_set_at = timezone.now()
    stay.save(update_fields=[
        "ceiling_of_care", "is_for_resuscitation", "ceiling_set_by",
        "ceiling_set_at", "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="icu.IcuStay",
        entity_id=stay.uuid,
        entity_label=f"Ceiling of care for {stay.patient.full_name}",
        reason=ceiling,
        metadata={"for_resuscitation": for_resuscitation},
    )
    return stay


def step_down_blockers(stay: IcuStay) -> list:
    """What still holds this patient in the unit.

    Sentences rather than a boolean, because "not ready" is never the useful
    answer. The bed manager needs to know that it is the noradrenaline, so
    they can ask whether it can come down.

    Each blocker is labelled `clinical` or `record`. Both stop a step-down,
    but they are different arguments: a patient on a vasopressor is unfit for
    a ward, whereas a critical alert nobody has acknowledged is a piece of
    unfinished reviewing. Presenting them as one undifferentiated list is how
    a charge nurse learns to skim the whole thing.
    """
    blockers = []

    def add(kind, detail):
        blockers.append({"kind": kind, "detail": detail})

    running = stay.infusions.filter(status=InfusionStatus.RUNNING)
    pressors = [
        infusion.drug_name for infusion in running
        if _is_vasopressor(infusion.drug_name)
    ]
    if pressors:
        add("clinical",
            f"Still on {', '.join(pressors)} — a ward cannot titrate a "
            "vasopressor.")

    vent = stay.ventilation.order_by("-recorded_at").first()
    if vent and vent.is_invasive:
        add("clinical",
            f"Invasively ventilated ({vent.get_mode_display()}) as of "
            f"{vent.recorded_at:%d %b %H:%M}.")
    elif vent and vent.fio2 and vent.fio2 > 40:
        add("clinical",
            f"Requires {vent.fio2}% oxygen — above what a general ward "
            "delivers.")

    latest = stay.observations.order_by("-recorded_at").first()
    if latest:
        gcs = latest.gcs_total
        if gcs is not None and gcs < 13 and not latest.gcs_verbal_not_testable:
            add("clinical", f"GCS {gcs} at {latest.recorded_at:%H:%M}.")

    if stay.devices.filter(
        device_type=DeviceType.DIALYSIS_CATHETER, removed_at__isnull=True,
    ).exists():
        add("clinical", "Dialysis catheter in situ — renal support ongoing.")

    unacknowledged = stay.alerts.filter(
        acknowledged_at__isnull=True, severity=AlertSeverity.CRITICAL,
    ).count()
    if unacknowledged:
        add("record",
            f"{unacknowledged} critical alert"
            f"{'s' if unacknowledged != 1 else ''} nobody has acknowledged.")

    return blockers


@tenant_atomic_method
def discharge_from_icu(
    stay: IcuStay,
    outcome: str,
    actor,
    notes: str = "",
    bed: Bed = None,
    at=None,
    override_blockers: bool = False,
) -> IcuStay:
    """End the ICU episode.

    Blockers are advisory: a unit under pressure steps down a patient on a low
    dose of noradrenaline to an HDU that can manage it, and a system that
    refuses gets worked around by not recording the infusion. So it refuses by
    default, states what is holding the patient, and takes an explicit
    override that is written into the audit trail.
    """
    if not stay.is_current:
        raise IcuError(
            f"This stay already ended on {stay.discharged_at:%Y-%m-%d %H:%M}."
        )
    if outcome == IcuOutcome.ONGOING:
        raise IcuError("A discharge needs an outcome.")

    blockers = step_down_blockers(stay)
    if blockers and outcome in (IcuOutcome.TO_WARD, IcuOutcome.TO_HDU):
        if not override_blockers:
            raise IcuError(
                "This patient is not ready to leave the unit.",
                detail={"blockers": blockers},
            )
        logger.warning(
            "ICU step-down overridden for %s: %s",
            stay.patient.full_name,
            "; ".join(row["detail"] for row in blockers),
        )

    at = at or timezone.now()
    if at < stay.admitted_at:
        raise IcuError("A discharge cannot precede the admission.")

    # Stop what is still running. An infusion left running against a closed
    # stay would accumulate volume forever in every later calculation.
    for infusion in stay.infusions.filter(status=InfusionStatus.RUNNING):
        stop_infusion(infusion, actor=actor, reason="ICU discharge", at=at)

    if bed is not None:
        transfer_bed(
            stay.admission, bed, actor=actor,
            reason=f"Out of ICU: {dict(IcuOutcome.choices).get(outcome, outcome)}",
        )

    stay.outcome = outcome
    stay.discharged_at = at
    stay.outcome_notes = notes
    stay.save(update_fields=[
        "outcome", "discharged_at", "outcome_notes", "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="icu.IcuStay",
        entity_id=stay.uuid,
        entity_label=f"{stay.patient.full_name} left the unit",
        reason=notes or outcome,
        metadata={
            "outcome": outcome,
            "hours": str(stay.hours),
            "blockers_overridden": blockers if override_blockers else [],
        },
    )
    return stay


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


@tenant_atomic_method
def chart_observation(
    stay: IcuStay,
    actor=None,
    at=None,
    source: str = ObservationSource.MANUAL,
    device_identifier: str = "",
    **values,
) -> Observation:
    """Record one set of vital signs, and raise whatever alerts follow.

    `at` is a parameter rather than always `now()`. Observations get charted
    late — a nurse writes the 04:00 set at 04:40 — and a chart that records
    when it was typed rather than when it was taken produces a trend that is
    quietly forty minutes out of step with the drugs beside it.
    """
    validate_stay_open(stay)

    allowed = {
        "heart_rate", "systolic", "diastolic", "mean_arterial_pressure",
        "respiratory_rate", "spo2", "temperature", "gcs_eye", "gcs_verbal",
        "gcs_motor", "gcs_verbal_not_testable", "pupil_left_mm",
        "pupil_right_mm", "pupils_reactive", "rass", "pain_score",
        "blood_glucose", "lactate", "notes",
    }
    unknown = set(values) - allowed
    if unknown:
        raise IcuError(f"Not observation fields: {', '.join(sorted(unknown))}.")

    observation = Observation.objects.create(
        stay=stay,
        recorded_at=at or timezone.now(),
        source=source,
        device_identifier=device_identifier,
        created_by_id=getattr(actor, "uuid", None),
        **values,
    )
    evaluate_alerts(stay, observation)
    return observation


@tenant_atomic_method
def validate_observation(observation: Observation, actor) -> Observation:
    """A person confirms a device reading.

    Validation is an added fact, never a filter. The unvalidated row stays, so
    that a number somebody rejected is still visible as a number the monitor
    produced — which is how a failing transducer gets noticed.
    """
    if observation.source != ObservationSource.DEVICE:
        raise IcuError("Only device readings need validating.")

    observation.validated_by_id = getattr(actor, "uuid", None)
    observation.validated_by_name = getattr(actor, "full_name", "") or ""
    observation.validated_at = timezone.now()
    observation.save(update_fields=[
        "validated_by_id", "validated_by_name", "validated_at", "updated_at",
    ])
    return observation


def trend(stay: IcuStay, parameter: str, hours: int = 24) -> list:
    """One parameter over time, for a sparkline.

    Returns points, not a summary. The shape is the clinical content: a
    pressure that has been 70 all night and a pressure that fell to 70 in the
    last hour are the same number and different emergencies.
    """
    since = timezone.now() - timedelta(hours=hours)
    rows = (
        stay.observations.filter(recorded_at__gte=since)
        .exclude(**{f"{parameter}__isnull": True})
        .order_by("recorded_at")
        .values("recorded_at", parameter, "source", "validated_at")
    )
    return [
        {
            "at": row["recorded_at"],
            "value": row[parameter],
            "source": row["source"],
            "validated": row["source"] != ObservationSource.DEVICE
            or row["validated_at"] is not None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def thresholds_for(stay: IcuStay) -> dict:
    """The unit's defaults, with this patient's overrides applied."""
    resolved = {
        parameter: {
            "low": low, "high": high,
            "critical_low": critical_low, "critical_high": critical_high,
            "source": "unit",
        }
        for parameter, (low, high, critical_low, critical_high)
        in DEFAULT_THRESHOLDS.items()
    }
    for override in stay.thresholds.all():
        resolved[override.parameter] = {
            "low": override.low,
            "high": override.high,
            "critical_low": override.critical_low,
            "critical_high": override.critical_high,
            "source": "patient",
            "reason": override.reason,
        }
    return resolved


@tenant_atomic_method
def evaluate_alerts(stay: IcuStay, observation: Observation) -> list:
    """Compare an observation against the thresholds and raise what breaches.

    Raised at the moment of charting rather than by a sweep, because an alert
    a minute late is an alert about a patient somebody has already walked away
    from.
    """
    resolved = thresholds_for(stay)
    unvalidated = (
        observation.source == ObservationSource.DEVICE
        and observation.validated_at is None
    )
    raised = []

    for parameter, limits in resolved.items():
        value = getattr(observation, parameter, None)
        if parameter == "mean_arterial_pressure":
            # Use the derived MAP when no arterial line reported one --
            # otherwise a patient on a cuff never triggers a pressure alert.
            value = observation.map_value
        if value is None:
            continue

        value = Decimal(str(value))
        severity = None
        threshold_text = ""

        critical_low = limits.get("critical_low")
        critical_high = limits.get("critical_high")
        low = limits.get("low")
        high = limits.get("high")

        if critical_low is not None and value < Decimal(str(critical_low)):
            severity, threshold_text = AlertSeverity.CRITICAL, f"< {critical_low}"
        elif critical_high is not None and value > Decimal(str(critical_high)):
            severity, threshold_text = AlertSeverity.CRITICAL, f"> {critical_high}"
        elif low is not None and value < Decimal(str(low)):
            severity, threshold_text = AlertSeverity.WARNING, f"< {low}"
        elif high is not None and value > Decimal(str(high)):
            severity, threshold_text = AlertSeverity.WARNING, f"> {high}"

        if severity is None:
            continue

        alert, created = Alert.objects.get_or_create(
            stay=stay,
            parameter=parameter,
            raised_at=observation.recorded_at,
            defaults={
                "observation": observation,
                "severity": severity,
                "value": str(value),
                "threshold": threshold_text,
                "from_unvalidated_device": unvalidated,
                "message": _alert_sentence(
                    parameter, value, threshold_text, limits, stay,
                ),
            },
        )
        if created:
            raised.append(alert)

    if raised:
        logger.info(
            "ICU alerts for %s: %s",
            stay.patient.full_name,
            ", ".join(f"{a.parameter}={a.value}" for a in raised),
        )
    return raised


def _alert_sentence(parameter, value, threshold_text, limits, stay) -> str:
    """A sentence a nurse can act on, not a field name and a number.

    Includes the resuscitation status when the patient is not for escalation,
    because that is the single most important thing to know before responding
    to the alert, and it is the thing least likely to be to hand at 3 a.m.
    """
    label = parameter.replace("_", " ")
    sentence = f"{label} {value} ({threshold_text})"
    if limits.get("source") == "patient":
        sentence += f" — patient threshold: {limits.get('reason', 'set')}"
    if not stay.is_for_resuscitation:
        sentence += ". Not for resuscitation — see the ceiling of care."
    return sentence


@tenant_atomic_method
def acknowledge_alert(alert: Alert, actor, action: str = "") -> Alert:
    """Somebody saw it, and says so.

    Re-acknowledging is refused rather than silently overwriting: the first
    person to see it is the one the record should name.
    """
    if alert.is_acknowledged:
        raise IcuError(
            f"Already acknowledged by {alert.acknowledged_by_name} at "
            f"{alert.acknowledged_at:%H:%M}."
        )
    alert.acknowledged_at = timezone.now()
    alert.acknowledged_by_id = getattr(actor, "uuid", None)
    alert.acknowledged_by_name = getattr(actor, "full_name", "") or ""
    alert.action_taken = action
    alert.save(update_fields=[
        "acknowledged_at", "acknowledged_by_id", "acknowledged_by_name",
        "action_taken", "updated_at",
    ])
    return alert


@tenant_atomic_method
def set_threshold(
    stay: IcuStay, parameter: str, actor, reason: str, **limits,
) -> AlertThreshold:
    """Widen or narrow one parameter for this patient.

    A reason is required. A threshold widened without one is indistinguishable
    from an alarm somebody silenced because it was annoying, and the two need
    opposite responses at a handover.
    """
    validate_stay_open(stay)
    if parameter not in DEFAULT_THRESHOLDS:
        raise IcuError(
            f"{parameter} is not an alertable parameter. Known: "
            f"{', '.join(sorted(DEFAULT_THRESHOLDS))}."
        )
    if not reason.strip():
        raise IcuError("Changing a patient's alert threshold must say why.")

    threshold, _ = AlertThreshold.objects.update_or_create(
        stay=stay,
        parameter=parameter,
        defaults={
            "low": limits.get("low"),
            "high": limits.get("high"),
            "critical_low": limits.get("critical_low"),
            "critical_high": limits.get("critical_high"),
            "reason": reason,
            "set_by_name": getattr(actor, "full_name", "") or "",
        },
    )
    record(
        AuditAction.UPDATE,
        entity_type="icu.AlertThreshold",
        entity_id=threshold.uuid,
        entity_label=f"{parameter} for {stay.patient.full_name}",
        reason=reason,
    )
    return threshold


def alert_summary(stay: IcuStay, hours: int = 24) -> dict:
    """What fired, what was seen, and how quickly.

    Time-to-acknowledge is the number that says whether the alerting is
    trusted. A unit where the median is four hours has alarm fatigue whatever
    anybody says about it.
    """
    since = timezone.now() - timedelta(hours=hours)
    rows = list(stay.alerts.filter(raised_at__gte=since))
    acknowledged = [
        row.minutes_to_acknowledge for row in rows if row.is_acknowledged
    ]
    by_parameter = {}
    for row in rows:
        by_parameter[row.parameter] = by_parameter.get(row.parameter, 0) + 1

    return {
        "hours": hours,
        "total": len(rows),
        "critical": sum(
            1 for row in rows if row.severity == AlertSeverity.CRITICAL
        ),
        "unacknowledged": sum(1 for row in rows if not row.is_acknowledged),
        "from_unvalidated_devices": sum(
            1 for row in rows if row.from_unvalidated_device
        ),
        "median_minutes_to_acknowledge": _median(acknowledged),
        "by_parameter": dict(
            sorted(by_parameter.items(), key=lambda item: -item[1])
        ),
    }


def _median(values: list):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ---------------------------------------------------------------------------
# Fluid balance
# ---------------------------------------------------------------------------


@tenant_atomic_method
def record_fluid(
    stay: IcuStay,
    direction: str,
    route: str,
    volume_ml: int,
    actor=None,
    description: str = "",
    at=None,
) -> FluidEntry:
    """One volume in or out."""
    validate_stay_open(stay)
    if volume_ml <= 0:
        raise IcuError(
            "A fluid entry must have a volume. To correct one, reverse it."
        )
    return FluidEntry.objects.create(
        stay=stay,
        direction=direction,
        route=route,
        volume_ml=volume_ml,
        description=description,
        recorded_at=at or timezone.now(),
        recorded_by_id=getattr(actor, "uuid", None),
        recorded_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
    )


@tenant_atomic_method
def reverse_fluid(entry: FluidEntry, actor, reason: str = "") -> FluidEntry:
    """Correct an entry by reversing it, never by editing it.

    An edited chart is a chart nobody can audit. The reversal is visible, and
    "somebody corrected the 14:00 output" is itself worth seeing.
    """
    if hasattr(entry, "reversed_by"):
        raise IcuError("That entry has already been reversed.")
    if entry.reverses_id:
        raise IcuError("A reversal cannot itself be reversed.")

    return FluidEntry.objects.create(
        stay=entry.stay,
        direction=(
            FluidDirection.OUT
            if entry.direction == FluidDirection.IN
            else FluidDirection.IN
        ),
        route=entry.route,
        volume_ml=entry.volume_ml,
        description=f"Reversal: {reason}" if reason else "Reversal",
        reverses=entry,
        recorded_by_id=getattr(actor, "uuid", None),
        recorded_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
    )


def fluid_balance(stay: IcuStay, hours: int = 24, until=None) -> dict:
    """In, out, and the difference, over a window — computed, never stored.

    Broken down by route because the total is ambiguous: two litres positive
    from maintenance fluid and two litres positive because the patient has
    stopped passing urine are the same figure and opposite problems.
    """
    until = until or timezone.now()
    since = until - timedelta(hours=hours)
    rows = stay.fluid_entries.filter(
        recorded_at__gte=since, recorded_at__lte=until,
    )

    intake = sum(
        row.volume_ml for row in rows if row.direction == FluidDirection.IN
    )
    output = sum(
        row.volume_ml for row in rows if row.direction == FluidDirection.OUT
    )

    by_route = {}
    for row in rows:
        key = f"{row.direction}:{row.route}"
        by_route[key] = by_route.get(key, 0) + row.volume_ml

    urine = sum(
        row.volume_ml for row in rows if row.route == FluidRoute.URINE
    )
    # Urine output per kilo per hour is the number that defines acute kidney
    # injury. Without a weight it cannot be computed, and guessing 70kg is how
    # a paediatric patient's oliguria gets missed -- so it stays None.
    weight = stay.weight_kg
    urine_rate = None
    if weight and hours:
        urine_rate = (
            Decimal(urine) / Decimal(str(weight)) / Decimal(hours)
        ).quantize(Decimal("0.01"))

    return {
        "hours": hours,
        "intake_ml": intake,
        "output_ml": output,
        "balance_ml": intake - output,
        "urine_ml": urine,
        "urine_ml_per_kg_per_hour": urine_rate,
        "by_route": by_route,
        "entries": rows.count(),
    }


def cumulative_balance(stay: IcuStay) -> dict:
    """Balance for every ICU day since admission.

    The cumulative figure is the one that matters and the one nobody has: a
    patient six litres up over four days is in trouble that no single day's
    chart shows.
    """
    days = []
    running = 0
    day = 1
    start = stay.admitted_at
    end = stay.discharged_at or timezone.now()

    while start < end:
        finish = min(start + timedelta(days=1), end)
        rows = stay.fluid_entries.filter(
            recorded_at__gte=start, recorded_at__lt=finish,
        )
        intake = sum(
            row.volume_ml for row in rows if row.direction == FluidDirection.IN
        )
        output = sum(
            row.volume_ml for row in rows if row.direction == FluidDirection.OUT
        )
        running += intake - output
        days.append({
            "icu_day": day,
            "from": start,
            "intake_ml": intake,
            "output_ml": output,
            "balance_ml": intake - output,
            "cumulative_ml": running,
        })
        start, day = finish, day + 1

    return {"days": days, "cumulative_ml": running}


# ---------------------------------------------------------------------------
# Infusions
# ---------------------------------------------------------------------------


def _is_vasopressor(drug_name: str) -> bool:
    lowered = drug_name.lower()
    return any(name in lowered for name in VASOPRESSORS)


@tenant_atomic_method
def start_infusion(
    stay: IcuStay,
    drug_name: str,
    rate,
    actor,
    concentration: str = "",
    rate_unit: str = "ml/hr",
    is_titratable: bool = False,
    target: str = "",
    maximum_rate=None,
    at=None,
) -> Infusion:
    """Start a continuous drug at a rate.

    The starting rate is written as an `InfusionRate` row rather than a field
    on the infusion, so that the first rate and every later change are the
    same kind of thing. A "starting rate" column plus a change log is two
    places to look for one answer, and volume calculations always forget one.
    """
    validate_stay_open(stay)
    if not drug_name.strip():
        raise IcuError("An infusion needs a drug name.")
    rate = Decimal(str(rate))
    if rate < 0:
        raise IcuError("A rate cannot be negative.")
    if is_titratable and not target.strip():
        raise IcuError(
            "A titratable infusion must say what it is titrated to — a nurse "
            "cannot titrate to nothing."
        )

    at = at or timezone.now()
    infusion = Infusion.objects.create(
        stay=stay,
        drug_name=drug_name,
        concentration=concentration,
        rate_unit=rate_unit,
        is_titratable=is_titratable,
        target=target,
        maximum_rate=maximum_rate,
        started_at=at,
        prescribed_by_id=getattr(actor, "uuid", None),
        prescribed_by_name=getattr(actor, "full_name", "") or "",
        created_by_id=getattr(actor, "uuid", None),
    )
    InfusionRate.objects.create(
        infusion=infusion,
        rate=rate,
        changed_at=at,
        reason="Started",
        changed_by_id=getattr(actor, "uuid", None),
        changed_by_name=getattr(actor, "full_name", "") or "",
    )
    record(
        AuditAction.CREATE,
        entity_type="icu.Infusion",
        entity_id=infusion.uuid,
        entity_label=f"{drug_name} for {stay.patient.full_name}",
        reason=f"{rate} {rate_unit}",
    )
    return infusion


@tenant_atomic_method
def change_rate(
    infusion: Infusion, rate, actor, reason: str = "", at=None,
) -> InfusionRate:
    """Titrate. Appends; never edits the previous rate."""
    if infusion.status == InfusionStatus.STOPPED:
        raise IcuError(
            f"{infusion.drug_name} was stopped at "
            f"{infusion.stopped_at:%H:%M}."
        )
    rate = Decimal(str(rate))
    if rate < 0:
        raise IcuError("A rate cannot be negative.")

    at = at or timezone.now()
    if at < infusion.started_at:
        raise IcuError("A rate change cannot precede the infusion.")
    if infusion.maximum_rate is not None and rate > infusion.maximum_rate:
        raise IcuError(
            f"{rate} is above the prescribed maximum of "
            f"{infusion.maximum_rate} {infusion.rate_unit}.",
            detail={"maximum": str(infusion.maximum_rate)},
        )

    # Two rates at the same instant cannot be ordered, and the volume
    # calculation would then depend on insertion order. Nudge rather than
    # refuse: the nurse's intent is unambiguous, and refusing a chart entry
    # mid-resuscitation is how charting stops happening.
    while InfusionRate.objects.filter(
        infusion=infusion, changed_at=at
    ).exists():
        at += timedelta(seconds=1)

    if rate == 0 and infusion.status == InfusionStatus.RUNNING:
        infusion.status = InfusionStatus.PAUSED
        infusion.save(update_fields=["status", "updated_at"])
    elif rate > 0 and infusion.status == InfusionStatus.PAUSED:
        infusion.status = InfusionStatus.RUNNING
        infusion.save(update_fields=["status", "updated_at"])

    return InfusionRate.objects.create(
        infusion=infusion,
        rate=rate,
        changed_at=at,
        reason=reason,
        changed_by_id=getattr(actor, "uuid", None),
        changed_by_name=getattr(actor, "full_name", "") or "",
    )


@tenant_atomic_method
def stop_infusion(
    infusion: Infusion, actor, reason: str = "", at=None,
) -> Infusion:
    """Stop it, writing a final zero so the volume calculation terminates."""
    if infusion.status == InfusionStatus.STOPPED:
        return infusion

    at = at or timezone.now()
    if at < infusion.started_at:
        at = infusion.started_at

    while InfusionRate.objects.filter(
        infusion=infusion, changed_at=at
    ).exists():
        at += timedelta(seconds=1)

    InfusionRate.objects.create(
        infusion=infusion,
        rate=Decimal("0"),
        changed_at=at,
        reason=reason or "Stopped",
        changed_by_id=getattr(actor, "uuid", None),
        changed_by_name=getattr(actor, "full_name", "") or "",
    )
    infusion.status = InfusionStatus.STOPPED
    infusion.stopped_at = at
    infusion.stop_reason = reason
    infusion.save(update_fields=[
        "status", "stopped_at", "stop_reason", "updated_at",
    ])
    return infusion


def infused_volume(infusion: Infusion, until=None) -> Decimal:
    """Volume delivered, from the rate history.

    Each rate applies until the next one. Only meaningful for a rate expressed
    per hour of volume — a mcg/kg/min rate integrates to a dose, not a volume,
    and returning a number that looks like millilitres would be worse than
    returning nothing.
    """
    if "ml/hr" not in infusion.rate_unit.lower():
        return None

    until = until or infusion.stopped_at or timezone.now()
    rates = list(infusion.rates.order_by("changed_at"))
    total = Decimal("0")

    for index, row in enumerate(rates):
        end = rates[index + 1].changed_at if index + 1 < len(rates) else until
        if end <= row.changed_at:
            continue
        hours = Decimal((end - row.changed_at).total_seconds()) / Decimal("3600")
        total += row.rate * hours

    return total.quantize(Decimal("0.1"))


def infusion_state(stay: IcuStay) -> list:
    """Everything running now, with its current rate and how long it has run.

    The current rate is the last rate row, not a stored field. There is one
    place the rate lives, and it is the history.
    """
    rows = []
    for infusion in stay.infusions.exclude(
        status=InfusionStatus.STOPPED
    ).prefetch_related("rates"):
        rates = list(infusion.rates.order_by("changed_at"))
        current = rates[-1] if rates else None
        rows.append({
            "uuid": str(infusion.uuid),
            "drug_name": infusion.drug_name,
            "concentration": infusion.concentration,
            "rate": current.rate if current else None,
            "rate_unit": infusion.rate_unit,
            "status": infusion.status,
            "is_titratable": infusion.is_titratable,
            "is_vasopressor": _is_vasopressor(infusion.drug_name),
            "target": infusion.target,
            "maximum_rate": infusion.maximum_rate,
            "started_at": infusion.started_at,
            "last_changed_at": current.changed_at if current else None,
            "changes": len(rates) - 1,
            "volume_ml": infused_volume(infusion),
        })
    return sorted(rows, key=lambda row: (not row["is_vasopressor"],
                                         row["drug_name"]))


# ---------------------------------------------------------------------------
# Ventilation
# ---------------------------------------------------------------------------


@tenant_atomic_method
def chart_ventilation(
    stay: IcuStay,
    mode: str,
    actor=None,
    at=None,
    source: str = ObservationSource.MANUAL,
    device_identifier: str = "",
    **values,
) -> VentilationRecord:
    """Record the ventilator's settings and what it delivered."""
    validate_stay_open(stay)

    allowed = {
        "is_invasive", "set_rate", "set_tidal_volume", "peep",
        "pressure_support", "fio2", "measured_rate", "expired_tidal_volume",
        "peak_pressure", "plateau_pressure", "minute_volume", "etco2",
        "pao2", "paco2", "ph", "notes",
    }
    unknown = set(values) - allowed
    if unknown:
        raise IcuError(f"Not ventilation fields: {', '.join(sorted(unknown))}.")

    fio2 = values.get("fio2")
    if fio2 is not None and not 21 <= fio2 <= 100:
        raise IcuError(
            f"FiO2 of {fio2}% is impossible — air is 21% and pure oxygen "
            "is 100%. Check whether a fraction was entered instead."
        )

    # NIV and high-flow are not invasive whatever anybody ticks. Getting this
    # wrong inflates the ventilator-day denominator and flatters the unit's
    # VAP rate.
    if mode in (VentilationMode.NIV, VentilationMode.HFNO,
                VentilationMode.SPONTANEOUS):
        values["is_invasive"] = False

    return VentilationRecord.objects.create(
        stay=stay,
        mode=mode,
        recorded_at=at or timezone.now(),
        source=source,
        device_identifier=device_identifier,
        created_by_id=getattr(actor, "uuid", None),
        **values,
    )


def ventilator_days(stay: IcuStay) -> dict:
    """Invasive and non-invasive time, from the charted records.

    Each record's mode is taken to hold until the next one. Approximate by
    construction — the alternative is a start/stop event pair that somebody
    forgets to close, which is not approximate but wrong.
    """
    rows = list(stay.ventilation.order_by("recorded_at"))
    if not rows:
        return {"invasive_hours": Decimal("0"), "non_invasive_hours": Decimal("0"),
                "records": 0, "current_mode": None}

    end = stay.discharged_at or timezone.now()
    invasive = Decimal("0")
    non_invasive = Decimal("0")

    for index, row in enumerate(rows):
        finish = rows[index + 1].recorded_at if index + 1 < len(rows) else end
        if finish <= row.recorded_at:
            continue
        hours = Decimal((finish - row.recorded_at).total_seconds()) / Decimal("3600")
        if row.is_invasive:
            invasive += hours
        elif row.mode != VentilationMode.SPONTANEOUS:
            non_invasive += hours

    latest = rows[-1]
    return {
        "invasive_hours": invasive.quantize(Decimal("0.1")),
        "non_invasive_hours": non_invasive.quantize(Decimal("0.1")),
        "invasive_days": (invasive / 24).quantize(Decimal("0.1")),
        "records": len(rows),
        "current_mode": latest.mode,
        "current_fio2": latest.fio2,
        "current_peep": latest.peep,
        "pf_ratio": latest.pf_ratio,
        "driving_pressure": latest.driving_pressure,
    }


# ---------------------------------------------------------------------------
# Lines and tubes
# ---------------------------------------------------------------------------


@tenant_atomic_method
def insert_device(
    stay: IcuStay,
    device_type: str,
    actor,
    site: str = "",
    size: str = "",
    at=None,
    in_emergency: bool = False,
    change_after_days: int = None,
) -> InvasiveDevice:
    """Record a line or tube going in.

    A line inserted in an emergency is meant to be replaced within 24 hours
    because asepsis was compromised. Defaulting `next_change_due` to tomorrow
    for those is the difference between a policy and a habit.
    """
    validate_stay_open(stay)
    at = at or timezone.now()

    if change_after_days is None:
        change_after_days = 1 if in_emergency else None

    return InvasiveDevice.objects.create(
        stay=stay,
        device_type=device_type,
        site=site,
        size=size,
        inserted_at=at,
        inserted_by_name=getattr(actor, "full_name", "") or "",
        inserted_in_emergency=in_emergency,
        next_change_due=(
            (at + timedelta(days=change_after_days)).date()
            if change_after_days else None
        ),
        created_by_id=getattr(actor, "uuid", None),
    )


@tenant_atomic_method
def remove_device(
    device: InvasiveDevice, actor, reason: str = "", infected: bool = False,
    at=None,
) -> InvasiveDevice:
    """Take it out, recording whether it was suspected of causing infection."""
    if device.removed_at:
        raise IcuError(
            f"That {device.get_device_type_display().lower()} was removed at "
            f"{device.removed_at:%d %b %H:%M}."
        )
    device.removed_at = at or timezone.now()
    device.removal_reason = reason
    device.was_infected = infected
    device.save(update_fields=[
        "removed_at", "removal_reason", "was_infected", "updated_at",
    ])
    return device


def device_days(facility, since=None, until=None) -> dict:
    """Line-days per device type, with the infection numerator beside them.

    The denominator is the whole point. "Six central line infections" means
    nothing; six per thousand line-days is a number a unit can be compared on
    and can act on.
    """
    until = until or timezone.now()
    since = since or (until - timedelta(days=30))

    rows = InvasiveDevice.objects.filter(
        stay__facility=facility, inserted_at__lt=until,
    ).exclude(removed_at__lt=since)

    by_type = {}
    for device in rows:
        start = max(device.inserted_at, since)
        finish = min(device.removed_at or until, until)
        if finish <= start:
            continue
        days = Decimal((finish - start).total_seconds()) / Decimal("86400")
        bucket = by_type.setdefault(
            device.device_type,
            {"device_days": Decimal("0"), "devices": 0, "infections": 0},
        )
        bucket["device_days"] += days
        bucket["devices"] += 1
        if device.was_infected:
            bucket["infections"] += 1

    for bucket in by_type.values():
        bucket["device_days"] = bucket["device_days"].quantize(Decimal("0.1"))
        bucket["per_thousand_device_days"] = (
            (Decimal(bucket["infections"]) * 1000 / bucket["device_days"])
            .quantize(Decimal("0.01"))
            if bucket["device_days"] > 0 else None
        )

    return {
        "from": since.date(),
        "to": until.date(),
        "by_type": by_type,
    }


def overdue_devices(stay: IcuStay) -> list:
    """Lines past their change date, and emergency lines still in.

    Both are things somebody meant to do and did not, and neither surfaces
    anywhere unless something asks.
    """
    today = timezone.localdate()
    overdue = []
    for device in stay.devices.filter(removed_at__isnull=True):
        if device.next_change_due and device.next_change_due <= today:
            overdue.append({
                "uuid": str(device.uuid),
                "device": device.get_device_type_display(),
                "site": device.site,
                "due": device.next_change_due,
                "days_in_situ": device.days_in_situ,
                "reason": "Change due",
            })
        elif device.inserted_in_emergency and device.days_in_situ > 1:
            overdue.append({
                "uuid": str(device.uuid),
                "device": device.get_device_type_display(),
                "site": device.site,
                "due": None,
                "days_in_situ": device.days_in_situ,
                "reason": "Inserted in an emergency, still in after 24 hours",
            })
    return overdue


# ---------------------------------------------------------------------------
# The daily round
# ---------------------------------------------------------------------------


@tenant_atomic_method
def record_round(
    stay: IcuStay,
    actor,
    assessment: str = "",
    plan: str = "",
    fasthug: dict = None,
    fasthug_reasons: dict = None,
    at=None,
    **flags,
) -> Round:
    """The consultant round for one ICU day.

    Re-running on the same day updates that day's round rather than creating a
    second one — a ward round is revised through the morning, and two
    documents both claiming to be "today's plan" is worse than one that
    changed.
    """
    validate_stay_open(stay)
    at = at or timezone.now()
    day = icu_day_of(stay, at)

    fasthug = fasthug or {}
    unknown = set(fasthug) - set(FASTHUG_KEYS)
    if unknown:
        raise IcuError(
            f"Not FASTHUG items: {', '.join(sorted(unknown))}. Known: "
            f"{', '.join(FASTHUG_KEYS)}."
        )

    # An item answered "no" without a reason is an item somebody clicked
    # through. The reason is the clinical content: thromboprophylaxis withheld
    # because of a bleed is a decision; withheld because nobody thought about
    # it is an incident.
    negatives = [key for key, value in fasthug.items() if value is False]
    reasons = fasthug_reasons or {}
    missing_reasons = [key for key in negatives if not reasons.get(key, "").strip()]
    if missing_reasons:
        raise IcuError(
            "A FASTHUG item answered no must say why: "
            f"{', '.join(missing_reasons)}.",
            detail={"items": missing_reasons},
        )

    round_row, created = Round.objects.update_or_create(
        stay=stay,
        icu_day=day,
        defaults={
            "round_at": at,
            "consultant_name": getattr(actor, "full_name", "") or "",
            "assessment": assessment,
            "plan": plan,
            "fasthug": fasthug,
            "fasthug_reasons": reasons,
            "is_ready_for_sedation_hold": flags.get("sedation_hold"),
            "is_ready_for_weaning_trial": flags.get("weaning_trial"),
            "is_ready_for_step_down": flags.get("step_down", False),
            "step_down_blockers": flags.get("blockers", ""),
            "family_updated": flags.get("family_updated", False),
            "family_update_notes": flags.get("family_notes", ""),
            "created_by_id": getattr(actor, "uuid", None),
        },
    )
    record(
        AuditAction.CREATE if created else AuditAction.UPDATE,
        entity_type="icu.Round",
        entity_id=round_row.uuid,
        entity_label=f"ICU day {day} round for {stay.patient.full_name}",
        reason=plan[:200],
    )
    return round_row


def fasthug_compliance(facility, since=None) -> dict:
    """How often each daily-goal item is actually being answered.

    Reported per item rather than as one percentage, because the items fail
    differently: sedation is nearly always addressed and thromboprophylaxis is
    the one that quietly is not, and an aggregate hides exactly that.
    """
    since = since or (timezone.now() - timedelta(days=30))
    rounds = Round.objects.filter(
        stay__facility=facility, round_at__gte=since,
    )
    total = rounds.count()
    answered = {key: 0 for key in FASTHUG_KEYS}
    negative = {key: 0 for key in FASTHUG_KEYS}

    for row in rounds:
        for key in FASTHUG_KEYS:
            if key in row.fasthug:
                answered[key] += 1
                if row.fasthug[key] is False:
                    negative[key] += 1

    return {
        "since": since.date(),
        "rounds": total,
        "items": [
            {
                "item": key,
                "answered": answered[key],
                "not_answered": total - answered[key],
                "answered_percent": (
                    round(answered[key] * 100 / total, 1) if total else None
                ),
                "declined": negative[key],
            }
            for key in FASTHUG_KEYS
        ],
    }


# ---------------------------------------------------------------------------
# Severity scoring
# ---------------------------------------------------------------------------


def _sofa_respiratory(pf_ratio, ventilated: bool):
    if pf_ratio is None:
        return None, None
    ratio = int(pf_ratio)
    if ratio < 100 and ventilated:
        return 4, ratio
    if ratio < 200 and ventilated:
        return 3, ratio
    if ratio < 300:
        return 2, ratio
    if ratio < 400:
        return 1, ratio
    return 0, ratio


def _sofa_cardiovascular(map_value, pressors: list):
    """Vasopressor dose beats blood pressure.

    A patient with a MAP of 75 on a large dose of noradrenaline is not a
    patient with a normal blood pressure, and scoring the number rather than
    the support is the commonest way a SOFA is understated.
    """
    if pressors:
        heavy = any(
            "noradrenaline" in name or "norepinephrine" in name
            or "adrenaline" in name or "epinephrine" in name
            for name in pressors
        )
        return (4 if heavy else 3), ", ".join(pressors)
    if map_value is None:
        return None, None
    return (1, map_value) if map_value < 70 else (0, map_value)


def _sofa_neurological(gcs):
    if gcs is None:
        return None, None
    if gcs < 6:
        return 4, gcs
    if gcs < 10:
        return 3, gcs
    if gcs < 13:
        return 2, gcs
    if gcs < 15:
        return 1, gcs
    return 0, gcs


@tenant_atomic_method
def score_sofa(
    stay: IcuStay,
    at=None,
    platelets=None,
    bilirubin=None,
    creatinine=None,
    urine_ml_24h=None,
) -> SofaScore:
    """Compute and store one day's SOFA, naming the systems it could not score.

    The respiratory, cardiovascular and neurological components come from what
    is already charted. The three laboratory components are passed in, because
    this module does not own the lab — and when they are not passed in they are
    recorded as *missing*, not as zero.

    That distinction is the whole reason this function is longer than a sum.
    SOFA gives 0 to a normal value, so a missing bilirubin and a healthy liver
    score identically, and the resulting error always runs the same way: the
    patient looks less sick than they are.
    """
    at = at or timezone.now()
    day = icu_day_of(stay, at)
    window_start = at - timedelta(hours=24)

    components = {}
    missing = []

    # Respiratory: worst PF ratio in the window.
    vents = [
        row for row in stay.ventilation.filter(
            recorded_at__gte=window_start, recorded_at__lte=at,
        )
        if row.pf_ratio is not None
    ]
    if vents:
        worst = min(vents, key=lambda row: row.pf_ratio)
        respiratory, value = _sofa_respiratory(worst.pf_ratio, worst.is_invasive)
        components["respiratory"] = {"pf_ratio": value,
                                     "ventilated": worst.is_invasive}
    else:
        respiratory = None
        missing.append("respiratory")

    # Cardiovascular: lowest MAP, or the vasopressors running.
    observations = list(stay.observations.filter(
        recorded_at__gte=window_start, recorded_at__lte=at,
    ))
    maps = [row.map_value for row in observations if row.map_value is not None]
    pressors = [
        infusion.drug_name for infusion in stay.infusions.filter(
            status=InfusionStatus.RUNNING
        ) if _is_vasopressor(infusion.drug_name)
    ]
    cardiovascular, value = _sofa_cardiovascular(
        min(maps) if maps else None, pressors,
    )
    if cardiovascular is None:
        missing.append("cardiovascular")
    else:
        components["cardiovascular"] = {"map": value if not pressors else None,
                                        "vasopressors": pressors}

    # Neurological: lowest GCS. A sedated patient's GCS is not their
    # neurology, so a not-testable verbal score excludes the day rather than
    # scoring 4 points of brain failure caused by the propofol.
    scores = [
        row.gcs_total for row in observations
        if row.gcs_total is not None and not row.gcs_verbal_not_testable
    ]
    neurological, value = _sofa_neurological(min(scores) if scores else None)
    if neurological is None:
        missing.append("neurological")
    else:
        components["neurological"] = {"gcs": value}

    # Coagulation, liver, renal: from the lab, if given.
    if platelets is None:
        coagulation = None
        missing.append("coagulation")
    else:
        platelets = Decimal(str(platelets))
        coagulation = (
            4 if platelets < 20 else 3 if platelets < 50
            else 2 if platelets < 100 else 1 if platelets < 150 else 0
        )
        components["coagulation"] = {"platelets": str(platelets)}

    if bilirubin is None:
        liver = None
        missing.append("liver")
    else:
        bilirubin = Decimal(str(bilirubin))
        liver = (
            4 if bilirubin >= 12 else 3 if bilirubin >= 6
            else 2 if bilirubin >= 2 else 1 if bilirubin >= 1.2 else 0
        )
        components["liver"] = {"bilirubin": str(bilirubin)}

    if creatinine is None and urine_ml_24h is None:
        renal = None
        missing.append("renal")
    else:
        renal = 0
        detail = {}
        if creatinine is not None:
            creatinine = Decimal(str(creatinine))
            renal = (
                4 if creatinine >= 5 else 3 if creatinine >= 3.5
                else 2 if creatinine >= 2 else 1 if creatinine >= 1.2 else 0
            )
            detail["creatinine"] = str(creatinine)
        if urine_ml_24h is not None:
            # Oliguria scores on its own and can beat the creatinine, which
            # lags a day behind the kidney.
            by_urine = 4 if urine_ml_24h < 200 else 3 if urine_ml_24h < 500 else 0
            renal = max(renal, by_urine)
            detail["urine_ml_24h"] = urine_ml_24h
        components["renal"] = detail

    parts = {
        "respiratory": respiratory or 0,
        "coagulation": coagulation or 0,
        "liver": liver or 0,
        "cardiovascular": cardiovascular or 0,
        "neurological": neurological or 0,
        "renal": renal or 0,
    }

    score, _ = SofaScore.objects.update_or_create(
        stay=stay,
        icu_day=day,
        defaults={
            "scored_for": at.date(),
            "scored_at": timezone.now(),
            "total": sum(parts.values()),
            "components": components,
            "missing_components": missing,
            **parts,
        },
    )
    return score


def severity_trend(stay: IcuStay) -> list:
    """SOFA by day, with the incomplete ones marked.

    A rising SOFA over three days is the single most useful trajectory in
    intensive care, and a day scored from half the data must not be plotted as
    if it were the same kind of point.
    """
    return [
        {
            "icu_day": row.icu_day,
            "date": row.scored_for,
            "total": row.total,
            "respiratory": row.respiratory,
            "coagulation": row.coagulation,
            "liver": row.liver,
            "cardiovascular": row.cardiovascular,
            "neurological": row.neurological,
            "renal": row.renal,
            "complete": row.is_complete,
            "missing": row.missing_components,
        }
        for row in stay.sofa_scores.order_by("icu_day")
    ]


# ---------------------------------------------------------------------------
# The unit
# ---------------------------------------------------------------------------


def unit_board(ward: Ward) -> list:
    """Every occupied bed in the unit, sickest and least-attended first.

    Ordered by unacknowledged critical alerts, then by SOFA. A board sorted by
    bed number is a board that tells a charge nurse nothing they did not
    already know from walking past.
    """
    rows = []
    stays = (
        IcuStay.objects.filter(ward=ward, outcome=IcuOutcome.ONGOING)
        .select_related("patient", "bed", "admission")
        .prefetch_related("alerts", "sofa_scores")
    )

    for stay in stays:
        latest = stay.observations.order_by("-recorded_at").first()
        sofa = stay.sofa_scores.order_by("-icu_day").first()
        vent = stay.ventilation.order_by("-recorded_at").first()
        unacknowledged = [
            alert for alert in stay.alerts.all() if not alert.is_acknowledged
        ]
        pressors = [
            row["drug_name"] for row in infusion_state(stay)
            if row["is_vasopressor"]
        ]
        rows.append({
            "stay": str(stay.uuid),
            "bed": stay.bed.code if stay.bed else "",
            "patient": stay.patient.full_name,
            "mrn": stay.patient.mrn,
            "admission": stay.admission.reference,
            "icu_day": icu_day_of(stay),
            "hours": stay.hours,
            "diagnosis": stay.primary_diagnosis or stay.reason,
            "consultant": stay.consultant_name,
            "sofa": sofa.total if sofa else None,
            "sofa_complete": sofa.is_complete if sofa else None,
            "ventilated": bool(vent and vent.is_invasive),
            "mode": vent.mode if vent else None,
            "fio2": vent.fio2 if vent else None,
            "vasopressors": pressors,
            "for_resuscitation": stay.is_for_resuscitation,
            "ceiling_of_care": stay.ceiling_of_care,
            "last_observation_at": latest.recorded_at if latest else None,
            "unacknowledged_alerts": len(unacknowledged),
            "critical_alerts": sum(
                1 for alert in unacknowledged
                if alert.severity == AlertSeverity.CRITICAL
            ),
            "balance_24h_ml": fluid_balance(stay)["balance_ml"],
        })

    return sorted(
        rows,
        key=lambda row: (
            -row["critical_alerts"],
            -row["unacknowledged_alerts"],
            -(row["sofa"] or 0),
            row["bed"],
        ),
    )


def unit_summary(facility, since=None) -> dict:
    """The unit's numbers: occupancy, turnover, support and outcome.

    Mortality is reported with the transferred-out and LAMA counts beside it,
    because both remove a patient from the denominator whose outcome nobody
    knows, and a mortality rate quoted without them is a rate that can be
    improved by transferring the sickest patients out.
    """
    since = since or (timezone.now() - timedelta(days=30))
    stays = IcuStay.objects.filter(facility=facility, admitted_at__gte=since)

    finished = stays.exclude(outcome=IcuOutcome.ONGOING)
    died = finished.filter(outcome=IcuOutcome.DIED).count()
    transferred = finished.filter(outcome=IcuOutcome.TRANSFERRED_OUT).count()
    lama = finished.filter(outcome=IcuOutcome.LAMA).count()
    completed = finished.count()

    hours = [stay.hours for stay in finished]
    ventilated = 0
    invasive_hours = Decimal("0")
    for stay in stays:
        days = ventilator_days(stay)
        if days["invasive_hours"] > 0:
            ventilated += 1
            invasive_hours += days["invasive_hours"]

    readmissions = 0
    for stay in stays:
        # A second ICU stay within the same admission, starting within 48
        # hours of the previous discharge, is the readmission rate -- the
        # number that says whether patients are being stepped down too early.
        previous = (
            stay.admission.icu_stays
            .filter(discharged_at__isnull=False,
                    discharged_at__lte=stay.admitted_at)
            .order_by("-discharged_at")
            .first()
        )
        if previous and (stay.admitted_at - previous.discharged_at) <= timedelta(hours=48):
            readmissions += 1

    return {
        "since": since.date(),
        "admissions": stays.count(),
        "current": stays.filter(outcome=IcuOutcome.ONGOING).count(),
        "completed": completed,
        "died": died,
        "mortality_percent": (
            round(died * 100 / completed, 1) if completed else None
        ),
        "transferred_out": transferred,
        "left_against_advice": lama,
        "outcome_unknown": transferred + lama,
        "median_hours": _median([float(value) for value in hours]),
        "ventilated": ventilated,
        "invasive_ventilator_days": (invasive_hours / 24).quantize(Decimal("0.1")),
        "readmissions_within_48h": readmissions,
        "readmission_percent": (
            round(readmissions * 100 / completed, 1) if completed else None
        ),
        "by_route": dict(
            stays.values_list("route")
            .annotate(count=models.Count("id"))
            .values_list("route", "count")
        ),
    }
