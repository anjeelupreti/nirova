"""Forgotten passwords, and the sessions a password change ends.

The refusals are the tests worth having. A reset flow that answered "no such
user" would let anybody test a list of addresses for who works at a hospital;
a link that worked twice, or for a day, would be a standing key in an inbox;
and a password change that left the old sessions signed in would leave the
person it was changed against — usually the reason for the change — exactly
where they were.
"""

import json

import pytest
from django.core import mail
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

EMAIL = "reception@manakamana.test"
NEW_PASSWORD = "Bhaktapur-Pottery-Square-31"


@pytest.fixture
def person(tenant, monkeypatch, settings):
    from apps.identity import password_reset
    from apps.identity.models import User

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    # Send in the test's own thread, so the outbox is filled before we look.
    monkeypatch.setattr(password_reset, "_dispatch", password_reset._send)
    mail.outbox.clear()
    # Requests are counted from the sign-in log, and a real one left there by
    # somebody using the running stack would eat into this test's allowance.
    # Cleared inside the test's own transaction, so the log survives the run.
    from apps.identity.models import LoginAttempt, LoginOutcome

    LoginAttempt.objects.filter(
        email=EMAIL, outcome__in=[LoginOutcome.RESET_REQUESTED, LoginOutcome.PASSWORD_RESET],
    ).delete()
    user = User.objects.filter(email=EMAIL).first()
    if user is None:
        pytest.skip(f"no {EMAIL}")
    return user


def _post(path, body):
    return Client().post(path, data=json.dumps(body), content_type="application/json")


def _link_parts():
    body = mail.outbox[-1].body
    link = next(word for word in body.split() if "/reset-password?" in word)
    query = link.split("?", 1)[1]
    parts = dict(pair.split("=", 1) for pair in query.split("&"))
    return parts["uid"], parts["token"]


def test_a_known_and_an_unknown_address_get_the_same_answer(person):
    known = _post("/api/auth/password/forgot/", {"email": EMAIL})
    unknown = _post("/api/auth/password/forgot/", {"email": "nobody-here@example.org"})

    assert known.status_code == unknown.status_code == 202
    assert json.loads(known.content) == json.loads(unknown.content)
    assert len(mail.outbox) == 1, "the unknown address was mailed, or the known one was not"
    assert mail.outbox[0].to == [EMAIL]


def test_the_link_sets_a_password_once(person):
    _post("/api/auth/password/forgot/", {"email": EMAIL})
    uid, token = _link_parts()

    assert Client().get(f"/api/auth/password/reset/?uid={uid}&token={token}").status_code == 200
    done = _post("/api/auth/password/reset/", {"uid": uid, "token": token, "new_password": NEW_PASSWORD})
    assert done.status_code == 200, done.content

    person.refresh_from_db()
    assert person.check_password(NEW_PASSWORD)
    assert "was changed" in mail.outbox[-1].subject, "the owner was not told"

    again = _post("/api/auth/password/reset/", {"uid": uid, "token": token, "new_password": "Another-Fine-Pass-77"})
    assert again.status_code == 400
    assert json.loads(again.content)["error"]["code"] == "reset_link_invalid"


def test_a_weak_password_is_refused_and_the_link_survives(person):
    _post("/api/auth/password/forgot/", {"email": EMAIL})
    uid, token = _link_parts()

    weak = _post("/api/auth/password/reset/", {"uid": uid, "token": token, "new_password": "password"})
    assert weak.status_code == 400
    assert json.loads(weak.content)["error"]["code"] == "weak_password"
    assert _post("/api/auth/password/reset/", {"uid": uid, "token": token,
                                               "new_password": NEW_PASSWORD}).status_code == 200


def test_a_forged_or_expired_link_is_refused(person, settings):
    _post("/api/auth/password/forgot/", {"email": EMAIL})
    uid, token = _link_parts()

    forged = _post("/api/auth/password/reset/", {"uid": uid, "token": token[:-2] + "zz", "new_password": NEW_PASSWORD})
    assert forged.status_code == 400

    settings.PASSWORD_RESET_TIMEOUT = -1
    expired = _post("/api/auth/password/reset/", {"uid": uid, "token": token, "new_password": NEW_PASSWORD})
    assert expired.status_code == 400


def test_requests_are_limited_without_saying_so(person):
    from apps.identity.password_reset import PER_ADDRESS

    answers = {_post("/api/auth/password/forgot/", {"email": EMAIL}).status_code for _ in range(PER_ADDRESS + 2)}
    assert answers == {202}
    assert len(mail.outbox) == PER_ADDRESS


def test_a_reset_signs_out_every_existing_session(person, tenant):
    refresh = RefreshToken.for_user(person)
    old = Client(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}", HTTP_X_ORGANIZATION=tenant.slug)
    assert old.get("/api/auth/me/").status_code == 200

    # A second's gap, so the token plainly predates the change: `iat` is whole
    # seconds and the same second is deliberately forgiven.
    from datetime import timedelta
    from django.utils import timezone

    person.set_password(NEW_PASSWORD)
    person.password_changed_at = timezone.now() + timedelta(seconds=1)
    person.save(update_fields=["password", "password_changed_at"])

    ended = old.get("/api/auth/me/")
    assert ended.status_code == 401
    assert json.loads(ended.content)["error"]["code"] == "session_ended"

    refused = _post("/api/auth/refresh/", {"refresh": str(refresh)})
    assert refused.status_code == 401, "the old session refreshed its way back in"


def test_changing_your_password_keeps_this_device_and_ends_the_others(person, tenant):
    from apps.identity.models import User

    person.set_password("NirovaDemo!2026")
    person.save(update_fields=["password", "password_changed_at"])
    user = User.objects.get(pk=person.pk)
    other = Client(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
                   HTTP_X_ORGANIZATION=tenant.slug)

    import time
    time.sleep(1.05)  # the other device's token must predate the change by a whole second
    this = Client(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
                  HTTP_X_ORGANIZATION=tenant.slug)
    changed = this.post("/api/auth/me/password/",
                        data=json.dumps({"current_password": "NirovaDemo!2026", "new_password": NEW_PASSWORD}),
                        content_type="application/json")
    assert changed.status_code == 200, changed.content
    body = json.loads(changed.content)

    fresh = Client(HTTP_AUTHORIZATION=f"Bearer {body['access']}", HTTP_X_ORGANIZATION=tenant.slug)
    assert fresh.get("/api/auth/me/").status_code == 200, "this device was signed out too"
    assert other.get("/api/auth/me/").status_code == 401, "the other device is still signed in"
