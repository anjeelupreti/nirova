"""A deleted notification has to leave the inbox with it.

**The inbox lists receipts, not notifications**, and a receipt is a plain
foreign key: soft-deleting a `Notification` hides it from `Notification.objects`
and leaves every receipt pointing at it exactly where it was. Deleting a
notification therefore did nothing at all for the people who had been told.

Found sideways. `seed_notifications_demo` deletes its own rows so that it can be
re-run -- its comment says so, and says four seeds in this project were once
found to work exactly once. Three runs left three copies of every notice in the
demo inbox. The seed was doing the right thing; all three *reads* were ignoring
it.

Three reads, found one at a time: the API's list queryset, `inbox()`, and
`summary()` -- which is the badge. A badge counting something the inbox cannot
show is the worst of the three: it sends somebody looking for a row that is not
there.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
OWNER = f"owner@{DEMO}.test"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None, None
    return (
        Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=tenant.slug,
            raise_request_exception=False,
        ),
        user,
    )


def _body(response):
    return json.loads(response.content.decode())


@pytest.fixture
def owner(tenant):
    client, user = _client(OWNER, tenant)
    if client is None:
        pytest.skip(f"no {OWNER}; run manage.py bootstrap")
    return client, user


@pytest.fixture
def raised(tenant, owner):
    """One notification addressed to the owner, removed afterwards."""
    from apps.notifications.services import notify

    _, user = owner
    notification = notify(
        source="test_suite",
        event="soft_delete_probe",
        category="info",
        title="A notice raised by the test suite",
        body="If this is still in the inbox after deletion, the leak is back.",
        recipients=[{
            "id": user.uuid,
            "name": getattr(user, "full_name", "") or user.email,
            "reason": "Raised by the test suite",
        }],
    )
    try:
        yield notification
    finally:
        from apps.notifications.models import Notification, NotificationReceipt

        NotificationReceipt.all_objects.filter(
            notification__source="test_suite"
        ).delete()
        Notification.all_objects.filter(source="test_suite").delete()


def _titles(client):
    response = client.get("/api/notifications/?page_size=100")
    assert response.status_code == 200, response.content[:300]
    return [row["notification"]["title"] if isinstance(row.get("notification"), dict)
            else row.get("title", "")
            for row in _body(response)["results"]]


def test_a_notification_reaches_the_person_it_names(owner, raised):
    """The precondition. Without it the deletion test proves nothing."""
    client, _ = owner
    assert "A notice raised by the test suite" in " ".join(_titles(client))


def test_deleting_a_notification_takes_it_out_of_the_inbox(owner, raised):
    """The leak itself.

    Soft-deleting the notification must remove it from the list, because the
    list is of receipts and a receipt does not notice its parent being deleted.
    """
    client, _ = owner
    assert "A notice raised by the test suite" in " ".join(_titles(client))

    raised.delete()

    remaining = " ".join(_titles(client))
    assert "A notice raised by the test suite" not in remaining, (
        "a deleted notification is still in the inbox -- the listing is of "
        "receipts, and a receipt is a plain foreign key that outlives its "
        "notification's deletion unless the queryset says otherwise"
    )


def test_deleting_a_notification_takes_it_out_of_the_badge(owner, raised):
    """The count and the list have to agree.

    A badge that counts something the inbox cannot show is worse than a badge
    that is simply wrong: it sends somebody looking for a row that is not there,
    and they conclude the list is broken.
    """
    from apps.notifications.services import summary

    _, user = owner
    before = summary(user.uuid)["unread"]

    raised.delete()

    after = summary(user.uuid)["unread"]
    assert after == before - 1, (
        f"unread went {before} -> {after} after deleting one unread "
        "notification; the badge is counting deleted rows"
    )


def test_the_inbox_and_the_badge_agree(owner, raised):
    """The invariant the demo seed asserts, pinned as a test.

    `inbox()` and `summary()` are separate queries over the same receipts, and
    they were fixed one at a time -- so for a while they disagreed, which is
    exactly the state the seed's own assertion caught.
    """
    from apps.notifications.services import inbox, summary

    _, user = owner
    rows = inbox(user.uuid, outstanding_only=True, limit=50)
    counts = summary(user.uuid)
    assert len(rows) == min(counts["outstanding"], 50), (
        f"the list shows {len(rows)} and the badge counts "
        f"{counts['outstanding']}"
    )


def test_an_inbox_is_only_ever_your_own(tenant, owner, raised):
    """Scoped in the queryset itself, so no later filter can widen it back."""
    other, _ = _client(f"doctor@{DEMO}.test", tenant)
    if other is None:
        pytest.skip("no doctor account")
    assert "A notice raised by the test suite" not in " ".join(_titles(other))
