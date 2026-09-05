"""The notification centre: one event, many people, and separate read state.

Three modules are currently working around the absence of this one. The
patient portal hands invitation codes over at the desk because nothing can
send them. Critical diagnostic alerts stay open until somebody records a
telephone call, because there is no other way to reach the clinician. Approvals
sit in five separate queues because there is nowhere to put "things waiting for
you". Each of those workarounds is a thing to unpick later, which is why this
comes before the analytics work.

The decisions that shape the tables, in the order they matter.

**A notification is a fact about what happened; whether somebody has read it is
a fact about what is true now.** This is the invariant this project keeps
rediscovering, and it decides the whole shape here. A critical potassium result
notifying five clinicians is *one* event and *five* read states -- not five
events. Storing it five times makes "how many people were told" and "how many
read it" indistinguishable from "it happened five times", and the second
question is the one that gets asked after somebody dies.

**Read and dismissed are not the same act.** Read means I have seen this.
Dismissed means I have dealt with it and it should stop asking. A critical
notification can be read by everyone and still be nobody's business until it is
acted on, so the two are separate timestamps and `CRITICAL` refuses to be
dismissed without a note saying what was done.

**Recipients are resolved when the event is raised, and then frozen.** Who
should be told is a question about the roster and the roles *at that moment*. A
nurse who changes ward next week was still the person told on Tuesday, and a
notification list rebuilt from a live query would quietly rewrite that. So the
receipts are rows, written once.

**The text is frozen too.** The same reasoning as the referral letter: a
notification says what was true when it was raised. "Bed 12 is critical"
regenerated from live data three days later is a different sentence with the
same timestamp on it.

**A repeating sweep must not produce a growing pile.** Reminders come from jobs
that run hourly -- licences expiring, stock below reorder, claims unanswered.
Each carries a `dedupe_key`, unique among notifications that are still open, so
running the sweep twelve times a day produces one notification, not twelve.

**Preferences cannot silence a critical notification.** Every other category is
the recipient's business. A critical value is not a preference, and a system
that lets somebody switch it off has built an accident and called it a setting.

**Channel is recorded even though only one exists.** Everything here is in-app
today; there is no SMS gateway yet. Recording the channel now means §93 adds a
delivery row rather than restructuring the table that the whole application
already reads from.
"""

from django.db import models
from django.utils import timezone

# BaseModel: UUID, timestamps, actor stamps, soft delete. The UUID is the
# published identifier -- with a database per tenant an integer PK names a
# different row in every customer's database.
from apps.common.models import BaseModel
from apps.organization.models import Facility


class NotificationCategory(models.TextChoices):
    """What kind of attention this wants, which decides how it behaves.

    The order is the order of urgency, and several rules read it: `CRITICAL`
    cannot be silenced by preference and cannot be dismissed without a note,
    `APPROVAL` and `TASK` stay open until something is done, and `INFORMATION`
    expires on its own.
    """

    CRITICAL = "critical", "Critical"
    WARNING = "warning", "Warning"
    APPROVAL = "approval", "Approval"
    TASK = "task", "Task"
    REMINDER = "reminder", "Reminder"
    INFORMATION = "information", "Information"


#: Categories nobody may switch off. A preference screen that offers to hide
#: critical results has built an accident and labelled it a setting.
UNSILENCEABLE = frozenset({NotificationCategory.CRITICAL})

#: Categories that represent outstanding work rather than news. These stay in
#: the inbox until acted on, and are what "12 waiting for you" counts.
ACTIONABLE = frozenset({
    NotificationCategory.CRITICAL,
    NotificationCategory.APPROVAL,
    NotificationCategory.TASK,
})


class NotificationChannel(models.TextChoices):
    """How a notification reached somebody.

    Only `IN_APP` is delivered today. The rest exist so that §93 adds a row
    here rather than a migration across every table that reads notifications.
    """

    IN_APP = "in_app", "In app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    PUSH = "push", "Push"


