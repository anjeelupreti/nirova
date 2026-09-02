"""Opening, documenting and closing encounters."""

import logging

from django.utils import timezone

# AuditAction / record / record_version: clinical documentation is the most
# consequential thing this system stores. Signing a note snapshots it.
from apps.audit.models import AuditAction
from apps.audit.services import record, record_version
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.encounters.models import (
    Diagnosis,
    ClinicalNote,
    Encounter,
    EncounterStatus,
    EncounterType,
    VitalSigns,
)
from apps.entitlements.services import require_module
from apps.patients.models import ConditionStatus, PatientCondition
from apps.scheduling.models import AppointmentStatus, QueueStatus
# tenant_atomic_method: transactions must open on the tenant database. A bare
# @transaction.atomic silently opens on the control plane -- see dev log 044.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.encounters")


class EncounterError(DomainError):
    code = "encounter_operation_failed"


class NoteLocked(EncounterError):
    code = "note_locked"
    message = "A signed note cannot be edited. Add an amendment instead."


def generate_encounter_reference() -> str:
    """Sequential, quotable reference: ENC-2026-000142."""
    year = timezone.now().year
    prefix = f"ENC-{year}-"
    last = (
        Encounter.all_objects.filter(reference__startswith=prefix)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:06d}"


@tenant_atomic_method
def start_encounter(
    organization,
    patient,
    facility,
    actor=None,
    encounter_type: str = EncounterType.OUTPATIENT,
    department=None,
    provider_uuid=None,
    provider_name: str = "",
    appointment=None,
    queue_token=None,
    chief_complaint: str = "",
    triage_category=None,
) -> Encounter:
    """Open an episode of care.

    Returns the existing open encounter if the patient already has one at this
    facility. A patient seen twice in a morning is one episode continuing, not
    two — and duplicate encounters would split their vitals and notes across
    records that each look incomplete.
    """
    require_module(organization, ModuleCode.CLINIC)

    existing = Encounter.objects.filter(
        patient=patient,
        facility=facility,
        status__in=[EncounterStatus.IN_PROGRESS, EncounterStatus.AWAITING_RESULTS],
    ).first()
    if existing:
        logger.info(
            "Reusing open encounter %s for %s", existing.reference, patient.mrn
        )
        return existing

    if appointment is not None:
        provider_uuid = provider_uuid or appointment.provider_uuid
        provider_name = provider_name or appointment.provider_name
        department = department or appointment.department
        chief_complaint = chief_complaint or appointment.reason

    encounter = Encounter.objects.create(
        reference=generate_encounter_reference(),
        patient=patient,
        facility=facility,
        department=department,
        encounter_type=encounter_type,
        provider_uuid=provider_uuid,
        provider_name=provider_name,
        appointment=appointment,
        queue_token=queue_token,
        chief_complaint=chief_complaint,
        triage_category=triage_category,
        triaged_at=timezone.now() if triage_category else None,
        triaged_by_id=getattr(actor, "uuid", None) if triage_category else None,
        created_by_id=getattr(actor, "uuid", None),
    )

    if appointment and appointment.status in {
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.ARRIVED,
    }:
        appointment.status = AppointmentStatus.IN_CONSULTATION
        appointment.consultation_started_at = encounter.started_at
        appointment.save(
            update_fields=["status", "consultation_started_at", "updated_at"]
        )

    record(
        AuditAction.CREATE,
        entity_type="encounters.Encounter",
        entity_id=encounter.uuid,
        entity_label=f"{encounter.reference} — {patient.mrn}",
        metadata={
            "encounter_type": encounter_type,
            "chief_complaint": chief_complaint,
        },
    )
    return encounter


