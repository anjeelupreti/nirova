"""Referrals: the handoff, and the loop that usually never closes.

Almost every clinical system can send a referral. The thing that goes wrong is
what happens afterwards: the patient is referred, and nobody at the referring
end ever learns whether they went, whether they were seen, or what was found.
The referral is written, filed, and forgotten by everyone except the patient.

So this module is built around the loop rather than the letter. Six decisions
follow from that, and most of them are about states that other systems collapse.

**Sent, acknowledged, seen and answered are four different things.** A
referral acknowledged by a hospital's front desk has not been seen by a
consultant. One seen by a consultant has not been answered back to the
referrer. Collapsing these into "in progress" is precisely how a referral sits
for four months with everybody assuming somebody else is chasing it.

**The referring clinician asks a question, and the answer must answer it.**
A referral asks something specific — "is this resectable?", "does she need
insulin?" — and a reply of "seen and treated" is not a response to it. The
question and the response are separate fields, and the response is its own
record with its own author and date.

**A declined referral is more useful than a silent one.** Declining carries a
reason from a fixed list, because the aggregate is what tells a referring
clinic what to fix: forty referrals declined for "insufficient information" is
a template problem, not forty individual mistakes.

**Internal and external referrals are genuinely different.** An internal one
can create an appointment and read the patient's record; an external one goes
to an organisation with no shared database, and every fact it needs must
travel with it. Modelling them as one thing with optional fields produces a
workflow whose external branch quietly does nothing.

**The letter is assembled, not typed.** Allergies, medications, results and
history are pulled together at the moment of sending and *frozen*, because a
letter is a statement of what was known then. A letter regenerated six months
later from live data is a different letter with the same date on it.

**Urgency carries a target, and breaching it is visible.** A referral pathway
with no clock is one nobody chases — the same reasoning as the emergency
department's triage targets.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# BaseModel: UUID, timestamps, soft delete. UUIDs are the published
# identifier — with a database per tenant an integer PK names a different row
# in every customer's database.
from apps.common.models import BaseModel
from apps.encounters.models import Encounter
from apps.organization.models import Department, Facility
from apps.patients.models import Patient


class ReferralDirection(models.TextChoices):
    """Where the referral is going, which decides what is possible.

    An internal referral can book an appointment and read the record. An
    outbound one goes to an organisation with no shared database and must
    carry everything with it. An inbound one arrives from outside and the
    hospital's job is to answer it. Three genuinely different workflows, so
    three values rather than one flag.
    """

    INTERNAL = "internal", "Within this organization"
    OUTBOUND = "outbound", "Out to another provider"
    INBOUND = "inbound", "In from another provider"


class ReferralUrgency(models.TextChoices):
    ROUTINE = "routine", "Routine"
    SOON = "soon", "Soon"
    #: The two-week cancer pathway and its equivalents.
    URGENT = "urgent", "Urgent"
    EMERGENCY = "emergency", "Emergency — same day"


#: Days within which each urgency should be seen.
#:
#: Data rather than code, because the numbers are set by policy and differ
#: between specialties and countries. Without a clock a referral pathway is
#: something nobody chases — the same reasoning as the emergency department's
#: triage targets.
TARGET_DAYS = {
    ReferralUrgency.EMERGENCY: 0,
    ReferralUrgency.URGENT: 14,
    ReferralUrgency.SOON: 42,
    ReferralUrgency.ROUTINE: 90,
}


class ReferralStatus(models.TextChoices):
    """Every state a referral can be in, and they are not merged.

    `ACKNOWLEDGED` and `ACCEPTED` are separate because a front desk logging
    receipt is not a department agreeing to see the patient. `SEEN` and
    `RESPONDED` are separate because being seen does not tell the referrer
    anything. Each of those pairs is a place where a referral silently stops.
    """

    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    ACKNOWLEDGED = "acknowledged", "Receipt acknowledged"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    BOOKED = "booked", "Appointment booked"
    SEEN = "seen", "Patient seen"
    #: The specialist has answered the referrer's question.
    RESPONDED = "responded", "Answered"
    #: Care handed back to the referrer.
    COMPLETED = "completed", "Completed"
    #: The patient did not attend. An outcome, not an absence.
    DID_NOT_ATTEND = "dna", "Patient did not attend"
    CANCELLED = "cancelled", "Cancelled"
    #: Nobody did anything for long enough that it is no longer live. Its own
    #: state, because a referral that quietly stopped mattering is the failure
    #: this module exists to make visible.
    LAPSED = "lapsed", "Lapsed without an outcome"


#: Statuses in which the referral is still somebody's responsibility.
OPEN_STATUSES = (
    ReferralStatus.DRAFT,
    ReferralStatus.SENT,
    ReferralStatus.ACKNOWLEDGED,
    ReferralStatus.ACCEPTED,
    ReferralStatus.BOOKED,
    ReferralStatus.SEEN,
)


#: Why a referral was declined.
#:
#: A fixed list, because the only useful thing about a decline is the
#: aggregate: forty referrals declined for "insufficient information" is a
#: template problem, not forty individual mistakes. Free text produces a year
#: of reasons nobody can count.
DECLINE_REASONS = [
    ("wrong_specialty", "Not this specialty"),
    ("insufficient_information", "Not enough clinical information"),
    ("no_investigations", "Required investigations not done first"),
    ("manageable_locally", "Can be managed at the referring facility"),
    ("no_capacity", "No capacity"),
    ("service_unavailable", "Service not offered here"),
    ("patient_ineligible", "Patient not eligible for this service"),
    ("duplicate", "Duplicate of an existing referral"),
    ("patient_declined", "Patient declined the referral"),
    ("other", "Other"),
]

DECLINE_REASON_KEYS = {key for key, _ in DECLINE_REASONS}


class ExternalProvider(BaseModel):
    """A hospital, clinic or specialist outside this organization.

    A directory rather than free text on each referral, so that "how many
    patients did we send to Bir Hospital last year, and how many came back
    with an answer" is a question with an answer.
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    provider_type = models.CharField(
        max_length=32, blank=True,
        help_text="Hospital, clinic, laboratory, individual specialist.",
    )
    specialties = models.JSONField(
        default=list, blank=True,
        help_text="What they accept referrals for.",
    )

    contact_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=512, blank=True)
    district = models.CharField(max_length=64, blank=True)

    #: How this provider is actually reached. A referral emailed to somebody
    #: with no email is a referral that was never sent, and the system should
    #: know that before it claims otherwise.
    accepts_email = models.BooleanField(default=False)
    accepts_paper = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uniq_provider_code"),
        ]

    def __str__(self):
        return self.name


