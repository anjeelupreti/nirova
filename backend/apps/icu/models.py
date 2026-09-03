"""Intensive care: the ward where the chart *is* the treatment.

Everywhere else in this system a clinical record documents what was decided.
In intensive care the record is the instrument: the noradrenaline rate is
changed because the last blood pressure was 78, and the next blood pressure is
the reason it is changed again. A chart that stores only "current" values
describes a patient who has no history, and every question intensive care
actually asks — why did the pressure fall, how much fluid is this patient up
over three days, how many ventilator days does this unit have — is a question
about history.

Six decisions follow from that, and each one is a place where the obvious
design is wrong.

**An ICU stay is an interval, not a flag on the admission.** A patient goes
ward → ICU → ward → ICU. Each ICU episode has its own severity, its own
ventilator days and its own outcome, and a `patient.in_icu` boolean can hold
none of them. This is the same error the bed board made before beds became
intervals, and the same error the employment history made before it became
append-only.

**Observations append. Nothing is edited.** A vital sign is an event with a
time. A "current vitals" row that gets updated is a patient with no trend, and
the trend is the whole of critical care.

**A rate change is an event, not an edit.** Titratable drugs change every few
minutes; overwriting the rate destroys the dose history that explains the
blood pressure. Volume infused is computed from the rate history, never stored
as a counter — the same rule as the stock ledger.

**Set is not measured.** A ventilator's set tidal volume and its delivered
tidal volume are different numbers, and the gap between them is a leak or a
stiff lung. A schema with one `tidal_volume` field hides the only thing worth
looking at.

**Missing is not normal.** A SOFA score computed without a bilirubin is not a
score with a normal bilirubin. Scoring here records which components were
missing and refuses to silently treat absence as health, because the direction
of that error is always to understate how sick somebody is.

**A device reading is not a validated reading.** Numbers pulled from a monitor
arrive faster and less reliably than a nurse's chart — an arterial line flushes
and reads 300/150. They are stored, marked as device-sourced, and remain
unvalidated until a person says otherwise. Scores and alerts say which kind
they used.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# `BaseModel` gives every row a UUID, created/updated stamps and the
# soft-delete behaviour the audit trail depends on. Published identifiers are
# UUIDs throughout, never integer PKs -- with a database per tenant, `id` 42
# means a different row in every customer's database.
from apps.common.models import BaseModel

# The ICU does not own beds, patients or admissions. It borrows the ward's.
# An ICU bed that is not a `Bed` would need its own occupancy, its own
# cleaning state and its own daily rate, and the census would then have to add
# up two incompatible bed boards.
from apps.inpatient.models import Admission, Bed, Ward
from apps.organization.models import Facility
from apps.patients.models import Patient

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# The stay
# ---------------------------------------------------------------------------


class IcuOutcome(models.TextChoices):
    """How the ICU episode ended.

    Discharge to a ward and death in the unit are the two that matter for
    mortality; the rest exist so that neither of those two absorbs cases that
    are not really theirs. A patient transferred to another hospital's ICU has
    an unknown outcome, and counting them as a survivor flatters the unit.
    """

    ONGOING = "ongoing", "Still in the unit"
    TO_WARD = "to_ward", "Stepped down to a ward"
    TO_HDU = "to_hdu", "Stepped down to HDU"
    TO_THEATRE = "to_theatre", "To theatre"
    TRANSFERRED_OUT = "transferred_out", "Transferred to another hospital"
    DIED = "died", "Died in the unit"
    #: Left against advice, or the family withdrew care and took them home.
    #: Common in Nepal, and invisible if folded into "died" or "discharged".
    LAMA = "lama", "Left against medical advice"


class AdmissionRoute(models.TextChoices):
    """Where the patient came from. Drives the expected mortality baseline."""

    EMERGENCY = "emergency", "Emergency department"
    WARD = "ward", "Deterioration on a ward"
    THEATRE = "theatre", "Post-operative"
    ANOTHER_HOSPITAL = "referral", "Referred from another hospital"
    DIRECT = "direct", "Direct admission"


class IcuStay(BaseModel):
    """One episode of intensive care within an admission.

    Separate from `Admission` because a single hospital stay can contain
    several ICU episodes, and each has its own severity, its own support days
    and its own outcome. Folding them into the admission would make "ICU
    length of stay" the length of the *hospital* stay, which is a different
    and much larger number.
    """

    admission = models.ForeignKey(
        Admission, on_delete=models.CASCADE, related_name="icu_stays",
    )
    #: Denormalised so the unit board can be drawn without joining through
    #: the admission on every row. Set once at admission and never changed.
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="icu_stays",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="icu_stays",
    )
    #: The ICU ward itself, so a hospital can run several units (general,
    #: cardiac, neonatal) with their own boards and their own numbers.
    ward = models.ForeignKey(
        Ward, on_delete=models.PROTECT, related_name="icu_stays",
    )
    bed = models.ForeignKey(
        Bed, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="icu_stays",
    )

    admitted_at = models.DateTimeField(default=timezone.now, db_index=True)
    discharged_at = models.DateTimeField(null=True, blank=True, db_index=True)

    route = models.CharField(
        max_length=16, choices=AdmissionRoute.choices,
        default=AdmissionRoute.WARD,
    )
    reason = models.CharField(max_length=512)
    primary_diagnosis = models.CharField(max_length=512, blank=True)

    consultant_id = models.UUIDField(null=True, blank=True)
    consultant_name = models.CharField(max_length=255, blank=True)

    #: Weight and height, recorded on the stay rather than looked up from the
    #: patient record. Two reasons. Vasopressors are dosed in mcg/kg/min, and
    #: a dose computed from a weight recorded two years ago is a dosing error.
    #: And urine output is judged in ml/kg/hr — without a weight the number
    #: cannot be computed, and assuming 70kg is exactly how a child's oliguria
    #: gets missed. Both are nullable, and everything that needs them returns
    #: nothing rather than guessing.
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
    )
    height_cm = models.PositiveSmallIntegerField(null=True, blank=True)

    outcome = models.CharField(
        max_length=20, choices=IcuOutcome.choices, default=IcuOutcome.ONGOING,
        db_index=True,
    )
    outcome_notes = models.TextField(blank=True)

    #: Severity on admission, recorded once. APACHE II is calculated from the
    #: worst values in the first 24 hours and is meaningless afterwards, so it
    #: lives on the stay rather than being recomputed daily like SOFA.
    apache_ii = models.PositiveSmallIntegerField(null=True, blank=True)
    apache_ii_components = models.JSONField(default=dict, blank=True)

    #: Resuscitation status. Recorded because it changes what an alert means:
    #: a falling blood pressure in a patient not for escalation is not a call
    #: for the arrest team, and a system that pages anyway teaches staff to
    #: ignore pages.
    is_for_resuscitation = models.BooleanField(default=True)
    ceiling_of_care = models.CharField(
        max_length=255, blank=True,
        help_text="What treatment this patient is, and is not, for.",
    )
    ceiling_set_by = models.CharField(max_length=255, blank=True)
    ceiling_set_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-admitted_at"]
        indexes = [
            models.Index(fields=["ward", "outcome"]),
            models.Index(fields=["facility", "admitted_at"]),
        ]
        constraints = [
            #: A discharge before the admission is a data-entry slip that
            #: silently produces negative length of stay, which then averages
            #: into the unit's statistics.
            models.CheckConstraint(
                condition=models.Q(discharged_at__isnull=True)
                | models.Q(discharged_at__gte=models.F("admitted_at")),
                name="icu_stay_discharge_after_admission",
            ),
            #: A stay is open or it is finished. "Ongoing" with a discharge
            #: time, or finished without one, is a row no query can classify.
            models.CheckConstraint(
                condition=(
                    models.Q(outcome=IcuOutcome.ONGOING, discharged_at__isnull=True)
                    | ~models.Q(outcome=IcuOutcome.ONGOING)
                    & models.Q(discharged_at__isnull=False)
                ),
                name="icu_stay_outcome_matches_discharge",
            ),
        ]

    def __str__(self):
        return f"ICU {self.patient_id} from {self.admitted_at:%Y-%m-%d %H:%M}"

    @property
    def is_current(self) -> bool:
        return self.outcome == IcuOutcome.ONGOING

    @property
    def hours(self) -> Decimal:
        """Length of stay in hours.

        Hours rather than days because ICU stays are frequently under 24 and
        rounding them to "1 day" makes a short post-operative observation look
        the same as a night of resuscitation.
        """
        end = self.discharged_at or timezone.now()
        return (Decimal((end - self.admitted_at).total_seconds()) / 3600).quantize(
            Decimal("0.1")
        )


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


class ObservationSource(models.TextChoices):
    """Who or what produced the number.

    The distinction is not bookkeeping. A monitor reports an arterial line
    reading 300/150 while it is being flushed; a nurse does not chart that. A
    score built from unvalidated device data is a score built on artefact, so
    every consumer of these rows is told where each number came from.
    """

    MANUAL = "manual", "Charted by a nurse"
    DEVICE = "device", "Read from a monitor"
    CALCULATED = "calculated", "Derived from other values"


class Observation(BaseModel):
    """One set of vital signs at one moment. Append-only.

    Stored as a row per time-point rather than a row per measurement, because
    the clinical unit is the observation round: a heart rate of 130 means
    something different beside a blood pressure of 70 than beside one of 140,
    and splitting them into separate rows makes every query re-assemble them
    by timestamp.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="observations",
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    source = models.CharField(
        max_length=12, choices=ObservationSource.choices,
        default=ObservationSource.MANUAL,
    )
    #: Which monitor, if any. A run of impossible values is usually one
    #: device, and without this nobody can tell which.
    device_identifier = models.CharField(max_length=64, blank=True)

    #: Device readings are unvalidated until a person confirms them. Nothing
    #: is deleted -- validation is an additional fact, not a filter.
    validated_by_id = models.UUIDField(null=True, blank=True)
    validated_by_name = models.CharField(max_length=255, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)

    heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Mean arterial pressure. Stored rather than always derived because an
    #: arterial line measures it directly, and the measured value is not the
    #: same as (S + 2D)/3.
    mean_arterial_pressure = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    #: Glasgow Coma Scale, split into its three parts. A total of 10 built
    #: from E4V1M5 and one built from E2V4M4 describe different patients, and
    #: the parts are what a neurosurgeon asks for.
    gcs_eye = models.PositiveSmallIntegerField(null=True, blank=True)
    gcs_verbal = models.PositiveSmallIntegerField(null=True, blank=True)
    gcs_motor = models.PositiveSmallIntegerField(null=True, blank=True)
    #: True when the patient is intubated: the verbal score cannot be tested,
    #: and recording 1 without this makes a sedated patient look moribund.
    gcs_verbal_not_testable = models.BooleanField(default=False)

    pupil_left_mm = models.PositiveSmallIntegerField(null=True, blank=True)
    pupil_right_mm = models.PositiveSmallIntegerField(null=True, blank=True)
    pupils_reactive = models.BooleanField(null=True, blank=True)

    #: Richmond Agitation-Sedation Scale, -5 (unrousable) to +4 (combative).
    #: Signed, so a small integer field would be wrong.
    rass = models.SmallIntegerField(null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)

    blood_glucose = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    lactate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["stay", "-recorded_at"])]

    def __str__(self):
        return f"obs {self.recorded_at:%H:%M}"

    @property
    def gcs_total(self) -> int | None:
        """The GCS total, or None when a part is missing.

        Deliberately returns None rather than summing what is present. A
        partial GCS added up is a smaller number, which reads as a sicker
        patient, and the whole point of this module is that missing is not a
        value.
        """
        parts = [self.gcs_eye, self.gcs_motor]
        verbal = 1 if self.gcs_verbal_not_testable else self.gcs_verbal
        parts.append(verbal)
        if any(part is None for part in parts):
            return None
        return sum(parts)

    @property
    def map_value(self) -> int | None:
        """Measured MAP if there is one, otherwise the estimate."""
        if self.mean_arterial_pressure:
            return self.mean_arterial_pressure
        if self.systolic and self.diastolic:
            return round((self.systolic + 2 * self.diastolic) / 3)
        return None

    @property
    def is_validated(self) -> bool:
        return (
            self.source != ObservationSource.DEVICE
            or self.validated_at is not None
        )


