"""The patient master: the record every clinical, billing and diagnostic
module ultimately points at.

This is the most consequential model in the system and the hardest to change
later, because everything else acquires a foreign key to it. Three properties
are therefore designed in from the start rather than retrofitted:

* **One patient, many visits, many facilities.** A patient registered at the
  Kathmandu clinic who is later admitted to the Bhaktapur hospital is the same
  person, with one record and one history. Registration is per organization,
  not per facility.
* **Identity in Nepal is messy.** Many patients have no national ID. Names are
  transliterated inconsistently. Dates of birth are often approximate, and are
  quoted in Bikram Sambat. The model accommodates that instead of pretending
  otherwise -- see `is_dob_estimated` and `PatientIdentifier`.
* **Duplicates are inevitable.** A walk-in at 2 a.m. will be registered again.
  The answer is not to prevent it but to detect and merge it without losing
  either history -- hence `merged_into` rather than deletion.
"""

# transaction / models: the MRN sequence is allocated under a row lock, so two
# simultaneous registrations cannot take the same number.
from django.db import models, transaction
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Facility


class Gender(models.TextChoices):
    """Nepal's official forms recognise a third gender; so does this system."""

    MALE = "male", "Male"
    FEMALE = "female", "Female"
    OTHER = "other", "Other"
    UNKNOWN = "unknown", "Not stated"


class MaritalStatus(models.TextChoices):
    SINGLE = "single", "Single"
    MARRIED = "married", "Married"
    WIDOWED = "widowed", "Widowed"
    DIVORCED = "divorced", "Divorced"
    SEPARATED = "separated", "Separated"
    UNKNOWN = "unknown", "Not stated"


class BloodGroup(models.TextChoices):
    A_POS = "A+", "A positive"
    A_NEG = "A-", "A negative"
    B_POS = "B+", "B positive"
    B_NEG = "B-", "B negative"
    AB_POS = "AB+", "AB positive"
    AB_NEG = "AB-", "AB negative"
    O_POS = "O+", "O positive"
    O_NEG = "O-", "O negative"
    UNKNOWN = "unknown", "Unknown"


class PatientCategory(models.TextChoices):
    """Who pays, and under what arrangement.

    Drives pricing, so it lives on the patient rather than being re-decided at
    every visit. An individual patient who later joins a corporate scheme has
    their category changed, and the change is versioned.
    """

    GENERAL = "general", "General"
    CORPORATE = "corporate", "Corporate"
    INSURANCE = "insurance", "Insurance"
    GOVERNMENT = "government", "Government scheme"
    STAFF = "staff", "Staff and dependants"
    CHARITY = "charity", "Charity / free"
    FOREIGN = "foreign", "Foreign national"


class PatientStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    DECEASED = "deceased", "Deceased"
    MERGED = "merged", "Merged into another record"


