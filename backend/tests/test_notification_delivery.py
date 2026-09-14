"""A critical result that only exists on a screen has not been escalated.

`NotificationChannel` declared EMAIL and SMS from the first day and nothing
ever sent either, so every alert this system raised lived inside a browser tab
— which at two in the morning nobody is looking at. What these check is the
behaviour that makes delivery trustworthy rather than decorative: that
critical reaches people whatever their preferences say, that ordinary news
does not, that a second attempt does not text somebody twice, and — the one
that matters most — that a delivery which did not happen is *recorded* as not
having happened.
"""

import pytest
from django.core import mail

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


@pytest.fixture
def people(tenant):
    from apps.identity.models import User

    owner = User.objects.get(email="owner@manakamana.test")
    doctor = User.objects.filter(email="doctor@manakamana.test").first()
    if doctor is None:
        pytest.skip("no demo doctor")
    return owner, doctor


def _raise(category, recipients, **kwargs):
    from apps.notifications.services import notify

    fields = {
        "source": "test", "event": "delivery",
        "title": "Potassium 6.9 mmol/L",
        "body": "Ram Bahadur Shrestha, MRN-000123. Threshold 6.5.",
        "category": category, "recipients": recipients,
        **kwargs,
    }
    return notify(**fields)


def _recipients(*users):
    return [{"id": user.uuid, "name": user.full_name, "reason": "test"} for user in users]


@pytest.fixture(autouse=True)
def outbox(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox.clear()
    return mail.outbox


def test_a_critical_alert_is_emailed_to_everybody_it_is_raised_for(people, outbox):
    from apps.notifications.delivery import DeliveryStatus, NotificationDelivery, deliver
    from apps.notifications.models import NotificationCategory

    owner, doctor = people
    notification = _raise(NotificationCategory.CRITICAL, _recipients(owner, doctor))
    counts = deliver(notification)

    assert counts["sent"] >= 1, counts
    addressed = {row.to[0] for row in outbox}
    assert owner.email in addressed
    assert "Potassium" in outbox[0].subject

    sent = NotificationDelivery.objects.filter(
        receipt__notification=notification, status=DeliveryStatus.SENT,
    )
    assert sent.exists()


def test_a_delivery_that_could_not_happen_is_recorded_as_such(people, outbox):
    """The failure mode this module exists to remove: silence. No phone on the
    account, or no SMS gateway configured, must leave a row saying so."""
    from apps.notifications.delivery import DeliveryStatus, NotificationDelivery, deliver
    from apps.notifications.models import NotificationCategory

    owner, _ = people
    notification = _raise(NotificationCategory.CRITICAL, _recipients(owner))
    deliver(notification)

    sms = NotificationDelivery.objects.filter(
        receipt__notification=notification, channel="sms",
    ).first()
    assert sms is not None, "the SMS attempt left no trace at all"
    assert sms.status == DeliveryStatus.UNREACHABLE
    assert sms.detail, "a failed delivery says nothing about why"


def test_delivering_twice_does_not_tell_anybody_twice(people, outbox):
    from apps.notifications.delivery import deliver
    from apps.notifications.models import NotificationCategory

    owner, _ = people
    notification = _raise(NotificationCategory.CRITICAL, _recipients(owner))
    deliver(notification)
    before = len(outbox)
    second = deliver(notification)

    assert len(outbox) == before, "a retry sent the same alert again"
    assert second["skipped"] >= 1


def test_ordinary_news_stays_on_the_screen(people, outbox):
    """A stock warning by SMS at midnight teaches people to ignore the channel
    that carries the critical result."""
    from apps.notifications.delivery import deliver
    from apps.notifications.models import NotificationCategory

    owner, _ = people
    notification = _raise(NotificationCategory.INFORMATION, _recipients(owner))
    counts = deliver(notification)

    assert counts["sent"] == 0
    assert outbox == []


def test_a_preference_cannot_silence_a_critical_alert(people, outbox):
    from apps.notifications.delivery import deliver
    from apps.notifications.models import NotificationCategory, NotificationPreference

    owner, _ = people
    # Written directly: `set_preference` refuses to store this, which is the
    # in-app half of the same rule.
    NotificationPreference.objects.update_or_create(
        owner_id=owner.uuid, category=NotificationCategory.CRITICAL,
        channel="email", defaults={"enabled": False},
    )
    notification = _raise(NotificationCategory.CRITICAL, _recipients(owner))
    deliver(notification)

    assert any(owner.email in row.to for row in outbox), (
        "a preference switched off a critical alert"
    )


def test_an_approval_respects_the_preference(people, outbox):
    from apps.notifications.delivery import DeliveryStatus, NotificationDelivery, deliver
    from apps.notifications.models import NotificationCategory, NotificationPreference

    owner, _ = people
    NotificationPreference.objects.update_or_create(
        owner_id=owner.uuid, category=NotificationCategory.APPROVAL,
        channel="email", defaults={"enabled": False},
    )
    notification = _raise(
        NotificationCategory.APPROVAL, _recipients(owner),
        title="Purchase order PO-0042 needs approval",
    )
    if notification is None:
        pytest.skip("the approval was silenced in-app as well")
    deliver(notification)

    assert not any(owner.email in row.to for row in outbox)
    declined = NotificationDelivery.objects.filter(
        receipt__notification=notification, channel="email",
        status=DeliveryStatus.DECLINED,
    )
    assert declined.exists(), "the refusal to send left no trace"


def test_the_sms_gateway_is_the_tenants_own(tenant, people, outbox, monkeypatch):
    """Configured, it is used; the token is stored sealed and never in the
    open, like every other key this product holds for a customer."""
    from apps.common.sealing import seal
    from apps.notifications import delivery
    from apps.notifications.models import NotificationCategory
    from apps.organization.config import set_config_value

    owner, _ = people
    owner.phone = "+977-9800000123"
    owner.save(update_fields=["phone"])

    set_config_value("notifications", "sms_url", "https://sms.example.np/send")
    set_config_value("notifications", "sms_token", seal("test-token-12345"))
    set_config_value("notifications", "sms_sender", "NIROVA")

    gateway = delivery.sms_settings()
    assert gateway["token"] == "test-token-12345", "the token did not unseal"
    assert gateway["url"] == "https://sms.example.np/send"

    monkeypatch.setattr(delivery, "send_sms", lambda to, text: (True, f"to {to}"))
    notification = _raise(NotificationCategory.CRITICAL, _recipients(owner))
    counts = delivery.deliver(notification)
    assert counts["sent"] >= 2, "email and SMS were both expected"
