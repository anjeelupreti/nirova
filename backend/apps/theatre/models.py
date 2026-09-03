"""The operating theatre: booking it, staffing it, and proving it was safe.

The highest-revenue room in a hospital and the one with the least forgiving
failure modes. Five decisions.

**A theatre is booked over an interval**, exactly as a bed is occupied over
one. Two operations in one room at one time is not a scheduling annoyance, it
is a patient on a trolley in a corridor, so the database refuses it rather
than trusting a calendar widget.

**The safety checklist is a first-class object, not a form.** The WHO surgical
safety checklist — sign in, time out, sign out — is the single most effective
patient-safety intervention in surgery, and it works because each phase is
performed aloud by a named person before the next thing happens. Modelled as
three phases with signatories, and a case that reaches incision without a
time-out is recorded as having done so. The system does not stop the surgeon;
it makes the omission undeniable.

**Timings are captured as separate events, not as a duration.** Scheduled
start, wheels in, anaesthesia start, incision, closure, wheels out. The gaps
between them are the whole of theatre productivity: a list that starts late
and a list that turns around slowly are different problems with the same
total.

**An implant is tracked to its serial number.** When a batch of prostheses is
recalled, the question is "which patients have one" and the only acceptable
answer is a list of names.

**A cancellation has an enumerated reason.** A cancelled list is the largest
single waste in a hospital, and "why" has to be countable — a free-text reason
tells nobody whether the fix is more beds, more anaesthetists or better
pre-assessment.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.hr.models import Employee
from apps.organization.models import Department, Facility
from apps.patients.models import Patient
from apps.pharmacy.models import Batch, Product, StockLocation

ZERO = Decimal("0.00")


class TheatreType(models.TextChoices):
    GENERAL = "general", "General"
    ORTHOPAEDIC = "orthopaedic", "Orthopaedic"
    CARDIAC = "cardiac", "Cardiac"
    NEURO = "neuro", "Neurosurgical"
    OBSTETRIC = "obstetric", "Obstetric"
    OPHTHALMIC = "ophthalmic", "Ophthalmic"
    ENDOSCOPY = "endoscopy", "Endoscopy"
    DAY_CASE = "day_case", "Day case"
    EMERGENCY = "emergency", "Emergency"
    HYBRID = "hybrid", "Hybrid"


class Theatre(BaseModel):
    """One operating room.

    `turnaround_minutes` is the room's own cleaning and setup time, held here
    rather than assumed, because a cardiac theatre and an endoscopy room are
    not comparable and a scheduler that assumed one number would overbook the
    slower room every day.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    theatre_type = models.CharField(
        max_length=20, choices=TheatreType.choices,
        default=TheatreType.GENERAL, db_index=True,
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="theatres"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="theatres",
    )
    #: Where consumables and implants are drawn from. Theatre stock is its own
    #: location, because a hospital counts it separately and a swab that left
    #: the main store must not still appear to be there.
    stock_location = models.ForeignKey(
        StockLocation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="theatres",
    )

    floor = models.CharField(max_length=32, blank=True)
    #: Minutes needed between cases to clean and set up.
    turnaround_minutes = models.PositiveSmallIntegerField(default=30)
    #: The hours the room is staffed. A case scheduled outside them is an
    #: out-of-hours case, which costs differently and is worth counting.
    session_starts_at = models.TimeField(null=True, blank=True)
    session_ends_at = models.TimeField(null=True, blank=True)

    has_laminar_flow = models.BooleanField(default=False)
    has_image_intensifier = models.BooleanField(default=False)
    has_microscope = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ot_theatre"
        ordering = ["facility_id", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_theatre_code_per_facility",
            )
        ]
        indexes = [models.Index(fields=["facility", "is_active"])]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Urgency(models.TextChoices):
    """How soon it has to happen.

    Drives the scheduling rules and, more usefully, the cancellation
    conversation: an elective case bumped for an emergency is a different
    event from one bumped because nobody booked an anaesthetist.
    """

    ELECTIVE = "elective", "Elective"
    SCHEDULED = "scheduled", "Scheduled urgent (within days)"
    URGENT = "urgent", "Urgent (within 24 hours)"
    EMERGENCY = "emergency", "Emergency (immediate)"


