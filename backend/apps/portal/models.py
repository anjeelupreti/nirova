"""The patient portal: a different audience, which changes what may be shown.

Every other module in this system is read by staff. This one is read by the
patient, and that single change makes several of the usual answers wrong.

**A patient account is not a staff account.** Not a flag on `identity.User`
but its own table with its own credential, because a flag is one bad query
away from a patient holding a clinician's permissions. Separate tables make
the separation structural rather than conditional.

**Registration is a claim, and a claim has to be verified.** Anyone can type
an MRN and a date of birth; letting that create an account is an enumeration
attack with a login at the end of it. An account is created only against an
invitation issued by somebody at the desk who saw the patient.

**A result is released, not exposed.** The laboratory already distinguishes
verified from released. The portal shows only released results — and holds
critical ones for a period even then, because a patient learning of a
critical potassium from a phone notification at eleven at night is a harm the
system caused. The hold is not silence: the portal says a clinician will be
in touch, which is true and is better than a gap the patient does not know
about.

**Proxy access is an authorization with an expiry and a revocation.** A parent
sees a child's record until the child is old enough; a relative sees an
adult's record only while consent stands. A boolean "linked" loses both, and
the complaint that follows — "my ex-husband can still see my results" — is not
recoverable.

**Every view through the portal is logged.** Not for the patient's own record,
where it would be noise, but for proxy access, where it is the only way to
answer who looked at what.
"""

from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# BaseModel gives every row a UUID, timestamps and soft delete. UUIDs are the
# published identifier — with a database per tenant, `id` 42 names a different
# row in every customer's database.
from apps.common.models import BaseModel
from apps.patients.models import Patient


class AccountStatus(models.TextChoices):
    #: Invited but not yet registered. Not an account anybody can log into.
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    #: Too many failed attempts. Time-limited, so it recovers on its own.
    LOCKED = "locked", "Locked"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


#: Failed logins before an account locks, and for how long.
#:
#: Data because it is a policy, and a lockout that never expires is a support
#: call rather than a security control.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

#: How long a portal session lasts. Short, because these are read on shared
#: and stolen phones far more often than a clinician's workstation is.
SESSION_HOURS = 12

#: How long a critical result is held back from the portal.
#:
#: Not to hide it: to give a clinician the chance to ring first. A patient
#: reading "potassium 7.1" on a phone at eleven at night, with nobody to ask,
#: is a harm the system caused. After the window it appears anyway, because an
#: indefinite hold is a result the patient never learns about at all.
CRITICAL_HOLD_HOURS = 24

#: And the same for any abnormal result, more briefly.
ABNORMAL_HOLD_HOURS = 4


class PortalAccount(BaseModel):
    """A patient's own login.

    Its own table, its own password. Not a role on a staff user, because the
    difference between "a patient" and "a member of staff" should not be one
    boolean that a bad query can get wrong.
    """

    patient = models.OneToOneField(
        Patient, on_delete=models.CASCADE, related_name="portal_account",
    )
    #: Phone first: in Nepal it is the identifier a patient actually has and
    #: remembers, and email is the optional one.
    login_identifier = models.CharField(max_length=128, unique=True, db_index=True)
    email = models.EmailField(blank=True)
    password_hash = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=12, choices=AccountStatus.choices,
        default=AccountStatus.INVITED, db_index=True,
    )
    registered_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    #: What the patient has agreed to see and be sent. Separate flags rather
    #: than one "notifications" switch, because somebody who wants appointment
    #: reminders does not necessarily want results pushed to their phone.
    wants_appointment_reminders = models.BooleanField(default=True)
    wants_result_notifications = models.BooleanField(default=False)
    preferred_language = models.CharField(max_length=8, default="ne")

    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-last_login_at"])]

    def __str__(self):
        return f"portal:{self.login_identifier}"

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def can_log_in(self) -> bool:
        return (
            self.status == AccountStatus.ACTIVE
            and not self.is_locked
            and bool(self.password_hash)
        )

    def set_password(self, raw: str) -> None:
        self.password_hash = make_password(raw)

    def check_password(self, raw: str) -> bool:
        return bool(self.password_hash) and check_password(raw, self.password_hash)