# ---------------------------------------------------------------------------
# Fluid balance
# ---------------------------------------------------------------------------


class FluidDirection(models.TextChoices):
    IN = "in", "In"
    OUT = "out", "Out"


class FluidRoute(models.TextChoices):
    """Enumerated because the balance is read by route, not only in total.

    Two litres positive from maintenance fluid and two litres positive because
    the patient is not passing urine are the same number and opposite
    problems.
    """

    IV = "iv", "Intravenous"
    ORAL = "oral", "Oral"
    NASOGASTRIC = "ng", "Nasogastric"
    BLOOD = "blood", "Blood product"
    FLUSH = "flush", "Line flush"
    URINE = "urine", "Urine"
    DRAIN = "drain", "Drain"
    NG_ASPIRATE = "ng_aspirate", "Nasogastric aspirate"
    VOMIT = "vomit", "Vomit"
    STOOL = "stool", "Stool"
    BLOOD_LOSS = "blood_loss", "Blood loss"
    INSENSIBLE = "insensible", "Insensible loss"
    OTHER = "other", "Other"


class FluidEntry(BaseModel):
    """One volume in or out, at one time. Append-only; the balance is derived.

    There is no running total anywhere in this module. A stored balance and a
    ledger disagree the first time an entry is corrected, and the ledger is
    always the one that is right — the same reasoning as the stock ledger and
    the leave ledger.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="fluid_entries",
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    direction = models.CharField(max_length=4, choices=FluidDirection.choices)
    route = models.CharField(max_length=16, choices=FluidRoute.choices)
    volume_ml = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)

    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_name = models.CharField(max_length=255, blank=True)

    #: A correction reverses an entry rather than editing it, and names the
    #: row it reverses. The chart then shows that somebody corrected a figure,
    #: which is itself clinically interesting.
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reversed_by",
    )

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["stay", "-recorded_at"])]

    def __str__(self):
        return f"{self.direction} {self.volume_ml}ml {self.route}"

    @property
    def signed_ml(self) -> int:
        return (
            self.volume_ml
            if self.direction == FluidDirection.IN
            else -self.volume_ml
        )


# ---------------------------------------------------------------------------
# Infusions
# ---------------------------------------------------------------------------


class InfusionStatus(models.TextChoices):
    RUNNING = "running", "Running"
    PAUSED = "paused", "Paused"
    STOPPED = "stopped", "Stopped"


class Infusion(BaseModel):
    """A continuous drug, from the moment it is started to the moment it stops.

    The rate lives in `InfusionRate` rows, not here. A `current_rate` column
    would be overwritten every few minutes on a noradrenaline infusion, and
    the question the notes always ask afterwards — "what was she on when the
    pressure dropped?" — would have no answer.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="infusions",
    )
    drug_name = models.CharField(max_length=255)
    concentration = models.CharField(
        max_length=128, blank=True,
        help_text="As made up, e.g. 4mg in 50ml.",
    )
    #: The unit the rate is expressed in. Vasopressors are ordered in
    #: mcg/kg/min and sedatives in mg/hr; storing a bare number and assuming a
    #: unit is how a hundred-fold overdose happens.
    rate_unit = models.CharField(max_length=32, default="ml/hr")
    route = models.CharField(max_length=32, default="IV")
    #: Titratable drugs are the reason this model exists; a fixed-rate
    #: antibiotic infusion is here too, and the flag says which is which.
    is_titratable = models.BooleanField(default=False)
    target = models.CharField(
        max_length=255, blank=True,
        help_text="What the nurse is titrating to, e.g. MAP > 65.",
    )
    maximum_rate = models.DecimalField(
        max_digits=8, decimal_places=3, null=True, blank=True,
    )

    status = models.CharField(
        max_length=12, choices=InfusionStatus.choices,
        default=InfusionStatus.RUNNING, db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(max_length=255, blank=True)

    prescribed_by_id = models.UUIDField(null=True, blank=True)
    prescribed_by_name = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["stay", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stopped_at__isnull=True)
                | models.Q(stopped_at__gte=models.F("started_at")),
                name="icu_infusion_stop_after_start",
            ),
        ]

    def __str__(self):
        return self.drug_name


