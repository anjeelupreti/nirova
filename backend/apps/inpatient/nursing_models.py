"""Nursing domain models: assignment, eMAR, SBAR handover, and shift tasks.

Built for the bedside:
1. NurseAssignment: Who is looking after which bed on which shift.
2. MedicationAdministration: eMAR record keeping doctor order separate from bedside execution.
3. NursingHandover: SBAR structured shift handover ensuring zero loss of continuity.
4. NursingTask: Shift duties, dressings, monitoring and line checks.
"""

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class ShiftChoice(models.TextChoices):
    MORNING = "morning", "Morning (07:00 – 15:00)"
    EVENING = "evening", "Evening (15:00 – 23:00)"
    NIGHT = "night", "Night (23:00 – 07:00)"


class NurseRole(models.TextChoices):
    PRIMARY = "primary", "Primary bedside nurse"
    BUDDY = "buddy", "Buddy / Relief nurse"
    CHARGE = "charge", "Charge / In-charge nurse"


class NurseAssignment(BaseModel):
    """Assignment of a nurse to a patient/bed for a specific date and shift.

    When a nurse arrives on shift, their workspace defaults to the patients
    assigned here.
    """

    admission = models.ForeignKey(
        "inpatient.Admission",
        on_delete=models.CASCADE,
        related_name="nurse_assignments",
        null=True,
        blank=True,
    )
    ward = models.ForeignKey(
        "inpatient.Ward",
        on_delete=models.CASCADE,
        related_name="nurse_assignments",
    )
    bed = models.ForeignKey(
        "inpatient.Bed",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nurse_assignments",
    )
    nurse_id = models.UUIDField(db_index=True)
    nurse_name = models.CharField(max_length=255)
    assigned_date = models.DateField(db_index=True)
    shift = models.CharField(
        max_length=16,
        choices=ShiftChoice.choices,
        default=ShiftChoice.MORNING,
        db_index=True,
    )
    role = models.CharField(
        max_length=16,
        choices=NurseRole.choices,
        default=NurseRole.PRIMARY,
    )
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)
    assigned_by_id = models.UUIDField(null=True, blank=True)
    assigned_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ipd_nurse_assignment"
        ordering = ["-assigned_date", "shift", "nurse_name"]
        indexes = [
            models.Index(fields=["nurse_id", "assigned_date", "shift"]),
            models.Index(fields=["ward", "assigned_date", "shift"]),
            models.Index(fields=["admission", "assigned_date", "shift"]),
        ]

    def __str__(self):
        return f"{self.nurse_name} -> {self.ward.name} ({self.shift} {self.assigned_date})"


class AdministrationStatus(models.TextChoices):
    GIVEN = "given", "Given"
    HELD = "held", "Held"
    REFUSED = "refused", "Refused by patient"
    OMITTED = "omitted", "Omitted / Missed"


class MedicationAdministration(BaseModel):
    """Electronic Medication Administration Record (eMAR).

    A prescription line is an *order*; this is the physical *administration*.
    Held and refused doses must record a clinical reason (e.g. 'SBP < 90', 'Patient vomiting').
    High-alert medications support dual-signing with a witness nurse.
    """

    admission = models.ForeignKey(
        "inpatient.Admission",
        on_delete=models.CASCADE,
        related_name="medication_administrations",
    )
    encounter = models.ForeignKey(
        "encounters.Encounter",
        on_delete=models.CASCADE,
        related_name="medication_administrations",
        null=True,
        blank=True,
    )
    prescription_line = models.ForeignKey(
        "prescriptions.PrescriptionLine",
        on_delete=models.CASCADE,
        related_name="administrations",
    )
    medicine_name = models.CharField(max_length=255)
    scheduled_time = models.DateTimeField(db_index=True)
    administered_at = models.DateTimeField(default=timezone.now, db_index=True)
    administered_by_id = models.UUIDField(db_index=True)
    administered_by_name = models.CharField(max_length=255)
    dose_given = models.CharField(max_length=64)
    route = models.CharField(max_length=16, default="PO")
    status = models.CharField(
        max_length=16,
        choices=AdministrationStatus.choices,
        default=AdministrationStatus.GIVEN,
        db_index=True,
    )
    reason = models.CharField(
        max_length=512,
        blank=True,
        help_text="Mandatory clinical rationale if held, refused or omitted.",
    )
    injection_site = models.CharField(
        max_length=128,
        blank=True,
        help_text="Anatomical site for injectables (e.g. Left deltoid, Abdomen).",
    )
    witness_by_id = models.UUIDField(null=True, blank=True)
    witness_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Second nurse sign-off for high-alert drugs.",
    )
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "ipd_medication_administration"
        ordering = ["-administered_at"]
        indexes = [
            models.Index(fields=["admission", "-administered_at"]),
            models.Index(fields=["prescription_line", "-administered_at"]),
            models.Index(fields=["status", "-administered_at"]),
        ]

    def __str__(self):
        return f"{self.medicine_name} ({self.status}) @ {self.administered_at:%Y-%m-%d %H:%M}"


