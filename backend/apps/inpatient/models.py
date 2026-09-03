"""Inpatient care: wards, beds, admissions, and the days in between.

An outpatient encounter is an event; an admission is a *duration*, and almost
every difference in this module follows from that.

**A bed is occupied over an interval, not by a flag.** `BedAssignment` records
who was in which bed from when to when. A boolean `is_occupied` on the bed
would answer "is it free now?" and permanently destroy "who was in bed 4 on
the night of the 14th?" — which is the question asked after a fall, an
infection outbreak, or a billing dispute.

**Charges accrue daily, and accrual is idempotent.** A three-week stay is
three weeks of bed charges, diet, nursing. The accrual job runs every night
and may run twice; charging twice for a Tuesday is the failure it is built to
prevent.

**Discharge is a process, not a status change.** Clearance from pharmacy, an
outstanding balance, medicines to take home, a summary to write. A discharge
that flipped a flag would let a patient leave with an unreconciled bill and no
discharge summary, which is how hospitals lose money and get sued in the same
afternoon.

**Transfer is an event.** Moving a patient between beds or wards writes a new
assignment and closes the old one, exactly as an HR transfer writes an event
rather than overwriting a department.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.organization.models import Department, Facility, Unit
from apps.patients.models import Patient

ZERO = Decimal("0.00")


class WardType(models.TextChoices):
    """What kind of ward it is.

    Drives staffing ratios, visiting rules and, most practically, the tariff:
    a bed in the ICU and a bed on a general ward are the same object and a
    tenfold difference in price.
    """

    GENERAL = "general", "General ward"
    PRIVATE = "private", "Private room"
    SEMI_PRIVATE = "semi_private", "Semi-private"
    DELUXE = "deluxe", "Deluxe"
    ICU = "icu", "Intensive care"
    NICU = "nicu", "Neonatal intensive care"
    PICU = "picu", "Paediatric intensive care"
    HDU = "hdu", "High dependency"
    MATERNITY = "maternity", "Maternity"
    ISOLATION = "isolation", "Isolation"
    BURN = "burn", "Burns"
    PSYCHIATRIC = "psychiatric", "Psychiatric"
    DAY_CARE = "day_care", "Day care"
    EMERGENCY = "emergency", "Emergency observation"


class Ward(BaseModel):
    """A named collection of beds under one nursing team.

    Sits alongside `Unit` rather than replacing it: a unit is the
    organizational box a ward belongs to, and a ward is the clinical object
    that has beds, a nurse-to-patient ratio and a tariff. A hospital with one
    "Medical" unit can run three wards inside it.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    ward_type = models.CharField(
        max_length=20, choices=WardType.choices, default=WardType.GENERAL,
        db_index=True,
    )

    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, related_name="wards"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="wards",
    )
    unit = models.ForeignKey(
        Unit, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="wards",
    )

    floor = models.CharField(max_length=32, blank=True)
    building = models.CharField(max_length=64, blank=True)

    #: Nurses per patient this ward is meant to run at. Recorded so an
    #: understaffed shift is visible as a number rather than as a feeling.
    nurse_to_patient_ratio = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("6.00"),
        help_text="Patients per nurse.",
    )
    #: Whether a male patient may be placed in a female bay and vice versa.
    #: Enforced at admission, because discovering it at the bedside is worse.
    is_gender_segregated = models.BooleanField(default=True)
    allows_attendant = models.BooleanField(
        default=True,
        help_text="Whether a family attendant may stay overnight.",
    )
    visiting_hours = models.CharField(max_length=128, blank=True)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ipd_ward"
        ordering = ["facility_id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_ward_code_per_facility",
            )
        ]
        indexes = [models.Index(fields=["facility", "ward_type", "is_active"])]

    def __str__(self):
        return f"{self.name} ({self.get_ward_type_display()})"

    @property
    def bed_count(self) -> int:
        return self.beds.filter(is_active=True).count()

    @property
    def is_critical_care(self) -> bool:
        """Whether this ward's beds need continuous monitoring.

        Used for staffing rules and for the discharge checks: a patient does
        not go home directly from an ICU bed without a step-down decision.
        """
        return self.ward_type in {
            WardType.ICU, WardType.NICU, WardType.PICU, WardType.HDU,
            WardType.BURN,
        }