class AsaGrade(models.IntegerChoices):
    """American Society of Anesthesiologists physical status.

    The single number that predicts perioperative risk, recorded because it
    determines whether a case can run in a day-case unit and because outcome
    reporting is meaningless without case-mix adjustment.
    """

    ASA_1 = 1, "1 — Healthy"
    ASA_2 = 2, "2 — Mild systemic disease"
    ASA_3 = 3, "3 — Severe systemic disease"
    ASA_4 = 4, "4 — Severe disease, constant threat to life"
    ASA_5 = 5, "5 — Moribund, not expected to survive without the operation"
    ASA_6 = 6, "6 — Brain-dead, organs being removed for donation"


class CaseStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    APPROVED = "approved", "Approved, awaiting a slot"
    SCHEDULED = "scheduled", "Scheduled"
    SENT_FOR = "sent_for", "Sent for"
    IN_THEATRE = "in_theatre", "In theatre"
    IN_RECOVERY = "in_recovery", "In recovery"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    POSTPONED = "postponed", "Postponed"


#: Statuses in which the case still occupies its slot.
LIVE_STATUSES = {
    CaseStatus.SCHEDULED, CaseStatus.SENT_FOR,
    CaseStatus.IN_THEATRE, CaseStatus.IN_RECOVERY,
}


class CancellationReason(models.TextChoices):
    """Why a case did not happen, in countable form.

    Grouped by who could have prevented it, because that is the only useful
    cut: a hospital cancelling for want of a bed has a different problem from
    one cancelling because patients arrive having eaten.
    """

    # Hospital-side
    NO_BED = "no_bed", "No bed available"
    NO_THEATRE_TIME = "no_theatre_time", "List overran"
    NO_STAFF = "no_staff", "Staff unavailable"
    NO_EQUIPMENT = "no_equipment", "Equipment or implant unavailable"
    EMERGENCY_BUMPED = "emergency_bumped", "Displaced by an emergency"
    # Patient-side
    PATIENT_UNFIT = "patient_unfit", "Patient medically unfit"
    PATIENT_NOT_FASTED = "patient_not_fasted", "Patient not fasted"
    PATIENT_DID_NOT_ATTEND = "patient_dna", "Patient did not attend"
    PATIENT_DECLINED = "patient_declined", "Patient declined"
    # Other
    CLINICAL_DECISION = "clinical_decision", "No longer indicated"
    ADMINISTRATIVE = "administrative", "Administrative"


#: Reasons the hospital could have prevented. The distinction is the point of
#: enumerating them at all: this is the number a theatre committee acts on.
AVOIDABLE_REASONS = {
    CancellationReason.NO_BED,
    CancellationReason.NO_THEATRE_TIME,
    CancellationReason.NO_STAFF,
    CancellationReason.NO_EQUIPMENT,
    CancellationReason.ADMINISTRATIVE,
}


