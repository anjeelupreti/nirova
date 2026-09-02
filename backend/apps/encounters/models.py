"""Encounters: one episode of care, and everything recorded during it.

An **encounter** is the unit clinical work attaches to. A patient is a person;
an encounter is one occasion on which that person was seen. Vitals, notes,
diagnoses, orders, prescriptions and charges all hang off an encounter rather
than off the patient directly, because "what was their blood pressure?" is
meaningless without "when, and who took it?".

The model is deliberately shaped to cover outpatient today and inpatient
later. An OPD consultation and a three-week admission are the same entity with
different `encounter_type` and different durations — which is what lets the
Hospital OS reuse this rather than build a parallel record.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Department, Facility, Unit
from apps.patients.models import Patient
from apps.scheduling.models import Appointment, QueueToken


class EncounterType(models.TextChoices):
    """What kind of episode this is.

    Drives billing, clinical templates and which fields are expected. An
    emergency encounter needs triage; a telemedicine one has no queue token.
    """

    OUTPATIENT = "outpatient", "Outpatient (OPD)"
    EMERGENCY = "emergency", "Emergency"
    INPATIENT = "inpatient", "Inpatient (IPD)"
    DAY_CARE = "day_care", "Day care"
    TELEMEDICINE = "telemedicine", "Telemedicine"
    HOME_VISIT = "home_visit", "Home visit"
    PROCEDURE = "procedure", "Procedure only"
    FOLLOW_UP = "follow_up", "Follow-up"
    HEALTH_CAMP = "health_camp", "Health camp"


class EncounterStatus(models.TextChoices):
    """Where the episode has got to.

    `IN_PROGRESS` and `AWAITING_RESULTS` are distinct because they mean
    different things to a doctor's worklist: one needs their attention now,
    the other is waiting on the laboratory.
    """

    PLANNED = "planned", "Planned"
    IN_PROGRESS = "in_progress", "In progress"
    AWAITING_RESULTS = "awaiting_results", "Awaiting results"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    LEFT_WITHOUT_BEING_SEEN = "lwbs", "Left without being seen"


#: Encounters a clinician still has work to do on.
OPEN_ENCOUNTER_STATUSES = {
    EncounterStatus.PLANNED,
    EncounterStatus.IN_PROGRESS,
    EncounterStatus.AWAITING_RESULTS,
}


class TriageCategory(models.IntegerChoices):
    """Five-level triage, the scale used across most of South Asia.

    Numbered so that ordering a queue by this field puts the sickest first
    without a lookup table.
    """

    RESUSCITATION = 1, "1 — Resuscitation (immediate)"
    EMERGENT = 2, "2 — Emergent (within 10 minutes)"
    URGENT = 3, "3 — Urgent (within 30 minutes)"
    LESS_URGENT = 4, "4 — Less urgent (within 60 minutes)"
    NON_URGENT = 5, "5 — Non-urgent (within 120 minutes)"


class Encounter(BaseModel):
    """One episode of care."""

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="encounters"
    )
    encounter_type = models.CharField(
        max_length=20,
        choices=EncounterType.choices,
        default=EncounterType.OUTPATIENT,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=EncounterStatus.choices,
        default=EncounterStatus.IN_PROGRESS,
        db_index=True,
    )

    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="encounters"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="encounters",
    )
    #: For inpatient care: the ward or bay. Left null for OPD.
    unit = models.ForeignKey(
        Unit, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="encounters",
    )

    #: The clinician responsible. A UUID rather than a foreign key because
    #: employees live in the HRMS module, which does not exist yet.
    provider_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    provider_name = models.CharField(max_length=255, blank=True)

    #: How the patient got here. Both optional: a walk-in has a token but no
    #: appointment, a telemedicine consultation has neither.
    appointment = models.OneToOneField(
        Appointment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="encounter",
    )
    queue_token = models.OneToOneField(
        QueueToken, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="encounter",
    )

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    #: What the patient says brought them in, in their own words. Kept
    #: separate from the structured note because the patient's own account is
    #: clinically meaningful and should not be paraphrased away.
    chief_complaint = models.CharField(max_length=512, blank=True)

    triage_category = models.IntegerField(
        choices=TriageCategory.choices, null=True, blank=True, db_index=True
    )
    triaged_at = models.DateTimeField(null=True, blank=True)
    triaged_by_id = models.UUIDField(null=True, blank=True)

    #: Set when this visit continues an earlier one, so a course of treatment
    #: reads as a thread rather than a scatter of unrelated visits.
    previous_encounter = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="follow_up_encounters",
    )

    #: How the episode ended, which is what drives discharge and billing.
    disposition = models.CharField(
        max_length=32,
        blank=True,
        choices=[
            ("discharged", "Discharged home"),
            ("admitted", "Admitted"),
            ("referred", "Referred out"),
            ("transferred", "Transferred"),
            ("observation", "Kept for observation"),
            ("absconded", "Absconded"),
            ("died", "Died"),
        ],
    )
    disposition_notes = models.CharField(max_length=512, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_instructions = models.TextField(blank=True)

    #: A clinician cannot un-say something. Once signed, the note is locked
    #: and further changes become amendments -- see `ClinicalNote`.
    is_signed = models.BooleanField(default=False)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "encounter"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["patient", "-started_at"]),
            models.Index(fields=["facility", "status", "-started_at"]),
            models.Index(fields=["provider_uuid", "-started_at"]),
            models.Index(fields=["encounter_type", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.full_name} ({self.encounter_type})"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ENCOUNTER_STATUSES

    @property
    def duration_minutes(self) -> int | None:
        if not self.ended_at:
            return None
        return int((self.ended_at - self.started_at).total_seconds() / 60)

    @property
    def is_editable(self) -> bool:
        """Whether records may still be added directly rather than amended."""
        return not self.is_signed

    def clean(self):
        if self.ended_at and self.ended_at < self.started_at:
            raise ValidationError(
                {"ended_at": "An encounter cannot end before it starts."}
            )


class VitalSigns(BaseModel):
    """One set of observations, taken at one moment.

    Stored as a set rather than as individual observations because vitals are
    taken and read together: a blood pressure without the pulse and
    temperature that accompanied it is much harder to interpret. Several sets
    per encounter are normal — on arrival, after treatment, before discharge.

    Every field is nullable. A nurse taking a temperature in triage should not
    be forced to invent a respiratory rate.
    """

    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="vitals"
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_name = models.CharField(max_length=255, blank=True)

    temperature_c = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    pulse_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    systolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Whether the oxygen saturation was measured on room air. A SpO2 of 94%
    #: on 4 litres of oxygen is a very different observation from 94% on air.
    on_room_air = models.BooleanField(default=True)
    oxygen_flow_lpm = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )

    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    height_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    #: Head circumference, for paediatric growth monitoring.
    head_circumference_cm = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )

    blood_glucose_mmol = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    pain_score = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="0-10."
    )
    #: Glasgow Coma Scale, 3-15. Present here rather than in a neurology
    #: module because it is taken at triage in any emergency department.
    gcs_total = models.PositiveSmallIntegerField(null=True, blank=True)

    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "vital_signs"
        ordering = ["-recorded_at"]
        verbose_name_plural = "vital signs"
        indexes = [models.Index(fields=["encounter", "-recorded_at"])]

    def __str__(self):
        return f"Vitals @ {self.recorded_at:%Y-%m-%d %H:%M}"

    @property
    def blood_pressure(self) -> str | None:
        if self.systolic_bp is None or self.diastolic_bp is None:
            return None
        return f"{self.systolic_bp}/{self.diastolic_bp}"

    @property
    def bmi(self) -> float | None:
        """Body mass index, when both weight and height are present."""
        weight = self._numeric(self.weight_kg)
        height = self._numeric(self.height_cm)
        if not weight or not height:
            return None
        metres = height / 100
        if metres <= 0:
            return None
        return round(weight / (metres * metres), 1)

    @staticmethod
    def _numeric(value):
        """Coerce a reading to a number, or None if it is not one.

        `abnormal_flags` may be called on an instance that has not been round
        -tripped through the database, where a DecimalField still holds
        whatever the caller assigned -- often a string. Comparing that against
        a threshold raises TypeError, and a TypeError here means a fever goes
        unflagged. Coercing defensively is the difference between a robust
        safety check and one that works only on the happy path.
        """
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def abnormal_flags(self) -> list:
        """Which readings fall outside adult reference ranges.

        Adult thresholds only, and deliberately wide — this exists to draw the
        eye on a busy screen, not to diagnose. Paediatric vitals vary by age
        and would give false alarms against these bounds, so a child's
        readings are better read by a clinician than flagged by a constant.
        Age-banded ranges belong in a clinical-rules module, not here.
        """
        flags = []

        temperature = self._numeric(self.temperature_c)
        if temperature is not None:
            if temperature >= 38:
                flags.append({"field": "temperature_c", "level": "high",
                              "note": "Fever"})
            elif temperature < 35:
                flags.append({"field": "temperature_c", "level": "low",
                              "note": "Hypothermia"})

        pulse = self._numeric(self.pulse_bpm)
        if pulse is not None:
            if pulse > 100:
                flags.append({"field": "pulse_bpm", "level": "high",
                              "note": "Tachycardia"})
            elif pulse < 50:
                flags.append({"field": "pulse_bpm", "level": "low",
                              "note": "Bradycardia"})

        systolic = self._numeric(self.systolic_bp)
        if systolic is not None:
            if systolic >= 140:
                flags.append({"field": "systolic_bp", "level": "high",
                              "note": "Hypertension"})
            elif systolic < 90:
                flags.append({"field": "systolic_bp", "level": "critical",
                              "note": "Hypotension"})

        spo2 = self._numeric(self.spo2_percent)
        if spo2 is not None and spo2 < 94:
            flags.append(
                {
                    "field": "spo2_percent",
                    "level": "critical" if spo2 < 90 else "high",
                    "note": "Low oxygen saturation",
                }
            )

        respiratory_rate = self._numeric(self.respiratory_rate)
        if respiratory_rate is not None and respiratory_rate > 24:
            flags.append({"field": "respiratory_rate", "level": "high",
                          "note": "Tachypnoea"})

        gcs = self._numeric(self.gcs_total)
        if gcs is not None and gcs < 15:
            flags.append(
                {
                    "field": "gcs_total",
                    "level": "critical" if gcs <= 8 else "high",
                    "note": "Reduced consciousness",
                }
            )
        return flags


class NoteType(models.TextChoices):
    SOAP = "soap", "SOAP note"
    PROGRESS = "progress", "Progress note"
    NURSING = "nursing", "Nursing note"
    PROCEDURE = "procedure", "Procedure note"
    DISCHARGE = "discharge", "Discharge summary"
    REFERRAL = "referral", "Referral letter"
    TRIAGE = "triage", "Triage note"


class ClinicalNote(BaseModel):
    """A clinician's written record for an encounter.

    SOAP is stored as four fields rather than one blob. The structure is not
    decoration: it is what lets a discharge summary pull the assessment, a
    referral letter pull the objective findings, and an audit ask whether a
    plan was recorded — none of which is possible over free text.

    Notes are **append-only once signed**. A signed note is a clinical and
    legal statement; correcting it means adding an amendment that says what
    changed and why, not editing history. `EntityVersion` snapshots every
    signature.
    """

    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="notes"
    )
    note_type = models.CharField(
        max_length=20, choices=NoteType.choices, default=NoteType.SOAP
    )

    # -- SOAP ------------------------------------------------------------

    #: What the patient reports: symptoms, history, how they feel.
    subjective = models.TextField(blank=True)
    #: What the clinician observes and measures: examination findings.
    objective = models.TextField(blank=True)
    #: What the clinician concludes. Structured diagnoses live in `Diagnosis`;
    #: this is the reasoning around them.
    assessment = models.TextField(blank=True)
    #: What will be done: treatment, orders, advice, follow-up.
    plan = models.TextField(blank=True)

    #: For note types that are not SOAP-shaped -- nursing observations,
    #: procedure records, referral letters.
    body = models.TextField(blank=True)

    author_id = models.UUIDField(null=True, blank=True, db_index=True)
    author_name = models.CharField(max_length=255, blank=True)
    author_role = models.CharField(max_length=128, blank=True)

    is_signed = models.BooleanField(default=False, db_index=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    #: An amendment points at the note it corrects. The original stays
    #: readable and unchanged.
    amends = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="amendments",
    )
    amendment_reason = models.TextField(blank=True)

    #: Template this note was written from, once specialty templates exist.
    template_code = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "clinical_note"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["encounter", "note_type"]),
            models.Index(fields=["author_id", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_note_type_display()} — {self.encounter.reference}"

    @property
    def is_amendment(self) -> bool:
        return self.amends_id is not None

    @property
    def is_empty(self) -> bool:
        return not any(
            [self.subjective, self.objective, self.assessment, self.plan, self.body]
        )


class DiagnosisCertainty(models.TextChoices):
    """How sure the clinician is.

    Recorded because a working diagnosis and a confirmed one carry very
    different weight later — in a discharge summary, in an insurance claim,
    and in the patient's permanent record. Flattening them loses that.
    """

    SUSPECTED = "suspected", "Suspected"
    WORKING = "working", "Working diagnosis"
    CONFIRMED = "confirmed", "Confirmed"
    RULED_OUT = "ruled_out", "Ruled out"


class Diagnosis(BaseModel):
    """A diagnosis made during an encounter.

    Distinct from `PatientCondition`: a diagnosis is what was decided at one
    visit, a condition is what the patient carries between visits. A confirmed
    chronic diagnosis is normally promoted into a condition -- but that is a
    deliberate act, not an automatic one, because not every diagnosis should
    follow a patient for life.
    """

    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="diagnoses"
    )
    #: Denormalised so a patient's diagnosis history can be read without
    #: joining every encounter they have ever had.
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="diagnoses"
    )

    name = models.CharField(max_length=255)
    icd10_code = models.CharField(max_length=16, blank=True, db_index=True)
    certainty = models.CharField(
        max_length=16,
        choices=DiagnosisCertainty.choices,
        default=DiagnosisCertainty.WORKING,
    )
    #: The main reason for the visit. Exactly one per encounter should be
    #: primary; billing and reporting both depend on it.
    is_primary = models.BooleanField(default=False)
    is_chronic = models.BooleanField(default=False)

    onset_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    diagnosed_by_id = models.UUIDField(null=True, blank=True)
    diagnosed_by_name = models.CharField(max_length=255, blank=True)

    #: Set when this diagnosis has been carried into the patient's ongoing
    #: condition list, so it is not promoted twice.
    promoted_to_condition = models.ForeignKey(
        "patients.PatientCondition", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="source_diagnoses",
    )

    class Meta:
        db_table = "diagnosis"
        ordering = ["-is_primary", "name"]
        verbose_name_plural = "diagnoses"
        indexes = [
            models.Index(fields=["encounter", "is_primary"]),
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["icd10_code"]),
        ]
        constraints = [
            # One primary diagnosis per encounter. Partial so soft-deleted
            # rows do not hold the slot -- see development log entry 035.
            models.UniqueConstraint(
                fields=["encounter"],
                condition=models.Q(is_primary=True, deleted_at__isnull=True),
                name="uniq_primary_diagnosis_per_encounter",
            )
        ]

    def __str__(self):
        marker = "primary" if self.is_primary else self.certainty
        return f"{self.name} ({marker})"