class BedStatus(models.TextChoices):
    """The physical state of a bed, which is not the same as occupancy.

    A bed under maintenance is unoccupied and unusable; a bed being cleaned is
    unoccupied and about to be usable. Collapsing these into "free" is how a
    patient gets sent to a bed with the previous patient's linen on it.
    """

    AVAILABLE = "available", "Available"
    OCCUPIED = "occupied", "Occupied"
    RESERVED = "reserved", "Reserved"
    CLEANING = "cleaning", "Being cleaned"
    MAINTENANCE = "maintenance", "Under maintenance"
    BLOCKED = "blocked", "Blocked"


#: Statuses in which a bed can take a new patient.
ASSIGNABLE_STATUSES = {BedStatus.AVAILABLE}


class Gender(models.TextChoices):
    ANY = "any", "Any"
    MALE = "male", "Male"
    FEMALE = "female", "Female"


class Bed(BaseModel):
    """One bed.

    `status` is the *physical* state — clean, dirty, broken. Whether somebody
    is in it right now is answered by `BedAssignment`, and the two are kept
    apart because a bed being unoccupied does not make it usable.
    """

    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    code = models.CharField(max_length=32, db_index=True)
    bay = models.CharField(
        max_length=32, blank=True,
        help_text="Room or bay within the ward.",
    )

    status = models.CharField(
        max_length=16, choices=BedStatus.choices,
        default=BedStatus.AVAILABLE, db_index=True,
    )
    status_reason = models.CharField(max_length=255, blank=True)
    status_changed_at = models.DateTimeField(default=timezone.now)

    #: Restricts who may be placed here. A bay designated female stays female
    #: even when the hospital is full, which is the point of recording it.
    gender_restriction = models.CharField(
        max_length=8, choices=Gender.choices, default=Gender.ANY
    )
    has_oxygen = models.BooleanField(default=False)
    has_suction = models.BooleanField(default=False)
    has_monitor = models.BooleanField(default=False)
    has_ventilator = models.BooleanField(default=False)
    is_isolation = models.BooleanField(default=False)

    #: What this bed costs per day. Held on the bed rather than only on the
    #: ward because a hospital will price the two window beds differently and
    #: creating a one-bed ward to express that is worse.
    daily_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    #: The billable service this bed's daily charge posts against. Null falls
    #: back to the ward's, and a missing one is reported at accrual rather
    #: than silently producing a free stay.
    service_code = models.CharField(max_length=32, blank=True)

    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ipd_bed"
        ordering = ["ward_id", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["ward", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_bed_code_per_ward",
            )
        ]
        indexes = [
            models.Index(fields=["ward", "status"]),
            models.Index(fields=["status", "is_active"]),
        ]

    def __str__(self):
        return f"{self.ward.code}/{self.code}"

    @property
    def current_assignment(self):
        """Who is in it now, or None."""
        return self.assignments.filter(vacated_at__isnull=True).first()

    @property
    def is_occupied(self) -> bool:
        return self.current_assignment is not None

    @property
    def is_assignable(self) -> bool:
        return (
            self.is_active
            and self.status in ASSIGNABLE_STATUSES
            and not self.is_occupied
        )


class AdmissionStatus(models.TextChoices):
    PENDING = "pending", "Awaiting a bed"
    ADMITTED = "admitted", "Admitted"
    DISCHARGE_INITIATED = "discharge_initiated", "Discharge in progress"
    DISCHARGED = "discharged", "Discharged"
    ABSCONDED = "absconded", "Absconded"
    LAMA = "lama", "Left against medical advice"
    TRANSFERRED_OUT = "transferred_out", "Transferred to another hospital"
    DIED = "died", "Died"
    CANCELLED = "cancelled", "Cancelled"


#: Statuses in which the patient is physically in the hospital.
IN_HOUSE_STATUSES = {
    AdmissionStatus.ADMITTED,
    AdmissionStatus.DISCHARGE_INITIATED,
}

