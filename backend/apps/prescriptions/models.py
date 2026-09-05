"""Prescriptions: what was prescribed, by whom, and what changed since.

Two properties drive every decision in this module.

**Nothing is overwritten.** A prescription is a clinical instruction and a
legal record. Changing a dose creates a new version and supersedes the old
one; stopping a drug records a reason and a time. "What were they taking on
the 14th?" must be answerable years later, and it cannot be if edits mutate
rows in place.

**The medicine is denormalised onto the line.** A prescription line stores the
drug's name, strength and form as text *as well as* a pointer to the catalogue
entry. The catalogue does not exist yet (it arrives with the pharmacy module),
and even once it does, a product can be renamed, reformulated or withdrawn —
none of which may retrospectively change what a doctor actually wrote.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient


class PrescriptionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    #: Replaced by a newer version of the same prescription.
    SUPERSEDED = "superseded", "Superseded"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class Prescription(BaseModel):
    """A set of medicines prescribed together, on one occasion.

    Grouped rather than stored as loose lines because a prescription is signed
    as a whole: the doctor takes responsibility for the combination, not for
    each drug in isolation. Interaction checking only makes sense against the
    set.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="prescriptions"
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="prescriptions",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="prescriptions"
    )

    prescriber_id = models.UUIDField(null=True, blank=True, db_index=True)
    prescriber_name = models.CharField(max_length=255, blank=True)
    #: The prescriber's council registration. Printed on the prescription and
    #: required for it to be dispensed legally.
    prescriber_registration = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=16,
        choices=PrescriptionStatus.choices,
        default=PrescriptionStatus.DRAFT,
        db_index=True,
    )
    prescribed_at = models.DateTimeField(default=timezone.now, db_index=True)
    #: Beyond this date the prescription may no longer be dispensed. Nepal has
    #: no single statutory validity period, so it is set per prescription.
    valid_until = models.DateField(null=True, blank=True)

    #: Versioning. A change produces a new row pointing back at the old one,
    #: which is marked superseded.
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    revision_reason = models.TextField(blank=True)

    #: Warnings raised at the time of prescribing, and what the prescriber did
    #: about them. Kept verbatim: if a doctor overrode an allergy alert, the
    #: record must show that the alert fired and that they saw it.
    safety_checks = models.JSONField(default=dict, blank=True)
    has_overridden_warning = models.BooleanField(default=False)
    override_reason = models.TextField(blank=True)

    is_signed = models.BooleanField(default=False)
    signed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)
    #: Advice for the patient, printed on the prescription in their language.
    patient_instructions = models.TextField(blank=True)

    class Meta:
        db_table = "prescription"
        ordering = ["-prescribed_at"]
        indexes = [
            models.Index(fields=["patient", "-prescribed_at"]),
            models.Index(fields=["status", "-prescribed_at"]),
            models.Index(fields=["prescriber_id", "-prescribed_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.full_name}"

    @property
    def is_dispensable(self) -> bool:
        """Whether a pharmacy may act on this prescription."""
        if self.status != PrescriptionStatus.ACTIVE or not self.is_signed:
            return False
        if self.valid_until and self.valid_until < timezone.localdate():
            return False
        return True

    @property
    def is_editable(self) -> bool:
        """A signed prescription is revised, never edited."""
        return not self.is_signed


class DoseRoute(models.TextChoices):
    """How the medicine is taken. Abbreviations are the ones used on charts."""

    ORAL = "PO", "By mouth"
    SUBLINGUAL = "SL", "Sublingual"
    INTRAVENOUS = "IV", "Intravenous"
    INTRAMUSCULAR = "IM", "Intramuscular"
    SUBCUTANEOUS = "SC", "Subcutaneous"
    TOPICAL = "TOP", "Topical"
    INHALED = "INH", "Inhaled"
    NEBULISED = "NEB", "Nebulised"
    RECTAL = "PR", "Rectal"
    VAGINAL = "PV", "Vaginal"
    OPHTHALMIC = "OPH", "Into the eye"
    OTIC = "OT", "Into the ear"
    NASAL = "NAS", "Nasal"
    INTRATHECAL = "IT", "Intrathecal"
    OTHER = "OTH", "Other"


class Frequency(models.TextChoices):
    """Dosing frequencies as they are actually written in Nepal.

    Latin abbreviations are kept because that is what appears on charts and
    what pharmacists read, but every one carries a plain-English label so the
    patient-facing print-out and the mobile app can be unambiguous.
    """

    OD = "OD", "Once daily"
    BD = "BD", "Twice daily"
    TDS = "TDS", "Three times daily"
    QDS = "QDS", "Four times daily"
    QID = "QID", "Four times daily"
    NOCTE = "NOCTE", "At night"
    MANE = "MANE", "In the morning"
    STAT = "STAT", "Immediately, once"
    PRN = "PRN", "As required"
    Q4H = "Q4H", "Every 4 hours"
    Q6H = "Q6H", "Every 6 hours"
    Q8H = "Q8H", "Every 8 hours"
    Q12H = "Q12H", "Every 12 hours"
    WEEKLY = "WEEKLY", "Once weekly"
    ALTERNATE = "ALT", "On alternate days"
    OTHER = "OTHER", "Other — see instructions"


#: Approximate doses per day, used to estimate the quantity to dispense.
#: Deliberately absent for PRN and OTHER: those cannot be computed, and
#: guessing would put a wrong number on a prescription.
DOSES_PER_DAY = {
    Frequency.OD: 1, Frequency.BD: 2, Frequency.TDS: 3, Frequency.QDS: 4,
    Frequency.QID: 4, Frequency.NOCTE: 1, Frequency.MANE: 1,
    Frequency.Q4H: 6, Frequency.Q6H: 4, Frequency.Q8H: 3, Frequency.Q12H: 2,
    Frequency.WEEKLY: 1 / 7, Frequency.ALTERNATE: 0.5,
}


class PrescriptionLineStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Course completed"
    DISCONTINUED = "discontinued", "Discontinued"
    SUBSTITUTED = "substituted", "Substituted"
    ON_HOLD = "on_hold", "On hold"


class PrescriptionLine(BaseModel):
    """One medicine on a prescription."""

    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="lines"
    )

    # -- what was prescribed ---------------------------------------------
    #
    # Held as text as well as a catalogue pointer. The text is what the doctor
    # wrote and must never change; the pointer is for stock, pricing and
    # interaction checking once the pharmacy catalogue exists.

    #: Pointer to the future pharmacy product. A UUID, not a foreign key,
    #: because that table does not exist yet.
    product_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    generic_name = models.CharField(max_length=255, db_index=True)
    brand_name = models.CharField(max_length=255, blank=True)
    strength = models.CharField(max_length=64, blank=True, help_text="e.g. 500 mg")
    dosage_form = models.CharField(
        max_length=64, blank=True, help_text="Tablet, syrup, injection…"
    )

    # -- how to take it ---------------------------------------------------

    dose = models.CharField(max_length=64, help_text="e.g. 1 tablet, 5 ml")
    route = models.CharField(
        max_length=8, choices=DoseRoute.choices, default=DoseRoute.ORAL
    )
    frequency = models.CharField(
        max_length=8, choices=Frequency.choices, default=Frequency.BD
    )
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)

    #: PRN medicines need a trigger. "Paracetamol as required" without saying
    #: what for is not a usable instruction.
    is_prn = models.BooleanField(default=False)
    prn_indication = models.CharField(max_length=255, blank=True)
    max_doses_per_day = models.PositiveSmallIntegerField(null=True, blank=True)

    instructions = models.CharField(
        max_length=512, blank=True, help_text="e.g. after food, with water"
    )

    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    quantity_unit = models.CharField(max_length=32, blank=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=PrescriptionLineStatus.choices,
        default=PrescriptionLineStatus.ACTIVE,
        db_index=True,
    )
    discontinued_at = models.DateTimeField(null=True, blank=True)
    discontinued_by_id = models.UUIDField(null=True, blank=True)
    discontinuation_reason = models.CharField(max_length=512, blank=True)

    #: Whether the pharmacy may dispense an equivalent generic. Some
    #: prescriptions are brand-specific for clinical reasons (narrow
    #: therapeutic index drugs), so this is the prescriber's decision.
    allow_substitution = models.BooleanField(default=True)

    #: Warnings specific to this line: an allergy match, an interaction with
    #: another line, a dose outside the usual range.
    warnings = models.JSONField(default=list, blank=True)

    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "prescription_line"
        ordering = ["display_order", "generic_name"]
        indexes = [
            models.Index(fields=["prescription", "status"]),
            models.Index(fields=["generic_name"]),
        ]

    def __str__(self):
        parts = [self.generic_name, self.strength, self.dose, self.frequency]
        return " ".join(part for part in parts if part)

    @property
    def display_name(self) -> str:
        """What a pharmacist reads. Brand in parentheses when present."""
        base = f"{self.generic_name} {self.strength}".strip()
        return f"{base} ({self.brand_name})" if self.brand_name else base

    @property
    def sig(self) -> str:
        """The dosing instruction in one line, as printed."""
        parts = [self.dose, self.get_route_display(), self.get_frequency_display()]
        if self.duration_days:
            parts.append(f"for {self.duration_days} days")
        if self.is_prn and self.prn_indication:
            parts.append(f"as required for {self.prn_indication}")
        if self.instructions:
            parts.append(f"({self.instructions})")
        return ", ".join(part for part in parts if part)

    def suggested_quantity(self) -> float | None:
        """Total units for the course, where it can be computed.

        Returns `None` for PRN and irregular frequencies rather than guessing.
        A wrong number on a prescription is worse than no number: the
        pharmacist would dispense it.
        """
        if self.is_prn or not self.duration_days:
            return None
        per_day = DOSES_PER_DAY.get(self.frequency)
        if per_day is None:
            return None

        # Extract the leading number from a dose like "1 tablet" or "2.5 ml".
        # Anything more elaborate ("1-2 tablets") is left to the prescriber.
        import re

        match = re.match(r"^\s*(\d+(?:\.\d+)?)", self.dose or "")
        if not match:
            return None
        return round(float(match.group(1)) * per_day * self.duration_days, 2)

    def clean(self):
        if self.is_prn and not self.prn_indication:
            raise ValidationError(
                {
                    "prn_indication":
                        "An as-required medicine must say what it is required for."
                }
            )
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "A course cannot end before it starts."}
            )


