"""Writing, revising and stopping prescriptions."""

import logging

from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record, record_version
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.prescriptions.models import (
    Prescription,
    PrescriptionLine,
    PrescriptionLineStatus,
    PrescriptionStatus,
)
# run_safety_checks: allergies, interactions and duplicates. It warns; it
# never blocks -- see apps/prescriptions/safety.py for why.
from apps.prescriptions.safety import run_safety_checks
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.prescribing")

#: How long a prescription stays dispensable unless told otherwise. Nepal has
#: no single statutory period; 30 days is common practice and is overridable
#: per prescription.
DEFAULT_VALIDITY_DAYS = 30


class PrescriptionError(DomainError):
    code = "prescription_operation_failed"


class OverrideRequired(PrescriptionError):
    """A high-severity warning was raised and not acknowledged.

    Distinct from a refusal: the prescriber may proceed, but must say why.
    Requiring the reason at the moment of decision is what makes the record
    worth having — a reason reconstructed later is a rationalisation.
    """

    code = "override_reason_required"
    status_code = 409
    message = "This prescription raises safety warnings that need a reason to proceed."


def generate_prescription_reference() -> str:
    year = timezone.now().year
    prefix = f"RX-{year}-"
    last = (
        Prescription.all_objects.filter(reference__startswith=prefix)
        .order_by("-reference")
        .values_list("reference", flat=True)
        .first()
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:06d}"


def preview_prescription(patient, lines: list) -> dict:
    """Run the safety checks without writing anything.

    Called as the prescriber types, so an allergy warning appears while they
    can still change their mind, rather than as a rejection after they commit.
    """
    return run_safety_checks(patient, lines)


@tenant_atomic_method
def create_prescription(
    organization,
    patient,
    facility,
    lines: list,
    actor=None,
    encounter=None,
    prescriber_name: str = "",
    prescriber_registration: str = "",
    notes: str = "",
    patient_instructions: str = "",
    valid_days: int = DEFAULT_VALIDITY_DAYS,
    override_reason: str = "",
    sign: bool = True,
) -> Prescription:
    """Write a prescription.

    The safety checks run here as well as in the preview, because the preview
    is advisory and this is the record. Between the two the patient's allergy
    list may have changed — a nurse may have just recorded the reaction the
    patient described in the waiting room.
    """
    require_module(organization, ModuleCode.CLINIC)

    if not lines:
        raise PrescriptionError("A prescription must have at least one medicine.")

    # Who is writing this, and may they? Until `apps.hr` existed the
    # prescriber was a bare uuid with nothing behind it -- no name to print,
    # no council number, and no way to notice that their registration had
    # lapsed. `Employee.for_user` closes that, and a lapsed registration is a
    # refusal rather than a warning: prescribing on one is an offence under
    # the council's own rules, and a warning somebody can click past is not a
    # control.
    #
    # Imported inside the function because `apps.hr` imports nothing from
    # here, and a module-level import in both directions would be a cycle.
    from apps.hr.services import assert_may_practise, provider_for

    prescriber = provider_for(getattr(actor, "uuid", None))
    if prescriber is not None:
        assert_may_practise(prescriber)
        # Printed on the prescription. Nepali law requires the prescriber's
        # council registration on a dispensable script, and taking it from
        # the verified record beats retyping it correctly every time.
        prescriber_name = prescriber_name or prescriber.full_name
        if not prescriber_registration:
            registration = next(
                (
                    credential for credential in prescriber.credentials.all()
                    if credential.credential_type == "council"
                    and not credential.is_expired
                ),
                None,
            )
            if registration:
                prescriber_registration = registration.reference_number

    # A merged record is a tombstone: its allergies and conditions moved to
    # the surviving chart, so a prescription written here would be both
    # unsafe to check and invisible on the patient's real record. Refuse and
    # name the survivor rather than silently redirecting -- the prescriber
    # should know which chart they are working in.
    if patient.is_merged:
        survivor = patient.resolve()
        raise PrescriptionError(
            f"{patient.mrn} was merged into {survivor.mrn}. Write the "
            "prescription against the surviving record.",
            detail={
                "merged_mrn": patient.mrn,
                "surviving_mrn": survivor.mrn,
                "surviving_uuid": str(survivor.uuid),
            },
        )

    safety = run_safety_checks(patient, lines)
    if safety["requires_override"] and not override_reason.strip():
        raise OverrideRequired(
            "This prescription raises warnings that need a reason before it "
            "can be signed.",
            detail=safety,
        )

    prescription = Prescription.objects.create(
        reference=generate_prescription_reference(),
        patient=patient,
        encounter=encounter,
        facility=facility,
        prescriber_id=getattr(actor, "uuid", None),
        prescriber_name=prescriber_name or getattr(actor, "full_name", ""),
        prescriber_registration=prescriber_registration,
        status=PrescriptionStatus.DRAFT,
        valid_until=timezone.localdate() + timezone.timedelta(days=valid_days),
        safety_checks=safety,
        has_overridden_warning=safety["requires_override"],
        override_reason=override_reason,
        notes=notes,
        patient_instructions=patient_instructions,
        created_by_id=getattr(actor, "uuid", None),
    )

    for order, line_data in enumerate(lines):
        data = dict(line_data)
        # Attach the warnings that concern this specific medicine, so a
        # pharmacist reading one line sees why it was flagged.
        generic = (data.get("generic_name") or "").lower()
        data["warnings"] = [
            warning
            for warning in safety["warnings"]
            if generic
            and (
                generic in str(warning.get("drug", "")).lower()
                or any(generic in str(d).lower() for d in warning.get("drugs", []))
            )
        ]
        data.setdefault("display_order", order)

        line = PrescriptionLine(prescription=prescription, **data)
        if line.quantity is None:
            line.quantity = line.suggested_quantity()
        line.created_by_id = getattr(actor, "uuid", None)
        line.save()

    if sign:
        sign_prescription(prescription, actor)

    if safety["has_critical"]:
        logger.warning(
            "PRESCRIPTION WITH CRITICAL WARNING rx=%s patient=%s prescriber=%s "
            "reason=%r",
            prescription.reference,
            patient.mrn,
            getattr(actor, "email", "unknown"),
            override_reason,
        )
    return prescription


