"""Sweeps: the jobs that notice a date has passed.

§99's reminder engine is not built. This is its first concrete instance, kept
here rather than in `apps/hr` because the pattern is the point and the next
three sweeps -- contracts, supplier agreements, stock nearing expiry -- are
the same shape against different tables.

The shape, and why each part of it is here.

**Every sweep is safe to run as often as you like.** It carries a `dedupe_key`
per subject, so an hourly cron produces one notification per expiring licence,
not twenty-four. This is the whole reason `dedupe_key` exists.

**A sweep resolves as well as raises.** When the licence is renewed the
notification goes away because the *situation* went away -- not because
somebody swiped it off their screen. A reminder that has to be manually
dismissed teaches people to dismiss reminders.

**Escalating urgency means a new notification, not an edited one.** Ninety
days out is a `REMINDER`; inside thirty days it is a `WARNING`; expired is
`CRITICAL`. Each band has its own key, so crossing a threshold raises a fresh
one rather than quietly rewriting a sentence somebody has already read and
filed. A notification is a statement about a moment.

**The holder is told, and so is whoever verifies credentials.** A nurse whose
registration lapses cannot legally work, and that is not only their problem --
it is the roster's problem, and somebody in the office has to chase it.
"""

from django.utils import timezone

from apps.notifications.models import NotificationCategory
from apps.notifications.services import notify, resolve_by_key
# holders_of: who to escalate to. Answers "who can verify credentials" from
# the permission outwards, which is the direction a sweep needs.
from apps.rbac.services import holders_of

#: Days before expiry at which each band begins. Ordered widest first; the
#: first band a credential falls into is the one that describes it.
BANDS = [
    (0, NotificationCategory.CRITICAL, "has expired"),
    (30, NotificationCategory.WARNING, "expires within a month"),
    (90, NotificationCategory.REMINDER, "expires within three months"),
]


def _band(days_left: int):
    """Which band a credential is in, or `None` if it is not close enough."""
    if days_left < 0:
        return BANDS[0]
    for threshold, category, phrase in reversed(BANDS[1:]):
        if days_left <= threshold:
            return (threshold, category, phrase)
    return None


def sweep_expiring_credentials(within_days: int = 90) -> dict:
    """Notify on professional registrations approaching or past expiry.

    Returns a small report rather than nothing, because a sweep that says
    "raised 0, resolved 0" every night for a month is how you discover it has
    been pointed at the wrong table.
    """
    from apps.hr.models import Credential, EmployeeStatus
    from apps.notifications.models import Notification

    today = timezone.localdate()
    raised = 0
    standing = 0
    resolved = 0
    seen_keys = set()

    credentials = (
        Credential.objects.filter(expires_on__isnull=False)
        .select_related("employee", "employee__facility")
    )

    for credential in credentials:
        employee = credential.employee
        # Somebody who has left does not need chasing about a licence, and
        # neither does the office.
        if employee.status != EmployeeStatus.ACTIVE:
            continue

        days_left = (credential.expires_on - today).days
        band = _band(days_left)
        if band is None or days_left > within_days:
            continue

        _threshold, category, phrase = band
        # The band is part of the key, so crossing from "three months" into
        # "one month" raises a new notification rather than editing one that
        # has already been read.
        key = f"credential_expiry:{credential.uuid}:{category}"
        seen_keys.add(key)

        recipients = []
        if employee.user_id:
            recipients.append({
                "id": employee.user_id,
                "name": employee.full_name,
                "reason": "It is your registration",
            })
        recipients.extend(
            person for person in holders_of(
                "credential.verify", facility=employee.facility,
            )
            if person["id"] != employee.user_id
        )

        when = (
            f"expired on {credential.expires_on:%d %b %Y}"
            if days_left < 0
            else f"expires on {credential.expires_on:%d %b %Y}, "
                 f"in {days_left} day{'' if days_left == 1 else 's'}"
        )
        # Counted before the call, because `notify` returns the *existing*
        # notification on a dedupe hit and there is no way to tell the two
        # apart from its return value. A sweep that reports "raised 1" every
        # hour when nothing has changed is a number that teaches people to
        # stop reading the report.
        already_open = Notification.objects.filter(
            dedupe_key=key, resolved_at__isnull=True,
        ).exists()

        result = notify(
            source="hr",
            event="credential_expiring",
            category=category,
            title=f"{employee.full_name}: {credential.name} {phrase}",
            body=f"{credential.issuing_body or 'Registration'} "
                 f"{credential.reference_number} {when}.".strip(),
            link="/people",
            recipients=recipients,
            subject_type="hr.Credential",
            subject_uuid=credential.uuid,
            facility=employee.facility,
            dedupe_key=key,
        )
        if result is not None:
            if already_open:
                standing += 1
            else:
                raised += 1

    # Anything renewed, corrected or belonging to a leaver now has an open
    # notification about a situation that has stopped being true. Resolve it
    # here rather than waiting for somebody to clear it by hand: a reminder
    # that outlives its cause is how people learn to ignore reminders.
    stale = Notification.objects.filter(
        source="hr", event="credential_expiring", resolved_at__isnull=True,
    ).exclude(dedupe_key__in=seen_keys)
    for notification in stale:
        resolve_by_key(notification.dedupe_key, reason="No longer expiring")
        resolved += 1

    return {
        "raised": raised,
        "standing": standing,
        "resolved": resolved,
        "checked": credentials.count(),
    }