class Patient(BaseModel):
    """A person receiving care from this organization."""

    # -- identity --------------------------------------------------------

    #: Medical record number, unique across the organization. Human-quotable
    #: because patients are asked for it at a counter: "MRN-000142".
    mrn = models.CharField(max_length=32, unique=True, db_index=True)

    #: Stored as separate parts rather than one string. Nepali names do not
    #: split reliably on whitespace -- "Krishna Bahadur Shrestha" has a middle
    #: name, "Sita Devi" does not -- and search needs the parts.
    first_name = models.CharField(max_length=128)
    middle_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128)
    #: The name in Devanagari, for documents issued in Nepali.
    full_name_nepali = models.CharField(max_length=255, blank=True)

    gender = models.CharField(
        max_length=16, choices=Gender.choices, default=Gender.UNKNOWN, db_index=True
    )

    date_of_birth = models.DateField(null=True, blank=True, db_index=True)
    #: True when the date of birth was derived from a stated age rather than a
    #: document. Paediatric dosing and geriatric protocols both depend on age,
    #: so a clinician must be able to see that a date is an approximation.
    is_dob_estimated = models.BooleanField(default=False)
    #: Captured when no date of birth is available at all. Kept alongside the
    #: date rather than replacing it, so the original statement survives.
    stated_age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    stated_age_months = models.PositiveSmallIntegerField(null=True, blank=True)

    marital_status = models.CharField(
        max_length=16, choices=MaritalStatus.choices, default=MaritalStatus.UNKNOWN
    )
    blood_group = models.CharField(
        max_length=8, choices=BloodGroup.choices, default=BloodGroup.UNKNOWN
    )
    occupation = models.CharField(max_length=128, blank=True)
    nationality = models.CharField(max_length=64, default="Nepali")
    ethnicity = models.CharField(max_length=64, blank=True)
    religion = models.CharField(max_length=64, blank=True)
    preferred_language = models.CharField(max_length=32, default="ne")

    # -- contact ---------------------------------------------------------

    phone = models.CharField(max_length=32, blank=True, db_index=True)
    alternate_phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    province = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True, db_index=True)
    municipality = models.CharField(max_length=128, blank=True)
    ward = models.CharField(max_length=16, blank=True)
    tole = models.CharField(max_length=128, blank=True, help_text="Locality or street.")
    #: Where the patient actually lives now, when different from the permanent
    #: address on their documents. Follow-up and homecare use this one.
    temporary_address = models.CharField(max_length=255, blank=True)

    # -- relationships ---------------------------------------------------

    guardian_name = models.CharField(max_length=255, blank=True)
    guardian_relationship = models.CharField(max_length=64, blank=True)
    guardian_phone = models.CharField(max_length=32, blank=True)
    #: Required for minors and for patients who cannot consent for themselves.
    is_guardian_required = models.BooleanField(default=False)

    #: Links family members so a household shares contact details and a
    #: paediatric record can reach a parent quickly.
    family_head = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="family_members",
    )
    relationship_to_family_head = models.CharField(max_length=64, blank=True)

    # -- commercial ------------------------------------------------------

    category = models.CharField(
        max_length=16,
        choices=PatientCategory.choices,
        default=PatientCategory.GENERAL,
        db_index=True,
    )
    corporate_account = models.CharField(max_length=128, blank=True)
    insurance_policy_number = models.CharField(max_length=64, blank=True)

    # -- registration ----------------------------------------------------

    #: Where the patient first registered. They may be seen anywhere in the
    #: organization afterwards; this is provenance, not a restriction.
    registered_at_facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="registered_patients",
    )
    registered_on = models.DateTimeField(default=timezone.now, db_index=True)
    referred_by = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=16,
        choices=PatientStatus.choices,
        default=PatientStatus.ACTIVE,
        db_index=True,
    )

    date_of_death = models.DateField(null=True, blank=True)
    cause_of_death = models.CharField(max_length=255, blank=True)

    #: Set when this record was merged into another. The row is kept, not
    #: deleted: prescriptions, invoices and lab results already point at it,
    #: and a merge must never orphan a clinical record.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="merged_records",
    )
    merged_at = models.DateTimeField(null=True, blank=True)

    photo_url = models.URLField(blank=True)
    #: Free-text flags a clinician must see immediately: "aggressive on
    #: admission", "hard of hearing", "no blood products". Structured
    #: allergies live in `PatientAllergy`; this is for what does not fit.
    alerts = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    #: Consent to be contacted, held per channel because they differ: a
    #: patient may accept appointment reminders but not campaigns.
    consent_sms = models.BooleanField(default=True)
    consent_email = models.BooleanField(default=False)
    consent_marketing = models.BooleanField(default=False)

    class Meta:
        db_table = "patient"
        ordering = ["-registered_on"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["phone", "status"]),
            models.Index(fields=["status", "-registered_on"]),
            models.Index(fields=["district", "municipality"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.mrn})"

    # -- derived ---------------------------------------------------------

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(part for part in parts if part)

    @property
    def age_years(self) -> int | None:
        """Age today, from the date of birth or the stated age.

        Returns `None` rather than 0 when age is genuinely unknown: a
        newborn and an unknown age must not look the same to a dosing
        calculation.
        """
        if self.date_of_birth:
            today = timezone.localdate()
            years = today.year - self.date_of_birth.year
            if (today.month, today.day) < (
                self.date_of_birth.month,
                self.date_of_birth.day,
            ):
                years -= 1
            return years
        return self.stated_age_years

    @property
    def is_minor(self) -> bool:
        age = self.age_years
        return age is not None and age < 18

    @property
    def is_merged(self) -> bool:
        return self.merged_into_id is not None

    def resolve(self) -> "Patient":
        """Follow the merge chain to the surviving record.

        Guarded against cycles: a merge loop would otherwise hang every
        request that touched the record.
        """
        seen = {self.pk}
        current = self
        while current.merged_into_id is not None:
            if current.merged_into_id in seen:
                break
            current = current.merged_into
            seen.add(current.pk)
        return current

    # -- MRN allocation --------------------------------------------------

    @classmethod
    @transaction.atomic
    def allocate_mrn(cls, prefix: str = "MRN") -> str:
        """Allocate the next medical record number.

        Takes the highest existing number under a row-level lock rather than
        counting rows: counting would reuse a number after a hard delete, and
        two concurrent registrations at a busy counter would collide.

        `select_for_update` holds the lock until the surrounding transaction
        commits, so the caller must create the patient inside that same
        transaction for the guarantee to hold.
        """
        last = (
            cls.all_objects.select_for_update()
            .filter(mrn__startswith=f"{prefix}-")
            .order_by("-mrn")
            .values_list("mrn", flat=True)
            .first()
        )
        if last:
            try:
                sequence = int(last.rsplit("-", 1)[1]) + 1
            except (IndexError, ValueError):
                sequence = cls.all_objects.count() + 1
        else:
            sequence = 1
        return f"{prefix}-{sequence:06d}"