@tenant_atomic_method
def sign_prescription(prescription: Prescription, actor=None) -> Prescription:
    """Sign a prescription, making it dispensable and locking it."""
    if prescription.is_signed:
        raise PrescriptionError(
            f"{prescription.reference} is already signed.",
            detail={"signed_at": prescription.signed_at.isoformat()},
        )
    if not prescription.lines.exists():
        raise PrescriptionError("An empty prescription cannot be signed.")

    prescription.is_signed = True
    prescription.signed_at = timezone.now()
    prescription.status = PrescriptionStatus.ACTIVE
    prescription.save(
        update_fields=["is_signed", "signed_at", "status", "updated_at"]
    )

    record_version(
        entity_type="prescriptions.Prescription",
        entity_id=prescription.uuid,
        snapshot=_snapshot(prescription),
        reason="Prescription signed",
    )
    record(
        AuditAction.PRESCRIPTION_CHANGE,
        entity_type="prescriptions.Prescription",
        entity_id=prescription.uuid,
        entity_label=f"{prescription.reference} — {prescription.patient.mrn}",
        metadata={
            "lines": prescription.lines.count(),
            "overridden_warning": prescription.has_overridden_warning,
            "override_reason": prescription.override_reason,
        },
    )
    return prescription


@tenant_atomic_method
def revise_prescription(
    original: Prescription,
    lines: list,
    reason: str,
    actor=None,
    override_reason: str = "",
) -> Prescription:
    """Replace a prescription with a corrected version.

    A new row, pointing back at the old one, which is marked superseded. The
    original stays exactly as it was written and signed — that is the whole
    reason revision exists rather than editing.
    """
    if not reason.strip():
        raise PrescriptionError("A revision must record why it was needed.")
    if original.status not in {PrescriptionStatus.ACTIVE, PrescriptionStatus.DRAFT}:
        raise PrescriptionError(
            f"{original.reference} is {original.get_status_display().lower()} "
            "and cannot be revised.",
            detail={"status": original.status},
        )

    # Built by a dedicated helper rather than by calling create_prescription:
    # a revision inherits the original's validity, prescriber registration and
    # patient instructions, and carries version/supersedes, none of which the
    # first-write path knows about.
    revision = _create_revision(original, lines, reason, actor, override_reason)

    original.status = PrescriptionStatus.SUPERSEDED
    original.save(update_fields=["status", "updated_at"])

    record(
        AuditAction.PRESCRIPTION_CHANGE,
        entity_type="prescriptions.Prescription",
        entity_id=revision.uuid,
        entity_label=f"{revision.reference} supersedes {original.reference}",
        reason=reason,
    )
    return revision


