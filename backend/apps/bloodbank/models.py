"""The blood bank: the one module where a wrong row kills somebody.

Everywhere else in this system a data error costs money or time. Here, a unit
of group A issued against a group B cross-match kills the patient within
minutes, and the error is not recoverable. So this module is built around
refusals rather than warnings, and around traceability that runs in both
directions: from a donor to everyone who received their blood, and from a
transfusion reaction back to the donation.

Seven decisions, each one a place where the convenient design is dangerous.

**A donation and a component are different objects.** One donation of whole
blood becomes red cells, plasma and platelets, each with its own expiry, its
own storage temperature and its own destination. Treating the bag as the unit
means the three components share one expiry — and platelets last five days
where red cells last thirty-five.

**Group is recorded twice, by two people, before anything is labelled.** Not a
workflow nicety: mislabelling at grouping is the single commonest cause of a
fatal transfusion, and the second check exists precisely because the first can
be wrong. The system stores both results and refuses to release a unit whose
two groupings disagree.

**Screening results are stored per infection, not as a pass/fail.** A unit
reactive for hepatitis B and a unit nobody tested are both "not safe", and
they demand completely different actions — one is a donor who must be told and
deferred, the other is a laboratory that missed a sample.

**A cross-match is between one unit and one patient, and it expires.** A
compatible cross-match from four days ago is not a compatible cross-match: the
patient may have been transfused since and developed antibodies. Seventy-two
hours is the usual limit and it lives in the data.

**Issue is refused, never warned.** No pre-authorisation-style override
anywhere in this module. Every other guard in this system can be overridden by
somebody with the right permission and a reason, because the alternative is
that people work around the system. Here the alternative to refusing is a
death, so `issue_unit` has no override parameter at all.

**Reservation and issue are different states.** A unit reserved for a
theatre list at 08:00 is not available to the emergency at 09:00, but it is
also still on the shelf and can be released. Collapsing the two either
double-issues units or leaves the bank looking emptier than it is.

**Every transfusion links a unit to a patient permanently.** A donor who
seroconverts is a look-back: which patients received their earlier donations.
Without the link, the answer is nobody knows.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# BaseModel gives every row a UUID, timestamps and soft delete; UUIDs are what
# the API publishes, because with a database per tenant an integer PK means a
# different row in every customer's database.
from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.organization.models import Facility
from apps.patients.models import Patient

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


class BloodGroup(models.TextChoices):
    A_POS = "A+", "A positive"
    A_NEG = "A-", "A negative"
    B_POS = "B+", "B positive"
    B_NEG = "B-", "B negative"
    AB_POS = "AB+", "AB positive"
    AB_NEG = "AB-", "AB negative"
    O_POS = "O+", "O positive"
    O_NEG = "O-", "O negative"


#: Which donor groups a recipient of each group may receive red cells from.
#:
#: Held as data rather than computed from the antigens, because the table is
#: the thing clinicians check against and a bug in an antigen calculation
#: would be invisible. O negative gives to everyone; AB positive receives from
#: everyone. Plasma runs the opposite way, which is why it has its own table.
RED_CELL_COMPATIBILITY = {
    "O-": ["O-"],
    "O+": ["O-", "O+"],
    "A-": ["O-", "A-"],
    "A+": ["O-", "O+", "A-", "A+"],
    "B-": ["O-", "B-"],
    "B+": ["O-", "O+", "B-", "B+"],
    "AB-": ["O-", "A-", "B-", "AB-"],
    "AB+": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
}

#: Plasma compatibility, which is the reverse of red cells: AB plasma has no
#: antibodies and suits everyone, O plasma suits only O recipients. A single
#: compatibility table used for both is the classic fatal shortcut.
PLASMA_COMPATIBILITY = {
    "O-": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
    "O+": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
    "A-": ["A-", "A+", "AB-", "AB+"],
    "A+": ["A-", "A+", "AB-", "AB+"],
    "B-": ["B-", "B+", "AB-", "AB+"],
    "B+": ["B-", "B+", "AB-", "AB+"],
    "AB-": ["AB-", "AB+"],
    "AB+": ["AB-", "AB+"],
}


# ---------------------------------------------------------------------------
# Donors
# ---------------------------------------------------------------------------


class DonorStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    #: Cannot donate for a while: recent donation, low haemoglobin, travel.
    TEMPORARILY_DEFERRED = "temporary", "Temporarily deferred"
    #: Cannot donate again. A reactive screening result, usually.
    PERMANENTLY_DEFERRED = "permanent", "Permanently deferred"
    DECEASED = "deceased", "Deceased"


class DonorType(models.TextChoices):
    VOLUNTARY = "voluntary", "Voluntary"
    #: Someone donating for a named patient. Common in Nepal and worth
    #: distinguishing, because the unit is often reserved for that patient.
    REPLACEMENT = "replacement", "Replacement for a patient"
    DIRECTED = "directed", "Directed to a named patient"
    AUTOLOGOUS = "autologous", "The patient's own blood"


class Donor(BaseModel):
    """Somebody who gives blood.

    Not a `Patient`. A donor is a healthy volunteer with a different record,
    different consent and different privacy expectations, and conflating them
    would put every donor into the patient index — where a receptionist
    searching for a patient would find them.
    """

    donor_number = models.CharField(max_length=32, unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    full_name_nepali = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=16, blank=True)
    blood_group = models.CharField(
        max_length=3, choices=BloodGroup.choices, blank=True, db_index=True,
    )

    phone = models.CharField(max_length=32, db_index=True)
    alternate_phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=512, blank=True)
    #: Citizenship number: the identifier a Nepali blood bank actually uses to
    #: recognise a returning donor, since names repeat and phones change.
    citizenship_number = models.CharField(max_length=32, blank=True, db_index=True)

    donor_type = models.CharField(
        max_length=16, choices=DonorType.choices, default=DonorType.VOLUNTARY,
    )
    status = models.CharField(
        max_length=16, choices=DonorStatus.choices, default=DonorStatus.ACTIVE,
        db_index=True,
    )
    #: Why, and until when. A deferral with no reason is one nobody can lift.
    deferral_reason = models.CharField(max_length=512, blank=True)
    deferred_until = models.DateField(null=True, blank=True, db_index=True)
    deferred_by_name = models.CharField(max_length=255, blank=True)

    #: A cache over the donations, rebuildable. Never the source of truth.
    donation_count = models.PositiveIntegerField(default=0)
    last_donated_on = models.DateField(null=True, blank=True)

    is_contactable = models.BooleanField(
        default=True,
        help_text="May be called when their group is needed.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["blood_group", "status"]),
            models.Index(fields=["status", "deferred_until"]),
        ]

    def __str__(self):
        return f"{self.donor_number} {self.full_name}"

    def eligible_on(self, on_date=None) -> tuple[bool, list]:
        """Whether this donor may give on a date, and why not.

        Returns reasons rather than a boolean alone, because the desk has to
        tell the donor something. A permanent deferral and "you gave five
        weeks ago" are the same answer and completely different conversations.
        """
        on_date = on_date or timezone.localdate()
        problems = []

        if self.status == DonorStatus.PERMANENTLY_DEFERRED:
            problems.append(
                self.deferral_reason or "Permanently deferred from donating."
            )
        elif self.status == DonorStatus.DECEASED:
            problems.append("Recorded as deceased.")
        elif self.deferred_until and on_date < self.deferred_until:
            problems.append(
                f"Deferred until {self.deferred_until}"
                + (f": {self.deferral_reason}" if self.deferral_reason else ".")
            )

        # The interval between donations. Whole blood is 90 days for men and
        # 120 for women in Nepal's guidance; the shorter figure is used when
        # gender is unrecorded, and the check is on the last donation rather
        # than on a counter that could drift.
        if self.last_donated_on:
            interval = 120 if self.gender.lower().startswith("f") else 90
            next_due = self.last_donated_on + timedelta(days=interval)
            if on_date < next_due:
                problems.append(
                    f"Last donated {self.last_donated_on}; eligible again on "
                    f"{next_due}."
                )

        return (not problems, problems)


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------


class DonationStatus(models.TextChoices):
    COLLECTED = "collected", "Collected"
    #: Grouped and screened, components separated, units on the shelf.
    PROCESSED = "processed", "Processed"
    #: A reactive screening result, or a collection that went wrong.
    DISCARDED = "discarded", "Discarded"


class Donation(BaseModel):
    """One bag of blood, from one donor, on one day.

    The parent of its components. Kept separate from the units it becomes,
    because a look-back starts here: a donor who seroconverts means every
    donation they ever gave, and every unit from each of them, has to be
    findable.
    """

    donation_number = models.CharField(max_length=32, unique=True, db_index=True)
    donor = models.ForeignKey(
        Donor, on_delete=models.PROTECT, related_name="donations",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="donations",
    )
    collected_at = models.DateTimeField(default=timezone.now, db_index=True)
    collected_by_name = models.CharField(max_length=255, blank=True)
    #: Off-site drives are where labelling errors concentrate, so the fact is
    #: recorded rather than inferred from the facility.
    collection_site = models.CharField(max_length=255, blank=True)
    is_mobile_drive = models.BooleanField(default=False)

    volume_ml = models.PositiveSmallIntegerField(default=450)
    bag_type = models.CharField(
        max_length=32, blank=True,
        help_text="Single, double, triple, quadruple.",
    )
    #: Screening haemoglobin, taken before collection. Below the threshold the
    #: donation should not have happened, and recording it is how that is
    #: audited afterwards.
    haemoglobin = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
    )
    donor_weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
    )

    #: An adverse event during collection: a faint, a haematoma. Recorded
    #: because it decides whether this donor is called again.
    had_adverse_event = models.BooleanField(default=False)
    adverse_event_detail = models.CharField(max_length=512, blank=True)

    status = models.CharField(
        max_length=16, choices=DonationStatus.choices,
        default=DonationStatus.COLLECTED, db_index=True,
    )
    discard_reason = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-collected_at"]
        indexes = [
            models.Index(fields=["donor", "-collected_at"]),
            models.Index(fields=["facility", "status"]),
        ]

    def __str__(self):
        return self.donation_number


class Grouping(BaseModel):
    """One person's determination of a donation's blood group.

    Two of these are required before anything is labelled, by two different
    people. Mislabelling at grouping is the commonest cause of a fatal
    transfusion, and the second check exists precisely because the first can be
    wrong — so it is a separate row by a separate person, not a checkbox on the
    first.
    """

    donation = models.ForeignKey(
        Donation, on_delete=models.CASCADE, related_name="groupings",
    )
    blood_group = models.CharField(max_length=3, choices=BloodGroup.choices)
    #: Forward and reverse grouping results, which is how the group is
    #: actually determined. Stored because a discrepancy between them is a
    #: finding in itself.
    forward_result = models.CharField(max_length=64, blank=True)
    reverse_result = models.CharField(max_length=64, blank=True)
    #: A weak D result matters: a weak-D donor is treated as positive, a
    #: weak-D recipient as negative, and getting it backwards is harmful.
    is_weak_d = models.BooleanField(default=False)
    antibody_screen = models.CharField(max_length=64, blank=True)

    performed_at = models.DateTimeField(default=timezone.now)
    performed_by_id = models.UUIDField(null=True, blank=True)
    performed_by_name = models.CharField(max_length=255)
    method = models.CharField(max_length=64, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["performed_at"]
        constraints = [
            #: One result per person per donation. The same person confirming
            #: their own result twice is not a second check, and without this
            #: it looks like one.
            models.UniqueConstraint(
                fields=["donation", "performed_by_name"],
                name="uniq_grouping_per_person",
            ),
        ]

    def __str__(self):
        return f"{self.donation_id} {self.blood_group} by {self.performed_by_name}"


class InfectionResult(models.TextChoices):
    NOT_TESTED = "not_tested", "Not tested"
    NON_REACTIVE = "non_reactive", "Non-reactive"
    REACTIVE = "reactive", "Reactive"
    #: Reactive on the first pass, non-reactive on repeat. The unit is still
    #: discarded and the donor still needs confirmatory testing.
    INDETERMINATE = "indeterminate", "Indeterminate"


#: The mandatory screening panel.
#:
#: Held as data because the panel is set by national guidance and changes: a
#: hospital adding malaria screening should add a row, not a column. Each entry
#: is (key, label, whether a reactive result permanently defers the donor).
SCREENING_PANEL = [
    ("hiv", "HIV 1 and 2", True),
    ("hbsag", "Hepatitis B surface antigen", True),
    ("hcv", "Hepatitis C", True),
    ("syphilis", "Syphilis (VDRL/TPHA)", False),
    ("malaria", "Malaria", False),
]

SCREENING_KEYS = [key for key, _, _ in SCREENING_PANEL]
PERMANENT_DEFERRAL_KEYS = {key for key, _, permanent in SCREENING_PANEL if permanent}


class Screening(BaseModel):
    """The transfusion-transmissible infection panel for one donation.

    Results are stored per infection rather than as a single pass/fail,
    because "not safe" is not one state. A unit reactive for hepatitis B and a
    unit nobody tested are both unsafe and demand opposite responses: the first
    is a donor who must be told and deferred, the second is a laboratory that
    lost a sample.
    """

    donation = models.OneToOneField(
        Donation, on_delete=models.CASCADE, related_name="screening",
    )
    #: {key: result} against `SCREENING_KEYS`. A missing key is untested, not
    #: negative — the same rule as the ICU's missing organ systems.
    results = models.JSONField(default=dict, blank=True)
    #: Optical density or titre values, kept for the confirmatory laboratory.
    values = models.JSONField(default=dict, blank=True)

    performed_at = models.DateTimeField(default=timezone.now)
    performed_by_name = models.CharField(max_length=255, blank=True)
    verified_by_name = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    kit_lot_number = models.CharField(max_length=64, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-performed_at"]

    def __str__(self):
        return f"screening {self.donation_id}"

    @property
    def untested(self) -> list:
        """Infections in the panel with no result. Missing is not negative."""
        return [
            key for key in SCREENING_KEYS
            if self.results.get(key, InfectionResult.NOT_TESTED)
            == InfectionResult.NOT_TESTED
        ]

    @property
    def reactive(self) -> list:
        return [
            key for key, value in self.results.items()
            if value in (InfectionResult.REACTIVE, InfectionResult.INDETERMINATE)
        ]

    @property
    def is_complete(self) -> bool:
        return not self.untested

    @property
    def is_safe(self) -> bool:
        """Safe to release: everything tested, nothing reactive."""
        return self.is_complete and not self.reactive


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


class ComponentType(models.TextChoices):
    WHOLE_BLOOD = "whole_blood", "Whole blood"
    RED_CELLS = "red_cells", "Packed red cells"
    PLASMA = "plasma", "Fresh frozen plasma"
    PLATELETS = "platelets", "Platelet concentrate"
    CRYOPRECIPITATE = "cryo", "Cryoprecipitate"


#: Shelf life and storage, per component.
#:
#: The reason components are separate objects. Platelets last five days at room
#: temperature; plasma lasts a year frozen; red cells last thirty-five days
#: refrigerated. One expiry on the parent bag would be wrong for two of the
#: three, and always in the dangerous direction for platelets.
#:
#: Each entry is (shelf-life days, minimum °C, maximum °C).
COMPONENT_SHELF_LIFE = {
    ComponentType.WHOLE_BLOOD: (35, Decimal("2"), Decimal("6")),
    ComponentType.RED_CELLS: (35, Decimal("2"), Decimal("6")),
    ComponentType.PLASMA: (365, Decimal("-30"), Decimal("-18")),
    ComponentType.PLATELETS: (5, Decimal("20"), Decimal("24")),
    ComponentType.CRYOPRECIPITATE: (365, Decimal("-30"), Decimal("-18")),
}

#: Which compatibility table each component uses. Plasma products run the
#: opposite way to red cells, and using one table for both is the classic
#: fatal shortcut.
PLASMA_COMPONENTS = {ComponentType.PLASMA, ComponentType.CRYOPRECIPITATE}


class UnitStatus(models.TextChoices):
    #: Made, but not yet cleared for use: grouping or screening incomplete.
    QUARANTINED = "quarantined", "Quarantined"
    AVAILABLE = "available", "Available"
    #: Held for a named patient. Still on the shelf, not available to others.
    RESERVED = "reserved", "Reserved"
    #: Cross-matched against a patient and physically set aside.
    CROSSMATCHED = "crossmatched", "Cross-matched"
    ISSUED = "issued", "Issued"
    TRANSFUSED = "transfused", "Transfused"
    RETURNED = "returned", "Returned to the bank"
    EXPIRED = "expired", "Expired"
    DISCARDED = "discarded", "Discarded"


class BloodUnit(BaseModel):
    """One component from one donation: the thing that is actually issued.

    The unit, not the bag. A single donation becomes red cells, plasma and
    platelets, each with its own expiry, its own storage and its own
    destination — and the platelets expire thirty days before the red cells.
    """

    unit_number = models.CharField(max_length=32, unique=True, db_index=True)
    donation = models.ForeignKey(
        Donation, on_delete=models.PROTECT, related_name="units",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="blood_units",
    )
    component = models.CharField(max_length=16, choices=ComponentType.choices)
    #: Copied from the donation's confirmed grouping. Denormalised on purpose:
    #: the shelf label carries the group, and a query that has to join through
    #: two tables to know what is in the fridge is a query nobody runs.
    blood_group = models.CharField(
        max_length=3, choices=BloodGroup.choices, db_index=True,
    )
    volume_ml = models.PositiveSmallIntegerField()

    prepared_at = models.DateTimeField(default=timezone.now)
    expires_on = models.DateField(db_index=True)
    storage_location = models.CharField(max_length=64, blank=True)
    #: The temperature range this component must be kept in. Copied from the
    #: table so that a unit records the rule that applied when it was made.
    storage_min_c = models.DecimalField(max_digits=4, decimal_places=1)
    storage_max_c = models.DecimalField(max_digits=4, decimal_places=1)

    status = models.CharField(
        max_length=16, choices=UnitStatus.choices,
        default=UnitStatus.QUARANTINED, db_index=True,
    )
    #: Who the unit is held for, when reserved or cross-matched.
    reserved_for = models.ForeignKey(
        Patient, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reserved_blood_units",
    )
    reserved_until = models.DateTimeField(null=True, blank=True)
    reserved_reason = models.CharField(max_length=255, blank=True)

    issued_at = models.DateTimeField(null=True, blank=True)
    issued_to_name = models.CharField(max_length=255, blank=True)
    #: Time out of the fridge. A red cell unit above 10 °C for more than
    #: thirty minutes cannot go back, and the clock starts here.
    left_storage_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    discard_reason = models.CharField(max_length=512, blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["expires_on", "unit_number"]
        indexes = [
            models.Index(fields=["facility", "status", "blood_group"]),
            models.Index(fields=["component", "status", "expires_on"]),
        ]
        constraints = [
            #: A reserved or cross-matched unit is held for somebody. Without
            #: this the bank shows units unavailable with nobody to release
            #: them to.
            models.CheckConstraint(
                condition=(
                    ~models.Q(status__in=["reserved", "crossmatched"])
                    | models.Q(reserved_for__isnull=False)
                ),
                name="held_unit_names_its_patient",
            ),
        ]

    def __str__(self):
        return f"{self.unit_number} {self.blood_group} {self.component}"

    @property
    def is_expired(self) -> bool:
        return self.expires_on < timezone.localdate()

    @property
    def days_to_expiry(self) -> int:
        return (self.expires_on - timezone.localdate()).days

    @property
    def compatibility_table(self) -> dict:
        return (
            PLASMA_COMPATIBILITY if self.component in PLASMA_COMPONENTS
            else RED_CELL_COMPATIBILITY
        )

    @property
    def is_available(self) -> bool:
        return self.status == UnitStatus.AVAILABLE and not self.is_expired


# ---------------------------------------------------------------------------
# Requests and cross-matching
# ---------------------------------------------------------------------------


class RequestUrgency(models.TextChoices):
    ROUTINE = "routine", "Routine"
    URGENT = "urgent", "Urgent — within an hour"
    #: No cross-match: group-specific or O negative, issued immediately.
    #: A real and necessary category, and one that must be visible afterwards
    #: because it carries risk the hospital accepted knowingly.
    EMERGENCY = "emergency", "Emergency — uncross-matched"


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PART_FILLED = "part_filled", "Partly filled"
    FILLED = "filled", "Filled"
    CANCELLED = "cancelled", "Cancelled"


class BloodRequest(BaseModel):
    """A clinician asking for blood for a patient."""

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="blood_requests",
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="blood_requests",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="blood_requests",
    )

    requested_at = models.DateTimeField(default=timezone.now, db_index=True)
    requested_by_name = models.CharField(max_length=255)
    required_by = models.DateTimeField(null=True, blank=True)
    urgency = models.CharField(
        max_length=12, choices=RequestUrgency.choices,
        default=RequestUrgency.ROUTINE, db_index=True,
    )

    component = models.CharField(max_length=16, choices=ComponentType.choices)
    units_requested = models.PositiveSmallIntegerField()
    indication = models.CharField(max_length=512)
    #: The patient's group as the requester believes it. Checked against the
    #: bank's own grouping, and a disagreement stops everything.
    stated_group = models.CharField(
        max_length=3, choices=BloodGroup.choices, blank=True,
    )
    #: The patient's haemoglobin, so an audit can ask whether the transfusion
    #: was indicated at all. Over-transfusion is the commonest quality finding
    #: in a blood bank and is invisible without this.
    haemoglobin = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
    )

    status = models.CharField(
        max_length=12, choices=RequestStatus.choices,
        default=RequestStatus.PENDING, db_index=True,
    )
    cancelled_reason = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["patient", "-requested_at"]),
        ]

    def __str__(self):
        return f"{self.reference} {self.component} ×{self.units_requested}"


#: How long a cross-match stays valid, in hours.
#:
#: Seventy-two is the usual limit. The patient may have been transfused since
#: and developed antibodies, so a compatible cross-match from four days ago is
#: not a compatible cross-match. Data rather than code, because some units
#: work to forty-eight.
CROSSMATCH_VALID_HOURS = 72


class CrossMatchResult(models.TextChoices):
    COMPATIBLE = "compatible", "Compatible"
    INCOMPATIBLE = "incompatible", "Incompatible"
    #: Compatible only after further work — a warm autoantibody, say. Its own
    #: result because it is a clinical decision, not a laboratory one.
    COMPATIBLE_WITH_CAUTION = "caution", "Compatible with caution"


class CrossMatch(BaseModel):
    """One unit tested against one patient, with an expiry.

    Between a unit and a patient, never between a group and a group. Two units
    of the same group can behave differently against the same patient's
    antibodies, which is the entire reason cross-matching exists.
    """

    unit = models.ForeignKey(
        BloodUnit, on_delete=models.PROTECT, related_name="cross_matches",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="cross_matches",
    )
    request = models.ForeignKey(
        BloodRequest, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="cross_matches",
    )

    performed_at = models.DateTimeField(default=timezone.now, db_index=True)
    performed_by_name = models.CharField(max_length=255)
    valid_until = models.DateTimeField(db_index=True)
    result = models.CharField(max_length=16, choices=CrossMatchResult.choices)
    method = models.CharField(max_length=64, blank=True)

    #: The patient's group as determined by the bank, from the patient's own
    #: sample. Stored on the cross-match rather than only on the patient,
    #: because a patient's recorded group can be corrected later and this must
    #: record what was believed at the time.
    patient_group = models.CharField(
        max_length=3, choices=BloodGroup.choices, blank=True,
    )
    antibody_screen = models.CharField(max_length=128, blank=True)
    incompatibility_detail = models.CharField(max_length=512, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-performed_at"]
        indexes = [models.Index(fields=["patient", "-performed_at"])]

    def __str__(self):
        return f"{self.unit_id} × {self.patient_id} {self.result}"

    @property
    def is_valid(self) -> bool:
        return (
            self.result != CrossMatchResult.INCOMPATIBLE
            and self.valid_until > timezone.now()
        )


# ---------------------------------------------------------------------------
# Transfusion
# ---------------------------------------------------------------------------


class TransfusionOutcome(models.TextChoices):
    COMPLETED = "completed", "Completed"
    #: Stopped part-way. Its own outcome because the volume actually given
    #: matters and because a stopped transfusion usually means a reaction.
    STOPPED = "stopped", "Stopped before completion"
    NOT_STARTED = "not_started", "Not started"


class Transfusion(BaseModel):
    """A unit going into a patient. The permanent link between the two.

    This row is what makes a look-back possible: a donor who seroconverts
    means finding every patient who received their earlier donations, and
    without the link the answer is that nobody knows.
    """

    unit = models.OneToOneField(
        BloodUnit, on_delete=models.PROTECT, related_name="transfusion",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="transfusions",
    )
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transfusions",
    )
    request = models.ForeignKey(
        BloodRequest, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transfusions",
    )
    cross_match = models.ForeignKey(
        CrossMatch, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="transfusions",
    )

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    volume_given_ml = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(
        max_length=16, choices=TransfusionOutcome.choices,
        default=TransfusionOutcome.COMPLETED,
    )

    #: The bedside check: two people, the patient's identity band, the unit
    #: number and the group, said aloud. It is the last barrier before a fatal
    #: error, and both names are recorded because one person checking alone is
    #: not the check.
    checked_by_first = models.CharField(max_length=255)
    checked_by_second = models.CharField(max_length=255)
    identity_confirmed = models.BooleanField(default=False)

    #: Observations during the transfusion. Stored as a list of dicts rather
    #: than rows because they are only ever read together, in order, as a
    #: chart, and never queried across patients.
    observations = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["patient", "-started_at"])]
        constraints = [
            #: The bedside check needs two different people. One person
            #: entering their own name twice is not a second check, and the
            #: form makes that trivially easy without this.
            models.CheckConstraint(
                condition=~models.Q(
                    checked_by_first=models.F("checked_by_second")
                ),
                name="bedside_check_needs_two_people",
            ),
        ]

    def __str__(self):
        return f"{self.unit_id} to {self.patient_id}"


class ReactionSeverity(models.TextChoices):
    MILD = "mild", "Mild"
    MODERATE = "moderate", "Moderate"
    SEVERE = "severe", "Severe"
    LIFE_THREATENING = "life_threatening", "Life-threatening"
    FATAL = "fatal", "Fatal"


#: The reaction types a blood bank reports on.
#:
#: A fixed list because the national haemovigilance return asks for these
#: categories, and free text produces a year of reports nobody can aggregate.
REACTION_TYPES = [
    ("febrile", "Febrile non-haemolytic"),
    ("allergic", "Allergic / urticarial"),
    ("anaphylactic", "Anaphylactic"),
    ("acute_haemolytic", "Acute haemolytic"),
    ("delayed_haemolytic", "Delayed haemolytic"),
    ("taco", "Circulatory overload (TACO)"),
    ("trali", "Transfusion-related acute lung injury"),
    ("bacterial", "Bacterial contamination"),
    ("hypotensive", "Hypotensive"),
    ("other", "Other"),
]

REACTION_TYPE_KEYS = {key for key, _ in REACTION_TYPES}


class TransfusionReaction(BaseModel):
    """Something went wrong, and it is reported rather than noted.

    Its own record with its own investigation, because a reaction is reportable
    to the national haemovigilance system and because an acute haemolytic
    reaction means a unit may have gone to the wrong patient — which makes
    every other unit from that cross-match session suspect.
    """

    transfusion = models.ForeignKey(
        Transfusion, on_delete=models.CASCADE, related_name="reactions",
    )
    reported_at = models.DateTimeField(default=timezone.now, db_index=True)
    reported_by_name = models.CharField(max_length=255)
    #: Minutes from the start of the transfusion. The single most diagnostic
    #: fact: a reaction in the first fifteen minutes is haemolytic until
    #: proved otherwise.
    minutes_into_transfusion = models.PositiveSmallIntegerField(
        null=True, blank=True,
    )

    reaction_type = models.CharField(max_length=24)
    severity = models.CharField(max_length=20, choices=ReactionSeverity.choices)
    symptoms = models.TextField()
    #: Was the transfusion stopped? If not, that is a finding in itself.
    transfusion_stopped = models.BooleanField(default=True)
    volume_transfused_ml = models.PositiveSmallIntegerField(
        null=True, blank=True,
    )
    treatment_given = models.TextField(blank=True)

    #: The investigation. Kept on the reaction rather than in a note, because
    #: the haemovigilance return asks whether it was done.
    unit_returned_to_bank = models.BooleanField(default=False)
    repeat_grouping_done = models.BooleanField(default=False)
    repeat_crossmatch_done = models.BooleanField(default=False)
    culture_sent = models.BooleanField(default=False)
    investigation_findings = models.TextField(blank=True)
    is_clerical_error = models.BooleanField(
        default=False,
        help_text="A wrong unit, a wrong patient, or a wrong label.",
    )

    reported_to_authority = models.BooleanField(default=False)
    reported_to_authority_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-reported_at"]
        indexes = [models.Index(fields=["severity", "-reported_at"])]

    def __str__(self):
        return f"{self.reaction_type} ({self.severity})"


def validate_reaction_type(value: str) -> None:
    """Refuse a reaction type outside the reportable list.

    A service-layer check so the message names the alternatives, which a
    constraint cannot.
    """
    if value not in REACTION_TYPE_KEYS:
        raise ValidationError(
            f"'{value}' is not a reportable reaction type. Use one of: "
            f"{', '.join(sorted(REACTION_TYPE_KEYS))}."
        )
