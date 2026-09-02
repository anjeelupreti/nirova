"""Registering, de-duplicating and merging patients."""

import logging

from django.db.models import Q
from django.utils import timezone

# AuditAction / record: patient data is sensitive, so registration, viewing
# and merging are all written to the tenant audit log.
from apps.audit.models import AuditAction
from apps.audit.services import record, record_version
from apps.catalog.keys import MeterKey, ModuleCode
from apps.common.exceptions import DomainError
# check_quota / require_module: registering a patient consumes an entitlement
# (patient volume is a billable dimension) and requires the clinic module.
from apps.entitlements.services import check_quota, require_module
from apps.patients.models import (
    Patient,
    PatientIdentifier,
    PatientMergeLog,
    PatientStatus,
)
# tenant_atomic_method: opens the transaction on the *tenant* database. A bare
# @transaction.atomic would open one on the control plane, leaving these
# writes unprotected and breaking the MRN row lock. See apps/tenancy/db.py.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.patients")


class PatientError(DomainError):
    code = "patient_operation_failed"


class DuplicatePatientWarning(DomainError):
    """Not an error in the usual sense -- a prompt to confirm.

    Returned as 409 so the client can show the candidates and let the user
    decide. Registration proceeds if they pass `force=True`, because a
    genuine duplicate name is common and blocking outright would stop a real
    patient being seen.
    """

    code = "possible_duplicate_patient"
    status_code = 409
    message = "One or more existing patients look like this person."


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------
#
# Ordered by how much each signal is worth. A shared national ID is close to
# proof; a shared name is barely a hint. The scores are deliberately blunt --
# this surfaces candidates for a human, it does not decide anything.

MATCH_WEIGHTS = {
    "identifier": 60,
    "phone": 25,
    "name_dob": 20,
    "name_exact": 10,
}
#: Total score at which candidates are shown to the registering clerk.
DUPLICATE_THRESHOLD = 30


def find_duplicate_candidates(
    first_name: str,
    last_name: str,
    phone: str = "",
    date_of_birth=None,
    identifiers: list | None = None,
    exclude_patient_id=None,
    limit: int = 10,
) -> list:
    """Find existing patients who may be the same person.

    Deliberately generous: showing a clerk three candidates costs a glance,
    while a missed duplicate splits a patient's history across two records and
    is expensive to unpick later.
    """
    scores: dict[int, dict] = {}

    def add(patient, signal: str):
        entry = scores.setdefault(
            patient.pk, {"patient": patient, "score": 0, "matched_on": []}
        )
        if signal not in entry["matched_on"]:
            entry["matched_on"].append(signal)
            entry["score"] += MATCH_WEIGHTS[signal]

    base = Patient.objects.exclude(status=PatientStatus.MERGED)
    if exclude_patient_id:
        base = base.exclude(pk=exclude_patient_id)

    # Strongest signal: the same document number.
    for identifier in identifiers or []:
        value = (identifier.get("value") or "").strip()
        if not value:
            continue
        matches = PatientIdentifier.objects.filter(
            identifier_type=identifier.get("identifier_type", ""), value=value
        ).select_related("patient")
        for match in matches:
            if match.patient_id and (
                not exclude_patient_id or match.patient_id != exclude_patient_id
            ):
                add(match.patient, "identifier")

    if phone:
        for patient in base.filter(
            Q(phone=phone) | Q(alternate_phone=phone) | Q(guardian_phone=phone)
        )[:20]:
            add(patient, "phone")

    if first_name and last_name:
        name_matches = base.filter(
            first_name__iexact=first_name.strip(), last_name__iexact=last_name.strip()
        )
        for patient in name_matches[:20]:
            add(patient, "name_exact")
            if date_of_birth and patient.date_of_birth == date_of_birth:
                add(patient, "name_dob")

    candidates = [
        entry for entry in scores.values() if entry["score"] >= DUPLICATE_THRESHOLD
    ]
    candidates.sort(key=lambda entry: entry["score"], reverse=True)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@tenant_atomic_method
def register_patient(
    organization,
    data: dict,
    actor=None,
    facility=None,
    identifiers: list | None = None,
    force: bool = False,
) -> Patient:
    """Register a new patient.

    Order matters. Entitlement is checked before anything is written, so a
    customer over their patient limit is told immediately rather than after a
    record exists. Duplicate detection runs next, before the MRN is allocated,
    so a rejected registration does not burn a number.
    """
    require_module(organization, ModuleCode.CLINIC)

    decision = check_quota(organization, "max_patients", requested=1)
    decision.raise_if_blocked()

    if not force:
        candidates = find_duplicate_candidates(
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            phone=data.get("phone", ""),
            date_of_birth=data.get("date_of_birth"),
            identifiers=identifiers,
        )
        if candidates:
            raise DuplicatePatientWarning(
                "This person may already be registered. Review the matches, "
                "or confirm to register a new record.",
                detail={
                    "candidates": [
                        {
                            "uuid": str(entry["patient"].uuid),
                            "mrn": entry["patient"].mrn,
                            "name": entry["patient"].full_name,
                            "phone": entry["patient"].phone,
                            "age": entry["patient"].age_years,
                            "score": entry["score"],
                            "matched_on": entry["matched_on"],
                        }
                        for entry in candidates
                    ]
                },
            )

    actor_id = getattr(actor, "uuid", None)
    patient = Patient.objects.create(
        mrn=Patient.allocate_mrn(),
        registered_at_facility=facility,
        created_by_id=actor_id,
        **data,
    )

    for identifier in identifiers or []:
        if identifier.get("value"):
            PatientIdentifier.objects.create(
                patient=patient,
                identifier_type=identifier["identifier_type"],
                value=identifier["value"].strip(),
                created_by_id=actor_id,
            )

    record(
        AuditAction.CREATE,
        entity_type="patients.Patient",
        entity_id=patient.uuid,
        entity_label=f"{patient.full_name} ({patient.mrn})",
        metadata={"mrn": patient.mrn, "forced_over_duplicate": force},
    )
    _meter_patient(organization)

    logger.info("Registered patient %s for %s", patient.mrn, organization.slug)
    return patient