class PortalInvitation(BaseModel):
    """A one-time code issued at the desk by somebody who saw the patient.

    This is the whole of the registration security. Without it the portal is
    "type an MRN and a date of birth", which is an enumeration attack with a
    login at the end: both facts are printed on every document the patient
    carries, and a stranger with a phone book can try thousands.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="portal_invitations",
    )
    #: Stored hashed. An invitation list readable by anybody with database
    #: access is a list of working credentials.
    code_hash = models.CharField(max_length=255)
    #: Enough of the code to identify which invitation a patient is holding,
    #: without being enough to use it.
    code_hint = models.CharField(max_length=8, blank=True)

    issued_by_id = models.UUIDField(null=True, blank=True)
    issued_by_name = models.CharField(max_length=255, blank=True)
    issued_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    #: Given to the patient how: printed, read aloud, sent by SMS. Recorded
    #: because "we sent it to the number on file" is the answer to a later
    #: question about who could have received it.
    delivered_by = models.CharField(max_length=24, blank=True)
    delivered_to = models.CharField(max_length=128, blank=True)

    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [models.Index(fields=["patient", "-issued_at"])]

    def __str__(self):
        return f"invitation for {self.patient_id}"

    @property
    def is_usable(self) -> bool:
        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )

    def check_code(self, raw: str) -> bool:
        return check_password(raw, self.code_hash)


class PortalSession(BaseModel):
    """One logged-in device, revocable.

    Sessions are rows rather than stateless tokens so that a patient can see
    where they are signed in and end one. "Log out everywhere" that does not
    actually invalidate anything is the commonest lie in a consumer account
    screen, and on a health record it matters.
    """

    account = models.ForeignKey(
        PortalAccount, on_delete=models.CASCADE, related_name="sessions",
    )
    #: Hashed, like a password. A session table readable by anybody with
    #: database access would otherwise be a list of live logins.
    token_hash = models.CharField(max_length=255, db_index=True)
    issued_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    device_label = models.CharField(max_length=128, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [models.Index(fields=["account", "-issued_at"])]

    def __str__(self):
        return f"session {self.device_label or self.account_id}"

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


class ProxyRelationship(models.TextChoices):
    PARENT = "parent", "Parent or guardian"
    CHILD = "child", "Adult child"
    SPOUSE = "spouse", "Spouse"
    SIBLING = "sibling", "Sibling"
    CARER = "carer", "Carer"
    #: Legal authority: a power of attorney, a court order.
    LEGAL = "legal", "Legal representative"


class ProxyAccess(BaseModel):
    """One account's permission to see another patient's record.

    An interval with a reason and a revocation, not a link. A parent sees a
    child's record until the child is old enough to hold their own; a relative
    sees an adult's record while consent stands and not a day after it is
    withdrawn. A boolean loses the expiry and the withdrawal, and "my ex-husband
    can still see my results" is not a complaint anybody recovers from.
    """

    account = models.ForeignKey(
        PortalAccount, on_delete=models.CASCADE, related_name="proxies",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="proxy_grants",
    )
    relationship = models.CharField(
        max_length=12, choices=ProxyRelationship.choices,
    )

    #: What they may see. Deliberately narrower than the patient's own view by
    #: default: a carer arranging appointments does not need the notes.
    can_see_results = models.BooleanField(default=False)
    can_see_invoices = models.BooleanField(default=True)
    can_book_appointments = models.BooleanField(default=True)

    granted_at = models.DateTimeField(default=timezone.now)
    granted_by_name = models.CharField(max_length=255, blank=True)
    #: How consent was obtained. A grant with no evidence is one nobody can
    #: defend when it is questioned.
    consent_evidence = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_name = models.CharField(max_length=255, blank=True)
    revoked_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-granted_at"]
        indexes = [models.Index(fields=["account", "patient"])]
        constraints = [
            #: One live grant per account and patient. A second row would mean
            #: revoking one and leaving the other, which is exactly the
            #: failure this model exists to prevent.
            models.UniqueConstraint(
                fields=["account", "patient"],
                condition=models.Q(revoked_at__isnull=True),
                name="uniq_live_proxy_per_patient",
            ),
        ]

    def __str__(self):
        return f"{self.account_id} → {self.patient_id}"

    @property
    def is_live(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


class PortalAccessLog(BaseModel):
    """Who looked at what, through the portal. Append-only.

    Written for proxy access rather than for a patient reading their own
    record, where it would be noise nobody could search. For a proxy it is the
    only way to answer the question that eventually gets asked.
    """

    account = models.ForeignKey(
        PortalAccount, on_delete=models.CASCADE, related_name="access_log",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="portal_access_log",
    )
    looked_at = models.DateTimeField(default=timezone.now, db_index=True)
    resource = models.CharField(max_length=32)
    detail = models.CharField(max_length=255, blank=True)
    #: True when the account was not the patient's own.
    via_proxy = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-looked_at"]
        indexes = [
            models.Index(fields=["patient", "-looked_at"]),
            models.Index(fields=["account", "-looked_at"]),
        ]

    def __str__(self):
        return f"{self.resource} at {self.looked_at:%Y-%m-%d %H:%M}"


class MessageDirection(models.TextChoices):
    FROM_PATIENT = "from_patient", "From the patient"
    TO_PATIENT = "to_patient", "To the patient"


class PortalMessage(BaseModel):
    """A message between a patient and the practice.

    Deliberately not a clinical channel. The portal states, and this model
    records, that a message is answered in working hours and is not the way to
    report an emergency — because a patient who describes chest pain here and
    waits is a foreseeable harm, and a system that accepts the message without
    saying so has invited it.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="portal_messages",
    )
    account = models.ForeignKey(
        PortalAccount, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="messages",
    )
    direction = models.CharField(
        max_length=16, choices=MessageDirection.choices, db_index=True,
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    sender_name = models.CharField(max_length=255, blank=True)

    read_at = models.DateTimeField(null=True, blank=True)
    #: Set when a member of staff has dealt with it. Distinct from read,
    #: because a message somebody glanced at is not a message anybody answered.
    answered_at = models.DateTimeField(null=True, blank=True)
    answered_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-sent_at"]
        indexes = [models.Index(fields=["patient", "-sent_at"])]

    def __str__(self):
        return self.subject[:40]

    @property
    def is_answered(self) -> bool:
        return self.answered_at is not None


def account_for_login(identifier: str):
    """Find an account by its login identifier, or nothing.

    Deliberately returns nothing rather than raising, so that the caller
    cannot accidentally leak whether an identifier exists: the authentication
    path must produce the same answer either way.
    """
    return PortalAccount.objects.filter(
        login_identifier__iexact=identifier.strip(),
    ).first()


def validate_proxy_relationship(value: str) -> None:
    if value not in ProxyRelationship.values:
        raise ValidationError(
            f"'{value}' is not a recognised relationship. Use one of: "
            f"{', '.join(ProxyRelationship.values)}."
        )