class IdentifierType(models.TextChoices):
    """Documents a Nepali patient might present. None is guaranteed."""

    NATIONAL_ID = "national_id", "National ID"
    CITIZENSHIP = "citizenship", "Citizenship certificate"
    PASSPORT = "passport", "Passport"
    DRIVING_LICENSE = "driving_license", "Driving licence"
    VOTER_ID = "voter_id", "Voter ID"
    BIRTH_CERTIFICATE = "birth_certificate", "Birth certificate"
    INSURANCE_CARD = "insurance_card", "Health insurance card"
    EMPLOYEE_ID = "employee_id", "Employee ID"
    REFUGEE_ID = "refugee_id", "Refugee ID"
    EXTERNAL_MRN = "external_mrn", "MRN at another facility"
    OTHER = "other", "Other"


class PatientIdentifier(BaseModel):
    """A document number a patient is known by.

    Separate from the patient row because a patient may hold several, may hold
    none, and may acquire one later. Modelling identity as a list of claims
    rather than a column is also what makes duplicate detection possible: two
    records sharing a citizenship number are almost certainly one person.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="identifiers"
    )
    identifier_type = models.CharField(
        max_length=32, choices=IdentifierType.choices, db_index=True
    )
    value = models.CharField(max_length=128, db_index=True)
    issued_by = models.CharField(max_length=128, blank=True)
    issued_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)

    #: Set once a document has been seen. An unverified number is a claim, not
    #: a fact, and insurance and legal processes need to know which it is.
    is_verified = models.BooleanField(default=False)
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    document_url = models.URLField(blank=True)

    class Meta:
        db_table = "patient_identifier"
        ordering = ["identifier_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["identifier_type", "value"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_identifier_value",
            )
        ]
        indexes = [models.Index(fields=["identifier_type", "value"])]

    def __str__(self):
        return f"{self.get_identifier_type_display()}: {self.value}"


class AllergySeverity(models.TextChoices):
    MILD = "mild", "Mild"
    MODERATE = "moderate", "Moderate"
    SEVERE = "severe", "Severe"
    LIFE_THREATENING = "life_threatening", "Life-threatening"


class AllergyStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    RESOLVED = "resolved", "Resolved"
    #: Recorded but not confirmed. Never silently dropped: an unverified
    #: penicillin allergy must still stop a prescription until a clinician
    #: rules it out.
    UNCONFIRMED = "unconfirmed", "Unconfirmed"
    REFUTED = "refuted", "Refuted"


class PatientAllergy(BaseModel):
    """A recorded allergy or intolerance.

    Structured rather than free text because prescribing has to check it
    automatically. `substance_code` is left free-form for now and should be
    bound to a drug dictionary when the pharmacy product master lands.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="allergies"
    )
    substance = models.CharField(max_length=255)
    substance_code = models.CharField(
        max_length=64, blank=True,
        help_text="Dictionary code, once a drug dictionary exists.",
    )
    category = models.CharField(
        max_length=32,
        choices=[
            ("medication", "Medication"),
            ("food", "Food"),
            ("environment", "Environmental"),
            ("biologic", "Biologic"),
        ],
        default="medication",
    )
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(
        max_length=24, choices=AllergySeverity.choices, default=AllergySeverity.MODERATE
    )
    status = models.CharField(
        max_length=16, choices=AllergyStatus.choices, default=AllergyStatus.ACTIVE
    )
    onset_date = models.DateField(null=True, blank=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "patient_allergy"
        ordering = ["-severity", "substance"]
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self):
        return f"{self.substance} ({self.get_severity_display()})"

    @property
    def blocks_prescribing(self) -> bool:
        """Whether this allergy should stop a prescription.

        Refuted allergies do not; unconfirmed ones do. The asymmetry is
        deliberate -- the cost of a spurious warning is an extra click, and
        the cost of a missed one can be anaphylaxis.
        """
        return self.status in {AllergyStatus.ACTIVE, AllergyStatus.UNCONFIRMED}


class ConditionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    RESOLVED = "resolved", "Resolved"
    REMISSION = "remission", "In remission"
    RELAPSE = "relapse", "Relapsed"


class PatientCondition(BaseModel):
    """A chronic or significant past condition.

    Distinct from a diagnosis on an encounter: a diagnosis is what was decided
    at one visit, a condition is what the patient carries between visits.
    Diabetes diagnosed in 2019 should surface in 2026 without anyone reading
    seven years of notes.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="conditions"
    )
    name = models.CharField(max_length=255)
    #: ICD-10 where known. Blank is accepted: coding often happens later, and
    #: refusing the record until it is coded loses the clinical fact.
    icd10_code = models.CharField(max_length=16, blank=True, db_index=True)
    category = models.CharField(
        max_length=32,
        choices=[
            ("chronic", "Chronic condition"),
            ("surgical", "Past surgery"),
            ("family", "Family history"),
            ("obstetric", "Obstetric history"),
            ("psychiatric", "Psychiatric history"),
        ],
        default="chronic",
    )
    status = models.CharField(
        max_length=16, choices=ConditionStatus.choices, default=ConditionStatus.ACTIVE
    )
    onset_date = models.DateField(null=True, blank=True)
    resolved_date = models.DateField(null=True, blank=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "patient_condition"
        ordering = ["-onset_date", "name"]
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self):
        return self.name


class PatientMergeLog(BaseModel):
    """A permanent record of one patient record being merged into another.

    Merges are irreversible in practice -- once records are combined, later
    clinical entries attach to the survivor -- so the *evidence* for the
    decision is kept. If a merge turns out to have been wrong, this is what
    makes untangling it possible.
    """

    surviving_patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="merges_received"
    )
    merged_patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="merges_performed"
    )
    reason = models.TextField()
    #: What matched: shared phone, shared citizenship number, name and date of
    #: birth. Recorded so a bad merge rule can be found and corrected.
    matched_on = models.JSONField(default=list, blank=True)
    #: A copy of the merged record as it stood, so nothing is lost even if
    #: fields were overwritten on the survivor.
    merged_snapshot = models.JSONField(default=dict, blank=True)

    performed_by_id = models.UUIDField(null=True, blank=True)
    performed_by_email = models.CharField(max_length=254, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "patient_merge_log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.merged_patient_id} → {self.surviving_patient_id}"
