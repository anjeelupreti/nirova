"""Emergency: the front door, where nothing about the patient is known yet.

Every other module in this system starts from a patient record. Emergency
starts from a body on a trolley, and the four decisions here all follow from
that.

**An unidentified patient must be registerable.** A road accident arrives
unconscious with no wallet. A system that requires a name either refuses to
register them — so nothing that happens next is recorded anywhere — or invites
staff to type "Unknown Male" into the name field, which then merges badly with
the next Unknown Male. Instead an arrival can be *provisional*: a real patient
record with a generated identifier, flagged as unidentified, merged into the
real record later through the merge machinery that already exists.

**Triage is an event, not a field.** A patient triaged as urgent at 09:00 can
be resuscitation at 09:40. Overwriting the category destroys the fact that
they deteriorated, which is exactly what a mortality review asks about.

**Every category carries a target time, and breaching it is visible.** A
triage scale with no clock is a scale nobody acts on.

**Leaving without being seen is an outcome, not an absence.** LWBS is a
quality metric a department is judged on, and it only exists if somebody
records it rather than the encounter simply going quiet.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.encounters.models import Encounter, TriageCategory
from apps.organization.models import Department, Facility
from apps.patients.models import Patient

ZERO = Decimal("0.00")

#: Minutes a patient of each triage category should wait before being seen.
#:
#: The numbers are in `TriageCategory`'s own labels; holding them here as data
#: makes them computable rather than merely displayed. Without this the scale
#: is five words a nurse chooses between and nothing measures.
TARGET_MINUTES = {
    TriageCategory.RESUSCITATION: 0,
    TriageCategory.EMERGENT: 10,
    TriageCategory.URGENT: 30,
    TriageCategory.LESS_URGENT: 60,
    TriageCategory.NON_URGENT: 120,
}


class ArrivalMode(models.TextChoices):
    """How they got here.

    Reported because it changes what happens next and because it is a quality
    measure in its own right: a department where most cardiac arrests arrive
    by private car has an ambulance-service problem, not a resuscitation one.
    """

    WALK_IN = "walk_in", "Walked in"
    AMBULANCE = "ambulance", "Ambulance"
    PRIVATE_VEHICLE = "private_vehicle", "Private vehicle"
    POLICE = "police", "Police"
    REFERRED = "referred", "Referred from another facility"
    HELICOPTER = "helicopter", "Air ambulance"
    OTHER = "other", "Other"


class Disposition(models.TextChoices):
    """How the emergency episode ended.

    Enumerated rather than left as a note because each is a different number
    on a departmental report, and the difference between "admitted" and
    "left without being seen" is the difference between a busy department and
    a failing one.
    """

    PENDING = "pending", "Still in the department"
    DISCHARGED = "discharged", "Discharged home"
    ADMITTED = "admitted", "Admitted"
    REFERRED = "referred", "Referred to another facility"
    LWBS = "lwbs", "Left without being seen"
    LAMA = "lama", "Left against medical advice"
    ABSCONDED = "absconded", "Absconded"
    DIED = "died", "Died in the department"
    BROUGHT_DEAD = "brought_dead", "Brought in dead"


#: Dispositions that close the episode.
CLOSED_DISPOSITIONS = {
    Disposition.DISCHARGED, Disposition.ADMITTED, Disposition.REFERRED,
    Disposition.LWBS, Disposition.LAMA, Disposition.ABSCONDED,
    Disposition.DIED, Disposition.BROUGHT_DEAD,
}


class Arrival(BaseModel):
    """One presentation to the emergency department.

    Wraps an `Encounter` of type `emergency`, so notes, prescriptions, orders
    and charges all work unchanged. What is here is what only an emergency
    presentation has: how they arrived, how sick they are, how long they have
    waited, and how it ended.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="arrivals"
    )
    encounter = models.OneToOneField(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="arrival",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="arrivals"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="arrivals",
    )

    arrived_at = models.DateTimeField(default=timezone.now, db_index=True)
    arrival_mode = models.CharField(
        max_length=20, choices=ArrivalMode.choices,
        default=ArrivalMode.WALK_IN, db_index=True,
    )
    ambulance_reference = models.CharField(max_length=64, blank=True)
    brought_by = models.CharField(max_length=255, blank=True)
    brought_by_phone = models.CharField(max_length=32, blank=True)

    presenting_complaint = models.CharField(max_length=512)

    #: True while the patient's identity is *still* unknown. Cleared on
    #: identification, so a board can show who still needs naming.
    is_unidentified = models.BooleanField(default=False, db_index=True)
    #: True if they were unknown when they walked through the door, and it
    #: stays true forever.
    #:
    #: Separate from `is_unidentified` because identification must not erase
    #: the fact that they arrived unnamed. "How many arrived unidentified last
    #: month?" drives the ID-band process and the police-liaison workload, and
    #: with one field the answer is zero for everybody eventually identified —
    #: which is to say, for almost everybody.
    arrived_unidentified = models.BooleanField(default=False, db_index=True)
    #: When somebody put a name to them. The gap from arrival is a real
    #: operational number: an hour unidentified is an hour nobody could ring a
    #: relative or check an allergy.
    identified_at = models.DateTimeField(null=True, blank=True)
    #: What staff can call them meanwhile. A physical description beats
    #: "Unknown Male 3" when two of them are in the department at once.
    provisional_description = models.CharField(max_length=255, blank=True)

    #: Latest triage, denormalised for the board. The history is in
    #: `TriageAssessment`.
    triage_category = models.IntegerField(
        choices=TriageCategory.choices, null=True, blank=True, db_index=True
    )
    triaged_at = models.DateTimeField(null=True, blank=True)
    #: When a clinician first saw them. The gap from `arrived_at` is the
    #: number a department is judged on.
    first_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    seen_by_id = models.UUIDField(null=True, blank=True)
    seen_by_name = models.CharField(max_length=255, blank=True)

    disposition = models.CharField(
        max_length=16, choices=Disposition.choices,
        default=Disposition.PENDING, db_index=True,
    )
    disposition_at = models.DateTimeField(null=True, blank=True)
    disposition_notes = models.TextField(blank=True)
    #: Where they went, for an admission or a referral.
    admission_reference = models.CharField(max_length=32, blank=True)
    referred_to = models.CharField(max_length=255, blank=True)

    is_mlc = models.BooleanField(
        default=False,
        help_text="Medico-legal: assault, accident, poisoning, burns.",
    )
    mlc_number = models.CharField(max_length=64, blank=True)
    police_informed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ed_arrival"
        ordering = ["-arrived_at"]
        indexes = [
            models.Index(fields=["facility", "disposition"]),
            models.Index(fields=["disposition", "triage_category", "arrived_at"]),
            models.Index(fields=["patient", "-arrived_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.full_name}"

    @property
    def is_open(self) -> bool:
        return self.disposition == Disposition.PENDING

    @property
    def waiting_minutes(self) -> int:
        """How long from arrival to first being seen, or to now.

        The single number an emergency department lives by. Counted to *now*
        while they are still waiting, so a board shows a wait growing rather
        than a blank.
        """
        end = self.first_seen_at or timezone.now()
        return max(int((end - self.arrived_at).total_seconds() // 60), 0)

    @property
    def target_minutes(self) -> int | None:
        if self.triage_category is None:
            return None
        return TARGET_MINUTES.get(self.triage_category)

    @property
    def is_breaching(self) -> bool:
        """Waited longer than their triage category allows.

        Still true after they have been seen — a breach that happened is a
        breach, and a board that forgot it the moment somebody walked over
        would under-report the department's performance to itself.
        """
        target = self.target_minutes
        if target is None:
            return False
        return self.waiting_minutes > target

    @property
    def minutes_to_breach(self) -> int | None:
        """Negative once breached. Null when not yet triaged."""
        target = self.target_minutes
        if target is None:
            return None
        return target - self.waiting_minutes

    @property
    def minutes_unidentified(self) -> int | None:
        """How long they went without a name. Null if they always had one."""
        if not self.arrived_unidentified:
            return None
        end = self.identified_at or timezone.now()
        return max(int((end - self.arrived_at).total_seconds() // 60), 0)

    @property
    def total_minutes(self) -> int:
        """Arrival to disposition — the department's length of stay."""
        end = self.disposition_at or timezone.now()
        return max(int((end - self.arrived_at).total_seconds() // 60), 0)

    def clean(self):
        if self.first_seen_at and self.first_seen_at < self.arrived_at:
            raise ValidationError(
                {"first_seen_at": "Nobody is seen before they arrive."}
            )


class TriageAssessment(BaseModel):
    """One triage decision, kept forever.

    A patient triaged urgent at 09:00 can be resuscitation at 09:40, and the
    fact that they *deteriorated* is exactly what a mortality review asks
    about. Overwriting a category destroys it; appending an assessment
    preserves it.
    """

    arrival = models.ForeignKey(
        Arrival, on_delete=models.CASCADE, related_name="assessments"
    )
    assessed_at = models.DateTimeField(default=timezone.now, db_index=True)
    category = models.IntegerField(choices=TriageCategory.choices)
    #: The category this replaced, so a deterioration is legible without
    #: joining to the previous row.
    previous_category = models.IntegerField(null=True, blank=True)

    assessed_by_id = models.UUIDField(null=True, blank=True)
    assessed_by_name = models.CharField(max_length=255, blank=True)
    reason = models.CharField(max_length=512, blank=True)

    # Vitals taken at triage. Duplicated from the encounter's observation
    # record on purpose: the triage set is what justified *this* category, and
    # a later reading must not retroactively change what the nurse was
    # looking at.
    pulse = models.PositiveSmallIntegerField(null=True, blank=True)
    systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_c = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    gcs = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Glasgow Coma Scale, 3–15."
    )
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ed_triage_assessment"
        ordering = ["-assessed_at"]
        indexes = [models.Index(fields=["arrival", "-assessed_at"])]

    def __str__(self):
        return f"{self.arrival.reference} → category {self.category}"

    @property
    def is_deterioration(self) -> bool:
        """A lower number is sicker, so a fall in category is a worsening."""
        return (
            self.previous_category is not None
            and self.category < self.previous_category
        )


class AlertPathway(models.TextChoices):
    """Time-critical pathways with a published clock.

    Each has a target measured from arrival, and each is the subject of an
    audit somebody publishes. Modelled as an enum rather than free text
    because a pathway nobody can count is a pathway nobody improves.
    """

    STEMI = "stemi", "STEMI — heart attack"
    STROKE = "stroke", "Stroke"
    SEPSIS = "sepsis", "Sepsis"
    TRAUMA = "trauma", "Major trauma"
    CARDIAC_ARREST = "cardiac_arrest", "Cardiac arrest"
    OBSTETRIC = "obstetric", "Obstetric emergency"
    PAEDIATRIC = "paediatric", "Paediatric emergency"
    POISONING = "poisoning", "Poisoning"
    BURN = "burn", "Major burn"


#: Minutes from arrival to the pathway's defining intervention.
#:
#: These are the internationally published targets — door-to-needle,
#: door-to-antibiotic — and they are data here so a department can adjust them
#: to its own standard without a code change.
PATHWAY_TARGET_MINUTES = {
    AlertPathway.STEMI: 90,
    AlertPathway.STROKE: 60,
    AlertPathway.SEPSIS: 60,
    AlertPathway.TRAUMA: 60,
    AlertPathway.CARDIAC_ARREST: 0,
    AlertPathway.OBSTETRIC: 30,
    AlertPathway.PAEDIATRIC: 30,
    AlertPathway.POISONING: 60,
    AlertPathway.BURN: 60,
}


class CriticalAlert(BaseModel):
    """A time-critical pathway activated for one patient.

    The clock starts at *arrival*, not at activation. A stroke recognised
    forty minutes late has already used forty minutes of its window, and a
    target measured from activation would hide precisely the delay that
    matters.
    """

    arrival = models.ForeignKey(
        Arrival, on_delete=models.CASCADE, related_name="alerts"
    )
    pathway = models.CharField(
        max_length=20, choices=AlertPathway.choices, db_index=True
    )
    activated_at = models.DateTimeField(default=timezone.now)
    activated_by_id = models.UUIDField(null=True, blank=True)
    activated_by_name = models.CharField(max_length=255, blank=True)

    #: When the pathway's defining intervention happened — thrombolysis,
    #: antibiotics, theatre.
    intervention_at = models.DateTimeField(null=True, blank=True)
    intervention = models.CharField(max_length=255, blank=True)

    stood_down_at = models.DateTimeField(null=True, blank=True)
    stood_down_reason = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ed_critical_alert"
        ordering = ["-activated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["arrival", "pathway"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_alert_per_arrival_pathway",
            )
        ]
        indexes = [models.Index(fields=["pathway", "-activated_at"])]

    def __str__(self):
        return f"{self.get_pathway_display()} on {self.arrival.reference}"

    @property
    def target_minutes(self) -> int:
        return PATHWAY_TARGET_MINUTES.get(self.pathway, 60)

    @property
    def recognition_minutes(self) -> int:
        """Arrival to somebody noticing. Often the whole delay."""
        return max(
            int(
                (self.activated_at - self.arrival.arrived_at).total_seconds()
                // 60
            ),
            0,
        )

    @property
    def door_to_intervention_minutes(self) -> int | None:
        if not self.intervention_at:
            return None
        return max(
            int(
                (
                    self.intervention_at - self.arrival.arrived_at
                ).total_seconds()
                // 60
            ),
            0,
        )

    @property
    def met_target(self) -> bool | None:
        """Null while the intervention has not happened."""
        elapsed = self.door_to_intervention_minutes
        if elapsed is None:
            return None
        return elapsed <= self.target_minutes


class ResuscitationEvent(BaseModel):
    """One timed entry in a resuscitation record.

    A resus is written afterwards from memory unless something records it as
    it happens, and "afterwards from memory" is not good enough for the thing
    a coroner reads. Each entry is timestamped on creation and never edited —
    a correction is another entry.
    """

    arrival = models.ForeignKey(
        Arrival, on_delete=models.CASCADE, related_name="resuscitation"
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    event_type = models.CharField(
        max_length=24,
        choices=[
            ("arrest", "Cardiac arrest"),
            ("cpr_start", "CPR started"),
            ("cpr_stop", "CPR stopped"),
            ("shock", "Defibrillation"),
            ("drug", "Drug given"),
            ("airway", "Airway intervention"),
            ("access", "Vascular access"),
            ("rhythm", "Rhythm check"),
            ("rosc", "Return of circulation"),
            ("procedure", "Procedure"),
            ("observation", "Observation"),
            ("death", "Death declared"),
        ],
    )
    detail = models.CharField(max_length=512, blank=True)
    #: For a drug: what and how much. Kept as text, because a resus is not the
    #: moment to make somebody pick from a dropdown.
    drug = models.CharField(max_length=128, blank=True)
    dose = models.CharField(max_length=64, blank=True)
    route = models.CharField(max_length=32, blank=True)
    joules = models.PositiveSmallIntegerField(null=True, blank=True)
    rhythm = models.CharField(max_length=64, blank=True)

    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ed_resuscitation_event"
        ordering = ["occurred_at"]
        indexes = [models.Index(fields=["arrival", "occurred_at"])]

    def __str__(self):
        return f"{self.arrival.reference} {self.occurred_at:%H:%M:%S} {self.event_type}"