class CodeStatusChoice(models.TextChoices):
    FULL_CODE = "full_code", "Full resuscitation (CPR)"
    DNR = "dnr", "Do Not Resuscitate (DNR / AND)"
    DNI = "dni", "Do Not Intubate"


class NursingHandover(BaseModel):
    """Structured SBAR shift handover note between outgoing and incoming nurses.

    Ensures zero clinical context loss between shifts:
    - S: Situation (current condition, reason for admission, acute concerns)
    - B: Background (diagnoses, surgeries, history, allergies, code status)
    - A: Assessment (vital trends, NEWS2 score, lines/drains, fluid balance)
    - R: Recommendation (pending tests, scheduled infusions, consults)
    """

    admission = models.ForeignKey(
        "inpatient.Admission",
        on_delete=models.CASCADE,
        related_name="handovers",
    )
    ward = models.ForeignKey(
        "inpatient.Ward",
        on_delete=models.CASCADE,
        related_name="handovers",
    )
    shift_date = models.DateField(default=timezone.now, db_index=True)
    shift = models.CharField(
        max_length=16,
        choices=ShiftChoice.choices,
        default=ShiftChoice.MORNING,
        db_index=True,
    )
    outgoing_nurse_id = models.UUIDField(db_index=True)
    outgoing_nurse_name = models.CharField(max_length=255)
    code_status = models.CharField(
        max_length=16,
        choices=CodeStatusChoice.choices,
        default=CodeStatusChoice.FULL_CODE,
    )

    # -- SBAR Structured Content ------------------------------------------
    situation = models.TextField(help_text="Current clinical state and immediate concerns.")
    background = models.TextField(blank=True, help_text="History, surgeries, allergies, code status.")
    assessment = models.TextField(help_text="Vitals, NEWS2 score, IV lines/catheters/drains, fluid balance.")
    recommendation = models.TextField(help_text="Plan for next shift, pending labs/imaging, consults.")

    # -- Receipt / Sign-off -----------------------------------------------
    is_acknowledged = models.BooleanField(default=False, db_index=True)
    incoming_nurse_id = models.UUIDField(null=True, blank=True)
    incoming_nurse_name = models.CharField(max_length=255, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ipd_nursing_handover"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["admission", "-shift_date"]),
            models.Index(fields=["ward", "-shift_date"]),
            models.Index(fields=["is_acknowledged", "-shift_date"]),
        ]

    def __str__(self):
        return f"Handover: {self.admission.reference} ({self.shift} {self.shift_date})"


class TaskCategory(models.TextChoices):
    VITALS = "vitals", "Vitals & Monitoring"
    MEDICATION = "medication", "Medication & Infusion"
    WOUND_CARE = "wound_care", "Wound & Dressing"
    FLUID_BALANCE = "fluid_balance", "Fluid & Intake/Output"
    HYGIENE = "hygiene", "Hygiene & Skin/Positioning"
    GENERAL = "general", "General Nursing Care"


class TaskStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class NursingTask(BaseModel):
    """Bedside operational duties and care actions due during a shift."""

    admission = models.ForeignKey(
        "inpatient.Admission",
        on_delete=models.CASCADE,
        related_name="nursing_tasks",
    )
    ward = models.ForeignKey(
        "inpatient.Ward",
        on_delete=models.CASCADE,
        related_name="nursing_tasks",
    )
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=20,
        choices=TaskCategory.choices,
        default=TaskCategory.GENERAL,
        db_index=True,
    )
    shift = models.CharField(
        max_length=16,
        blank=True,
        help_text="Target shift ('morning', 'evening', 'night') or blank for any.",
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
        db_index=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_id = models.UUIDField(null=True, blank=True)
    completed_by_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ipd_nursing_task"
        ordering = ["due_at", "-created_at"]
        indexes = [
            models.Index(fields=["admission", "status"]),
            models.Index(fields=["ward", "status"]),
            models.Index(fields=["status", "due_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.status}) - {self.admission.reference}"