class InfusionRate(BaseModel):
    """The rate from one moment until the next rate row. Append-only.

    A rate is an interval, and the interval's end is simply the next row's
    start. Storing an explicit end would need two writes for every change and
    would go wrong exactly once, leaving a gap nobody notices until a dose
    calculation is short.
    """

    infusion = models.ForeignKey(
        Infusion, on_delete=models.CASCADE, related_name="rates",
    )
    rate = models.DecimalField(max_digits=8, decimal_places=3)
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)
    #: Why it was changed. On a titratable drug this is the clinical story:
    #: "MAP 55" or "weaning". Free text on purpose -- an enumeration here
    #: would be guessed at rather than filled in.
    reason = models.CharField(max_length=255, blank=True)
    changed_by_id = models.UUIDField(null=True, blank=True)
    changed_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["changed_at"]
        indexes = [models.Index(fields=["infusion", "changed_at"])]
        constraints = [
            #: Two rates at the same instant on one infusion cannot be
            #: ordered, and the volume calculation would then depend on
            #: insertion order.
            models.UniqueConstraint(
                fields=["infusion", "changed_at"],
                name="uniq_infusion_rate_at_instant",
            ),
        ]

    def __str__(self):
        return f"{self.rate} at {self.changed_at:%H:%M}"


# ---------------------------------------------------------------------------
# Ventilation
# ---------------------------------------------------------------------------


