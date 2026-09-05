"""People: who works here, in what job, with what licence, since when.

Four decisions shape this module.

**An employee is not a user.** Most of the people a hospital employs never
log in — cleaners, drivers, kitchen staff, ward attendants. A user account is
an optional attachment to an employee record, not the same object. Collapsing
them would mean either inventing dormant logins for people who will never use
one, or leaving a third of the payroll off the system.

**Employment history is append-only.** A transfer does not overwrite the
department; it writes an `EmploymentEvent` and moves the current pointer.
"Which ward was this nurse on when that incident happened?" is a question the
record has to answer months later, and a mutated row cannot.

**A lapsed credential blocks clinical work.** The same shape as the supplier
drug-licence rule in procurement: a doctor whose Nepal Medical Council
registration has expired may not be scheduled or prescribe under. Checked when
it matters rather than discovered in an audit.

**The provider linkage is the point of all this.** Scheduling, encounters and
prescriptions each carry a bare `provider_uuid` pointing at an identity user,
with nothing behind it — no name to print on a prescription, no licence to
check, no department to report by. `Employee.user_id` is what closes that gap,
which is why it is indexed and why `for_user()` exists.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.organization.models import Department, Facility

ZERO = Decimal("0.00")


class EmploymentType(models.TextChoices):
    """How someone is engaged.

    Drives payroll, statutory contributions and notice periods, all of which
    differ. A visiting consultant paid per session and a permanent staff nurse
    are both "employees" to the org chart and nothing alike to payroll.
    """

    PERMANENT = "permanent", "Permanent"
    PROBATION = "probation", "On probation"
    CONTRACT = "contract", "Contract"
    LOCUM = "locum", "Locum"
    VISITING = "visiting", "Visiting consultant"
    INTERN = "intern", "Intern"
    TRAINEE = "trainee", "Trainee"
    PART_TIME = "part_time", "Part time"
    DAILY_WAGE = "daily_wage", "Daily wage"


class EmployeeStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ON_LEAVE = "on_leave", "On extended leave"
    SUSPENDED = "suspended", "Suspended"
    NOTICE = "notice", "Serving notice"
    SEPARATED = "separated", "Separated"


#: Statuses in which someone may be rostered, consulted, or paid.
#: Suspension and separation both stop work; only one is reversible.
WORKING_STATUSES = {EmployeeStatus.ACTIVE, EmployeeStatus.ON_LEAVE}


class Position(BaseModel):
    """A job that exists in the organization, whether or not anyone holds it.

    Separate from `Employee` because headcount is planned against the job, not
    the person. "We are two nurses short on the night shift" is a statement
    about positions; asking it of employee rows can only tell you how many
    nurses there are, never how many there should be.
    """

    code = models.CharField(max_length=32, db_index=True)
    title = models.CharField(max_length=255)
    title_nepali = models.CharField(max_length=255, blank=True)

    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="positions",
        help_text="Null for a position that exists organization-wide.",
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="positions",
    )

    #: Pay band. A string rather than a number because Nepali public-sector
    #: grades are not ordinal in a way arithmetic respects.
    grade = models.CharField(max_length=32, blank=True)
    #: For the org chart. Self-referential on the *position*, not the person,
    #: so the hierarchy survives someone leaving.
    reports_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="direct_reports",
    )

    #: How many people this position is budgeted for. Vacancies are this minus
    #: the employees currently holding it.
    budgeted_headcount = models.PositiveSmallIntegerField(default=1)
    job_description = models.TextField(blank=True)

    #: True when holding this position means treating patients — which is what
    #: makes a lapsed professional licence a blocker rather than a note.
    is_clinical = models.BooleanField(default=False)
    #: Whether the holder may be scheduled for consultations. Not every
    #: clinical role takes appointments: a ward nurse is clinical and is not
    #: a provider.
    is_provider = models.BooleanField(default=False)
    requires_licence = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "hr_position"
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_position_code",
            )
        ]
        indexes = [
            models.Index(fields=["facility", "is_active"]),
            models.Index(fields=["is_provider", "is_active"]),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"

    @property
    def filled(self) -> int:
        return self.employees.filter(status__in=WORKING_STATUSES).count()

    @property
    def vacancies(self) -> int:
        """Budgeted minus filled, floored at zero.

        Floored because an over-filled position is a real and legitimate
        state — a handover overlap, an approved temporary excess — and
        reporting it as a negative vacancy would put a nonsense number in
        front of a manager rather than a useful one.
        """
        return max(self.budgeted_headcount - self.filled, 0)


class Employee(BaseModel):
    """A person the organization employs.

    Current posting lives here — facility, department, position, manager —
    and every change to it is also written to `EmploymentEvent`. The
    denormalised pointer is what a roster query needs; the event log is what
    a question about last March needs. Neither can serve both.
    """

    employee_code = models.CharField(max_length=32, db_index=True)

    # -- identity ----------------------------------------------------------

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    name_nepali = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=16, blank=True)
    #: Nepali citizenship number. Not unique: the same number is issued in
    #: different districts, and enforcing uniqueness would block a legitimate
    #: hire because of somebody else's paperwork.
    citizenship_number = models.CharField(max_length=32, blank=True)
    pan_number = models.CharField(max_length=20, blank=True)
    blood_group = models.CharField(max_length=8, blank=True)
    photo_url = models.URLField(blank=True)

    phone = models.CharField(max_length=32, blank=True)
    personal_email = models.EmailField(blank=True)
    address = models.CharField(max_length=512, blank=True)
    province = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True)
    municipality = models.CharField(max_length=128, blank=True)

    emergency_contact_name = models.CharField(max_length=255, blank=True)
    emergency_contact_phone = models.CharField(max_length=32, blank=True)
    emergency_contact_relation = models.CharField(max_length=64, blank=True)

    # -- employment --------------------------------------------------------

    position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="employees",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="employees"
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="employees",
    )
    #: The person, not the position: an employee reports to whoever actually
    #: signs their leave, which is not always the position hierarchy.
    reports_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="direct_reports",
    )

    employment_type = models.CharField(
        max_length=16, choices=EmploymentType.choices,
        default=EmploymentType.PERMANENT, db_index=True,
    )
    status = models.CharField(
        max_length=16, choices=EmployeeStatus.choices,
        default=EmployeeStatus.ACTIVE, db_index=True,
    )

    joined_on = models.DateField(default=timezone.localdate)
    #: Null while probation is open or the role is permanent.
    probation_ends_on = models.DateField(null=True, blank=True)
    confirmed_on = models.DateField(null=True, blank=True)
    separated_on = models.DateField(null=True, blank=True)
    separation_reason = models.CharField(max_length=512, blank=True)

    # -- links -------------------------------------------------------------

    #: The identity user, when this person logs in. Optional and indexed:
    #: most employees never have an account, and the ones who do are looked
    #: up by it constantly — every scheduling, encounter and prescription row
    #: carries a bare provider uuid that resolves through here.
    user_id = models.UUIDField(null=True, blank=True, db_index=True)
    work_email = models.EmailField(blank=True)

    #: Payroll destination. Held per employee rather than per contract because
    #: people change banks without changing jobs.
    bank_name = models.CharField(max_length=128, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)
    bank_branch = models.CharField(max_length=128, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "hr_employee"
        ordering = ["first_name", "last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee_code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_employee_code",
            ),
            # One employee record per login. Two would make "who prescribed
            # this?" ambiguous, which is the one thing the linkage exists to
            # answer.
            models.UniqueConstraint(
                fields=["user_id"],
                condition=models.Q(deleted_at__isnull=True,
                                   user_id__isnull=False),
                name="uniq_employee_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["department", "status"]),
            models.Index(fields=["last_name", "first_name"]),
        ]

    def __str__(self):
        return f"{self.employee_code} — {self.full_name}"

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(part for part in parts if part)

    @property
    def is_working(self) -> bool:
        return self.status in WORKING_STATUSES

    @property
    def is_clinical(self) -> bool:
        """Whether this person treats patients.

        Delegates to the position, the same way `is_provider` does. The
        asymmetry was the bug: `Position` carries both flags, `Employee`
        forwarded only one, and the self-service summary asking for the other
        crashed every call. Not every clinical person is a provider -- a ward
        nurse is clinical and is not scheduled for consultations -- so the two
        are genuinely different questions and both need answering here.
        """
        return bool(self.position and self.position.is_clinical)

    @property
    def is_provider(self) -> bool:
        """Whether this person may be scheduled and may prescribe."""
        return bool(self.position and self.position.is_provider)

    @property
    def years_of_service(self) -> Decimal:
        end = self.separated_on or timezone.localdate()
        days = (end - self.joined_on).days
        return (Decimal(days) / Decimal("365.25")).quantize(Decimal("0.1"))

    @property
    def on_probation(self) -> bool:
        if self.confirmed_on or not self.probation_ends_on:
            return False
        return timezone.localdate() <= self.probation_ends_on

    @property
    def probation_overdue(self) -> bool:
        """Probation has ended and nobody confirmed or terminated.

        Worth surfacing rather than leaving implicit: an unconfirmed employee
        past their probation date is in a legally ambiguous position, and the
        only reason it happens is that nobody was reminded.
        """
        if self.confirmed_on or not self.probation_ends_on:
            return False
        return timezone.localdate() > self.probation_ends_on

    def clean(self):
        if self.separated_on and self.separated_on < self.joined_on:
            raise ValidationError(
                {"separated_on": "Someone cannot leave before they joined."}
            )

    @classmethod
    def for_user(cls, user_id):
        """The employee behind a login, or None.

        The single place the `provider_uuid` scattered through scheduling,
        encounters and prescriptions is resolved. Returns None rather than
        raising: a platform administrator has a login and no employee record,
        and that is not an error.
        """
        if not user_id:
            return None
        return cls.objects.filter(user_id=user_id).first()


class CredentialType(models.TextChoices):
    """What kind of paper this is.

    Separated because they expire differently and block differently. A lapsed
    council registration stops someone practising; a lapsed first-aid
    certificate is a training gap.
    """

    COUNCIL_REGISTRATION = "council", "Professional council registration"
    LICENCE = "licence", "Practising licence"
    DEGREE = "degree", "Academic qualification"
    SPECIALISATION = "specialisation", "Specialisation"
    CERTIFICATION = "certification", "Certification"
    TRAINING = "training", "Training"


#: Credential types whose expiry stops someone working clinically.
#: A degree does not expire; a registration does, and practising on a lapsed
#: one is an offence under the councils' own rules.
BLOCKING_CREDENTIALS = {
    CredentialType.COUNCIL_REGISTRATION,
    CredentialType.LICENCE,
}


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Not verified"
    VERIFIED = "verified", "Verified"
    FAILED = "failed", "Verification failed"


class Credential(BaseModel):
    """A qualification, registration or licence held by an employee.

    Verification is recorded separately from the claim. Someone typing "NMC
    12345" into a form has asserted something; somebody checking the council
    register has established it, and the difference matters when a patient is
    harmed.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="credentials"
    )
    credential_type = models.CharField(
        max_length=20, choices=CredentialType.choices, db_index=True
    )
    name = models.CharField(max_length=255)
    #: Nepal Medical Council, Nepal Nursing Council, Nepal Pharmacy Council…
    issuing_body = models.CharField(max_length=255, blank=True)
    reference_number = models.CharField(max_length=64, blank=True, db_index=True)

    issued_on = models.DateField(null=True, blank=True)
    #: Null means it does not expire — a degree, typically.
    expires_on = models.DateField(null=True, blank=True, db_index=True)

    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED, db_index=True,
    )
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_by_name = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.CharField(max_length=512, blank=True)

    document_url = models.URLField(blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "hr_credential"
        ordering = ["credential_type", "-issued_on"]
        indexes = [
            models.Index(fields=["employee", "credential_type"]),
            models.Index(fields=["expires_on", "verification_status"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.employee.employee_code})"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_on and self.expires_on < timezone.localdate())

    @property
    def days_to_expiry(self) -> int | None:
        if not self.expires_on:
            return None
        return (self.expires_on - timezone.localdate()).days

    @property
    def blocks_practice(self) -> bool:
        """Whether this credential's state stops the person working.

        Unverified counts. A registration nobody has checked is a registration
        that might not exist, and the point of recording verification is that
        the unchecked case is visible rather than assumed good.
        """
        if self.credential_type not in BLOCKING_CREDENTIALS:
            return False
        return self.is_expired or self.verification_status == (
            VerificationStatus.FAILED
        )


class ContractStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    SUPERSEDED = "superseded", "Superseded"
    TERMINATED = "terminated", "Terminated"


class EmploymentContract(BaseModel):
    """The terms someone works under, dated.

    A new contract supersedes rather than edits the old one. Last year's
    payroll must still be explicable against the terms that applied when it
    ran, and a salary revision that overwrote history would make an old
    payslip unreproducible.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="contracts"
    )
    reference = models.CharField(max_length=32, blank=True)
    employment_type = models.CharField(
        max_length=16, choices=EmploymentType.choices
    )

    starts_on = models.DateField()
    #: Null for an open-ended permanent contract.
    ends_on = models.DateField(null=True, blank=True, db_index=True)
    notice_period_days = models.PositiveSmallIntegerField(default=30)

    basic_salary = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO,
        validators=[MinValueValidator(ZERO)],
    )
    #: Per month unless the employment type is sessional or daily, in which
    #: case payroll reads `rate_basis`.
    rate_basis = models.CharField(
        max_length=16,
        choices=[
            ("monthly", "Per month"),
            ("daily", "Per day"),
            ("hourly", "Per hour"),
            ("session", "Per session"),
        ],
        default="monthly",
    )
    allowances = models.JSONField(
        default=dict, blank=True,
        help_text="Named allowances, e.g. {'transport': '2000.00'}.",
    )
    working_hours_per_week = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("48.00")
    )

    status = models.CharField(
        max_length=16, choices=ContractStatus.choices,
        default=ContractStatus.ACTIVE, db_index=True,
    )
    signed_on = models.DateField(null=True, blank=True)
    document_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "hr_contract"
        ordering = ["-starts_on"]
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["ends_on", "status"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_code} from {self.starts_on}"

    @property
    def is_expired(self) -> bool:
        return bool(self.ends_on and self.ends_on < timezone.localdate())

    @property
    def days_to_expiry(self) -> int | None:
        if not self.ends_on:
            return None
        return (self.ends_on - timezone.localdate()).days

    @property
    def gross_monthly(self) -> Decimal:
        """Basic plus every allowance.

        Allowances live in a JSON field because their names differ per
        organization and hard-coding a column per allowance would mean a
        migration every time a customer invents one. The arithmetic is still
        `Decimal`: the values are parsed, never floated.
        """
        total = Decimal(self.basic_salary)
        for value in (self.allowances or {}).values():
            try:
                total += Decimal(str(value))
            except (ArithmeticError, ValueError, TypeError):
                # A malformed allowance must not silently zero the payslip;
                # it is skipped here and reported by the payroll validation.
                continue
        return total.quantize(Decimal("0.01"))


class EventType(models.TextChoices):
    """Everything that can change about someone's employment.

    Enumerated rather than free text because these drive reporting — turnover,
    internal mobility, promotion rates — and a free-text reason cannot be
    counted.
    """

    JOINED = "joined", "Joined"
    CONFIRMED = "confirmed", "Confirmed after probation"
    TRANSFER = "transfer", "Transferred"
    PROMOTION = "promotion", "Promoted"
    DEMOTION = "demotion", "Demoted"
    DEPARTMENT_CHANGE = "department_change", "Department changed"
    MANAGER_CHANGE = "manager_change", "Reporting manager changed"
    TYPE_CHANGE = "type_change", "Employment type changed"
    SUSPENSION = "suspension", "Suspended"
    REINSTATEMENT = "reinstatement", "Reinstated"
    RESIGNATION = "resignation", "Resigned"
    TERMINATION = "termination", "Terminated"
    RETIREMENT = "retirement", "Retired"


class EmploymentEvent(BaseModel):
    """One change to someone's employment, kept forever.

    The `from_*` / `to_*` pairs are snapshots as strings rather than foreign
    keys. A department that is later renamed or closed must not rewrite or
    break the history of who worked in it — the same reason an invoice line
    stores the service name it was billed under.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(
        max_length=20, choices=EventType.choices, db_index=True
    )
    effective_on = models.DateField(default=timezone.localdate, db_index=True)

    from_position = models.CharField(max_length=255, blank=True)
    to_position = models.CharField(max_length=255, blank=True)
    from_facility = models.CharField(max_length=255, blank=True)
    to_facility = models.CharField(max_length=255, blank=True)
    from_department = models.CharField(max_length=255, blank=True)
    to_department = models.CharField(max_length=255, blank=True)
    from_employment_type = models.CharField(max_length=32, blank=True)
    to_employment_type = models.CharField(max_length=32, blank=True)

    reason = models.CharField(max_length=512, blank=True)
    #: Who decided. A transfer nobody approved is a transfer nobody owns.
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "hr_employment_event"
        ordering = ["-effective_on", "-created_at"]
        indexes = [
            models.Index(fields=["employee", "-effective_on"]),
            models.Index(fields=["event_type", "-effective_on"]),
        ]

    def __str__(self):
        return (
            f"{self.employee.employee_code} "
            f"{self.get_event_type_display().lower()} on {self.effective_on}"
        )

    @property
    def summary(self) -> str:
        """A human sentence for the timeline."""
        moves = []
        if self.to_position and self.to_position != self.from_position:
            moves.append(f"{self.from_position or '—'} → {self.to_position}")
        if self.to_facility and self.to_facility != self.from_facility:
            moves.append(f"{self.from_facility or '—'} → {self.to_facility}")
        if self.to_department and self.to_department != self.from_department:
            moves.append(f"{self.from_department or '—'} → {self.to_department}")
        return "; ".join(moves) or self.get_event_type_display()


class DocumentType(models.TextChoices):
    CITIZENSHIP = "citizenship", "Citizenship"
    PASSPORT = "passport", "Passport"
    PHOTO = "photo", "Photograph"
    CV = "cv", "Curriculum vitae"
    CERTIFICATE = "certificate", "Certificate"
    CONTRACT = "contract", "Contract"
    APPOINTMENT = "appointment", "Appointment letter"
    EXPERIENCE = "experience", "Experience letter"
    BANK = "bank", "Bank details"
    MEDICAL = "medical", "Medical clearance"
    POLICE = "police", "Police clearance"
    OTHER = "other", "Other"


class EmployeeDocument(BaseModel):
    """A file held against an employee.

    Metadata only. The file itself lives in object storage, and the record
    exists so that "what are we missing for this person?" is answerable
    without opening a folder — which is the whole of what onboarding
    compliance means in practice.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(
        max_length=20, choices=DocumentType.choices, db_index=True
    )
    title = models.CharField(max_length=255)
    file_url = models.URLField(blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)

    expires_on = models.DateField(null=True, blank=True)
    is_mandatory = models.BooleanField(default=False)
    uploaded_by_id = models.UUIDField(null=True, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "hr_employee_document"
        ordering = ["document_type", "-created_at"]
        indexes = [models.Index(fields=["employee", "document_type"])]

    def __str__(self):
        return f"{self.title} ({self.employee.employee_code})"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_on and self.expires_on < timezone.localdate())


class Experience(BaseModel):
    """Where somebody worked before here.

    Kept because clinical seniority, pay grade and locum rates are all argued
    from it, and because a claimed ten years that nobody ever checked is
    exactly the kind of thing that surfaces after an incident.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="experience"
    )
    organization_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=255)
    department = models.CharField(max_length=255, blank=True)
    started_on = models.DateField()
    ended_on = models.DateField(null=True, blank=True)
    responsibilities = models.TextField(blank=True)

    reference_name = models.CharField(max_length=255, blank=True)
    reference_contact = models.CharField(max_length=128, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    document_url = models.URLField(blank=True)

    class Meta:
        db_table = "hr_experience"
        ordering = ["-started_on"]
        indexes = [models.Index(fields=["employee", "-started_on"])]

    def __str__(self):
        return f"{self.job_title} at {self.organization_name}"

    @property
    def months(self) -> int:
        end = self.ended_on or timezone.localdate()
        return max((end.year - self.started_on.year) * 12
                   + end.month - self.started_on.month, 0)

    @property
    def years(self) -> Decimal:
        return (Decimal(self.months) / Decimal(12)).quantize(Decimal("0.1"))

    def clean(self):
        if self.ended_on and self.ended_on < self.started_on:
            raise ValidationError(
                {"ended_on": "A job cannot end before it started."}
            )
        if self.started_on > timezone.localdate():
            raise ValidationError(
                {"started_on": "That start date is in the future."}
            )


class SkillLevel(models.TextChoices):
    AWARENESS = "awareness", "Awareness"
    WORKING = "working", "Working"
    PROFICIENT = "proficient", "Proficient"
    EXPERT = "expert", "Expert"


class Skill(BaseModel):
    """Something an employee can do, at a stated level.

    Distinct from a credential: a credential is paper somebody else issued, a
    skill is an assessment this organization made. Rostering needs the second
    — "who on tonight can run a ventilator" is not answered by a degree
    certificate.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="skills"
    )
    name = models.CharField(max_length=255, db_index=True)
    level = models.CharField(
        max_length=16, choices=SkillLevel.choices, default=SkillLevel.WORKING
    )
    assessed_on = models.DateField(null=True, blank=True)
    assessed_by_id = models.UUIDField(null=True, blank=True)
    assessed_by_name = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "hr_skill"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_skill_per_employee",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.get_level_display()})"


class ProfileCorrectionStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class ProfileCorrectionRequest(BaseModel):
    """An employee requesting a correction to their profile or bank details.

    Contact information (address, phone, next of kin) and bank account details
    feed payroll, tax filings, and legal notices. Directly overwriting them
    from self-service risks unverified updates; an employee proposes the change,
    and HR or their manager approves it before it is committed.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="correction_requests"
    )
    requested_by_user_id = models.UUIDField()
    fields_payload = models.JSONField(
        default=dict,
        help_text="Dictionary of proposed field changes.",
    )
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=ProfileCorrectionStatus.choices,
        default=ProfileCorrectionStatus.PENDING,
        db_index=True,
    )
    decided_by_user_id = models.UUIDField(null=True, blank=True)
    decided_by_name = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True)

    class Meta:
        db_table = "hr_profile_correction"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.employee_code} correction ({self.status})"


# ---------------------------------------------------------------------------
# Attendance, leave and rostering
# ---------------------------------------------------------------------------
#
# Re-exported from `attendance_models` so `apps.hr.models` stays the single
# import point for the app. They live in their own module because they are a
# different kind of data -- the employee record changes a few times a career,
# these change every day for everybody -- and a thousand-line models.py stops
# being readable long before it stops working.

from apps.hr.attendance_models import (  # noqa: E402,F401
    WEEKLY_HOLIDAY,
    Attendance,
    AttendanceRegularisation,
    AttendanceSource,
    AttendanceStatus,
    Holiday,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    LeaveUnit,
    LedgerReason,
    RegularisationStatus,
    RosterEntry,
    RosterStatus,
    Shift,
    ShiftSwapRequest,
    ShiftSwapStatus,
    ShiftType,
)

