"""Getting a notification off the screen and to the person.

`NotificationChannel` has declared EMAIL and SMS since the app was written and
**nothing has ever sent either**. Every notification this system raises exists
only inside the console, which means a critical potassium result escalates to
a bell icon that exists while somebody happens to be looking at a browser tab.
At two in the morning, nobody is.

The rules this module keeps:

**What cannot be silenced cannot be silenced here either.** A critical
category is delivered on every channel the person can be reached on,
regardless of preference, exactly as it is in-app (`UNSILENCEABLE` in
`services.py`). Everything else asks the preference first.

**A delivery that did not happen is recorded as not having happened.** Every
attempt writes a row: sent, failed with the provider's words, or "no address"
/ "no gateway configured". A notification quietly not sent is the failure mode
this whole module exists to remove, and silence is how it comes back.

**Sending is a job, not part of the request.** The event has already happened;
an SMS gateway that is slow or down must not slow a ward round or fail a
transaction. The task retries with a backoff and gives up loudly.

**One send per person per notification.** The unique constraint is the
guarantee, not a `try`: a retried task, two workers, or a sweep raising the
same event twice must not put two texts on somebody's phone at 3 a.m.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.notifications.models import (
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationReceipt,
)

logger = logging.getLogger("nirova.notifications")

#: Categories that reach beyond the screen. Everything else stays in-app
#: unless the person asked for it: a stock warning by SMS at midnight teaches
#: people to ignore the channel that carries the critical result.
REACH_OUT = frozenset({
    NotificationCategory.CRITICAL,
    NotificationCategory.APPROVAL,
})


class DeliveryStatus(models.TextChoices):
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    #: Nothing to send to: no email on the account, no phone, no gateway.
    UNREACHABLE = "unreachable", "No way to reach them"
    #: The person turned this category off on this channel.
    DECLINED = "declined", "Turned off by the recipient"


class NotificationDelivery(BaseModel):
    """One attempt to reach one person on one channel.

    A row per attempt rather than a flag on the receipt, because "we tried and
    the gateway refused" and "we never tried" are different facts and the
    second is the one that gets a hospital into trouble.
    """

    receipt = models.ForeignKey(
        NotificationReceipt, on_delete=models.CASCADE, related_name="deliveries",
    )
    channel = models.CharField(max_length=16, choices=NotificationChannel.choices)
    #: The address used, kept so somebody can answer "where did it go?"
    address = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=DeliveryStatus.choices)
    detail = models.CharField(max_length=512, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_delivery"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "channel"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_delivery_per_channel",
            ),
        ]

    def __str__(self):
        return f"{self.channel} → {self.address}: {self.status}"


# ---------------------------------------------------------------------------
# The gateways
# ---------------------------------------------------------------------------

def sms_settings() -> dict:
    """This tenant's SMS gateway, if it has configured one.

    Nepali gateways (Sparrow, Aakash and the rest) are all the same shape: a
    URL, a token, a sender id, and the message in a query parameter. So the
    configuration is that shape rather than one named provider, and a hospital
    with a contract with any of them can use it.
    """
    from apps.common.sealing import unseal
    from apps.organization.config import config_value

    return {
        "url": str(config_value("notifications", "sms_url", default="") or ""),
        "token": unseal(config_value("notifications", "sms_token", default="")),
        "sender": str(config_value("notifications", "sms_sender", default="") or ""),
    }


def send_sms(to: str, text: str) -> tuple[bool, str]:
    """Returns (sent, detail). Never raises: the caller records the outcome."""
    import urllib.error
    import urllib.parse
    import urllib.request

    gateway = sms_settings()
    if not gateway["url"] or not gateway["token"]:
        return False, "No SMS gateway is configured for this organization."

    payload = urllib.parse.urlencode({
        "token": gateway["token"],
        "from": gateway["sender"],
        "to": to,
        "text": text[:320],
    }).encode()
    try:
        request = urllib.request.Request(gateway["url"], data=payload)
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = response.read().decode(errors="ignore")[:200]
        return True, body
    except urllib.error.HTTPError as error:
        return False, f"{error.code}: {error.read().decode(errors='ignore')[:180]}"
    except Exception as error:  # noqa: BLE001
        return False, str(error)[:180]


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])
        return True, ""
    except Exception as error:  # noqa: BLE001
        return False, str(error)[:180]


# ---------------------------------------------------------------------------
# Deciding and doing
# ---------------------------------------------------------------------------

def _accounts(receipts) -> dict:
    """Email and phone for each recipient, from the control plane.

    One query for the lot: a critical result on a ward can have a dozen
    recipients, and a lookup each would be a dozen round trips to another
    database while somebody waits.
    """
    from apps.identity.models import User

    ids = [row.recipient_id for row in receipts]
    return {
        str(user.uuid): user
        for user in User.objects.filter(uuid__in=ids, is_active=True)
    }


def deliver(notification: Notification, force: bool = False) -> dict:
    """Send one notification on every channel its recipients can be reached on.

    Idempotent: a delivery row already present for a receipt and channel means
    it has been attempted, and it is not attempted again.

    `force` is for an announcement whose sender asked for it to go out by
    email — "the OPD is closed on Saturday" is information, and information
    does not normally leave the screen, but somebody deciding it should is a
    different thing from the system deciding. It overrides the *category*
    rule and not the recipient's: anybody who has switched that category off
    on that channel still does not get it.
    """
    from apps.notifications.services import UNSILENCEABLE, _preference_allows

    counts = {"sent": 0, "failed": 0, "unreachable": 0, "declined": 0, "skipped": 0}
    if not force and notification.category not in REACH_OUT:
        return counts

    receipts = list(notification.receipts.all())
    accounts = _accounts(receipts)
    critical = notification.category in UNSILENCEABLE
    text = f"{notification.title}\n\n{notification.body}".strip()

    for receipt in receipts:
        user = accounts.get(str(receipt.recipient_id))
        for channel, address in (
            (NotificationChannel.EMAIL, getattr(user, "email", "")),
            (NotificationChannel.SMS, getattr(user, "phone", "")),
        ):
            if NotificationDelivery.objects.filter(
                receipt=receipt, channel=channel,
            ).exists():
                counts["skipped"] += 1
                continue

            if not critical and not _preference_allows(
                receipt.recipient_id, notification.category, channel,
            ):
                _record(receipt, channel, address, DeliveryStatus.DECLINED,
                        "The recipient turned this category off on this channel.")
                counts["declined"] += 1
                continue

            if not address:
                _record(receipt, channel, "", DeliveryStatus.UNREACHABLE,
                        f"No {channel} address on the account.")
                counts["unreachable"] += 1
                continue

            if channel == NotificationChannel.EMAIL:
                sent, detail = send_email(address, notification.title, text)
            else:
                sent, detail = send_sms(address, text)

            if sent:
                _record(receipt, channel, address, DeliveryStatus.SENT, detail)
                counts["sent"] += 1
            else:
                _record(
                    receipt, channel, address,
                    DeliveryStatus.UNREACHABLE if "configured" in detail
                    else DeliveryStatus.FAILED,
                    detail,
                )
                counts["unreachable" if "configured" in detail else "failed"] += 1

    if counts["failed"]:
        logger.warning(
            "notification %s: %s deliveries failed", notification.uuid, counts["failed"],
        )
    return counts


def _record(receipt, channel, address, status, detail) -> None:
    NotificationDelivery.objects.update_or_create(
        receipt=receipt, channel=channel,
        defaults={
            "address": address[:255],
            "status": status,
            "detail": (detail or "")[:512],
            "sent_at": timezone.now() if status == DeliveryStatus.SENT else None,
        },
    )
