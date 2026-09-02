"""Diagnostics: laboratory and radiology, ordered and reported.

One app for both, because the *workflow* is the same shape — order, collect
or acquire, process, report, verify, release — and the differences are in the
middle. A blood test has a specimen; a chest X-ray has an image. Splitting
them into two apps would duplicate the ordering, the result routing, the
critical-value escalation and the charge capture, and would make a panel that
contains both (a "pre-operative screen" with bloods and a chest film)
impossible to express.

Two properties shape everything here.

**A result is a clinical statement with an author.** It is entered by one
person and *verified* by another before anyone acts on it. Unverified results
are visible but marked, because a clinician waiting on a potassium should be
able to see the preliminary number — while knowing it is preliminary.

**A critical value is an event, not a flag.** A potassium of 7.1 does not just
render in red; it obliges someone to pick up a phone, and the system has to
record that they did, whom they told, and when. `CriticalValueAlert` exists
because "the result was in the system" is not a defence when nobody looked.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.organization.models import Department, Facility
from apps.patients.models import Patient


class DiagnosticModality(models.TextChoices):
    """What kind of investigation this is.

    Radiology modalities are named individually rather than lumped under
    "imaging" because they schedule differently, cost differently, and a
    worklist is always per modality — a radiographer runs the CT scanner, not
    "imaging".
    """

    LABORATORY = "laboratory", "Laboratory"
    XRAY = "xray", "X-ray"
    ULTRASOUND = "ultrasound", "Ultrasound"
    CT = "ct", "CT"
    MRI = "mri", "MRI"
    MAMMOGRAPHY = "mammography", "Mammography"
    ECG = "ecg", "ECG"
    ECHO = "echo", "Echocardiography"
    ENDOSCOPY = "endoscopy", "Endoscopy"
    OTHER = "other", "Other"


#: Modalities that produce a specimen rather than an image. Drives whether an
#: order needs collection and accessioning.
SPECIMEN_MODALITIES = {DiagnosticModality.LABORATORY}


class SpecimenType(models.TextChoices):
    BLOOD = "blood", "Blood"
    SERUM = "serum", "Serum"
    PLASMA = "plasma", "Plasma"
    URINE = "urine", "Urine"
    STOOL = "stool", "Stool"
    SPUTUM = "sputum", "Sputum"
    CSF = "csf", "Cerebrospinal fluid"
    SWAB = "swab", "Swab"
    TISSUE = "tissue", "Tissue"
    FLUID = "fluid", "Body fluid"
    OTHER = "other", "Other"


class ResultDataType(models.TextChoices):
    """How a result is expressed, which decides how it is validated and shown.

    A numeric potassium is compared against a reference range; a blood group
    is one of eight values; a culture is free text a microbiologist wrote.
    Storing all three as text and hoping would make reference ranges,
    trending and critical-value detection impossible.
    """

    NUMERIC = "numeric", "Numeric"
    TEXT = "text", "Free text"
    CODED = "coded", "One of a fixed set"
    #: Positive / negative / indeterminate.
    QUALITATIVE = "qualitative", "Qualitative"
    #: A panel header that holds no value of its own.
    GROUP = "group", "Group heading"


class TestDefinition(BaseModel):
    """A test or investigation that can be ordered.

    The catalogue. A panel (a "liver function test") is a `TestDefinition`
    with children — one order line produces one panel, and the panel's
    analytes are its own rows, because that is how a laboratory reports it and
    how a clinician reads it.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=64, blank=True)
    modality = models.CharField(
        max_length=20, choices=DiagnosticModality.choices, db_index=True
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="test_definitions",
    )

    #: A panel's analytes. Self-referential so a panel can itself sit inside a
    #: larger profile without a second model.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE,
        related_name="components",
    )
    is_panel = models.BooleanField(default=False)

    result_data_type = models.CharField(
        max_length=16, choices=ResultDataType.choices,
        default=ResultDataType.NUMERIC,
    )
    unit = models.CharField(max_length=32, blank=True)
    #: Allowed values for a CODED result, in order.
    allowed_values = models.JSONField(default=list, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)

    # -- specimen and process -------------------------------------------

    specimen_type = models.CharField(
        max_length=16, choices=SpecimenType.choices, blank=True
    )
    #: Fasting, timed collection, protect from light -- shown to whoever takes
    #: the sample, at the moment they take it.
    collection_instructions = models.CharField(max_length=512, blank=True)
    patient_preparation = models.CharField(max_length=512, blank=True)

    #: Expected turnaround, used to set a due time on the order and to flag
    #: breaches. Section 115 of the specification asks for TAT breach
    #: detection; this is where the expectation comes from.
    turnaround_minutes = models.PositiveIntegerField(default=240)
    #: True when the test is sent to an external laboratory. Those need a
    #: different chase-up: nobody in this building can hurry them.
    is_outsourced = models.BooleanField(default=False)
    outsource_partner = models.CharField(max_length=128, blank=True)

    #: The billable service. A bare UUID rather than a foreign key only
    #: because billing is a separate app; both live in the tenant database, so
    #: this could tighten to a real relation later.
    service_uuid = models.UUIDField(null=True, blank=True)

    requires_consent = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "test_definition"
        ordering = ["modality", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_test_code",
            )
        ]
        indexes = [models.Index(fields=["modality", "is_active"])]

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def needs_specimen(self) -> bool:
        return self.modality in SPECIMEN_MODALITIES