class Notification(BaseModel):
    """One thing that happened, stated once.

    Immutable after creation. Nothing in the service layer updates a
    notification's text or category -- if the underlying situation changes, the
    module that owns it raises a new notification and resolves this one, so the
    history reads as a sequence of statements rather than one sentence that
    kept being rewritten.
    """

    category = models.CharField(
        max_length=16, choices=NotificationCategory.choices,
        default=NotificationCategory.INFORMATION, db_index=True,
    )

    #: Which module raised it: "diagnostics", "procurement", "hr". Kept as a
    #: plain string rather than a foreign key to anything, because the whole
    #: point of a central inbox is that it does not depend on the modules that
    #: fill it.
    source = models.CharField(max_length=32, db_index=True)

    #: A stable key for the *kind* of event, e.g. "critical_value" or
    #: "licence_expiring". What preferences are expressed against, and what
    #: reporting groups by. The title is for a human; this is for the system.
    event = models.CharField(max_length=64, db_index=True)

    title = models.CharField(max_length=160)
    body = models.CharField(max_length=1024, blank=True)

    #: Where in the application to go. Stored rather than derived, so that a
    #: notification about a screen that has since moved still points somewhere
    #: honest, and so the inbox needs to know nothing about routing.
    link = models.CharField(max_length=255, blank=True)

    #: What it is about, in the loosest possible terms: a type name and a
    #: UUID. Deliberately not a generic foreign key -- notifications outlive
    #: the rows they refer to (a cancelled order, a merged patient), and a
    #: cascade that deleted the notification would delete the evidence that
    #: anybody was told.
    subject_type = models.CharField(max_length=48, blank=True, db_index=True)
    subject_uuid = models.UUIDField(null=True, blank=True, db_index=True)

    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="notifications",
    )

    #: Who or what caused it. Blank for anything raised by a sweep, which is
    #: most reminders -- and "the system" is a truthful answer that a foreign
    #: key to a user could not give.
    actor_name = models.CharField(max_length=255, blank=True)

    #: Set only by repeating jobs. Unique among notifications that are still
    #: open, so an hourly sweep produces one row rather than twenty-four.
    dedupe_key = models.CharField(max_length=128, blank=True, db_index=True)

    raised_at = models.DateTimeField(default=timezone.now, db_index=True)

    #: When the underlying situation stopped being true -- the stock was
    #: reordered, the claim was answered, the licence was renewed. Separate
    #: from any recipient having read it: a notification everybody read and
    #: nobody acted on is not resolved.
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolved_reason = models.CharField(max_length=255, blank=True)

    #: Information ages out; critical does not. Null means it stands until
    #: resolved.
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-raised_at"]
        indexes = [
            models.Index(fields=["source", "event", "raised_at"]),
            models.Index(fields=["category", "resolved_at"]),
        ]
        constraints = [
            # One open notification per dedupe key. Partial, so that resolved
            # rows keep their key and the history of "this fired every day for
            # a week" survives -- which is the number worth reporting.
            #
            # `deleted_at__isnull=True` is not decoration. Without it a
            # soft-deleted notification still satisfies this condition and
            # blocks the key forever, while `Notification.objects` -- which is
            # what `notify` looks through -- cannot see the row that is doing
            # the blocking. The insert then fails, `notify` swallows the error
            # by design, and every future notification under that key vanishes
            # silently. Any partial constraint on a soft-deleting model has to
            # agree with the manager, or the code and the database are
            # enforcing two different rules.
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=(
                    models.Q(resolved_at__isnull=True)
                    & models.Q(deleted_at__isnull=True)
                    & ~models.Q(dedupe_key="")
                ),
                name="uniq_open_notification_per_dedupe_key",
            ),
            models.CheckConstraint(
                condition=models.Q(resolved_at__isnull=True)
                | models.Q(resolved_at__gte=models.F("raised_at")),
                name="notification_resolved_after_raised",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.category}] {self.title}"

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    @property
    def is_actionable(self) -> bool:
        return self.category in ACTIONABLE


class NotificationReceipt(BaseModel):
    """One person's copy of one notification, and what they have done with it.

    This is the "what is true now" half. It exists per recipient because five
    people being told one thing is one event and five states, and because the
    question "who was told and did they read it" is asked after every serious
    incident.
    """

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="receipts",
    )

    #: The recipient's user UUID rather than a foreign key: users live in the
    #: control-plane database and notifications live in the tenant's, so a
    #: foreign key across them is not a thing the router can serve.
    recipient_id = models.UUIDField(db_index=True)
    recipient_name = models.CharField(max_length=255, blank=True)

    #: Why this person was chosen -- the role or permission that put them on
    #: the list. Frozen at the moment of raising, so that "why was I told
    #: about this?" and "why was I *not*?" both have answers a week later,
    #: after the roster has changed.
    reason = models.CharField(max_length=160, blank=True)

    channel = models.CharField(
        max_length=16, choices=NotificationChannel.choices,
        default=NotificationChannel.IN_APP,
    )

    delivered_at = models.DateTimeField(default=timezone.now)

    #: Seen in a list. Distinct from opened, because a badge going quiet is
    #: not evidence that anybody read anything.
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    #: Dealt with, and should stop asking. A critical notification refuses to
    #: be dismissed without a note saying what was done about it.
    dismissed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dismissed_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-delivered_at"]
        indexes = [
            models.Index(fields=["recipient_id", "read_at"]),
            models.Index(fields=["recipient_id", "dismissed_at"]),
        ]
        constraints = [
            # One receipt per person per notification. Without this, a sweep
            # that re-resolves recipients quietly doubles somebody's unread
            # count and the badge stops being believable.
            models.UniqueConstraint(
                fields=["notification", "recipient_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_receipt_per_recipient",
            ),
            # Dismissing implies reading. Enforced here rather than trusted to
            # the service layer, because the unread count is subtracted from
            # in two places and a dismissed-but-unread row makes it negative.
            models.CheckConstraint(
                condition=models.Q(dismissed_at__isnull=True)
                | models.Q(read_at__isnull=False),
                name="receipt_dismissed_implies_read",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.recipient_name or self.recipient_id} -> {self.notification_id}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    @property
    def is_outstanding(self) -> bool:
        """Still wants something from this person."""
        return self.dismissed_at is None and self.notification.is_open


class NotificationPreference(BaseModel):
    """What one person wants to be told about, within what they are allowed.

    A preference can quieten a category; it cannot silence `CRITICAL`, and
    `set_preference` refuses rather than storing a value it will then ignore.
    Storing an unenforceable preference is worse than refusing it, because the
    screen then tells somebody they have turned something off when they have
    not.
    """

    owner_id = models.UUIDField(db_index=True)
    category = models.CharField(max_length=16, choices=NotificationCategory.choices)
    channel = models.CharField(
        max_length=16, choices=NotificationChannel.choices,
        default=NotificationChannel.IN_APP,
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner_id", "category", "channel"],
                name="uniq_preference_per_owner_category_channel",
            ),
        ]

    def __str__(self) -> str:
        state = "on" if self.enabled else "off"
        return f"{self.owner_id} {self.category}/{self.channel}: {state}"