class SurgicalCase(BaseModel):
    """One operation, from request to recovery.

    The timings are separate fields rather than a duration, because the gaps
    between them *are* theatre productivity. A list that starts late and one
    that turns around slowly produce the same total minutes and need opposite
    fixes.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="surgical_cases"
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgical_cases",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="surgical_cases"
    )
    theatre = models.ForeignKey(
        Theatre, null=True, blank=True, on_delete=models.PROTECT,
        related_name="cases",
    )

    # -- what and why ------------------------------------------------------

    planned_procedure = models.CharField(max_length=512)
    procedure_code = models.CharField(max_length=32, blank=True)
    #: What was actually done. Often differs from the plan, and the difference
    #: is clinically and commercially significant.
    performed_procedure = models.CharField(max_length=512, blank=True)
    laterality = models.CharField(
        max_length=12,
        choices=[
            ("left", "Left"), ("right", "Right"),
            ("bilateral", "Bilateral"), ("na", "Not applicable"),
        ],
        default="na",
        help_text="Confirmed aloud at the time-out; wrong-side surgery is a "
                  "never event.",
    )
    indication = models.TextField(blank=True)
    urgency = models.CharField(
        max_length=16, choices=Urgency.choices,
        default=Urgency.ELECTIVE, db_index=True,
    )
    asa_grade = models.IntegerField(
        choices=AsaGrade.choices, null=True, blank=True
    )
    is_day_case = models.BooleanField(default=False)

    status = models.CharField(
        max_length=16, choices=CaseStatus.choices,
        default=CaseStatus.REQUESTED, db_index=True,
    )

    # -- when --------------------------------------------------------------

    requested_at = models.DateTimeField(default=timezone.now)
    requested_by_id = models.UUIDField(null=True, blank=True)
    requested_by_name = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)

    scheduled_start = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    #: Booked length, so a list can be planned before anything happens.
    planned_minutes = models.PositiveSmallIntegerField(default=60)

    #: The event timings. Each one is a moment somebody records, and every
    #: productivity figure in this module is a difference between two of them.
    sent_for_at = models.DateTimeField(null=True, blank=True)
    wheels_in_at = models.DateTimeField(null=True, blank=True)
    anaesthesia_start_at = models.DateTimeField(null=True, blank=True)
    incision_at = models.DateTimeField(null=True, blank=True)
    closure_at = models.DateTimeField(null=True, blank=True)
    wheels_out_at = models.DateTimeField(null=True, blank=True)
    recovery_out_at = models.DateTimeField(null=True, blank=True)

    # -- how it ended ------------------------------------------------------

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(
        max_length=24, choices=CancellationReason.choices, blank=True,
        db_index=True,
    )
    cancellation_notes = models.CharField(max_length=512, blank=True)

    findings = models.TextField(blank=True)
    complications = models.TextField(blank=True)
    #: Estimated blood loss, millilitres. A number surgeons quote and
    #: registries collect.
    blood_loss_ml = models.PositiveIntegerField(null=True, blank=True)
    specimen_sent = models.BooleanField(default=False)
    specimen_detail = models.CharField(max_length=512, blank=True)
    post_op_instructions = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ot_case"
        ordering = ["-scheduled_start", "-requested_at"]
        constraints = [
            # A scheduled case has both ends of its slot or neither. A start
            # with no end cannot be checked for an overlap, so the row that
            # would silently escape the clash detection is refused instead.
            models.CheckConstraint(
                condition=(
                    models.Q(scheduled_start__isnull=True,
                             scheduled_end__isnull=True)
                    | models.Q(scheduled_start__isnull=False,
                               scheduled_end__isnull=False)
                ),
                name="ot_case_slot_has_both_ends",
            ),
        ]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["theatre", "scheduled_start"]),
            models.Index(fields=["patient", "-requested_at"]),
            models.Index(fields=["status", "scheduled_start"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.planned_procedure[:40]}"

    # -- derived timings ---------------------------------------------------

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_STATUSES

    @property
    def anaesthesia_minutes(self) -> int | None:
        """Anaesthesia start to wheels out. What the anaesthetist bills."""
        if not (self.anaesthesia_start_at and self.wheels_out_at):
            return None
        return int(
            (self.wheels_out_at - self.anaesthesia_start_at).total_seconds() // 60
        )

    @property
    def operating_minutes(self) -> int | None:
        """Incision to closure. What surgeons mean by 'the operation took'."""
        if not (self.incision_at and self.closure_at):
            return None
        return int((self.closure_at - self.incision_at).total_seconds() // 60)

    @property
    def theatre_minutes(self) -> int | None:
        """Wheels in to wheels out. What the room was actually occupied for.

        The figure that matters for utilisation, and reliably larger than the
        operating time — which is why booking a list on surgeons' estimates
        overruns it.
        """
        if not (self.wheels_in_at and self.wheels_out_at):
            return None
        return int((self.wheels_out_at - self.wheels_in_at).total_seconds() // 60)

    @property
    def start_delay_minutes(self) -> int | None:
        """How late the patient came into the room against the schedule.

        Negative when early. The first case of a list starting late is the
        most-studied waste in surgery, and it only exists as a number if the
        scheduled time is kept alongside the actual one.
        """
        if not (self.scheduled_start and self.wheels_in_at):
            return None
        return int(
            (self.wheels_in_at - self.scheduled_start).total_seconds() // 60
        )

    @property
    def overran_minutes(self) -> int | None:
        """Actual theatre time beyond what was booked."""
        actual = self.theatre_minutes
        if actual is None:
            return None
        return actual - self.planned_minutes

    @property
    def was_avoidable_cancellation(self) -> bool:
        return self.cancellation_reason in AVOIDABLE_REASONS

    def clean(self):
        order = [
            ("wheels_in_at", "wheels in"),
            ("anaesthesia_start_at", "anaesthesia"),
            ("incision_at", "incision"),
            ("closure_at", "closure"),
            ("wheels_out_at", "wheels out"),
        ]
        seen = None
        seen_label = ""
        for field, label in order:
            value = getattr(self, field)
            if value is None:
                continue
            if seen is not None and value < seen:
                raise ValidationError(
                    {field: f"{label} cannot be before {seen_label}."}
                )
            seen, seen_label = value, label


class TeamRole(models.TextChoices):
    """Who is in the room, and in what capacity.

    Enumerated because the roles are not interchangeable: an operating list
    without a scrub nurse does not run, and a case attributed to the wrong
    surgeon is a wrong outcome in somebody's audit.
    """

    PRIMARY_SURGEON = "surgeon", "Primary surgeon"
    ASSISTANT_SURGEON = "assistant", "Assistant surgeon"
    ANAESTHETIST = "anaesthetist", "Anaesthetist"
    ANAESTHETIC_ASSISTANT = "anaes_assistant", "Anaesthetic assistant"
    SCRUB_NURSE = "scrub_nurse", "Scrub nurse"
    CIRCULATING_NURSE = "circulating_nurse", "Circulating nurse"
    PERFUSIONIST = "perfusionist", "Perfusionist"
    RADIOGRAPHER = "radiographer", "Radiographer"
    OBSERVER = "observer", "Observer"
    TRAINEE = "trainee", "Trainee"


#: Roles without which a case cannot proceed.
REQUIRED_ROLES = {
    TeamRole.PRIMARY_SURGEON,
    TeamRole.ANAESTHETIST,
    TeamRole.SCRUB_NURSE,
}

#: Roles that must hold a current professional registration.
LICENSED_ROLES = {
    TeamRole.PRIMARY_SURGEON,
    TeamRole.ASSISTANT_SURGEON,
    TeamRole.ANAESTHETIST,
    TeamRole.SCRUB_NURSE,
    TeamRole.CIRCULATING_NURSE,
}


class TeamMember(BaseModel):
    """One person assigned to one case in one role."""

    case = models.ForeignKey(
        SurgicalCase, on_delete=models.CASCADE, related_name="team"
    )
    employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgical_assignments",
    )
    role = models.CharField(max_length=20, choices=TeamRole.choices)
    #: Snapshot, because the person may leave and the case record must still
    #: say who operated.
    name = models.CharField(max_length=255)
    registration_number = models.CharField(max_length=64, blank=True)

    scrubbed_in_at = models.DateTimeField(null=True, blank=True)
    scrubbed_out_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ot_team_member"
        ordering = ["role", "name"]
        constraints = [
            # One person per role per case for the roles that are singular.
            # Two primary surgeons is a data error; two assistants is normal.
            models.UniqueConstraint(
                fields=["case", "role"],
                condition=models.Q(
                    deleted_at__isnull=True,
                    role__in=["surgeon", "anaesthetist"],
                ),
                name="uniq_singular_role_per_case",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.get_role_display()}"


class ChecklistPhase(models.TextChoices):
    """The three phases of the WHO surgical safety checklist.

    Each happens at a specific moment and involves specific people, which is
    why they are three records rather than one form with a submit button.
    """

    SIGN_IN = "sign_in", "Sign in — before anaesthesia"
    TIME_OUT = "time_out", "Time out — before incision"
    SIGN_OUT = "sign_out", "Sign out — before leaving theatre"


#: The items each phase asks, in the order they are asked aloud.
#:
#: Data rather than a form template because a hospital adds its own items —
#: and because a checklist whose contents live in a React component cannot be
#: audited.
CHECKLIST_ITEMS = {
    ChecklistPhase.SIGN_IN: [
        "Patient has confirmed identity, site, procedure and consent",
        "Site marked, or not applicable",
        "Anaesthesia machine and medication check complete",
        "Pulse oximeter on the patient and functioning",
        "Known allergy?",
        "Difficult airway or aspiration risk?",
        "Risk of more than 500 ml blood loss?",
    ],
    ChecklistPhase.TIME_OUT: [
        "All team members have introduced themselves by name and role",
        "Surgeon, anaesthetist and nurse confirm patient, site and procedure",
        "Anticipated critical events reviewed by the surgeon",
        "Anaesthetic concerns reviewed",
        "Sterility confirmed, equipment issues raised",
        "Antibiotic prophylaxis given within the last 60 minutes",
        "Essential imaging displayed",
    ],
    ChecklistPhase.SIGN_OUT: [
        "Nurse confirms the name of the procedure recorded",
        "Instrument, swab and needle counts are correct",
        "Specimen labelled, including the patient's name",
        "Equipment problems identified and recorded",
        "Key concerns for recovery and management reviewed",
    ],
}


class SafetyChecklist(BaseModel):
    """One phase of the WHO checklist, performed and signed.

    A record rather than a form because the checklist works by being said
    aloud by a named person at a named moment. `completed_at` is when it was
    performed, and the case's own timings are what make an omission visible:
    an incision before the time-out is a fact this record makes undeniable.

    The system does not block the surgeon. A checklist that stops an operation
    gets bypassed within a week; one that records the bypass gets discussed at
    the next governance meeting.
    """

    case = models.ForeignKey(
        SurgicalCase, on_delete=models.CASCADE, related_name="checklists"
    )
    phase = models.CharField(
        max_length=16, choices=ChecklistPhase.choices, db_index=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_id = models.UUIDField(null=True, blank=True)
    completed_by_name = models.CharField(max_length=255, blank=True)

    #: `{item text: bool}`. A dict rather than a row per item because the
    #: items are a template that changes and the answers are a snapshot of
    #: what was asked *that day*.
    responses = models.JSONField(default=dict, blank=True)
    concerns = models.TextField(blank=True)
    #: Set when the phase was skipped rather than performed. Recorded, never
    #: silently absent.
    was_skipped = models.BooleanField(default=False)
    skip_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "ot_safety_checklist"
        ordering = ["case_id", "phase"]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "phase"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_checklist_phase_per_case",
            )
        ]

    def __str__(self):
        return f"{self.case.reference} {self.phase}"

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None and not self.was_skipped

    @property
    def unanswered(self) -> list:
        """Items in the template that this record does not answer."""
        expected = CHECKLIST_ITEMS.get(self.phase, [])
        return [item for item in expected if item not in (self.responses or {})]

    @property
    def negative_answers(self) -> list:
        """Items answered 'no'. Not all are problems — some are questions."""
        return [
            item for item, answer in (self.responses or {}).items()
            if answer is False
        ]


class ConsumptionKind(models.TextChoices):
    CONSUMABLE = "consumable", "Consumable"
    IMPLANT = "implant", "Implant"
    DRUG = "drug", "Drug"
    BLOOD = "blood", "Blood product"


class CaseConsumption(BaseModel):
    """Something used in the case, taken from real stock.

    Implants carry a serial number and a lot number. When a batch of
    prostheses is recalled the question is "which patients have one", and the
    only acceptable answer is a list of names — which needs the serial, not
    just the product.
    """

    case = models.ForeignKey(
        SurgicalCase, on_delete=models.CASCADE, related_name="consumption"
    )
    kind = models.CharField(
        max_length=16, choices=ConsumptionKind.choices,
        default=ConsumptionKind.CONSUMABLE, db_index=True,
    )
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.PROTECT,
        related_name="theatre_consumption",
    )
    batch = models.ForeignKey(
        Batch, null=True, blank=True, on_delete=models.PROTECT,
        related_name="theatre_consumption",
    )
    #: Snapshots, so a recall search does not depend on the product still
    #: existing under the same name.
    description = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=64, blank=True)
    #: The individual device. Unique per implant, which is the whole point.
    serial_number = models.CharField(max_length=128, blank=True, db_index=True)
    manufacturer = models.CharField(max_length=255, blank=True)
    expires_on = models.DateField(null=True, blank=True)

    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal("1.000")
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    total_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    #: The ledger movement this produced, so stock and theatre reconcile.
    stock_entry_uuid = models.UUIDField(null=True, blank=True)
    #: The billing charge, likewise.
    charge_uuid = models.UUIDField(null=True, blank=True)

    implanted_site = models.CharField(max_length=128, blank=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_name = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ot_case_consumption"
        ordering = ["kind", "description"]
        constraints = [
            # One physical device, one patient. A serial number appearing
            # twice means either a data-entry error or a counterfeit, and both
            # are things a hospital needs to know at the moment of entry
            # rather than at the moment of a recall.
            models.UniqueConstraint(
                fields=["serial_number"],
                condition=models.Q(
                    deleted_at__isnull=True,
                    kind="implant",
                ) & ~models.Q(serial_number=""),
                name="uniq_implant_serial",
            )
        ]
        indexes = [
            models.Index(fields=["case", "kind"]),
            models.Index(fields=["serial_number"]),
            models.Index(fields=["batch", "kind"]),
        ]

    def __str__(self):
        return f"{self.description} × {self.quantity}"


class AnaesthesiaType(models.TextChoices):
    GENERAL = "general", "General"
    SPINAL = "spinal", "Spinal"
    EPIDURAL = "epidural", "Epidural"
    REGIONAL = "regional", "Regional block"
    LOCAL = "local", "Local infiltration"
    SEDATION = "sedation", "Sedation"
    COMBINED = "combined", "Combined"
    NONE = "none", "None"


class AnaesthesiaRecord(BaseModel):
    """The anaesthetist's record of the case.

    Separate from the surgical record because it is a different clinician's
    document with a different retention requirement, and because in a dispute
    the two are read independently.
    """

    case = models.OneToOneField(
        SurgicalCase, on_delete=models.CASCADE, related_name="anaesthesia"
    )
    anaesthesia_type = models.CharField(
        max_length=16, choices=AnaesthesiaType.choices,
        default=AnaesthesiaType.GENERAL,
    )
    airway = models.CharField(
        max_length=64, blank=True,
        help_text="Endotracheal tube, LMA, face mask, none.",
    )
    intubation_attempts = models.PositiveSmallIntegerField(null=True, blank=True)
    was_difficult_airway = models.BooleanField(default=False)
    difficult_airway_detail = models.CharField(max_length=512, blank=True)

    #: Fluids in and out, millilitres.
    crystalloid_ml = models.PositiveIntegerField(default=0)
    colloid_ml = models.PositiveIntegerField(default=0)
    blood_ml = models.PositiveIntegerField(default=0)
    urine_output_ml = models.PositiveIntegerField(default=0)

    lowest_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    lowest_spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    adverse_events = models.TextField(blank=True)
    reversal_given = models.BooleanField(default=False)
    post_op_analgesia = models.CharField(max_length=512, blank=True)

    anaesthetist_id = models.UUIDField(null=True, blank=True)
    anaesthetist_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ot_anaesthesia_record"

    def __str__(self):
        return f"Anaesthesia for {self.case.reference}"

    @property
    def total_input_ml(self) -> int:
        return self.crystalloid_ml + self.colloid_ml + self.blood_ml


class RecoveryRecord(BaseModel):
    """Post-anaesthesia care, and the score that decides discharge.

    The Aldrete score is what a recovery nurse actually uses to decide whether
    somebody can leave, so it is a field rather than a note — a threshold you
    cannot query is a threshold nobody audits.
    """

    case = models.OneToOneField(
        SurgicalCase, on_delete=models.CASCADE, related_name="recovery"
    )
    arrived_at = models.DateTimeField(default=timezone.now)
    discharged_at = models.DateTimeField(null=True, blank=True)

    #: Aldrete score, 0–10. Ten is fully recovered; most units discharge at 9.
    aldrete_score = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    had_nausea = models.BooleanField(default=False)
    had_shivering = models.BooleanField(default=False)
    complications = models.TextField(blank=True)

    discharged_to = models.CharField(
        max_length=32,
        choices=[
            ("ward", "Ward"), ("icu", "Intensive care"),
            ("hdu", "High dependency"), ("home", "Home"),
            ("day_unit", "Day-case unit"),
        ],
        blank=True,
    )
    nurse_id = models.UUIDField(null=True, blank=True)
    nurse_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ot_recovery_record"

    def __str__(self):
        return f"Recovery for {self.case.reference}"

    @property
    def minutes_in_recovery(self) -> int | None:
        if not self.discharged_at:
            return None
        return int(
            (self.discharged_at - self.arrived_at).total_seconds() // 60
        )