class ReferenceRange(BaseModel):
    """What counts as normal, for whom.

    Ranges are per test *and* per population. A haemoglobin of 12.5 g/dL is
    normal in an adult woman, low in an adult man, and normal in a child --
    reporting one range for all three produces false alarms that teach
    clinicians to ignore the flags.

    Critical thresholds live here too, because "critically low" is also a
    population-specific judgement.
    """

    test = models.ForeignKey(
        TestDefinition, on_delete=models.CASCADE, related_name="reference_ranges"
    )

    #: Empty means the range applies to any sex.
    applies_to_sex = models.CharField(max_length=16, blank=True)
    min_age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Pregnancy shifts many ranges materially.
    applies_when_pregnant = models.BooleanField(null=True, blank=True)

    normal_low = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    normal_high = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    #: Below or above these, someone must be told rather than merely shown.
    critical_low = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    critical_high = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )

    #: For qualitative and coded tests, the value that is not a concern.
    normal_value = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "reference_range"
        ordering = ["test_id", "min_age_years"]

    def __str__(self):
        return f"{self.test.code}: {self.normal_low}–{self.normal_high}"

    def matches(self, patient) -> bool:
        """Whether this range applies to a given patient."""
        if self.applies_to_sex and patient.gender != self.applies_to_sex:
            return False
        age = patient.age_years
        if age is None:
            # With no age, only a range that does not depend on age can apply.
            return self.min_age_years is None and self.max_age_years is None
        if self.min_age_years is not None and age < self.min_age_years:
            return False
        if self.max_age_years is not None and age > self.max_age_years:
            return False
        return True

    def specificity(self) -> int:
        """How narrowly this range is targeted. More specific wins."""
        return sum(
            [
                1 if self.applies_to_sex else 0,
                1 if self.min_age_years is not None else 0,
                1 if self.max_age_years is not None else 0,
                1 if self.applies_when_pregnant is not None else 0,
            ]
        )


class OrderPriority(models.TextChoices):
    ROUTINE = "routine", "Routine"
    URGENT = "urgent", "Urgent"
    #: Immediately, now. Reserved for cases where treatment waits on it.
    STAT = "stat", "STAT"


class OrderStatus(models.TextChoices):
    """Where an order has got to.

    Deliberately granular through the pre-analytical stages, because that is
    where laboratory orders go missing. "Ordered but never collected" and
    "collected but never received" are different failures with different
    fixes, and a single "pending" hides both.
    """

    DRAFT = "draft", "Draft"
    ORDERED = "ordered", "Ordered"
    COLLECTED = "collected", "Specimen collected"
    RECEIVED = "received", "Received in the laboratory"
    IN_PROGRESS = "in_progress", "In progress"
    RESULTED = "resulted", "Result entered"
    VERIFIED = "verified", "Verified"
    #: Released to the ordering clinician and the patient record.
    RELEASED = "released", "Released"
    REJECTED = "rejected", "Specimen rejected"
    CANCELLED = "cancelled", "Cancelled"


#: Orders still owed to somebody.
OPEN_ORDER_STATUSES = {
    OrderStatus.ORDERED,
    OrderStatus.COLLECTED,
    OrderStatus.RECEIVED,
    OrderStatus.IN_PROGRESS,
    OrderStatus.RESULTED,
}


