"""Raising notifications, resolving them, and reading an inbox.

The rules this layer keeps, and why each one is here.

**Raising is one call and it never raises an exception into the caller.** A
notification is a side effect of something else -- a result released, a claim
rejected, a licence expiring. If telling somebody fails, the thing that
happened still happened, and a module that rolls back a released laboratory
result because the notification table was busy has made the cure worse than the
disease. So `notify` catches, logs, and returns `None`.

**But it is never called inside the caller's transaction either.** Log entry
149 in the development log states the rule this follows: if the thing being
written must outlive a refusal, it cannot be written inside the transaction the
refusal aborts. A notification about a refusal is exactly that case -- "your
claim was rejected" must survive the exception that rejected it.

**Recipients are resolved now and frozen.** `notify` takes a resolved list of
people, not a query to run later. Who should be told is a question about the
roles and the roster at this moment, and re-running it next week would rewrite
who was told on Tuesday.

**A dedupe key collapses repeats while a notification is open, not forever.**
The partial constraint lets the same key be reused once the previous one is
resolved, so "this fired every morning for a week" stays countable.

**Preferences are applied per recipient at raise time, and cannot silence
`CRITICAL`.** Applying them at read time instead would mean the row exists,
the count includes it, and the person is told about something they asked not
to be told about the moment anybody rebuilds the query.

**Marking read is idempotent; dismissing a critical one needs a note.** A
badge that goes quiet is not evidence anybody read anything, and a critical
alert that can be swiped away without a word is the same defect the diagnostics
module already refuses.
"""

import logging

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: who was told, and who cleared it. After a serious incident the two
# questions asked are "was anybody told?" and "what did they do about it?", and
# a dismissed critical alert is an answer to the second.
from apps.audit.services import record
from apps.common.exceptions import DomainError
# tenant_atomic: notify() swallows its own errors by design, and on PostgreSQL
# a swallowed database error inside somebody else's open transaction poisons
# it -- every subsequent statement fails with "current transaction is aborted".
# Doing the writes inside a nested atomic makes them a savepoint, so a failure
# here rolls back to that savepoint and the caller's transaction survives.
from apps.tenancy.db import tenant_atomic
from apps.notifications.models import (
    ACTIONABLE,
    UNSILENCEABLE,
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationPreference,
    NotificationReceipt,
)

logger = logging.getLogger("nirova.notifications")


class NotificationError(DomainError):
    """Raised by the inbox operations a person performs directly.

    `notify` deliberately does not raise -- see the module docstring. These are
    for the actions somebody takes *on* their inbox, where a refusal is a
    sentence they need to read.
    """

    code = "notification_error"


# ---------------------------------------------------------------------------
# Raising
# ---------------------------------------------------------------------------


def _preference_allows(owner_id, category: str, channel: str) -> bool:
    """Whether this person wants this, within what they are allowed to refuse.

    Critical is checked first and short-circuits: there is no stored value
    that can turn it off, because `set_preference` refuses to store one.
    """
    if category in UNSILENCEABLE:
        return True
    pref = NotificationPreference.objects.filter(
        owner_id=owner_id, category=category, channel=channel,
    ).first()
    # Absent means on. A person who has never opened the preferences screen
    # should receive things, not silently receive nothing.
    return True if pref is None else pref.enabled


def notify(
    *,
    source: str,
    event: str,
    title: str,
    recipients: list,
    category: str = NotificationCategory.INFORMATION,
    body: str = "",
    link: str = "",
    subject_type: str = "",
    subject_uuid=None,
    facility=None,
    actor_name: str = "",
    dedupe_key: str = "",
    expires_at=None,
    channel: str = NotificationChannel.IN_APP,
) -> Notification | None:
    """Raise one notification for a resolved list of people.

    `recipients` is a list of `{"id": uuid, "name": str, "reason": str}` --
    already resolved, because who should be told is a question about right now.

    Returns the notification, or `None` if there was nobody to tell or if
    something went wrong. **Never raises into the caller**: the event being
    notified about has already happened, and a failure to mention it must not
    undo it.
    """
    try:
        if not recipients:
            # Not an error. "Nobody currently holds the role that would care"
            # is a real answer, and worth a log line rather than an exception,
            # because it usually means a role assignment is missing.
            logger.info(
                "notification %s/%s had no recipients", source, event,
            )
            return None

        if dedupe_key:
            existing = Notification.objects.filter(
                dedupe_key=dedupe_key, resolved_at__isnull=True,
            ).first()
            if existing is not None:
                # The situation is already on somebody's list. Adding a second
                # row would make an hourly sweep look like an emergency.
                return existing

        # A savepoint, so that failing to tell somebody cannot abort the
        # transaction that is recording the thing they were to be told about.
        with tenant_atomic():
            return _write(
                source=source, event=event, title=title, body=body, link=link,
                category=category, subject_type=subject_type,
                subject_uuid=subject_uuid, facility=facility,
                actor_name=actor_name, dedupe_key=dedupe_key,
                expires_at=expires_at, recipients=recipients, channel=channel,
            )

    except Exception:
        # The event being notified about has already happened. Swallow, log
        # loudly, and let the caller carry on.
        logger.exception("failed to raise notification %s/%s", source, event)
        return None