@tenant_atomic_method
def record_vitals(encounter, data: dict, actor=None) -> VitalSigns:
    """Record one set of observations.

    Permitted on a signed encounter: a nurse taking observations after the
    doctor has signed their note is normal, and the vitals are a new
    observation rather than a change to the note.
    """
    vitals = VitalSigns.objects.create(
        encounter=encounter,
        recorded_by_id=getattr(actor, "uuid", None),
        recorded_by_name=getattr(actor, "full_name", ""),
        created_by_id=getattr(actor, "uuid", None),
        **data,
    )

    flags = vitals.abnormal_flags()
    critical = [flag for flag in flags if flag["level"] == "critical"]

    record(
        AuditAction.CREATE,
        entity_type="encounters.VitalSigns",
        entity_id=vitals.uuid,
        entity_label=f"Vitals for {encounter.reference}",
        metadata={"abnormal": flags},
    )
    if critical:
        # Escalation routing belongs to the notification module; until it
        # exists, a loud log line is what makes this visible in operations.
        logger.warning(
            "CRITICAL VITALS encounter=%s patient=%s flags=%s",
            encounter.reference,
            encounter.patient.mrn,
            [flag["note"] for flag in critical],
        )
    return vitals


@tenant_atomic_method
def write_note(encounter, data: dict, actor=None, sign: bool = False) -> ClinicalNote:
    """Write a clinical note, optionally signing it."""
    if not encounter.is_editable and not sign:
        raise NoteLocked(
            f"Encounter {encounter.reference} is signed. Add an amendment.",
            detail={"encounter": encounter.reference},
        )

    note = ClinicalNote.objects.create(
        encounter=encounter,
        author_id=getattr(actor, "uuid", None),
        author_name=getattr(actor, "full_name", ""),
        created_by_id=getattr(actor, "uuid", None),
        **data,
    )
    if sign:
        sign_note(note, actor)
    return note


@tenant_atomic_method
def sign_note(note: ClinicalNote, actor=None) -> ClinicalNote:
    """Sign a note, locking it and snapshotting its content.

    The snapshot is the point. A signed note is a clinical and legal
    statement; the version record is what proves what it said at the moment
    it was signed, independent of anything that happens afterwards.
    """
    if note.is_signed:
        raise EncounterError(
            "This note is already signed.",
            detail={"note": str(note.uuid), "signed_at": note.signed_at.isoformat()},
        )
    if note.is_empty:
        raise EncounterError("An empty note cannot be signed.")

    note.is_signed = True
    note.signed_at = timezone.now()
    note.save(update_fields=["is_signed", "signed_at", "updated_at"])

    record_version(
        entity_type="encounters.ClinicalNote",
        entity_id=note.uuid,
        snapshot={
            "note_type": note.note_type,
            "subjective": note.subjective,
            "objective": note.objective,
            "assessment": note.assessment,
            "plan": note.plan,
            "body": note.body,
            "author": note.author_name,
            "encounter": note.encounter.reference,
        },
        reason="Note signed",
    )
    record(
        AuditAction.APPROVE,
        entity_type="encounters.ClinicalNote",
        entity_id=note.uuid,
        entity_label=f"{note.get_note_type_display()} — {note.encounter.reference}",
        metadata={"signed_by": getattr(actor, "email", "")},
    )
    return note


@tenant_atomic_method
def amend_note(original: ClinicalNote, data: dict, reason: str, actor=None) -> ClinicalNote:
    """Correct a signed note by adding an amendment.

    The original is never touched. Both remain readable, in order, so the
    record shows what was said, what was corrected, and why.
    """
    if not reason.strip():
        raise EncounterError("An amendment must say why the note is being corrected.")
    if not original.is_signed:
        raise EncounterError(
            "An unsigned note is edited directly, not amended.",
            detail={"note": str(original.uuid)},
        )

    amendment = ClinicalNote.objects.create(
        encounter=original.encounter,
        note_type=original.note_type,
        amends=original,
        amendment_reason=reason,
        author_id=getattr(actor, "uuid", None),
        author_name=getattr(actor, "full_name", ""),
        created_by_id=getattr(actor, "uuid", None),
        **data,
    )
    record(
        AuditAction.UPDATE,
        entity_type="encounters.ClinicalNote",
        entity_id=amendment.uuid,
        entity_label=f"Amendment to {original.uuid}",
        reason=reason,
        metadata={"amends": str(original.uuid)},
    )
    return amendment


