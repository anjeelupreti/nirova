"""Ordering investigations, collecting specimens, and reporting results."""

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record, record_version
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.diagnostics.models import (
    OPEN_ORDER_STATUSES,
    AlertStatus,
    CriticalValueAlert,
    DiagnosticModality,
    DiagnosticOrder,
    DiagnosticResult,
    OrderPriority,
    OrderStatus,
    ReferenceRange,
    ResultDataType,
    ResultFlag,
    TestDefinition,
)
from apps.encounters.models import EncounterStatus
from apps.entitlements.services import require_module
# assert_different_actors: a result is entered by one person and verified by
# another. That is the whole point of verification.
from apps.rbac.services import assert_different_actors
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.diagnostics")

#: Which entitlement module each modality needs. Radiology and laboratory are
#: sold separately, so ordering a CT on a plan without radiology should be
#: refused at the point of ordering rather than discovered at the scanner.
MODALITY_MODULE = {
    DiagnosticModality.LABORATORY: ModuleCode.LABORATORY,
}


def module_for(modality: str) -> str:
    """The module a modality requires. Everything non-laboratory is radiology."""
    return MODALITY_MODULE.get(modality, ModuleCode.RADIOLOGY)


class DiagnosticsError(DomainError):
    code = "diagnostics_operation_failed"


class ResultLocked(DiagnosticsError):
    code = "result_locked"
    message = "A verified result is amended, not edited."


# ---------------------------------------------------------------------------
# Reference ranges
# ---------------------------------------------------------------------------


def select_reference_range(test: TestDefinition, patient) -> ReferenceRange | None:
    """The narrowest range that applies to this patient.

    Specificity wins: an adult-female range beats an adult range, which beats
    an any-patient range. Reporting a haemoglobin against the wrong
    population's range produces false alarms, and false alarms teach
    clinicians to ignore flags — which is worse than having none.
    """
    candidates = [
        candidate
        for candidate in ReferenceRange.objects.filter(test=test)
        if candidate.matches(patient)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.specificity(), reverse=True)
    return candidates[0]


def interpret(value, test: TestDefinition, patient) -> dict:
    """Classify a value against the patient's reference range.

    Returns the flag and the range text to print alongside it. The range is
    captured onto the result rather than looked up at read time, because
    ranges get revised and a report must keep showing the range the result
    was actually judged against.
    """
    reference = select_reference_range(test, patient)
    blank = {"flag": ResultFlag.NORMAL, "reference_text": "", "range": reference}

    if reference is None:
        return blank

    # Qualitative and coded results are compared against an expected value
    # rather than a band.
    if test.result_data_type in {
        ResultDataType.QUALITATIVE,
        ResultDataType.CODED,
    }:
        if not reference.normal_value:
            return blank
        is_normal = str(value).strip().lower() == reference.normal_value.strip().lower()
        return {
            "flag": ResultFlag.NORMAL if is_normal else ResultFlag.ABNORMAL,
            "reference_text": reference.normal_value,
            "range": reference,
        }

    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return blank

    # Critical thresholds are checked before the normal band: a value can be
    # both outside the normal range and critically so, and the more urgent
    # classification is the one that matters.
    if reference.critical_low is not None and numeric <= reference.critical_low:
        flag = ResultFlag.CRITICAL_LOW
    elif reference.critical_high is not None and numeric >= reference.critical_high:
        flag = ResultFlag.CRITICAL_HIGH
    elif reference.normal_low is not None and numeric < reference.normal_low:
        flag = ResultFlag.LOW
    elif reference.normal_high is not None and numeric > reference.normal_high:
        flag = ResultFlag.HIGH
    else:
        flag = ResultFlag.NORMAL

    parts = []
    if reference.normal_low is not None:
        parts.append(_trim(reference.normal_low))
    if reference.normal_high is not None:
        parts.append(_trim(reference.normal_high))
    reference_text = "–".join(parts) if parts else ""

    return {"flag": flag, "reference_text": reference_text, "range": reference}


