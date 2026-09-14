"""Using a template, and keeping it honest.

Three rules, and they are the whole module:

**Applying a template writes nothing.** It returns lines shaped exactly like
the ones the prescribing form posts, for the prescriber to change and sign.
A template that wrote a prescription would be a prescription nobody read.

**What a template cannot know is left blank.** A dose adjusted for weight, a
duration that depends on the culture result, a medicine the patient is
allergic to: the template carries the common case and the prescriber carries
the patient. Anything patient-specific is absent rather than defaulted, and
the allergy and interaction checks run on the result as they do on anything
typed by hand.

**Mine and ours are both visible; only mine is mine to edit.** Every
prescriber sees the organization's templates and their own. Nobody sees
another clinician's, and nobody edits the organization's without
`catalog.manage` — it is formulary curation, not a note.
"""

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.prescriptions.models import DoseRoute, Frequency
from apps.prescriptions.templates_models import (
    PrescriptionTemplate,
    PrescriptionTemplateLine,
)


class TemplateError(DomainError):
    code = "template_refused"


def visible_to(user) -> QuerySet:
    """The organization's templates, plus this prescriber's own."""
    return (
        PrescriptionTemplate.objects.filter(is_active=True)
        .filter(Q(owner_id__isnull=True) | Q(owner_id=getattr(user, "uuid", None)))
        .prefetch_related("lines")
    )


def describe(template: PrescriptionTemplate) -> dict:
    return {
        "uuid": str(template.uuid),
        "name": template.name,
        "description": template.description,
        "shared": template.is_shared,
        "owner_name": template.owner_name,
        "department": template.department.name if template.department_id else "",
        "tags": template.tags or [],
        "patient_instructions": template.patient_instructions,
        "times_used": template.times_used,
        "lines": [
            {
                "uuid": str(line.uuid),
                "product_uuid": str(line.product_uuid) if line.product_uuid else None,
                "generic_name": line.generic_name,
                "brand_name": line.brand_name,
                "strength": line.strength,
                "dosage_form": line.dosage_form,
                "dose": line.dose,
                "route": line.route,
                "frequency": line.frequency,
                "frequency_label": Frequency(line.frequency).label if line.frequency else "",
                "duration_days": line.duration_days,
                "is_prn": line.is_prn,
                "prn_indication": line.prn_indication,
                "instructions": line.instructions,
                "quantity": str(line.quantity) if line.quantity is not None else (
                    str(line.suggested_quantity()) if line.suggested_quantity() is not None else ""
                ),
                "quantity_unit": line.quantity_unit,
                "display_order": line.display_order,
            }
            for line in template.lines.all()
        ],
    }


@transaction.atomic
def save_template(*, user, name: str, lines: list, uuid=None, shared: bool = False,
                  description: str = "", tags=None, patient_instructions: str = "",
                  may_curate: bool = False) -> PrescriptionTemplate:
    """Create or replace a template, lines and all.

    The lines are replaced rather than merged: a template is a short list
    somebody is looking at while they edit it, and a partial update would make
    "removed" and "not sent" the same thing.
    """
    name = (name or "").strip()
    if not name:
        raise TemplateError("A template needs a name.")
    if not lines:
        raise TemplateError("A template with no medicines in it is not a template.")
    if shared and not may_curate:
        raise TemplateError(
            "Shared templates are the organization's formulary. Save this as "
            "your own, or ask somebody who curates the catalogue.",
            code="not_yours_to_share",
        )

    if uuid:
        template = PrescriptionTemplate.objects.filter(uuid=uuid).first()
        if template is None:
            raise TemplateError("That template no longer exists.", code="not_found")
        _assert_may_edit(template, user, may_curate)
    else:
        template = PrescriptionTemplate()

    template.name = name
    template.description = description.strip()
    template.tags = list(tags or [])
    template.patient_instructions = patient_instructions.strip()
    template.owner_id = None if shared else getattr(user, "uuid", None)
    template.owner_name = "" if shared else (getattr(user, "full_name", "") or "")
    template.save()

    template.lines.all().delete()
    for position, row in enumerate(lines):
        line = PrescriptionTemplateLine(
            template=template,
            product_uuid=row.get("product_uuid") or None,
            generic_name=str(row.get("generic_name", "")).strip(),
            brand_name=str(row.get("brand_name", "")).strip(),
            strength=str(row.get("strength", "")).strip(),
            dosage_form=str(row.get("dosage_form", "")).strip(),
            dose=str(row.get("dose", "")).strip(),
            route=row.get("route") or DoseRoute.ORAL,
            frequency=row.get("frequency") or Frequency.BD,
            duration_days=row.get("duration_days") or None,
            is_prn=bool(row.get("is_prn")),
            prn_indication=str(row.get("prn_indication", "")).strip(),
            instructions=str(row.get("instructions", "")).strip(),
            quantity=row.get("quantity") or None,
            quantity_unit=str(row.get("quantity_unit", "")).strip(),
            display_order=position,
        )
        try:
            line.clean()
        except Exception as invalid:  # noqa: BLE001 — surfaced as a domain error
            raise TemplateError(
                f"{line.generic_name or 'A line'}: "
                + "; ".join(
                    message
                    for messages in getattr(invalid, "message_dict", {}).values()
                    for message in messages
                ) or str(invalid),
            ) from invalid
        line.save()

    record(
        AuditAction.UPDATE if uuid else AuditAction.CREATE,
        entity_type="prescriptions.PrescriptionTemplate",
        entity_id=template.uuid,
        entity_label=f"{template.name} ({'shared' if template.is_shared else 'personal'})",
        metadata={"lines": len(lines)},
    )
    return template


def _assert_may_edit(template: PrescriptionTemplate, user, may_curate: bool) -> None:
    if template.is_shared:
        if not may_curate:
            raise TemplateError(
                "This is a shared template. Changing it changes what every "
                "prescriber here is offered.",
                code="not_yours_to_edit",
            )
        return
    if template.owner_id != getattr(user, "uuid", None):
        # Not "forbidden": as far as this prescriber is concerned somebody
        # else's personal template does not exist.
        raise TemplateError("That template no longer exists.", code="not_found")


@transaction.atomic
def retire(template: PrescriptionTemplate, user, may_curate: bool = False) -> None:
    """Templates are deactivated, never deleted: what was prescribed from one
    is history, and the name in the audit trail has to keep meaning something."""
    _assert_may_edit(template, user, may_curate)
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])
    record(
        AuditAction.DELETE,
        entity_type="prescriptions.PrescriptionTemplate",
        entity_id=template.uuid,
        entity_label=template.name,
    )


@transaction.atomic
def apply(template: PrescriptionTemplate, user) -> dict:
    """The lines this template offers, and a note of its use.

    **Nothing is prescribed here.** The caller puts these on the prescribing
    form; the prescriber edits, the safety checks run, and only signing writes
    a prescription. The use is counted so that the list can be ordered by what
    people reach for, which after a fortnight beats any curation.
    """
    PrescriptionTemplate.objects.filter(pk=template.pk).update(
        times_used=F("times_used") + 1, last_used_at=timezone.now(),
    )
    payload = describe(template)
    payload["times_used"] += 1
    return payload