#: Outcomes that end an admission. Enumerated distinctly because they are
#: reported distinctly: a hospital's mortality rate, its LAMA rate and its
#: absconder rate are three different conversations with a regulator.
CLOSED_STATUSES = {
    AdmissionStatus.DISCHARGED,
    AdmissionStatus.ABSCONDED,
    AdmissionStatus.LAMA,
    AdmissionStatus.TRANSFERRED_OUT,
    AdmissionStatus.DIED,
    AdmissionStatus.CANCELLED,
}


class AdmissionSource(models.TextChoices):
    OPD = "opd", "From outpatients"
    EMERGENCY = "emergency", "From emergency"
    REFERRAL = "referral", "Referred in"
    TRANSFER = "transfer", "Transferred from another hospital"
    DIRECT = "direct", "Direct admission"
    BIRTH = "birth", "Born here"


class Admission(BaseModel):
    """One inpatient stay.

    Attached to an `Encounter` of type `inpatient`, so the clinical record —
    notes, prescriptions, orders, charges — hangs off the same object as an
    outpatient visit does. The admission adds what only a stay has: a bed, a
    length, a diet, an attendant, a discharge.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="admissions"
    )
    encounter = models.OneToOneField(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="admission",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="admissions"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="admissions",
    )

    status = models.CharField(
        max_length=24, choices=AdmissionStatus.choices,
        default=AdmissionStatus.PENDING, db_index=True,
    )
    source = models.CharField(
        max_length=16, choices=AdmissionSource.choices,
        default=AdmissionSource.OPD,
    )

    admitted_at = models.DateTimeField(default=timezone.now, db_index=True)
    discharged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    expected_discharge = models.DateField(null=True, blank=True)

    #: Who is responsible. A bare uuid because the consultant is an identity
    #: user resolved through `apps.hr` — the same linkage as everywhere else.
    consultant_id = models.UUIDField(null=True, blank=True, db_index=True)
    consultant_name = models.CharField(max_length=255, blank=True)
    admitting_diagnosis = models.CharField(max_length=512, blank=True)
    provisional_diagnosis = models.CharField(max_length=512, blank=True)
    final_diagnosis = models.CharField(max_length=512, blank=True)

    #: Who to call and who is staying. A Nepali hospital admission is a family
    #: event; the attendant is a real person with a real bed-side pass.
    attendant_name = models.CharField(max_length=255, blank=True)
    attendant_phone = models.CharField(max_length=32, blank=True)
    attendant_relation = models.CharField(max_length=64, blank=True)
    attendant_citizenship = models.CharField(max_length=32, blank=True)

    #: Money taken up front against the bill. Nepali private hospitals almost
    #: always take one, and it is applied at discharge.
    deposit_expected = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )

    diet_plan = models.CharField(max_length=128, blank=True)
    is_mlc = models.BooleanField(
        default=False,
        help_text="Medico-legal case: assault, accident, poisoning, burns.",
    )
    mlc_number = models.CharField(max_length=64, blank=True)
    police_informed_at = models.DateTimeField(null=True, blank=True)

    #: How the stay ended, in the patient's own interest as well as the
    #: hospital's — a LAMA needs a signed form, a death needs a certificate.
    outcome_notes = models.TextField(blank=True)
    discharge_summary = models.TextField(blank=True)
    discharge_advice = models.TextField(blank=True)
    follow_up_on = models.DateField(null=True, blank=True)

    cancelled_reason = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ipd_admission"
        ordering = ["-admitted_at"]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["patient", "-admitted_at"]),
            models.Index(fields=["status", "-admitted_at"]),
            models.Index(fields=["consultant_id", "-admitted_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.patient.full_name}"

    @property
    def is_in_house(self) -> bool:
        return self.status in IN_HOUSE_STATUSES

    @property
    def current_bed(self):
        assignment = self.bed_assignments.filter(vacated_at__isnull=True).first()
        return assignment.bed if assignment else None

    @property
    def length_of_stay_days(self) -> int:
        """Days counted the way a hospital bills them.

        A patient admitted at 23:00 and discharged at 09:00 the next morning
        has stayed one day, not zero — the bed was unavailable for a night.
        So the count is of *nights*, floored at one for any stay at all.
        """
        end = self.discharged_at or timezone.now()
        nights = (end.date() - self.admitted_at.date()).days
        return max(nights, 1)

    @property
    def is_overstaying(self) -> bool:
        """Past the expected discharge date and still here.

        Worth surfacing: an overstay is usually either a clinical
        deterioration nobody escalated or a discharge nobody completed, and
        both are things a ward round should be told about.
        """
        if not self.expected_discharge or not self.is_in_house:
            return False
        return timezone.localdate() > self.expected_discharge

    def clean(self):
        if self.discharged_at and self.discharged_at < self.admitted_at:
            raise ValidationError(
                {"discharged_at": "A patient cannot leave before they arrive."}
            )


class BedAssignment(BaseModel):
    """Who was in which bed, from when to when.

    The whole reason a bed does not carry an `is_occupied` flag. An open
    assignment — `vacated_at` null — is the current occupant; a closed one is
    history, and history is what answers a question about the night of the
    fourteenth.
    """

    admission = models.ForeignKey(
        Admission, on_delete=models.CASCADE, related_name="bed_assignments"
    )
    bed = models.ForeignKey(
        Bed, on_delete=models.PROTECT, related_name="assignments"
    )
    ward = models.ForeignKey(
        Ward, on_delete=models.PROTECT, related_name="assignments"
    )

    occupied_at = models.DateTimeField(default=timezone.now, db_index=True)
    vacated_at = models.DateTimeField(null=True, blank=True, db_index=True)

    #: The rate captured at the time. The bed's price may be revised next
    #: month; what this patient was charged for last Tuesday must not move.
    daily_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )

    reason = models.CharField(
        max_length=255, blank=True,
        help_text="Why they were moved here, for a transfer.",
    )
    assigned_by_id = models.UUIDField(null=True, blank=True)
    assigned_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ipd_bed_assignment"
        ordering = ["-occupied_at"]
        constraints = [
            # One live occupant per bed. Two patients in one bed is a data
            # error that produces a real safety incident, so the database
            # refuses it rather than trusting the service layer alone.
            models.UniqueConstraint(
                fields=["bed"],
                condition=models.Q(vacated_at__isnull=True,
                                   deleted_at__isnull=True),
                name="uniq_live_assignment_per_bed",
            ),
            # And one bed per admission, for the mirror reason.
            models.UniqueConstraint(
                fields=["admission"],
                condition=models.Q(vacated_at__isnull=True,
                                   deleted_at__isnull=True),
                name="uniq_live_bed_per_admission",
            ),
        ]
        indexes = [
            models.Index(fields=["admission", "-occupied_at"]),
            models.Index(fields=["bed", "-occupied_at"]),
            models.Index(fields=["ward", "vacated_at"]),
        ]

    def __str__(self):
        return f"{self.admission.reference} in {self.bed}"

    @property
    def is_current(self) -> bool:
        return self.vacated_at is None

    @property
    def nights(self) -> int:
        end = self.vacated_at or timezone.now()
        return max((end.date() - self.occupied_at.date()).days, 1)


class AccrualKind(models.TextChoices):
    """What a daily accrual was for.

    Enumerated so an inpatient bill can be read by category — bed, nursing,
    diet — which is exactly how a patient queries it.
    """

    BED = "bed", "Bed"
    NURSING = "nursing", "Nursing"
    DIET = "diet", "Diet"
    ATTENDANT = "attendant", "Attendant"
    SERVICE = "service", "Service"


class DailyAccrual(BaseModel):
    """One day's recurring charge on one admission.

    Exists so accrual can be **idempotent**. The nightly job may run twice,
    be re-run after a failure, or be triggered by hand for a missed day, and
    charging a patient twice for a Tuesday is the failure this table prevents:
    the unique constraint refuses the second attempt rather than relying on
    nobody clicking twice.
    """

    admission = models.ForeignKey(
        Admission, on_delete=models.CASCADE, related_name="accruals"
    )
    accrual_date = models.DateField(db_index=True)
    kind = models.CharField(
        max_length=16, choices=AccrualKind.choices, default=AccrualKind.BED
    )

    #: The bed occupied on that date, for a bed accrual. Null for anything
    #: not tied to a bed.
    bed_assignment = models.ForeignKey(
        BedAssignment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="accruals",
    )
    service_code = models.CharField(max_length=32, blank=True)
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("1.00")
    )
    unit_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    #: The billing charge this produced, so the accrual and the bill can be
    #: reconciled without guessing.
    charge_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ipd_daily_accrual"
        ordering = ["-accrual_date", "kind"]
        constraints = [
            # One accrual per admission, per day, per kind. This is the whole
            # idempotence guarantee.
            models.UniqueConstraint(
                fields=["admission", "accrual_date", "kind"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_accrual_per_admission_day_kind",
            )
        ]
        indexes = [models.Index(fields=["admission", "-accrual_date"])]

    def __str__(self):
        return f"{self.admission.reference} {self.accrual_date} {self.kind}"


class ClearanceKind(models.TextChoices):
    """The things that must be settled before somebody leaves.

    Discharge is a process, not a flag, and this enumerates the process. Each
    is a real department that has to say yes, and a hospital that skipped them
    loses money on unreturned equipment and unbilled medicines.
    """

    CLINICAL = "clinical", "Clinical sign-off"
    NURSING = "nursing", "Nursing handover"
    PHARMACY = "pharmacy", "Pharmacy — returns and take-home"
    BILLING = "billing", "Billing settled"
    DIET = "diet", "Dietary stopped"
    HOUSEKEEPING = "housekeeping", "Bed released for cleaning"
    RECORDS = "records", "Discharge summary filed"


class DischargeClearance(BaseModel):
    """One department's sign-off on a discharge.

    Recorded per department rather than as a single "cleared" flag so that a
    discharge stuck for two hours has a nameable reason — and a name attached
    to it.
    """

    admission = models.ForeignKey(
        Admission, on_delete=models.CASCADE, related_name="clearances"
    )
    kind = models.CharField(
        max_length=16, choices=ClearanceKind.choices, db_index=True
    )
    is_cleared = models.BooleanField(default=False)
    cleared_by_id = models.UUIDField(null=True, blank=True)
    cleared_by_name = models.CharField(max_length=255, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    blocking_reason = models.CharField(max_length=512, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "ipd_discharge_clearance"
        ordering = ["kind"]
        constraints = [
            models.UniqueConstraint(
                fields=["admission", "kind"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_clearance_per_admission_kind",
            )
        ]

    def __str__(self):
        state = "cleared" if self.is_cleared else "pending"
        return f"{self.admission.reference} {self.kind}: {state}"


class NursingRound(BaseModel):
    """An observation entry made at the bedside.

    Vitals live on the encounter, where every other clinical observation
    does. What is here is what only an inpatient has: which shift, which
    nurse, and the intake-output balance that a ward round actually reads.
    """

    admission = models.ForeignKey(
        Admission, on_delete=models.CASCADE, related_name="rounds"
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)
    shift = models.CharField(
        max_length=16,
        choices=[
            ("morning", "Morning"),
            ("evening", "Evening"),
            ("night", "Night"),
        ],
        blank=True,
    )
    nurse_id = models.UUIDField(null=True, blank=True)
    nurse_name = models.CharField(max_length=255, blank=True)

    #: Millilitres. Fluid balance is the number that gets a deteriorating
    #: patient noticed, and it is only meaningful cumulatively — which is why
    #: it is recorded per round rather than as a running total somebody edits.
    intake_ml = models.PositiveIntegerField(default=0)
    output_ml = models.PositiveIntegerField(default=0)

    pain_score = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="0–10."
    )
    observations = models.TextField(blank=True)
    interventions = models.TextField(blank=True)
    #: Set when the nurse wants a doctor. The point of a flag rather than a
    #: note is that it can be listed.
    escalated = models.BooleanField(default=False)
    escalation_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "ipd_nursing_round"
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["admission", "-recorded_at"]),
            models.Index(fields=["escalated", "-recorded_at"]),
        ]

    def __str__(self):
        return f"{self.admission.reference} at {self.recorded_at:%Y-%m-%d %H:%M}"

    @property
    def balance_ml(self) -> int:
        return self.intake_ml - self.output_ml