def _write(
    *, source, event, title, body, link, category, subject_type, subject_uuid,
    facility, actor_name, dedupe_key, expires_at, recipients, channel,
) -> Notification:
    """The writes, inside the savepoint `notify` opens around them."""
    notification = Notification.objects.create(
        source=source, event=event, title=title, body=body, link=link,
        category=category, subject_type=subject_type,
        subject_uuid=subject_uuid, facility=facility,
        actor_name=actor_name, dedupe_key=dedupe_key,
        expires_at=expires_at,
    )

    receipts = []
    for person in recipients:
        owner_id = person.get("id")
        if owner_id is None:
            continue
        if not _preference_allows(owner_id, category, channel):
            continue
        receipts.append(NotificationReceipt(
            notification=notification,
            recipient_id=owner_id,
            recipient_name=person.get("name", "") or "",
            reason=person.get("reason", "") or "",
            channel=channel,
        ))

    if not receipts:
        # Everybody who would have been told has turned this category off.
        # The notification stays -- it is a record that the event happened
        # and that nobody was reachable, which is worth being able to see.
        logger.info(
            "notification %s/%s silenced for every recipient by preference",
            source, event,
        )
        return notification

    # ignore_conflicts: two sweeps racing on the same event would
    # otherwise trip uniq_receipt_per_recipient. Losing the duplicate is
    # exactly the desired outcome.
    NotificationReceipt.objects.bulk_create(receipts, ignore_conflicts=True)

    if category in UNSILENCEABLE:
        record(
            action=AuditAction.CREATE,
            entity_type="Notification",
            entity_id=str(notification.uuid),
            entity_label=f"Critical notification: {title}",
            metadata={"recipients": len(receipts), "event": event},
        )

    return notification


def resolve(notification: Notification, reason: str = "") -> Notification:
    """Mark the underlying situation as no longer true.

    Separate from anybody having read it: a notification everybody read and
    nobody acted on is not resolved, and conflating the two is how a stock-out
    warning disappears from the screen while the shelf is still empty.
    """
    if notification.resolved_at is not None:
        return notification
    notification.resolved_at = timezone.now()
    notification.resolved_reason = reason
    notification.save(update_fields=["resolved_at", "resolved_reason", "updated_at"])
    return notification


def resolve_by_key(dedupe_key: str, reason: str = "") -> int:
    """Resolve whatever is open under this key. Safe to call when nothing is.

    What a sweep calls when the condition clears -- the stock was reordered,
    the licence renewed -- so the notification goes away because the situation
    went away, not because somebody swiped it.
    """
    count = 0
    for notification in Notification.objects.filter(
        dedupe_key=dedupe_key, resolved_at__isnull=True,
    ):
        resolve(notification, reason)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Reading an inbox
# ---------------------------------------------------------------------------


def inbox(
    owner_id,
    *,
    unread_only: bool = False,
    outstanding_only: bool = False,
    category: str = "",
    limit: int = 50,
):
    """One person's notifications, newest first.

    `outstanding_only` is the one that answers "what is waiting for me": not
    dismissed, and the underlying situation still open. It is deliberately not
    the same as unread -- a thing can be read three times and still be waiting.
    """
    queryset = (
        NotificationReceipt.objects.filter(recipient_id=owner_id)
        .select_related("notification", "notification__facility")
    )
    if unread_only:
        queryset = queryset.filter(read_at__isnull=True)
    if outstanding_only:
        queryset = queryset.filter(
            dismissed_at__isnull=True,
            notification__resolved_at__isnull=True,
        )
    if category:
        queryset = queryset.filter(notification__category=category)

    now = timezone.now()
    queryset = queryset.filter(
        models.Q(notification__expires_at__isnull=True)
        | models.Q(notification__expires_at__gt=now)
    )
    return list(queryset.order_by("-delivered_at")[:limit])


def summary(owner_id) -> dict:
    """The badge, and the breakdown behind it.

    Counted from the receipts every time rather than kept as a number on the
    user. This project does not keep counters: a stored unread count is wrong
    the first time two requests race, and nobody ever notices because a badge
    showing 3 when the answer is 4 looks exactly like a badge.
    """
    now = timezone.now()
    live = (
        NotificationReceipt.objects.filter(recipient_id=owner_id)
        .filter(
            models.Q(notification__expires_at__isnull=True)
            | models.Q(notification__expires_at__gt=now)
        )
        .select_related("notification")
    )

    unread = live.filter(read_at__isnull=True).count()
    outstanding = live.filter(
        dismissed_at__isnull=True, notification__resolved_at__isnull=True,
    )

    by_category = {}
    for row in outstanding.values("notification__category").annotate(
        n=models.Count("id"),
    ):
        by_category[row["notification__category"]] = row["n"]

    return {
        "unread": unread,
        "outstanding": outstanding.count(),
        "critical": by_category.get(NotificationCategory.CRITICAL, 0),
        "needs_action": sum(
            by_category.get(category, 0) for category in ACTIONABLE
        ),
        "by_category": by_category,
    }


