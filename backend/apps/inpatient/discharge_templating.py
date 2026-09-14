"""Discharge templates: the same going-home, written well once.

A ward discharges the same few conditions over and over -- pneumonia, typhoid,
a urinary infection with sepsis, a normal delivery -- and until now every
summary was typed from nothing at the moment a family was waiting at the door.
What that produced was three lines of course, "advice given", and one generic
sentence about coming back if unwell, handed to somebody who will read it at
home with nobody to ask.

**A template is a starting point, never a summary.** Applying one returns the
text for the form; the clinician edits what happened to *this* patient, and
only discharging writes anything. Blanks the template cannot know -- the day
the fever settled, what the X-ray showed -- are left as blanks to fill.

**Written for two readers.** The course is for the next clinician. The advice,
diet, activity and warning signs are for the patient and whoever looks after
them, in plain words, because that half of the sheet is read in a kitchen.

**Warning signs are specific.** "Come back if unwell" tells nobody anything. A
typhoid discharge says a hard, swollen belly; a delivery says soaking a pad in
an hour. They are a list, printed as a list.

Mine and ours, as with prescription templates: everyone discharging sees the
organization's and their own; sharing or editing a shared one needs
`catalog.manage`.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.common.exceptions import DomainError
from apps.inpatient.models import DischargeTemplate

MAX_WARNING_SIGNS = 12


class TemplateError(DomainError):
    code = "template_refused"


def visible_to(user) -> QuerySet:
    """The organization's templates, plus this clinician's own."""
    return DischargeTemplate.objects.filter(is_active=True).filter(
        Q(owner_id__isnull=True) | Q(owner_id=getattr(user, "uuid", None)),
    )


def describe(template: DischargeTemplate) -> dict:
    return {
        "uuid": str(template.uuid),
        "name": template.name,
        "diagnosis": template.diagnosis,
        "shared": template.is_shared,
        "owner_name": template.owner_name,
        "course": template.course,
        "advice": template.advice,
        "diet": template.diet,
        "activity": template.activity,
        "warning_signs": list(template.warning_signs or []),
        "follow_up_days": template.follow_up_days,
        "times_used": template.times_used,
    }


def clean_warning_signs(signs) -> list:
    """Non-empty lines, trimmed, at most twelve: a list somebody will read."""
    cleaned = [str(sign).strip() for sign in (signs or []) if str(sign).strip()]
    return cleaned[:MAX_WARNING_SIGNS]


@transaction.atomic
def save_template(*, user, data: dict, uuid=None, shared: bool = False,
                  may_curate: bool = False) -> DischargeTemplate:
    name = str(data.get("name", "")).strip()
    if not name:
        raise TemplateError("A template needs a name.")
    signs = clean_warning_signs(data.get("warning_signs"))
    if not (str(data.get("course", "")).strip() or str(data.get("advice", "")).strip() or signs):
        raise TemplateError(
            "A discharge template needs a course, advice or warning signs -- "
            "otherwise there is nothing in it to start from.",
        )
    days = data.get("follow_up_days")
    if days in ("", None):
        days = None
    else:
        try:
            days = int(days)
        except (TypeError, ValueError) as invalid:
            raise TemplateError("Follow-up must be a number of days.") from invalid
        if not 0 <= days <= 365:
            raise TemplateError("Follow-up must be within a year.")
    if shared and not may_curate:
        raise TemplateError(
            "Shared templates are what every clinician here is offered. Save "
            "this as your own, or ask somebody who curates the catalogue.",
            code="not_yours_to_share",
        )

    if uuid:
        template = DischargeTemplate.objects.filter(uuid=uuid).first()
        if template is None:
            raise TemplateError("That template no longer exists.", code="not_found")
        _assert_may_edit(template, user, may_curate)
    else:
        template = DischargeTemplate()

    template.name = name
    template.diagnosis = str(data.get("diagnosis", "")).strip()
    template.course = str(data.get("course", "")).strip()
    template.advice = str(data.get("advice", "")).strip()
    template.diet = str(data.get("diet", "")).strip()
    template.activity = str(data.get("activity", "")).strip()
    template.warning_signs = signs
    template.follow_up_days = days
    template.owner_id = None if shared else getattr(user, "uuid", None)
    template.owner_name = "" if shared else (getattr(user, "full_name", "") or "")
    template.save()

    record(
        AuditAction.UPDATE if uuid else AuditAction.CREATE,
        entity_type="inpatient.DischargeTemplate",
        entity_id=template.uuid,
        entity_label=f"{template.name} ({'shared' if template.is_shared else 'personal'})",
    )
    return template


def _assert_may_edit(template: DischargeTemplate, user, may_curate: bool) -> None:
    if template.is_shared:
        if not may_curate:
            raise TemplateError(
                "This is a shared template. Changing it changes what every "
                "clinician here is offered.",
                code="not_yours_to_edit",
            )
        return
    if template.owner_id != getattr(user, "uuid", None):
        raise TemplateError("That template no longer exists.", code="not_found")


@transaction.atomic
def retire(template: DischargeTemplate, user, may_curate: bool = False) -> None:
    _assert_may_edit(template, user, may_curate)
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])
    record(
        AuditAction.DELETE,
        entity_type="inpatient.DischargeTemplate",
        entity_id=template.uuid,
        entity_label=template.name,
    )


@transaction.atomic
def apply(template: DischargeTemplate, user, today=None) -> dict:
    """The text for the discharge form, with the follow-up turned into a date.

    Nothing is written to the admission. The use is counted so the list can be
    ordered by what people reach for.
    """
    DischargeTemplate.objects.filter(pk=template.pk).update(
        times_used=F("times_used") + 1, last_used_at=timezone.now(),
    )
    payload = describe(template)
    payload["times_used"] += 1
    today = today or timezone.localdate()
    payload["follow_up_on"] = (
        (today + timedelta(days=template.follow_up_days)).isoformat()
        if template.follow_up_days
        else None
    )
    return payload
