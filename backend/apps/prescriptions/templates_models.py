"""Prescription templates: the same script, written once.

A doctor in an outpatient clinic writes "Amoxicillin 500 mg, 1 capsule three
times daily for five days, after food" perhaps forty times in a morning, and
until now typed every one of them. That is not only slow: a line typed forty
times is forty chances to write 5 mg for 500, or to leave the duration off and
send somebody home with an open-ended course of an antibiotic.

**A template is a starting point, never a prescription.** Applying one returns
lines onto the screen for the prescriber to change, check and sign. Nothing is
written to a patient's record by choosing a template, and the safety checks
that run on a prescription run on the result exactly as if it had been typed —
because from that point on it *was*.

**Two owners, deliberately.** An organization's templates are its formulary
habits, edited by whoever curates them; a clinician's own are their practice,
and nobody else sees them. Anything else — a per-department layer, say — can
be added later, but "mine" and "ours" is the distinction people actually
articulate.

**The quantity is computed, not typed.** Dose times doses-a-day times days is
arithmetic a person should not be repeating, and `DOSES_PER_DAY` already
carries the frequencies it can be computed for. For PRN and "other", where it
cannot be, the template carries the number somebody decided.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import BaseModel
from apps.organization.models import Department
from apps.prescriptions.models import DOSES_PER_DAY, DoseRoute, Frequency


class PrescriptionTemplate(BaseModel):
    """A named set of lines a prescriber applies and then edits."""

    name = models.CharField(max_length=128, db_index=True)
    #: What it is for, in the words a clinician would search by: "Adult URTI",
    #: "Post-extraction, penicillin allergy".
    description = models.CharField(max_length=255, blank=True)

    #: Whose it is. `None` means the organization's own, visible to every
    #: prescriber; a uuid means one clinician's, visible only to them.
    owner_id = models.UUIDField(null=True, blank=True, db_index=True)
    owner_name = models.CharField(max_length=255, blank=True)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="prescription_templates",
    )

    #: Free text the searcher might type: "cough", "dental", "paediatric".
    tags = models.JSONField(default=list, blank=True)
    #: Advice printed for the patient with anything this template produces.
    patient_instructions = models.TextField(blank=True)

    #: Counted, not guessed: the list is ordered by what people actually use,
    #: which after a fortnight is a better ranking than any curation.
    times_used = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prescription_template"
        ordering = ["-times_used", "name"]
        indexes = [
            models.Index(fields=["owner_id", "is_active"]),
            models.Index(fields=["-times_used"]),
        ]

    def __str__(self):
        return self.name

    @property
    def is_shared(self) -> bool:
        return self.owner_id is None


class PrescriptionTemplateLine(BaseModel):
    """One medicine in a template, in the same vocabulary as a real line."""

    template = models.ForeignKey(
        PrescriptionTemplate, on_delete=models.CASCADE, related_name="lines",
    )

    #: The catalogue item, when there is one. Kept as a uuid rather than a
    #: foreign key for the same reason `PrescriptionLine` does: a prescription
    #: names a medicine, and a product that is later delisted must not take
    #: the history of what was prescribed with it.
    product_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    generic_name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=255, blank=True)
    strength = models.CharField(max_length=64, blank=True)
    dosage_form = models.CharField(max_length=32, blank=True)

    dose = models.CharField(max_length=64, help_text="e.g. 1 tablet, 5 ml")
    route = models.CharField(max_length=16, choices=DoseRoute.choices, default=DoseRoute.ORAL)
    frequency = models.CharField(max_length=8, choices=Frequency.choices, default=Frequency.BD)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)

    is_prn = models.BooleanField(default=False)
    prn_indication = models.CharField(max_length=255, blank=True)

    #: How to take it, in the words the patient reads: "after food", "with a
    #: full glass of water". The Latin stays in `frequency`.
    instructions = models.CharField(max_length=255, blank=True)

    #: Left blank where it can be computed from dose, frequency and duration;
    #: set where it cannot (PRN, "other"), because a prescription with no
    #: quantity is one the pharmacy has to ring back about.
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    quantity_unit = models.CharField(max_length=32, blank=True)

    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "prescription_template_line"
        ordering = ["display_order", "id"]

    def __str__(self):
        return f"{self.generic_name} {self.strength} {self.frequency}"

    def clean(self):
        if not self.generic_name.strip():
            raise ValidationError({"generic_name": "A line needs a medicine."})
        # **The vocabulary, checked here.** A `CharField` with `choices` does
        # not validate on save, so a template saved with `route="oral"` —
        # which is the word, not the code — stored happily and was then
        # rejected by the prescribing form's own safety check, at the moment a
        # doctor tried to use it. Found by applying a template in the running
        # app and watching the preview 400.
        if self.route not in DoseRoute.values:
            raise ValidationError({
                "route": f"'{self.route}' is not a route. Use one of: "
                         + ", ".join(DoseRoute.values),
            })
        if self.frequency not in Frequency.values:
            raise ValidationError({
                "frequency": f"'{self.frequency}' is not a frequency. Use one of: "
                             + ", ".join(Frequency.values),
            })
        if self.is_prn and not self.prn_indication.strip():
            raise ValidationError({
                "prn_indication": "A when-required medicine needs to say when.",
            })
        if self.quantity is None and self.suggested_quantity() is None:
            raise ValidationError({
                "quantity": (
                    "This frequency cannot have its quantity computed, so the "
                    "template has to carry one."
                ),
            })

    def suggested_quantity(self) -> Decimal | None:
        """Units to dispense, or `None` when it cannot honestly be computed.

        The dose is free text because "1 tablet", "5 ml" and "2 puffs" are all
        real; the leading number is what multiplies. A dose with no number in
        it ("apply sparingly") returns nothing rather than a guess.
        """
        per_day = DOSES_PER_DAY.get(self.frequency)
        if per_day is None or not self.duration_days:
            return None
        import re

        match = re.match(r"\s*(\d+(?:\.\d+)?)", self.dose or "")
        if not match:
            return None
        units = Decimal(match.group(1)) * Decimal(str(per_day)) * self.duration_days
        return units.quantize(Decimal("0.01"))