def _create_revision(original, lines, reason, actor, override_reason):
    """Build the successor row. Split out to keep `revise_prescription` readable."""
    safety = run_safety_checks(original.patient, lines)
    if safety["requires_override"] and not override_reason.strip():
        raise OverrideRequired(
            "The revised prescription raises warnings that need a reason.",
            detail=safety,
        )

    revision = Prescription.objects.create(
        reference=generate_prescription_reference(),
        patient=original.patient,
        encounter=original.encounter,
        facility=original.facility,
        prescriber_id=getattr(actor, "uuid", None),
        prescriber_name=getattr(actor, "full_name", "") or original.prescriber_name,
        prescriber_registration=original.prescriber_registration,
        status=PrescriptionStatus.ACTIVE,
        valid_until=original.valid_until,
        version=original.version + 1,
        supersedes=original,
        revision_reason=reason,
        safety_checks=safety,
        has_overridden_warning=safety["requires_override"],
        override_reason=override_reason,
        notes=original.notes,
        patient_instructions=original.patient_instructions,
        is_signed=True,
        signed_at=timezone.now(),
        created_by_id=getattr(actor, "uuid", None),
    )
    for order, line_data in enumerate(lines):
        data = dict(line_data)
        data.setdefault("display_order", order)
        line = PrescriptionLine(prescription=revision, **data)
        if line.quantity is None:
            line.quantity = line.suggested_quantity()
        line.created_by_id = getattr(actor, "uuid", None)
        line.save()

    record_version(
        entity_type="prescriptions.Prescription",
        entity_id=revision.uuid,
        snapshot=_snapshot(revision),
        reason=f"Revision of {original.reference}: {reason}",
    )
    return revision


@tenant_atomic_method
def discontinue_line(line: PrescriptionLine, reason: str, actor=None) -> PrescriptionLine:
    """Stop one medicine without disturbing the rest of the prescription.

    Stopping a drug is a clinical decision in its own right and is recorded as
    one: who, when, why. The line stays visible with its end date, because
    "they were on this until the 14th" is part of the history.
    """
    if not reason.strip():
        raise PrescriptionError("Stopping a medicine must record a reason.")
    if line.status != PrescriptionLineStatus.ACTIVE:
        raise PrescriptionError(
            f"{line.generic_name} is already "
            f"{line.get_status_display().lower()}.",
            detail={"status": line.status},
        )

    line.status = PrescriptionLineStatus.DISCONTINUED
    line.discontinued_at = timezone.now()
    line.discontinued_by_id = getattr(actor, "uuid", None)
    line.discontinuation_reason = reason
    line.end_date = timezone.localdate()
    line.save(
        update_fields=[
            "status", "discontinued_at", "discontinued_by_id",
            "discontinuation_reason", "end_date", "updated_at",
        ]
    )

    # A prescription whose every line has stopped is itself finished.
    remaining = line.prescription.lines.filter(
        status=PrescriptionLineStatus.ACTIVE
    ).exists()
    if not remaining:
        line.prescription.status = PrescriptionStatus.COMPLETED
        line.prescription.save(update_fields=["status", "updated_at"])

    record(
        AuditAction.PRESCRIPTION_CHANGE,
        entity_type="prescriptions.PrescriptionLine",
        entity_id=line.uuid,
        entity_label=f"{line.generic_name} on {line.prescription.reference}",
        reason=reason,
        changes={"status": {"before": PrescriptionLineStatus.ACTIVE,
                            "after": PrescriptionLineStatus.DISCONTINUED}},
    )
    return line


def active_medications(patient) -> list:
    """Everything the patient is currently taking, across prescriptions.

    The list a clinician needs before prescribing anything new, and the one a
    pharmacist checks at the counter. Assembled across prescriptions because
    a patient on five drugs may well have them on three separate scripts.
    """
    lines = (
        PrescriptionLine.objects.filter(
            prescription__patient=patient,
            prescription__status=PrescriptionStatus.ACTIVE,
            status=PrescriptionLineStatus.ACTIVE,
        )
        .select_related("prescription")
        .order_by("generic_name")
    )
    today = timezone.localdate()
    return [
        {
            "uuid": str(line.uuid),
            "prescription_reference": line.prescription.reference,
            "prescribed_at": line.prescription.prescribed_at,
            "prescriber": line.prescription.prescriber_name,
            "display_name": line.display_name,
            "generic_name": line.generic_name,
            "sig": line.sig,
            "start_date": line.start_date,
            "end_date": line.end_date,
            # A course whose end date has passed but which nobody has closed
            # is worth flagging: it is either finished or being continued
            # without a decision.
            "is_overdue_review": bool(line.end_date and line.end_date < today),
            "warnings": line.warnings,
        }
        for line in lines
    ]


def _snapshot(prescription: Prescription) -> dict:
    return {
        "reference": prescription.reference,
        "patient_mrn": prescription.patient.mrn,
        "prescriber": prescription.prescriber_name,
        "prescribed_at": prescription.prescribed_at.isoformat(),
        "version": prescription.version,
        "override_reason": prescription.override_reason,
        "lines": [
            {
                "generic_name": line.generic_name,
                "brand_name": line.brand_name,
                "strength": line.strength,
                "dose": line.dose,
                "route": line.route,
                "frequency": line.frequency,
                "duration_days": line.duration_days,
                "quantity": str(line.quantity) if line.quantity else None,
                "instructions": line.instructions,
            }
            for line in prescription.lines.all()
        ],
    }