@tenant_atomic_method
def add_diagnosis(encounter, data: dict, actor=None) -> Diagnosis:
    """Record a diagnosis against an encounter.

    Setting a diagnosis primary demotes any existing primary, rather than
    letting the unique constraint raise. Choosing a new primary is a normal
    clinical act as a picture clarifies; making the clinician un-set the old
    one first would be friction for nothing.
    """
    is_primary = data.get("is_primary", False)
    if is_primary:
        Diagnosis.objects.filter(encounter=encounter, is_primary=True).update(
            is_primary=False
        )

    diagnosis = Diagnosis.objects.create(
        encounter=encounter,
        patient=encounter.patient,
        diagnosed_by_id=getattr(actor, "uuid", None),
        diagnosed_by_name=getattr(actor, "full_name", ""),
        created_by_id=getattr(actor, "uuid", None),
        **data,
    )
    record(
        AuditAction.CREATE,
        entity_type="encounters.Diagnosis",
        entity_id=diagnosis.uuid,
        entity_label=f"{diagnosis.name} — {encounter.reference}",
        metadata={"icd10": diagnosis.icd10_code, "primary": is_primary},
    )
    return diagnosis


@tenant_atomic_method
def promote_to_condition(diagnosis: Diagnosis, actor=None) -> PatientCondition:
    """Carry a diagnosis into the patient's ongoing condition list.

    Deliberate rather than automatic. Most diagnoses are episodic — a chest
    infection should not follow someone for life — and a condition list that
    fills with every past complaint stops being read, which defeats its
    purpose.
    """
    if diagnosis.promoted_to_condition_id:
        return diagnosis.promoted_to_condition

    condition = PatientCondition.objects.create(
        patient=diagnosis.patient,
        name=diagnosis.name,
        icd10_code=diagnosis.icd10_code,
        category="chronic",
        status=ConditionStatus.ACTIVE,
        onset_date=diagnosis.onset_date,
        recorded_by_id=getattr(actor, "uuid", None),
        notes=f"From {diagnosis.encounter.reference}",
        created_by_id=getattr(actor, "uuid", None),
    )
    diagnosis.promoted_to_condition = condition
    diagnosis.is_chronic = True
    diagnosis.save(update_fields=["promoted_to_condition", "is_chronic", "updated_at"])

    record(
        AuditAction.CREATE,
        entity_type="patients.PatientCondition",
        entity_id=condition.uuid,
        entity_label=f"{condition.name} — {diagnosis.patient.mrn}",
        reason=f"Promoted from diagnosis on {diagnosis.encounter.reference}",
    )
    return condition