def _meter_patient(organization) -> None:
    """Count the registration against the patient meter.

    Failure is logged, never raised: a metering problem is a billing problem
    for the platform to fix, not a reason a patient cannot be registered.
    """
    from apps.metering.models import UsageEvent

    try:
        UsageEvent.objects.create(
            organization=organization, meter_key=MeterKey.PATIENTS, quantity=1
        )
    except Exception:
        logger.exception("Failed to meter patient registration for %s", organization.slug)


# ---------------------------------------------------------------------------
# Viewing
# ---------------------------------------------------------------------------


def record_patient_access(patient, reason: str = "") -> None:
    """Log that someone opened a patient's record.

    Every access to identifiable clinical data is logged, not only changes.
    "Who looked at this record?" is the question asked after a privacy
    complaint, and it cannot be answered retrospectively unless the reads were
    recorded at the time.
    """
    record(
        AuditAction.VIEW_SENSITIVE,
        entity_type="patients.Patient",
        entity_id=patient.uuid,
        entity_label=f"{patient.full_name} ({patient.mrn})",
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


@tenant_atomic_method
def merge_patients(
    surviving: Patient,
    duplicate: Patient,
    actor,
    reason: str,
    matched_on: list | None = None,
) -> Patient:
    """Merge `duplicate` into `surviving`.

    The duplicate row is kept, not deleted. Prescriptions, invoices and lab
    results already point at it, and a merge must never orphan a clinical
    record. It is marked merged and carries a pointer to the survivor, so
    anything reaching it can follow `resolve()` to the live record.

    Clinical history moves; demographics do not overwrite. The surviving
    record's details were more likely confirmed at a counter, and silently
    replacing a verified address with an older one would be a regression
    nobody would notice.
    """
    if surviving.pk == duplicate.pk:
        raise PatientError("A patient cannot be merged into themselves.")
    if duplicate.is_merged:
        raise PatientError(
            f"{duplicate.mrn} has already been merged.",
            detail={"merged_into": str(duplicate.merged_into.uuid)},
        )
    if surviving.is_merged:
        raise PatientError(
            f"{surviving.mrn} is itself a merged record. Merge into "
            f"{surviving.resolve().mrn} instead.",
            detail={"resolve_to": surviving.resolve().mrn},
        )
    if not reason.strip():
        raise PatientError("A merge must record why the records are the same.")

    snapshot = {
        "mrn": duplicate.mrn,
        "full_name": duplicate.full_name,
        "gender": duplicate.gender,
        "date_of_birth": (
            duplicate.date_of_birth.isoformat() if duplicate.date_of_birth else None
        ),
        "phone": duplicate.phone,
        "district": duplicate.district,
        "registered_on": duplicate.registered_on.isoformat(),
    }

    # Clinical history transfers. Identifiers move too, since a document
    # number belongs to the person, not the record.
    duplicate.identifiers.update(patient=surviving)
    duplicate.allergies.update(patient=surviving)
    duplicate.conditions.update(patient=surviving)

    duplicate.status = PatientStatus.MERGED
    duplicate.merged_into = surviving
    duplicate.merged_at = timezone.now()
    duplicate.updated_by_id = getattr(actor, "uuid", None)
    duplicate.save(
        update_fields=["status", "merged_into", "merged_at", "updated_by_id", "updated_at"]
    )

    merge_log = PatientMergeLog.objects.create(
        surviving_patient=surviving,
        merged_patient=duplicate,
        reason=reason,
        matched_on=matched_on or [],
        merged_snapshot=snapshot,
        performed_by_id=getattr(actor, "uuid", None),
        performed_by_email=getattr(actor, "email", ""),
        created_by_id=getattr(actor, "uuid", None),
    )

    # Versioned as well as audited: a merge changes what the surviving record
    # means, and that is exactly the kind of change entry 023 keeps snapshots
    # for.
    record_version(
        entity_type="patients.Patient",
        entity_id=surviving.uuid,
        snapshot=snapshot,
        changed_fields=["merged_records"],
        reason=f"Merged {duplicate.mrn} into {surviving.mrn}: {reason}",
    )
    record(
        AuditAction.PATIENT_MERGE,
        entity_type="patients.Patient",
        entity_id=surviving.uuid,
        entity_label=f"{surviving.full_name} ({surviving.mrn})",
        reason=reason,
        metadata={
            "merged_mrn": duplicate.mrn,
            "surviving_mrn": surviving.mrn,
            "merge_log": str(merge_log.uuid),
        },
    )

    logger.warning(
        "Merged patient %s into %s by %s",
        duplicate.mrn,
        surviving.mrn,
        getattr(actor, "email", "unknown"),
    )
    return surviving