class PrescriptionPresentation(BaseModel):
    """A prescription handed over at a pharmacy counter.

    The missing half of the browse-versus-lookup design. `Prescription.facility`
    records where a prescription was **written**, and a patient may take it to
    any pharmacy -- that is what a prescription is -- so nothing in the system
    knew which pharmacy was holding one.

    The consequence was concrete: with the relationship check on, a pharmacist
    browsed an **empty list**. Correct for dispensing against a reference
    somebody hands you, and useless for the ordinary question *"what is waiting
    to be dispensed here?"*

    So the act of presenting is recorded as a fact rather than inferred from a
    filter. It is the same reasoning as everywhere else in this project: what
    happened is a row, and what is true now is derived from the rows.

    **This is a care relationship.** A patient who walks into a pharmacy and
    hands over a prescription has chosen that pharmacy and consented to it
    being read. Recording the moment is what lets the relationship outlive the
    single request that created it -- otherwise the prescription vanishes from
    the counter's screen the instant they navigate away from it.
    """

    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="presentations",
    )
    #: Where it was handed over -- which is the point, and is usually *not*
    #: `prescription.facility`.
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="presented_prescriptions",
    )

    presented_at = models.DateTimeField(default=timezone.now, db_index=True)
    presented_to_id = models.UUIDField(null=True, blank=True, db_index=True)
    presented_to_name = models.CharField(max_length=255, blank=True)

    #: Cleared when the prescription is dispensed or the patient takes it
    #: elsewhere. Separate from the prescription's own status, because "this
    #: pharmacy is holding it" and "it has been dispensed somewhere" are
    #: different facts -- the recurring rule in this project.
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "prescription_presentation"
        ordering = ["-presented_at"]
        indexes = [
            models.Index(fields=["facility", "is_active", "-presented_at"]),
            models.Index(fields=["prescription", "is_active"]),
        ]
        constraints = [
            # One live presentation per prescription per pharmacy. Presenting
            # the same prescription twice at the same counter is one patient
            # standing there, not two.
            models.UniqueConstraint(
                fields=["prescription", "facility"],
                condition=models.Q(is_active=True, deleted_at__isnull=True),
                name="uniq_live_presentation_per_pharmacy",
            ),
        ]

    def __str__(self):
        return f"{self.prescription.reference} @ {self.facility.code}"