class DiagnosticOrder(BaseModel):
    """A request for one investigation."""

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="diagnostic_orders"
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="diagnostic_orders",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="diagnostic_orders"
    )
    test = models.ForeignKey(
        TestDefinition, on_delete=models.PROTECT, related_name="orders"
    )

    #: Snapshot, for the same reason charges snapshot their service: a test
    #: can be renamed or retired, and a report issued last year must still
    #: read correctly.
    test_code = models.CharField(max_length=32)
    test_name = models.CharField(max_length=255)
    modality = models.CharField(max_length=20, choices=DiagnosticModality.choices,
                                db_index=True)

    ordered_by_id = models.UUIDField(null=True, blank=True, db_index=True)
    ordered_by_name = models.CharField(max_length=255, blank=True)
    ordered_at = models.DateTimeField(default=timezone.now, db_index=True)

    priority = models.CharField(
        max_length=12, choices=OrderPriority.choices,
        default=OrderPriority.ROUTINE, db_index=True,
    )
    status = models.CharField(
        max_length=16, choices=OrderStatus.choices,
        default=OrderStatus.ORDERED, db_index=True,
    )

    #: Why the test was requested. Not decoration: a radiologist reading a
    #: film without the clinical question is guessing, and a laboratory
    #: deciding whether to add on a test needs to know what is being looked
    #: for.
    clinical_indication = models.CharField(max_length=512, blank=True)
    clinical_notes = models.TextField(blank=True)

    #: When the result is expected, from the test's turnaround time. Stored
    #: rather than computed so a change to the catalogue does not
    #: retrospectively make old orders look late.
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # -- specimen --------------------------------------------------------

    #: Barcode. Unique across the tenant, because a mislabelled specimen is
    #: the single most dangerous error a laboratory makes.
    accession_number = models.CharField(
        max_length=32, null=True, blank=True, unique=True, db_index=True
    )
    specimen_type = models.CharField(
        max_length=16, choices=SpecimenType.choices, blank=True
    )
    collected_at = models.DateTimeField(null=True, blank=True)
    collected_by_id = models.UUIDField(null=True, blank=True)
    collected_by_name = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.CharField(max_length=255, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    # -- completion ------------------------------------------------------

    resulted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_by_name = models.CharField(max_length=255, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    #: The charge raised for this order, so a cancelled order can be traced
    #: to the money and credited.
    charge_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "diagnostic_order"
        ordering = ["-ordered_at"]
        indexes = [
            models.Index(fields=["patient", "-ordered_at"]),
            models.Index(fields=["facility", "status", "priority"]),
            models.Index(fields=["modality", "status"]),
            models.Index(fields=["status", "due_at"]),
        ]

    def __str__(self):
        return f"{self.reference} — {self.test_name} for {self.patient.mrn}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ORDER_STATUSES

    @property
    def is_overdue(self) -> bool:
        """Past its expected turnaround and still not released."""
        if not self.due_at or not self.is_open:
            return False
        return timezone.now() > self.due_at

    @property
    def turnaround_minutes(self) -> int | None:
        """Actual turnaround, ordered to released."""
        if not self.released_at:
            return None
        return int((self.released_at - self.ordered_at).total_seconds() / 60)

    @property
    def collection_to_result_minutes(self) -> int | None:
        """The laboratory's own portion of the turnaround.

        Separated from the total deliberately: a laboratory cannot be held to
        account for a specimen that sat on a ward for three hours, and
        conflating the two hides where the delay actually is.
        """
        if not self.collected_at or not self.resulted_at:
            return None
        return int((self.resulted_at - self.collected_at).total_seconds() / 60)


class ResultFlag(models.TextChoices):
    NORMAL = "normal", "Normal"
    LOW = "low", "Low"
    HIGH = "high", "High"
    CRITICAL_LOW = "critical_low", "Critically low"
    CRITICAL_HIGH = "critical_high", "Critically high"
    ABNORMAL = "abnormal", "Abnormal"


CRITICAL_FLAGS = {ResultFlag.CRITICAL_LOW, ResultFlag.CRITICAL_HIGH}


class DiagnosticResult(BaseModel):
    """One reported value.

    A panel produces several, one per analyte. A radiology study produces one
    with a narrative report in `text_value`.

    Amendment follows the same rule as clinical notes: a verified result is
    superseded by a new row, never edited. A clinician may have acted on the
    original, and the record has to show what they saw.
    """

    order = models.ForeignKey(
        DiagnosticOrder, on_delete=models.CASCADE, related_name="results"
    )
    test = models.ForeignKey(
        TestDefinition, on_delete=models.PROTECT, related_name="results"
    )
    analyte_code = models.CharField(max_length=32)
    analyte_name = models.CharField(max_length=255)

    #: Exactly one of these carries the value, according to the test's data
    #: type. Numeric is kept separate so results can be trended and compared
    #: against reference ranges -- which is impossible over text.
    numeric_value = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    text_value = models.TextField(blank=True)
    coded_value = models.CharField(max_length=64, blank=True)

    unit = models.CharField(max_length=32, blank=True)
    #: The range applied, copied in at the time. Ranges get revised; a report
    #: must keep showing the range the result was judged against.
    reference_text = models.CharField(max_length=128, blank=True)
    flag = models.CharField(
        max_length=16, choices=ResultFlag.choices, default=ResultFlag.NORMAL,
        db_index=True,
    )

    entered_by_id = models.UUIDField(null=True, blank=True)
    entered_by_name = models.CharField(max_length=255, blank=True)
    entered_at = models.DateTimeField(default=timezone.now)

    #: A second person confirms before anyone acts on it.
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    #: Amendment chain. The superseded row stays exactly as it was.
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    amendment_reason = models.CharField(max_length=512, blank=True)
    is_superseded = models.BooleanField(default=False, db_index=True)

    #: Which analyser produced it, for quality investigation.
    instrument = models.CharField(max_length=64, blank=True)
    method = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "diagnostic_result"
        ordering = ["display_order", "analyte_name"]
        indexes = [
            models.Index(fields=["order", "is_superseded"]),
            models.Index(fields=["flag", "-entered_at"]),
            models.Index(fields=["test", "-entered_at"]),
        ]

    def __str__(self):
        return f"{self.analyte_name}: {self.display_value} {self.unit}".strip()

    @property
    def display_value(self) -> str:
        """The value as it should be printed.

        Trailing zeros are stripped only after a decimal point. Stripping them
        unconditionally turns a platelet count of 280 into 28 -- a normal
        result rendered as critical thrombocytopenia -- and 1000 into 1. The
        guard is the whole reason this is not a one-liner.
        """
        if self.numeric_value is None:
            return self.coded_value or self.text_value

        places = self.test.decimal_places if self.test_id else 2
        text = f"{self.numeric_value:.{places}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    @property
    def is_critical(self) -> bool:
        return self.flag in CRITICAL_FLAGS

    @property
    def is_abnormal(self) -> bool:
        return self.flag != ResultFlag.NORMAL

    def clean(self):
        has_value = (
            self.numeric_value is not None
            or bool(self.text_value)
            or bool(self.coded_value)
        )
        if not has_value:
            raise ValidationError("A result must carry a value.")


class AlertStatus(models.TextChoices):
    PENDING = "pending", "Awaiting acknowledgement"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    ESCALATED = "escalated", "Escalated"
    CLOSED = "closed", "Closed"


class CriticalValueAlert(BaseModel):
    """A result that obliges someone to be told, and the record that they were.

    Exists as its own entity rather than a flag on the result because the
    obligation is not "display this in red" — it is "telephone the requesting
    clinician, and record whom you spoke to and when". A laboratory that
    cannot show it made that call has not discharged its duty, however
    correct the number on the screen was.
    """

    result = models.ForeignKey(
        DiagnosticResult, on_delete=models.CASCADE, related_name="critical_alerts"
    )
    order = models.ForeignKey(
        DiagnosticOrder, on_delete=models.CASCADE, related_name="critical_alerts"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="critical_alerts"
    )

    value = models.CharField(max_length=64)
    flag = models.CharField(max_length=16, choices=ResultFlag.choices)
    threshold = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=16, choices=AlertStatus.choices,
        default=AlertStatus.PENDING, db_index=True,
    )
    raised_at = models.DateTimeField(default=timezone.now, db_index=True)

    #: Whom the laboratory told, how, and when. Free text for the name because
    #: the person reached is often not the person who ordered -- a covering
    #: doctor, the ward sister.
    notified_person = models.CharField(max_length=255, blank=True)
    notified_via = models.CharField(max_length=64, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    notified_by_id = models.UUIDField(null=True, blank=True)

    acknowledged_by_id = models.UUIDField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    action_taken = models.TextField(blank=True)

    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_note = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "critical_value_alert"
        ordering = ["-raised_at"]
        indexes = [
            models.Index(fields=["status", "-raised_at"]),
            models.Index(fields=["patient", "-raised_at"]),
        ]

    def __str__(self):
        return f"{self.result.analyte_name} {self.value} — {self.get_status_display()}"

    @property
    def minutes_outstanding(self) -> int:
        """How long the alert has gone unacknowledged.

        The number a quality report is built on: an alert raised at 02:00 and
        acknowledged at 09:00 is a finding, not a footnote.
        """
        end = self.acknowledged_at or timezone.now()
        return int((end - self.raised_at).total_seconds() / 60)