class Referral(BaseModel):
    """One handoff of a patient's care, and everything that happened to it."""

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="referrals",
    )
    #: The encounter the referral came out of. Nullable because an inbound
    #: referral has no encounter here until the patient is seen.
    encounter = models.ForeignKey(
        Encounter, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals",
    )
    direction = models.CharField(
        max_length=12, choices=ReferralDirection.choices, db_index=True,
    )

    # -- who is asking -----------------------------------------------------
    from_facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="referrals_made",
    )
    from_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals_made",
    )
    referrer_id = models.UUIDField(null=True, blank=True)
    referrer_name = models.CharField(max_length=255)
    #: For an inbound referral the referrer is outside, and their registration
    #: number is how the reply gets back to the right person.
    referrer_registration = models.CharField(max_length=64, blank=True)
    referrer_contact = models.CharField(max_length=128, blank=True)

    # -- who is being asked ------------------------------------------------
    to_facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="referrals_received",
    )
    to_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals_received",
    )
    to_provider = models.ForeignKey(
        ExternalProvider, null=True, blank=True, on_delete=models.PROTECT,
        related_name="referrals",
    )
    to_clinician_name = models.CharField(max_length=255, blank=True)
    specialty = models.CharField(max_length=64, db_index=True)

    # -- what is being asked ----------------------------------------------
    urgency = models.CharField(
        max_length=12, choices=ReferralUrgency.choices,
        default=ReferralUrgency.ROUTINE, db_index=True,
    )
    reason = models.CharField(
        max_length=512,
        help_text="Why the patient is being referred.",
    )
    #: The specific thing the referrer wants to know. Separate from `reason`
    #: because "chronic cough" is not a question, and a reply of "seen and
    #: treated" answers nothing. The response is checked against this.
    question = models.CharField(
        max_length=512, blank=True,
        help_text="The specific question the referrer wants answered.",
    )
    clinical_summary = models.TextField(blank=True)
    provisional_diagnosis = models.CharField(max_length=512, blank=True)
    diagnosis_code = models.CharField(max_length=32, blank=True)

    status = models.CharField(
        max_length=16, choices=ReferralStatus.choices,
        default=ReferralStatus.DRAFT, db_index=True,
    )

    # -- the loop ----------------------------------------------------------
    created_on = models.DateField(default=timezone.localdate, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    #: Somebody at the other end logged receipt. Not the same as accepting it.
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_name = models.CharField(max_length=255, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=32, blank=True)
    decline_notes = models.CharField(max_length=512, blank=True)
    booked_for = models.DateTimeField(null=True, blank=True)
    seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    #: Set when the specialist answers the referrer. The state everybody
    #: forgets, and the one the referring clinician is actually waiting for.
    responded_at = models.DateTimeField(null=True, blank=True, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    #: When this should have been seen by, from the urgency. Stored rather
    #: than computed so that a change of policy does not silently rewrite
    #: whether last year's referrals breached.
    target_date = models.DateField(null=True, blank=True, db_index=True)

    #: The letter as it was sent: allergies, medications, results and history
    #: frozen at that moment. A letter regenerated later from live data is a
    #: different letter with the same date on it.
    letter = models.JSONField(default=dict, blank=True)
    letter_generated_at = models.DateTimeField(null=True, blank=True)

    #: How it actually left the building. A referral "sent" by email to a
    #: provider with no email address never went anywhere.
    sent_by_method = models.CharField(max_length=24, blank=True)
    sent_notes = models.CharField(max_length=512, blank=True)

    cancelled_reason = models.CharField(max_length=512, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_on", "-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_on"]),
            models.Index(fields=["status", "target_date"]),
            models.Index(fields=["specialty", "status"]),
            models.Index(fields=["direction", "status"]),
        ]
        constraints = [
            #: A decline names a reason. Enforced here as well as in the
            #: service because a decline with no reason is the one outcome
            #: that teaches the referring clinic nothing.
            models.CheckConstraint(
                condition=models.Q(declined_at__isnull=True)
                | ~models.Q(decline_reason=""),
                name="decline_names_a_reason",
            ),
            #: A referral is answered only if it was seen. Answering one
            #: nobody saw means the response is about a different patient, a
            #: different visit, or nothing at all.
            models.CheckConstraint(
                condition=models.Q(responded_at__isnull=True)
                | models.Q(seen_at__isnull=False),
                name="answer_follows_being_seen",
            ),
            #: And it cannot be seen before it was sent. Not pedantry: the
            #: waiting time is `seen_at - sent_at`, so a single reversed pair
            #: puts a negative number into the median and the breach rate, and
            #: a negative wait is not obviously wrong to anybody reading a
            #: report. The seed produced exactly this on its first run.
            models.CheckConstraint(
                condition=models.Q(seen_at__isnull=True)
                | models.Q(sent_at__isnull=True)
                | models.Q(seen_at__gte=models.F("sent_at")),
                name="seen_after_sent",
            ),
            #: And the answer cannot predate the visit it reports on. Added
            #: after the migration that straightened `seen_at` pulled a
            #: sighting forward past an existing response and turned the
            #: median time-to-answer negative — a repair to one ordering
            #: breaking another, which is why both are now stated.
            models.CheckConstraint(
                condition=models.Q(responded_at__isnull=True)
                | models.Q(seen_at__isnull=True)
                | models.Q(responded_at__gte=models.F("seen_at")),
                name="answer_after_seen",
            ),
        ]

    def __str__(self):
        return f"{self.reference} to {self.specialty}"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def days_waiting(self) -> int | None:
        """Days since it was sent, until it was seen."""
        if not self.sent_at:
            return None
        end = self.seen_at or timezone.now()
        return (end.date() - self.sent_at.date()).days

    @property
    def is_breaching(self) -> bool:
        """Past its target and not yet seen.

        Stays true after the patient is finally seen, if they were seen late —
        the same rule as the emergency department's breach flag. A breach that
        disappears once somebody deals with it is a breach nobody counts.
        """
        if not self.target_date:
            return False
        if self.seen_at:
            return self.seen_at.date() > self.target_date
        return timezone.localdate() > self.target_date

    @property
    def days_to_target(self) -> int | None:
        if not self.target_date or self.seen_at:
            return None
        return (self.target_date - timezone.localdate()).days

    @property
    def awaiting_answer(self) -> bool:
        """Seen, but the referrer has still not been told anything."""
        return self.seen_at is not None and self.responded_at is None


class ReferralResponse(BaseModel):
    """What the specialist told the referrer.

    Its own record rather than a field on the referral, because a referral can
    be answered more than once — an interim opinion, then a definitive one
    after investigations — and overwriting the first loses the fact that the
    referrer was told something different in between.
    """

    referral = models.ForeignKey(
        Referral, on_delete=models.CASCADE, related_name="responses",
    )
    responded_at = models.DateTimeField(default=timezone.now, db_index=True)
    responder_id = models.UUIDField(null=True, blank=True)
    responder_name = models.CharField(max_length=255)

    #: The answer to the referrer's question, kept separate from the general
    #: findings. A response that recites the history without answering is the
    #: commonest complaint referring clinicians have.
    answer = models.TextField()
    findings = models.TextField(blank=True)
    diagnosis = models.CharField(max_length=512, blank=True)
    treatment = models.TextField(blank=True)
    #: What the referrer is being asked to do now. The half of a reply that
    #: makes it actionable rather than informational.
    advice_to_referrer = models.TextField(blank=True)

    #: True when the specialist is handing care back rather than keeping the
    #: patient. The referring clinician needs to know which, and a letter that
    #: does not say leaves both ends assuming the other is following up.
    care_handed_back = models.BooleanField(default=True)
    follow_up_here = models.BooleanField(default=False)
    follow_up_on = models.DateField(null=True, blank=True)

    is_interim = models.BooleanField(
        default=False,
        help_text="An opinion before investigations are complete.",
    )
    attachments = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["responded_at"]
        indexes = [models.Index(fields=["referral", "responded_at"])]

    def __str__(self):
        return f"response to {self.referral_id}"


class ReferralEvent(BaseModel):
    """Everything that happened to a referral, in order. Append-only.

    A referral is a conversation between two organisations over weeks. The
    status says where it is; this says how it got there, which is what
    anybody picking it up — or auditing why it took four months — needs.
    """

    referral = models.ForeignKey(
        Referral, on_delete=models.CASCADE, related_name="events",
    )
    happened_at = models.DateTimeField(default=timezone.now, db_index=True)
    event = models.CharField(max_length=24)
    detail = models.CharField(max_length=1000, blank=True)
    actor_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["happened_at", "id"]
        indexes = [models.Index(fields=["referral", "happened_at"])]

    def __str__(self):
        return f"{self.event} {self.happened_at:%Y-%m-%d}"


def validate_decline_reason(reason: str) -> None:
    """Refuse a decline reason outside the countable list.

    In the service layer so the message can name the alternatives, which a
    check constraint cannot.
    """
    if reason not in DECLINE_REASON_KEYS:
        raise ValidationError(
            f"'{reason}' is not a recognised reason for declining. Use one "
            f"of: {', '.join(sorted(DECLINE_REASON_KEYS))}."
        )


def target_for(urgency: str, on_date=None):
    """The date by which a referral of this urgency should be seen."""
    on_date = on_date or timezone.localdate()
    return on_date + timedelta(days=TARGET_DAYS.get(urgency, 90))