def _trim(value: Decimal) -> str:
    """Render a decimal without trailing zeros: 3.50 becomes 3.5."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def generate_order_reference(modality: str) -> str:
    """Sequential reference, prefixed by kind: LAB-2026-000142, RAD-2026-000031.

    Prefixed because a laboratory and a radiology worklist are read by
    different people, and a reference that says which it is saves a lookup
    every time one is quoted down a phone.
    """
    prefix = "LAB" if modality == DiagnosticModality.LABORATORY else "RAD"
    year = timezone.now().year
    stem = f"{prefix}-{year}-"
    last = (
        DiagnosticOrder.all_objects.filter(reference__startswith=stem)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{sequence:06d}"


def generate_accession_number() -> str:
    """The barcode that travels with the specimen.

    Distinct from the order reference and allocated at collection, not at
    ordering: an order that is never collected should not consume an
    accession number, and a re-collected specimen needs a new one so the two
    tubes cannot be confused.
    """
    today = timezone.localdate()
    stem = f"{today:%y%m%d}-"
    last = (
        DiagnosticOrder.all_objects.filter(accession_number__startswith=stem)
        .order_by("-accession_number")
        .values_list("accession_number", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{sequence:04d}"


@tenant_atomic_method
def place_order(
    organization,
    patient,
    facility,
    test: TestDefinition,
    actor=None,
    encounter=None,
    priority: str = OrderPriority.ROUTINE,
    clinical_indication: str = "",
    clinical_notes: str = "",
    capture_charge: bool = True,
) -> DiagnosticOrder:
    """Request an investigation.

    Refuses without a clinical indication for anything above routine. A
    radiologist reading a film without the clinical question is guessing, and
    an urgent request with no stated reason cannot be triaged against the
    other urgent requests.
    """
    require_module(organization, module_for(test.modality))

    if priority != OrderPriority.ROUTINE and not clinical_indication.strip():
        raise DiagnosticsError(
            f"An {priority} request must say what is being looked for.",
            detail={"field": "clinical_indication"},
        )

    order = DiagnosticOrder.objects.create(
        reference=generate_order_reference(test.modality),
        patient=patient,
        encounter=encounter,
        facility=facility,
        test=test,
        test_code=test.code,
        test_name=test.name,
        modality=test.modality,
        specimen_type=test.specimen_type,
        ordered_by_id=getattr(actor, "uuid", None),
        ordered_by_name=getattr(actor, "full_name", ""),
        priority=priority,
        clinical_indication=clinical_indication,
        clinical_notes=clinical_notes,
        due_at=timezone.now() + timedelta(minutes=test.turnaround_minutes),
        created_by_id=getattr(actor, "uuid", None),
    )

    if capture_charge and test.service_uuid:
        _charge_for(organization, order, actor)

    # The encounter is now waiting on somebody else. Moving it out of
    # "in progress" is what keeps a doctor's worklist honest: these patients
    # need nothing from them until the result lands.
    if encounter and encounter.status == EncounterStatus.IN_PROGRESS:
        encounter.status = EncounterStatus.AWAITING_RESULTS
        encounter.save(update_fields=["status", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="diagnostics.DiagnosticOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} — {test.name} for {patient.mrn}",
        metadata={"priority": priority, "modality": test.modality},
    )
    return order


def _charge_for(organization, order: DiagnosticOrder, actor) -> None:
    """Raise the charge for an order.

    Failure is logged, not raised. A billing misconfiguration must not stop a
    clinician ordering a test on a sick patient; the uncharged order surfaces
    in revenue reporting, which is where that problem belongs.
    """
    from apps.billing.models import ServiceItem
    from apps.billing.services import capture_charge as capture

    try:
        service = ServiceItem.objects.filter(uuid=order.test.service_uuid).first()
        if service is None:
            return
        charge = capture(
            organization,
            patient=order.patient,
            facility=order.facility,
            service=service,
            actor=actor,
            encounter=order.encounter,
        )
        order.charge_uuid = charge.uuid
        order.save(update_fields=["charge_uuid", "updated_at"])
    except Exception:
        logger.exception(
            "Could not charge for order %s; the order stands", order.reference
        )


@tenant_atomic_method
def collect_specimen(
    order: DiagnosticOrder, actor=None, specimen_type: str = ""
) -> DiagnosticOrder:
    """Record collection and allocate the accession number."""
    if not order.test.needs_specimen:
        raise DiagnosticsError(
            f"{order.test_name} does not involve a specimen.",
            detail={"modality": order.modality},
        )
    if order.status != OrderStatus.ORDERED:
        raise DiagnosticsError(
            f"Order {order.reference} is {order.get_status_display().lower()}.",
            detail={"status": order.status},
        )

    order.accession_number = generate_accession_number()
    order.specimen_type = specimen_type or order.specimen_type
    order.collected_at = timezone.now()
    order.collected_by_id = getattr(actor, "uuid", None)
    order.collected_by_name = getattr(actor, "full_name", "")
    order.status = OrderStatus.COLLECTED
    order.save(
        update_fields=[
            "accession_number", "specimen_type", "collected_at",
            "collected_by_id", "collected_by_name", "status", "updated_at",
        ]
    )

    record(
        AuditAction.UPDATE,
        entity_type="diagnostics.DiagnosticOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} collected",
        metadata={"accession": order.accession_number},
    )
    return order


@tenant_atomic_method
def receive_specimen(order: DiagnosticOrder, actor=None) -> DiagnosticOrder:
    """Book a specimen into the laboratory.

    A separate step from collection because the gap between them is where
    specimens are lost, and a system that cannot distinguish "not yet
    collected" from "collected but never arrived" cannot help find them.
    """
    if order.status != OrderStatus.COLLECTED:
        raise DiagnosticsError(
            f"Order {order.reference} is {order.get_status_display().lower()}; "
            "only a collected specimen can be received.",
            detail={"status": order.status},
        )
    order.received_at = timezone.now()
    order.status = OrderStatus.RECEIVED
    order.save(update_fields=["received_at", "status", "updated_at"])
    return order


@tenant_atomic_method
def reject_specimen(order: DiagnosticOrder, reason: str, actor=None) -> DiagnosticOrder:
    """Reject a specimen — haemolysed, clotted, mislabelled, insufficient.

    A rejection is a clinical event, not a deletion: the clinician is still
    waiting, and somebody has to be told to take another. The order stays
    visible with its reason attached.
    """
    if not reason.strip():
        raise DiagnosticsError("A rejection must record why.")

    order.status = OrderStatus.REJECTED
    order.rejection_reason = reason
    order.rejected_at = timezone.now()
    order.save(
        update_fields=["status", "rejection_reason", "rejected_at", "updated_at"]
    )

    record(
        AuditAction.UPDATE,
        entity_type="diagnostics.DiagnosticOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} rejected",
        reason=reason,
    )
    logger.warning(
        "Specimen rejected for %s (%s): %s",
        order.reference, order.patient.mrn, reason,
    )
    return order


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@tenant_atomic_method
def enter_results(order: DiagnosticOrder, results: list, actor=None) -> list:
    """Record the values for an order.

    Each is interpreted against the patient's own reference range as it is
    entered, and a critical value raises an alert immediately — not at
    verification. A potassium of 7.1 must not wait for a second pair of eyes
    before anyone is told it exists.
    """
    if order.status in {OrderStatus.CANCELLED, OrderStatus.REJECTED}:
        raise DiagnosticsError(
            f"Order {order.reference} is {order.get_status_display().lower()}.",
            detail={"status": order.status},
        )

    created = []
    for index, entry in enumerate(results):
        analyte = _resolve_analyte(order, entry)
        value = entry.get("value")
        interpretation = interpret(value, analyte, order.patient)

        result = DiagnosticResult(
            order=order,
            test=analyte,
            analyte_code=analyte.code,
            analyte_name=analyte.name,
            unit=entry.get("unit") or analyte.unit,
            reference_text=interpretation["reference_text"],
            flag=interpretation["flag"],
            entered_by_id=getattr(actor, "uuid", None),
            entered_by_name=getattr(actor, "full_name", ""),
            instrument=entry.get("instrument", ""),
            method=entry.get("method", ""),
            notes=entry.get("notes", ""),
            display_order=entry.get("display_order", index),
            created_by_id=getattr(actor, "uuid", None),
        )

        if analyte.result_data_type == ResultDataType.NUMERIC:
            try:
                result.numeric_value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                raise DiagnosticsError(
                    f"{analyte.name} expects a number, not {value!r}.",
                    detail={"analyte": analyte.code, "value": str(value)},
                )
        elif analyte.result_data_type in {
            ResultDataType.CODED,
            ResultDataType.QUALITATIVE,
        }:
            result.coded_value = str(value)
        else:
            result.text_value = str(value)

        result.save()
        created.append(result)

        if result.is_critical:
            _raise_critical_alert(result, interpretation["range"])

    order.status = OrderStatus.RESULTED
    order.resulted_at = timezone.now()
    order.save(update_fields=["status", "resulted_at", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="diagnostics.DiagnosticOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} resulted",
        metadata={
            "results": len(created),
            "abnormal": sum(1 for r in created if r.is_abnormal),
            "critical": sum(1 for r in created if r.is_critical),
        },
    )
    return created


def _resolve_analyte(order: DiagnosticOrder, entry: dict) -> TestDefinition:
    """Which test definition an entered value belongs to.

    A panel's values name their analyte; a single test's value does not need
    to.
    """
    code = entry.get("analyte_code")
    if not code:
        return order.test

    analyte = TestDefinition.objects.filter(code=code).first()
    if analyte is None:
        raise DiagnosticsError(
            f"No test defined with code '{code}'.", detail={"analyte_code": code}
        )
    return analyte


def _raise_critical_alert(result: DiagnosticResult, reference) -> CriticalValueAlert:
    """Open a critical-value alert and log it loudly.

    The log line is deliberate. Until the notification module exists, a
    WARNING in the application log is the only thing that will reach an
    operations dashboard, and a critical result that nobody sees is precisely
    the failure this whole mechanism exists to prevent.
    """
    threshold = ""
    if reference is not None:
        if result.flag == ResultFlag.CRITICAL_LOW and reference.critical_low is not None:
            threshold = f"≤ {_trim(reference.critical_low)}"
        elif reference.critical_high is not None:
            threshold = f"≥ {_trim(reference.critical_high)}"

    alert = CriticalValueAlert.objects.create(
        result=result,
        order=result.order,
        patient=result.order.patient,
        value=result.display_value,
        flag=result.flag,
        threshold=threshold,
    )
    logger.warning(
        "CRITICAL RESULT %s %s=%s %s (patient %s, order %s) — alert %s",
        result.flag,
        result.analyte_name,
        result.display_value,
        result.unit,
        result.order.patient.mrn,
        result.order.reference,
        alert.uuid,
    )
    record(
        AuditAction.CREATE,
        entity_type="diagnostics.CriticalValueAlert",
        entity_id=alert.uuid,
        entity_label=f"{result.analyte_name} {result.display_value} — "
                     f"{result.order.patient.mrn}",
        severity="critical",
        metadata={"order": result.order.reference, "threshold": threshold},
    )
    return alert


@tenant_atomic_method
def verify_order(order: DiagnosticOrder, actor=None) -> DiagnosticOrder:
    """Verify and release an order's results.

    The person who entered the results may not verify them. That is the
    entire purpose of verification: a second pair of eyes on a number that
    someone is about to act on. Enforced here rather than trusted to process.
    """
    if order.status != OrderStatus.RESULTED:
        raise DiagnosticsError(
            f"Order {order.reference} is {order.get_status_display().lower()}; "
            "only a resulted order can be verified.",
            detail={"status": order.status},
        )

    results = list(order.results.filter(is_superseded=False))
    if not results:
        raise DiagnosticsError("There are no results to verify.")

    actor_id = getattr(actor, "uuid", None)
    for result in results:
        assert_different_actors(result.entered_by_id, actor_id, "result verification")

    now = timezone.now()
    order.results.filter(is_superseded=False).update(
        is_verified=True, verified_by_id=actor_id, verified_at=now
    )

    order.status = OrderStatus.RELEASED
    order.verified_at = now
    order.verified_by_id = actor_id
    order.verified_by_name = getattr(actor, "full_name", "")
    order.released_at = now
    order.save(
        update_fields=[
            "status", "verified_at", "verified_by_id", "verified_by_name",
            "released_at", "updated_at",
        ]
    )

    _reopen_encounter(order)

    record_version(
        entity_type="diagnostics.DiagnosticOrder",
        entity_id=order.uuid,
        snapshot=_snapshot(order),
        reason="Results verified and released",
    )
    record(
        AuditAction.APPROVE,
        entity_type="diagnostics.DiagnosticOrder",
        entity_id=order.uuid,
        entity_label=f"{order.reference} released",
        metadata={
            "turnaround_minutes": order.turnaround_minutes,
            "verified_by": getattr(actor, "email", ""),
        },
    )
    return order


def _reopen_encounter(order: DiagnosticOrder) -> None:
    """Return an encounter to the doctor once nothing is outstanding.

    Only when *every* order on the encounter is done — a patient with three
    tests outstanding should not reappear on a worklist because one came
    back.
    """
    encounter = order.encounter
    if encounter is None or encounter.status != EncounterStatus.AWAITING_RESULTS:
        return

    still_waiting = DiagnosticOrder.objects.filter(
        encounter=encounter, status__in=list(OPEN_ORDER_STATUSES)
    ).exists()
    if not still_waiting:
        encounter.status = EncounterStatus.IN_PROGRESS
        encounter.save(update_fields=["status", "updated_at"])


@tenant_atomic_method
def amend_result(
    original: DiagnosticResult, value, reason: str, actor=None
) -> DiagnosticResult:
    """Correct a verified result by superseding it.

    The original stays exactly as reported. A clinician may already have
    acted on it, and the record must show what they saw as well as what it
    was corrected to.
    """
    if not reason.strip():
        raise DiagnosticsError("An amendment must say why the result changed.")
    if not original.is_verified:
        raise DiagnosticsError(
            "An unverified result is corrected by re-entering it, not amended.",
            detail={"result": str(original.uuid)},
        )

    order = original.order
    interpretation = interpret(value, original.test, order.patient)

    amendment = DiagnosticResult(
        order=order,
        test=original.test,
        analyte_code=original.analyte_code,
        analyte_name=original.analyte_name,
        unit=original.unit,
        reference_text=interpretation["reference_text"],
        flag=interpretation["flag"],
        entered_by_id=getattr(actor, "uuid", None),
        entered_by_name=getattr(actor, "full_name", ""),
        supersedes=original,
        amendment_reason=reason,
        display_order=original.display_order,
        created_by_id=getattr(actor, "uuid", None),
    )
    if original.test.result_data_type == ResultDataType.NUMERIC:
        amendment.numeric_value = Decimal(str(value))
    elif original.test.result_data_type in {
        ResultDataType.CODED,
        ResultDataType.QUALITATIVE,
    }:
        amendment.coded_value = str(value)
    else:
        amendment.text_value = str(value)
    amendment.save()

    original.is_superseded = True
    original.save(update_fields=["is_superseded", "updated_at"])

    if amendment.is_critical:
        _raise_critical_alert(amendment, interpretation["range"])

    record(
        AuditAction.UPDATE,
        entity_type="diagnostics.DiagnosticResult",
        entity_id=amendment.uuid,
        entity_label=f"Amended {original.analyte_name} on {order.reference}",
        reason=reason,
        changes={
            "value": {
                "before": original.display_value,
                "after": amendment.display_value,
            }
        },
    )
    logger.warning(
        "RESULT AMENDED %s %s: %s -> %s (%s)",
        order.reference, original.analyte_name,
        original.display_value, amendment.display_value, reason,
    )
    return amendment


# ---------------------------------------------------------------------------
# Critical value alerts
# ---------------------------------------------------------------------------


@tenant_atomic_method
def notify_critical(
    alert: CriticalValueAlert,
    person: str,
    via: str,
    actor=None,
) -> CriticalValueAlert:
    """Record that someone was actually told.

    The person told is free text because it is often not the person who
    ordered — a covering doctor, the ward sister, whoever answered. What
    matters for the record is that a named human was reached.
    """
    if not person.strip():
        raise DiagnosticsError("Record who was told.")

    alert.notified_person = person
    alert.notified_via = via
    alert.notified_at = timezone.now()
    alert.notified_by_id = getattr(actor, "uuid", None)
    alert.save(
        update_fields=[
            "notified_person", "notified_via", "notified_at",
            "notified_by_id", "updated_at",
        ]
    )
    record(
        AuditAction.UPDATE,
        entity_type="diagnostics.CriticalValueAlert",
        entity_id=alert.uuid,
        entity_label=f"Critical value communicated to {person}",
        metadata={"via": via, "minutes_to_notify": alert.minutes_outstanding},
    )
    return alert


@tenant_atomic_method
def acknowledge_critical(
    alert: CriticalValueAlert, action_taken: str, actor=None
) -> CriticalValueAlert:
    """Close an alert, recording what was done about it."""
    if not action_taken.strip():
        raise DiagnosticsError(
            "Recording what was done is the point of acknowledging."
        )

    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by_id = getattr(actor, "uuid", None)
    alert.acknowledged_at = timezone.now()
    alert.action_taken = action_taken
    alert.save(
        update_fields=[
            "status", "acknowledged_by_id", "acknowledged_at",
            "action_taken", "updated_at",
        ]
    )
    record(
        AuditAction.APPROVE,
        entity_type="diagnostics.CriticalValueAlert",
        entity_id=alert.uuid,
        entity_label=f"Critical value acknowledged after "
                     f"{alert.minutes_outstanding} minutes",
        reason=action_taken,
    )
    return alert


# ---------------------------------------------------------------------------
# Worklists and reporting
# ---------------------------------------------------------------------------


def worklist(facility, modality: str = "", status: str = "", limit: int = 100) -> list:
    """What the laboratory or imaging department has to do, in the right order.

    STAT first, then urgent, then oldest — the order the work should actually
    be picked up in, rather than the order it arrived.
    """
    queryset = DiagnosticOrder.objects.filter(
        facility=facility, status__in=list(OPEN_ORDER_STATUSES)
    ).select_related("patient", "test")

    if modality:
        queryset = queryset.filter(modality=modality)
    if status:
        queryset = queryset.filter(status=status)

    priority_rank = {
        OrderPriority.STAT: 0,
        OrderPriority.URGENT: 1,
        OrderPriority.ROUTINE: 2,
    }
    orders = sorted(
        queryset[: limit * 2],
        key=lambda o: (priority_rank.get(o.priority, 3), o.ordered_at),
    )
    return orders[:limit]


def turnaround_report(facility, since=None) -> dict:
    """Turnaround performance, split where the delay actually occurs.

    Total turnaround and laboratory turnaround are reported separately: a
    laboratory cannot be held to account for a specimen that sat on a ward
    for three hours, and one combined number hides which it was.
    """
    since = since or (timezone.now() - timedelta(days=7))
    released = DiagnosticOrder.objects.filter(
        facility=facility, status=OrderStatus.RELEASED, released_at__gte=since
    ).select_related("test")

    total_times = [o.turnaround_minutes for o in released if o.turnaround_minutes]
    lab_times = [
        o.collection_to_result_minutes
        for o in released
        if o.collection_to_result_minutes
    ]
    breached = [o for o in released if o.due_at and o.released_at > o.due_at]

    open_orders = DiagnosticOrder.objects.filter(
        facility=facility, status__in=list(OPEN_ORDER_STATUSES)
    )
    overdue = [o for o in open_orders if o.is_overdue]

    return {
        "since": since.isoformat(),
        "released": released.count(),
        "average_total_minutes": (
            int(sum(total_times) / len(total_times)) if total_times else 0
        ),
        "average_lab_minutes": (
            int(sum(lab_times) / len(lab_times)) if lab_times else 0
        ),
        "breached": len(breached),
        "breach_rate_percent": (
            round(len(breached) / released.count() * 100, 1)
            if released.count()
            else 0.0
        ),
        "open": open_orders.count(),
        "overdue": len(overdue),
        "rejected": DiagnosticOrder.objects.filter(
            facility=facility, status=OrderStatus.REJECTED,
            rejected_at__gte=since,
        ).count(),
        "critical_alerts_open": CriticalValueAlert.objects.filter(
            status=AlertStatus.PENDING
        ).count(),
    }


def patient_results(patient, limit: int = 50) -> list:
    """A patient's released results, newest first.

    Superseded rows are excluded: a clinician reading a chart wants the
    current value. The amendment history stays reachable from the order.
    """
    orders = (
        DiagnosticOrder.objects.filter(
            patient=patient, status=OrderStatus.RELEASED
        )
        .prefetch_related("results")
        .order_by("-released_at")[:limit]
    )
    return [
        {
            "reference": order.reference,
            "test_name": order.test_name,
            "modality": order.modality,
            "released_at": order.released_at,
            "turnaround_minutes": order.turnaround_minutes,
            "results": [
                {
                    "analyte": result.analyte_name,
                    "value": result.display_value,
                    "unit": result.unit,
                    "reference": result.reference_text,
                    "flag": result.flag,
                    "is_abnormal": result.is_abnormal,
                    "is_critical": result.is_critical,
                    "was_amended": result.supersedes_id is not None,
                }
                for result in order.results.filter(is_superseded=False)
            ],
        }
        for order in orders
    ]


def _snapshot(order: DiagnosticOrder) -> dict:
    return {
        "reference": order.reference,
        "patient_mrn": order.patient.mrn,
        "test": order.test_name,
        "modality": order.modality,
        "ordered_by": order.ordered_by_name,
        "ordered_at": order.ordered_at.isoformat(),
        "released_at": order.released_at.isoformat() if order.released_at else None,
        "verified_by": order.verified_by_name,
        "results": [
            {
                "analyte": result.analyte_name,
                "value": result.display_value,
                "unit": result.unit,
                "reference": result.reference_text,
                "flag": result.flag,
            }
            for result in order.results.filter(is_superseded=False)
        ],
    }