class VentilationMode(models.TextChoices):
    """Support modes, from full control to none.

    Ordered from most to least support so a query can ask "was this patient
    more supported this morning than last night" without a lookup table.
    """

    CMV = "cmv", "Controlled mandatory ventilation"
    SIMV = "simv", "Synchronised intermittent mandatory"
    PSV = "psv", "Pressure support"
    CPAP = "cpap", "CPAP"
    NIV = "niv", "Non-invasive ventilation"
    HFNO = "hfno", "High-flow nasal oxygen"
    T_PIECE = "t_piece", "T-piece"
    SPONTANEOUS = "spontaneous", "Self-ventilating"


class VentilationRecord(BaseModel):
    """A ventilator's settings and what it actually delivered, at one moment.

    The two halves are the point. `set_tidal_volume` is what was asked for;
    `expired_tidal_volume` is what came back. A single `tidal_volume` field
    would silently answer both questions with whichever one somebody typed,
    and the difference between them is a cuff leak or a failing lung.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="ventilation",
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    mode = models.CharField(max_length=16, choices=VentilationMode.choices)
    #: Invasive means an endotracheal or tracheostomy tube. Ventilator-day
    #: surveillance counts invasive days only, and NIV counted as invasive
    #: makes a unit's VAP rate look artificially good.
    is_invasive = models.BooleanField(default=True)

    # What was asked for.
    set_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    set_tidal_volume = models.PositiveSmallIntegerField(null=True, blank=True)
    peep = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    pressure_support = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    #: Fraction of inspired oxygen as a percentage, 21 to 100.
    fio2 = models.PositiveSmallIntegerField(null=True, blank=True)

    # What happened.
    measured_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    expired_tidal_volume = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    peak_pressure = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    plateau_pressure = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    minute_volume = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    etco2 = models.PositiveSmallIntegerField(null=True, blank=True)

    # Blood gas, when one was taken alongside.
    pao2 = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    paco2 = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    ph = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True
    )

    source = models.CharField(
        max_length=12, choices=ObservationSource.choices,
        default=ObservationSource.MANUAL,
    )
    device_identifier = models.CharField(max_length=64, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["stay", "-recorded_at"])]

    def __str__(self):
        return f"{self.mode} at {self.recorded_at:%H:%M}"

    @property
    def pf_ratio(self) -> Decimal | None:
        """PaO2/FiO2, the number that defines ARDS severity.

        None when either half is missing, rather than a guess. A PF ratio
        computed against an assumed FiO2 is the kind of number that ends up in
        a research dataset and cannot be traced back.
        """
        if self.pao2 is None or not self.fio2:
            return None
        # FiO2 is stored as a percentage; the ratio is defined against the
        # fraction, so 40% becomes 0.40.
        fraction = Decimal(self.fio2) / Decimal("100")
        return (self.pao2 / fraction).quantize(Decimal("1"))

    @property
    def driving_pressure(self) -> Decimal | None:
        """Plateau minus PEEP: the pressure the lung actually sees."""
        if self.plateau_pressure is None or self.peep is None:
            return None
        return self.plateau_pressure - self.peep


# ---------------------------------------------------------------------------
# Lines and tubes
# ---------------------------------------------------------------------------


class DeviceType(models.TextChoices):
    CENTRAL_LINE = "central_line", "Central venous catheter"
    ARTERIAL_LINE = "arterial_line", "Arterial line"
    PERIPHERAL_LINE = "peripheral_line", "Peripheral cannula"
    URINARY_CATHETER = "urinary_catheter", "Urinary catheter"
    ENDOTRACHEAL = "endotracheal", "Endotracheal tube"
    TRACHEOSTOMY = "tracheostomy", "Tracheostomy"
    NASOGASTRIC = "nasogastric", "Nasogastric tube"
    CHEST_DRAIN = "chest_drain", "Chest drain"
    DIALYSIS_CATHETER = "dialysis_catheter", "Dialysis catheter"
    OTHER = "other", "Other"


class InvasiveDevice(BaseModel):
    """A line or tube, from insertion to removal.

    An interval, not a flag, because the number infection control asks for is
    *line-days*: the denominator of every catheter-related infection rate. A
    boolean "has a central line" can produce a count of lines and never a
    count of days, and a rate without a denominator is not a rate.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="devices",
    )
    device_type = models.CharField(max_length=24, choices=DeviceType.choices)
    site = models.CharField(max_length=128, blank=True)
    size = models.CharField(max_length=32, blank=True)

    inserted_at = models.DateTimeField(default=timezone.now, db_index=True)
    inserted_by_name = models.CharField(max_length=255, blank=True)
    #: Lines put in during a resuscitation are inserted without full asepsis
    #: and are meant to be replaced within 24 hours. Recording it is how
    #: anybody remembers to.
    inserted_in_emergency = models.BooleanField(default=False)

    removed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    removal_reason = models.CharField(max_length=255, blank=True)
    #: Suspected infection at removal. The surveillance numerator.
    was_infected = models.BooleanField(default=False)

    #: When the dressing or the line itself is next due for attention. A date
    #: nobody computes is a date nobody acts on.
    next_change_due = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-inserted_at"]
        indexes = [models.Index(fields=["stay", "removed_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(removed_at__isnull=True)
                | models.Q(removed_at__gte=models.F("inserted_at")),
                name="icu_device_removed_after_inserted",
            ),
        ]

    def __str__(self):
        return f"{self.device_type} {self.site}"

    @property
    def days_in_situ(self) -> Decimal:
        end = self.removed_at or timezone.now()
        return (
            Decimal((end - self.inserted_at).total_seconds()) / Decimal("86400")
        ).quantize(Decimal("0.1"))


# ---------------------------------------------------------------------------
# The daily round
# ---------------------------------------------------------------------------


#: The daily-goals checklist, as data.
#:
#: FASTHUG is the intensive-care equivalent of the surgical safety checklist:
#: seven things that get forgotten on a busy round and each of which kills
#: somebody occasionally. Held here rather than in a form so that it can be
#: audited, versioned and reported on -- the same reasoning as the WHO
#: checklist in the theatre module.
FASTHUG_ITEMS = [
    ("feeding", "Feeding — enteral unless there is a reason not to"),
    ("analgesia", "Analgesia — assessed and adequate"),
    ("sedation", "Sedation — target RASS set, and being met"),
    ("thromboprophylaxis", "Thromboprophylaxis — given, or a reason not to"),
    ("head_up", "Head of bed elevated 30–45°"),
    ("ulcer_prophylaxis", "Stress ulcer prophylaxis — indicated or stopped"),
    ("glucose", "Glucose control — within the unit's range"),
]

FASTHUG_KEYS = [key for key, _ in FASTHUG_ITEMS]


class Round(BaseModel):
    """One consultant round: the assessment, the plan, and the daily goals.

    A round is a document, not a set of fields on the stay. Yesterday's plan
    is evidence — "why was she not extubated on Tuesday" is a question with an
    answer only if Tuesday's plan still exists.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="rounds",
    )
    round_at = models.DateTimeField(default=timezone.now, db_index=True)
    #: Which ICU day this round belongs to. Explicit rather than derived from
    #: the timestamp, because the unit day runs 07:00 to 07:00 and a round at
    #: 06:45 belongs to the day that is ending.
    icu_day = models.PositiveSmallIntegerField()

    consultant_name = models.CharField(max_length=255, blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)

    #: The seven FASTHUG answers: {key: true|false}. Missing keys are missing,
    #: not false -- an item nobody considered is a different fact from one
    #: considered and declined.
    fasthug = models.JSONField(default=dict, blank=True)
    #: Why an item was answered no. Keyed the same way.
    fasthug_reasons = models.JSONField(default=dict, blank=True)

    #: The two questions worth asking every day, and the two that get skipped.
    is_ready_for_sedation_hold = models.BooleanField(null=True, blank=True)
    is_ready_for_weaning_trial = models.BooleanField(null=True, blank=True)
    is_ready_for_step_down = models.BooleanField(default=False)
    step_down_blockers = models.CharField(max_length=512, blank=True)

    family_updated = models.BooleanField(default=False)
    family_update_notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-round_at"]
        indexes = [models.Index(fields=["stay", "-round_at"])]
        constraints = [
            #: One consultant round per ICU day. A second round on the same
            #: day is an addendum to the first, and two "the plan for today"
            #: documents cannot both be the plan.
            models.UniqueConstraint(
                fields=["stay", "icu_day"], name="uniq_round_per_icu_day",
            ),
        ]

    def __str__(self):
        return f"round day {self.icu_day}"

    @property
    def missed_items(self) -> list[str]:
        """FASTHUG items nobody answered either way."""
        return [key for key in FASTHUG_KEYS if key not in self.fasthug]

    @property
    def negative_items(self) -> list[str]:
        return [key for key in FASTHUG_KEYS if self.fasthug.get(key) is False]


# ---------------------------------------------------------------------------
# Severity scoring
# ---------------------------------------------------------------------------


class SofaScore(BaseModel):
    """A daily SOFA score, with its components frozen and its gaps named.

    Two rules, both learned the hard way in every unit that has tried this.

    First, the components are stored, not just the total. A score of 9
    recomputed six months later from the same database gives a different
    answer as soon as anybody corrects a lab value, and then the research
    dataset and the chart disagree with no way to tell which is which.

    Second, `missing_components` is stored and is not empty by accident. SOFA
    assigns 0 to a normal value, so a missing bilirubin scores the same as a
    healthy liver — the score silently understates severity, always in the
    same direction. A score that names its gaps can be excluded from analysis;
    one that hides them cannot.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="sofa_scores",
    )
    icu_day = models.PositiveSmallIntegerField()
    scored_for = models.DateField(db_index=True)
    scored_at = models.DateTimeField(default=timezone.now)

    respiratory = models.PositiveSmallIntegerField(default=0)
    coagulation = models.PositiveSmallIntegerField(default=0)
    liver = models.PositiveSmallIntegerField(default=0)
    cardiovascular = models.PositiveSmallIntegerField(default=0)
    neurological = models.PositiveSmallIntegerField(default=0)
    renal = models.PositiveSmallIntegerField(default=0)
    total = models.PositiveSmallIntegerField(default=0)

    #: The values each component was computed from, kept so the score can be
    #: explained without re-querying data that may since have changed.
    components = models.JSONField(default=dict, blank=True)
    #: Systems with no data. The score is still stored, because a partial SOFA
    #: is useful at the bedside; it is flagged, because a partial SOFA is not
    #: comparable.
    missing_components = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-scored_for"]
        constraints = [
            models.UniqueConstraint(
                fields=["stay", "icu_day"], name="uniq_sofa_per_icu_day",
            ),
        ]

    def __str__(self):
        return f"SOFA {self.total} day {self.icu_day}"

    @property
    def is_complete(self) -> bool:
        return not self.missing_components


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertSeverity(models.TextChoices):
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class Alert(BaseModel):
    """Something crossed a threshold, and somebody has to say they saw it.

    An alert that clears itself when the number comes back is not an alert; it
    is a screen effect. The event happened, and the record of it survives the
    patient improving — a run of six self-clearing desaturations overnight is
    exactly what a morning review needs to see.

    Acknowledgement names a person and a time. An acknowledgement that any
    click satisfies teaches staff to click, which is how alarm fatigue is
    manufactured.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="alerts",
    )
    observation = models.ForeignKey(
        Observation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="alerts",
    )
    raised_at = models.DateTimeField(default=timezone.now, db_index=True)
    severity = models.CharField(
        max_length=12, choices=AlertSeverity.choices,
        default=AlertSeverity.WARNING, db_index=True,
    )
    parameter = models.CharField(max_length=48)
    value = models.CharField(max_length=32)
    threshold = models.CharField(max_length=64)
    message = models.CharField(max_length=512)

    #: Alerts from unvalidated device data are marked, because an artefact
    #: alert and a real one demand different responses and the difference is
    #: knowable at the moment it is raised.
    from_unvalidated_device = models.BooleanField(default=False)

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_id = models.UUIDField(null=True, blank=True)
    acknowledged_by_name = models.CharField(max_length=255, blank=True)
    #: What was done. Optional, because forcing a note produces "seen".
    action_taken = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-raised_at"]
        indexes = [
            models.Index(fields=["stay", "-raised_at"]),
            models.Index(fields=["acknowledged_at", "severity"]),
        ]
        constraints = [
            #: The same parameter breaching at the same instant twice is one
            #: event double-recorded, usually by a device feed retrying.
            models.UniqueConstraint(
                fields=["stay", "parameter", "raised_at"],
                name="uniq_alert_per_parameter_instant",
            ),
        ]

    def __str__(self):
        return f"{self.severity} {self.parameter} {self.value}"

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None

    @property
    def minutes_to_acknowledge(self) -> int | None:
        if not self.acknowledged_at:
            return None
        return int((self.acknowledged_at - self.raised_at).total_seconds() // 60)


#: Default alert thresholds.
#:
#: Data, not code, so a unit can hold its own -- a neonatal unit's normal heart
#: rate is a general unit's tachycardia. Each entry is
#: (parameter, low, high, critical_low, critical_high).
DEFAULT_THRESHOLDS = {
    "heart_rate": (50, 120, 40, 150),
    "systolic": (90, 180, 80, 200),
    "mean_arterial_pressure": (65, 110, 55, 130),
    "respiratory_rate": (10, 25, 8, 35),
    "spo2": (92, None, 88, None),
    "temperature": (Decimal("36.0"), Decimal("38.0"), Decimal("35.0"), Decimal("39.5")),
    "blood_glucose": (Decimal("4.0"), Decimal("10.0"), Decimal("3.0"), Decimal("20.0")),
    "lactate": (None, Decimal("2.0"), None, Decimal("4.0")),
}


class AlertThreshold(BaseModel):
    """A per-patient override of the unit's defaults.

    A patient with chronic lung disease lives at 88% saturation, and alerting
    on that all night is how the alarm that matters gets ignored. The override
    names who set it and why, because a widened threshold is a clinical
    decision, not a preference.
    """

    stay = models.ForeignKey(
        IcuStay, on_delete=models.CASCADE, related_name="thresholds",
    )
    parameter = models.CharField(max_length=48)
    low = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    high = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    critical_low = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    critical_high = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    reason = models.CharField(max_length=255, blank=True)
    set_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stay", "parameter"],
                name="uniq_threshold_per_parameter",
            ),
        ]

    def __str__(self):
        return f"{self.parameter} threshold"


def validate_stay_open(stay: IcuStay) -> None:
    """Refuse to chart against a finished stay.

    Not a constraint because the message matters: charting into a discharged
    patient's record usually means the wrong patient is selected, and the
    error should say so rather than being a foreign-key failure.
    """
    if not stay.is_current:
        raise ValidationError(
            "This ICU stay ended on "
            f"{stay.discharged_at:%Y-%m-%d %H:%M}. Nothing further can be "
            "charted against it — check whether you have the right patient."
        )


def icu_day_of(stay: IcuStay, at=None) -> int:
    """Which ICU day a moment falls in, counting the admission day as day 1.

    Days are counted from the admission time rather than from midnight,
    because "day 3" in a handover means seventy-two hours of illness, not
    three calendar dates — a patient admitted at 23:50 would otherwise be on
    day 2 ten minutes later.
    """
    at = at or timezone.now()
    elapsed = at - stay.admitted_at
    return max(1, int(elapsed / timedelta(days=1)) + 1)