@tenant_atomic_method
def close_encounter(
    encounter,
    actor=None,
    disposition: str = "discharged",
    disposition_notes: str = "",
    follow_up_date=None,
    follow_up_instructions: str = "",
    sign: bool = True,
) -> Encounter:
    """End an episode of care.

    Refuses to close an encounter with no documentation at all. A visit with
    no note, no diagnosis and no vitals is almost always an encounter opened
    by mistake, and closing it silently makes the mistake permanent.
    """
    if encounter.status in {EncounterStatus.COMPLETED, EncounterStatus.CANCELLED}:
        raise EncounterError(
            f"Encounter {encounter.reference} is already "
            f"{encounter.get_status_display().lower()}.",
            detail={"status": encounter.status},
        )

    has_documentation = (
        encounter.notes.exists()
        or encounter.diagnoses.exists()
        or encounter.vitals.exists()
    )
    if not has_documentation:
        raise EncounterError(
            "This encounter has no notes, diagnoses or vitals recorded. Add "
            "documentation, or cancel it if it was opened in error.",
            detail={"encounter": encounter.reference},
        )

    encounter.status = EncounterStatus.COMPLETED
    encounter.ended_at = timezone.now()
    encounter.disposition = disposition
    encounter.disposition_notes = disposition_notes
    encounter.follow_up_date = follow_up_date
    encounter.follow_up_instructions = follow_up_instructions
    if sign:
        encounter.is_signed = True
        encounter.signed_at = timezone.now()
        encounter.signed_by_id = getattr(actor, "uuid", None)
    encounter.save(
        update_fields=[
            "status", "ended_at", "disposition", "disposition_notes",
            "follow_up_date", "follow_up_instructions", "is_signed",
            "signed_at", "signed_by_id", "updated_at",
        ]
    )

    # Close out the appointment and queue token this encounter came from, so
    # the front desk does not still show the patient as waiting.
    if encounter.appointment and encounter.appointment.status not in {
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
    }:
        encounter.appointment.status = AppointmentStatus.COMPLETED
        encounter.appointment.consultation_ended_at = encounter.ended_at
        encounter.appointment.save(
            update_fields=["status", "consultation_ended_at", "updated_at"]
        )
    if encounter.queue_token and encounter.queue_token.is_active:
        encounter.queue_token.status = QueueStatus.COMPLETED
        encounter.queue_token.completed_at = encounter.ended_at
        encounter.queue_token.save(
            update_fields=["status", "completed_at", "updated_at"]
        )

    record(
        AuditAction.UPDATE,
        entity_type="encounters.Encounter",
        entity_id=encounter.uuid,
        entity_label=encounter.reference,
        changes={"status": {"before": EncounterStatus.IN_PROGRESS,
                            "after": EncounterStatus.COMPLETED}},
        metadata={"disposition": disposition, "duration_minutes":
                  encounter.duration_minutes},
    )
    return encounter


def patient_clinical_summary(patient) -> dict:
    """Everything a clinician wants before they see the patient.

    One call rather than five, and ordered by what matters: allergies first,
    then active conditions, then recent history. A doctor with ninety seconds
    per patient should not have to assemble this from tabs.
    """
    from apps.patients.models import PatientAllergy

    recent = (
        Encounter.objects.filter(patient=patient)
        .select_related("facility")
        .prefetch_related("diagnoses")
        .order_by("-started_at")[:10]
    )
    latest_vitals = (
        VitalSigns.objects.filter(encounter__patient=patient)
        .order_by("-recorded_at")
        .first()
    )

    return {
        "patient": {
            "uuid": str(patient.uuid),
            "mrn": patient.mrn,
            "name": patient.full_name,
            "age": patient.age_years,
            "gender": patient.gender,
            "blood_group": patient.blood_group,
            "alerts": patient.alerts,
        },
        "allergies": [
            {
                "substance": allergy.substance,
                "severity": allergy.severity,
                "reaction": allergy.reaction,
                "status": allergy.status,
                "blocks_prescribing": allergy.blocks_prescribing,
            }
            for allergy in PatientAllergy.objects.filter(patient=patient)
            if allergy.blocks_prescribing
        ],
        "conditions": [
            {"name": condition.name, "icd10_code": condition.icd10_code,
             "status": condition.status, "onset_date": condition.onset_date}
            for condition in patient.conditions.filter(
                status=ConditionStatus.ACTIVE
            )
        ],
        "latest_vitals": (
            {
                "recorded_at": latest_vitals.recorded_at,
                "temperature_c": latest_vitals.temperature_c,
                "pulse_bpm": latest_vitals.pulse_bpm,
                "blood_pressure": latest_vitals.blood_pressure,
                "spo2_percent": latest_vitals.spo2_percent,
                "bmi": latest_vitals.bmi,
                "abnormal": latest_vitals.abnormal_flags(),
            }
            if latest_vitals
            else None
        ),
        "recent_encounters": [
            {
                "reference": encounter.reference,
                "started_at": encounter.started_at,
                "encounter_type": encounter.encounter_type,
                "facility": encounter.facility.name,
                "chief_complaint": encounter.chief_complaint,
                "status": encounter.status,
                "diagnoses": [
                    {"name": d.name, "icd10_code": d.icd10_code,
                     "is_primary": d.is_primary}
                    for d in encounter.diagnoses.all()
                ],
            }
            for encounter in recent
        ],
    }