def mark_read(receipt: NotificationReceipt) -> NotificationReceipt:
    """Idempotent. The first read is the one that counts."""
    if receipt.read_at is not None:
        return receipt
    receipt.read_at = timezone.now()
    receipt.save(update_fields=["read_at", "updated_at"])
    return receipt


def mark_all_read(owner_id) -> int:
    """Clear the badge. Deliberately does not dismiss anything.

    Clearing a badge is a statement about attention, not about work. Somebody
    catching up on a morning's notifications has not approved anything, and a
    "mark all read" that also emptied the approvals queue would be a disaster
    dressed as a convenience.
    """
    return NotificationReceipt.objects.filter(
        recipient_id=owner_id, read_at__isnull=True,
    ).update(read_at=timezone.now())


def dismiss(receipt: NotificationReceipt, note: str = "") -> NotificationReceipt:
    """Say this has been dealt with, and stop showing it.

    A critical notification refuses without a note. The diagnostics module
    already takes this position for critical values -- an alert that can be
    cleared without a word about what was done is a record that somebody
    silenced it, which is worse than no record at all.
    """
    notification = receipt.notification
    if notification.category in UNSILENCEABLE and not note.strip():
        raise NotificationError(
            "A critical notification cannot be dismissed without saying what "
            "was done about it.",
            code="note_required",
        )
    if receipt.dismissed_at is not None:
        return receipt

    now = timezone.now()
    receipt.dismissed_at = now
    receipt.dismissed_note = note.strip()
    # The constraint requires read before dismissed, and dismissing something
    # is a stronger claim than reading it -- so set both rather than refusing
    # a perfectly sensible action on a row nobody happened to open first.
    if receipt.read_at is None:
        receipt.read_at = now
    receipt.save(update_fields=[
        "dismissed_at", "dismissed_note", "read_at", "updated_at",
    ])

    if notification.category in UNSILENCEABLE:
        record(
            action=AuditAction.UPDATE,
            entity_type="NotificationReceipt",
            entity_id=str(receipt.uuid),
            entity_label=f"Critical notification cleared: {notification.title}",
            reason=note.strip(),
        )
    return receipt


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def preferences_for(owner_id) -> list:
    """Every category, with its current setting and whether it can be changed.

    Built from the full category list rather than from stored rows, because a
    screen that only shows what somebody has already changed cannot be used to
    change anything else.
    """
    stored = {
        (p.category, p.channel): p
        for p in NotificationPreference.objects.filter(owner_id=owner_id)
    }
    out = []
    for category, label in NotificationCategory.choices:
        pref = stored.get((category, NotificationChannel.IN_APP))
        out.append({
            "category": category,
            "label": label,
            "channel": NotificationChannel.IN_APP,
            "enabled": True if pref is None else pref.enabled,
            "can_change": category not in UNSILENCEABLE,
        })
    return out


def set_preference(
    owner_id, category: str, enabled: bool,
    channel: str = NotificationChannel.IN_APP,
) -> NotificationPreference:
    """Refuses to store a preference it would then ignore.

    Silently accepting "turn off critical alerts" and then delivering them
    anyway is worse than refusing: the screen would tell somebody they are not
    being notified about something they are being notified about, and the next
    person to read the code would have to work out which half was the lie.
    """
    if category not in NotificationCategory.values:
        raise NotificationError(
            f"'{category}' is not a notification category.",
            code="unknown_category",
        )
    if category in UNSILENCEABLE and not enabled:
        raise NotificationError(
            "Critical notifications cannot be switched off. They are how "
            "somebody finds out that a result needs acting on today.",
            code="not_silenceable",
        )
    pref, _ = NotificationPreference.objects.update_or_create(
        owner_id=owner_id, category=category, channel=channel,
        defaults={"enabled": enabled},
    )
    return pref


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


def expire_stale(older_than_days: int = 90) -> int:
    """Resolve information and reminders nobody acted on, so the inbox stays real.

    Actionable categories are left alone on purpose. An approval nobody has
    dealt with in ninety days is not stale -- it is the most interesting thing
    in the system, and ageing it out would hide exactly the failure worth
    seeing.
    """
    cutoff = timezone.now() - timezone.timedelta(days=older_than_days)
    stale = Notification.objects.filter(
        resolved_at__isnull=True,
        raised_at__lt=cutoff,
    ).exclude(category__in=list(ACTIONABLE))

    count = 0
    for notification in stale:
        resolve(notification, reason=f"Aged out after {older_than_days} days")
        count += 1
    return count
