"""A person's own account.

None of this existed. Somebody could sign in and could not change their own
name, their phone number, or their password. `update_user` was reachable only
through the staff-administration API — which is somebody *else* editing you
and needs `user.update` — so a doctor who married and changed their surname
had to ask an administrator, and anybody who suspected their password was
known had no way to change it at all.

The tests worth having here are the refusals. This is the one endpoint in the
system whose subject and object are the same person, so the usual permission
machinery is not what protects it: what protects it is requiring the current
password, and refusing to let a login identifier be changed without a verified
round trip that this system cannot yet make.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
PASSWORD = "NirovaDemo!2026"


def _client(email, tenant=None):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None, None
    headers = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if tenant is not None:
        headers["HTTP_X_ORGANIZATION"] = tenant.slug
    return Client(**headers), user


def _body(response):
    return json.loads(response.content.decode())


@pytest.fixture
def me(tenant):
    client, user = _client(f"doctor@{DEMO}.test", tenant)
    if client is None:
        pytest.skip("no doctor account; run manage.py bootstrap")
    return client, user


@pytest.fixture(autouse=True)
def _restore(tenant):
    """Put the demo accounts back exactly as they were found.

    These tests change a real user's name and password on a shared demo
    tenant. One that left `doctor@manakamana.test` with a different password
    would break every later test that signs in as them -- and the failure
    would appear in a completely unrelated file.
    """
    from apps.identity.models import User

    user = User.objects.filter(email=f"doctor@{DEMO}.test").first()
    if user is None:
        yield
        return

    before = {
        "full_name": user.full_name,
        "preferred_name": user.preferred_name,
        "phone": user.phone,
        "preferences": dict(user.preferences or {}),
        "password": user.password,
    }
    yield

    user.refresh_from_db()
    for field, value in before.items():
        setattr(user, field, value)
    user.save(update_fields=[*before, "updated_at"])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def test_somebody_can_read_their_own_account(me):
    client, user = me
    body = _body(client.get("/api/auth/me/"))

    assert body["email"] == user.email
    assert "preferences" in body
    assert body["preference_catalogue"], (
        "the catalogue travels with the values so the screen needs no second "
        "copy of the labels"
    )
    # Never. Not hashed, not partially, not at all.
    assert "password" not in body
    assert "mfa_secret" not in body


def test_somebody_can_change_their_own_name(me):
    """The case that motivated this: a surname changes and nobody should have
    to raise a ticket."""
    client, user = me
    response = client.patch(
        "/api/auth/me/",
        data=json.dumps({"full_name": "Sabina Rana-Magar", "phone": "9801234567"}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content

    user.refresh_from_db()
    assert user.full_name == "Sabina Rana-Magar"
    assert user.phone == "9801234567"


def test_an_email_address_cannot_be_changed_here(me):
    """It is a login, and changing it needs a verified round trip this system
    cannot make.

    Refused loudly rather than ignored silently: a PATCH that accepted the
    field and dropped it would leave somebody believing their login had
    changed.
    """
    client, user = me
    response = client.patch(
        "/api/auth/me/",
        data=json.dumps({"email": "someone.else@example.test"}),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content
    assert "login" in _body(response)["error"]["message"]

    user.refresh_from_db()
    assert user.email == f"doctor@{DEMO}.test"


def test_nobody_can_promote_themselves_through_this_endpoint(me):
    """The allow-list, tested rather than assumed.

    `ProfileSerializer` names the editable fields, so a submitted
    `is_platform_staff` is not so much refused as unheard. That is the right
    behaviour and it needs a test, because the failure mode of an allow-list
    is somebody widening it without noticing what else it lets through.
    """
    client, user = me
    was_platform_staff = user.is_platform_staff

    response = client.patch(
        "/api/auth/me/",
        data=json.dumps({
            "full_name": "Still Me",
            "is_platform_staff": True,
            "is_superuser": True,
            "must_change_password": False,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content

    user.refresh_from_db()
    assert user.is_platform_staff == was_platform_staff, (
        "a user made themselves platform staff by adding a field to a PATCH"
    )
    assert user.is_superuser is False


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------


def test_changing_a_password_requires_the_current_one(me):
    """**The whole security value of this endpoint.**

    Without it, a session left open on a ward computer is a permanent account
    takeover: anybody walking past sets a new password and locks the owner
    out. Requiring the old one means possession of the session is not enough.
    """
    client, user = me
    response = client.post(
        "/api/auth/me/password/",
        data=json.dumps({
            "current_password": "not the right one",
            "new_password": "a-perfectly-fine-new-password-42",
        }),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content
    assert _body(response)["error"]["code"] == "wrong_password"

    user.refresh_from_db()
    assert user.check_password(PASSWORD), "the password changed anyway"


def test_a_password_can_be_changed_with_the_current_one(me):
    from django.utils import timezone

    client, user = me
    new_password = "Chautari-Bakery-Lalitpur-9"

    response = client.post(
        "/api/auth/me/password/",
        data=json.dumps({
            "current_password": PASSWORD,
            "new_password": new_password,
        }),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content

    user.refresh_from_db()
    assert user.check_password(new_password)
    assert user.password_changed_at is not None
    assert user.password_changed_at <= timezone.now()
    assert user.must_change_password is False

    # Every other device is signed out -- what somebody changing their password
    # because they think they are compromised needs -- and this one is handed
    # a fresh pair of tokens so it is not.
    body = _body(response)
    assert "signed out" in body["note"]
    assert body["access"] and body["refresh"]


def test_a_weak_password_is_refused_by_django_s_own_validators(me):
    """The same rules `createsuperuser` enforces, not a second opinion."""
    client, user = me
    response = client.post(
        "/api/auth/me/password/",
        data=json.dumps({
            "current_password": PASSWORD,
            "new_password": "password",
        }),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_the_new_password_may_not_be_the_old_one(me):
    client, _ = me
    response = client.post(
        "/api/auth/me/password/",
        data=json.dumps({
            "current_password": PASSWORD,
            "new_password": PASSWORD,
        }),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def test_preferences_come_back_complete_even_when_nothing_is_set(me):
    """Every declared key, at its default.

    So the interface never has to decide what an absent value means, and a
    preference added next release is present rather than `undefined` in a
    component somewhere.
    """
    from apps.identity.preferences import DEFAULTS

    client, _ = me
    body = _body(client.get("/api/auth/me/"))
    assert set(body["preferences"]) == set(DEFAULTS)


def test_a_preference_can_be_set_and_others_are_left_alone(me):
    """Merged, not replaced.

    A PUT of the whole object would mean an old browser tab, saving after a
    release, silently erasing the two preferences it had not been taught
    about.
    """
    client, user = me

    client.patch(
        "/api/auth/me/preferences/",
        data=json.dumps({"theme": "dark"}),
        content_type="application/json",
    )
    response = client.patch(
        "/api/auth/me/preferences/",
        data=json.dumps({"density": "compact"}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content

    body = _body(response)
    assert body["theme"] == "dark", "the second save erased the first"
    assert body["density"] == "compact"

    user.refresh_from_db()
    assert user.preferences["theme"] == "dark"


@pytest.mark.parametrize(
    "payload",
    [
        {"theme": "neon"},                 # not one of the choices
        {"density": 7},                    # not a choice at all
        {"favourite_colour": "blue"},      # not a preference this system has
    ],
)
def test_a_preference_that_would_mean_nothing_is_refused(me, payload):
    """The reason this is a declared registry and not a JSON dump.

    Without it, this endpoint is a way to write arbitrary keys onto a user
    row, and every reader downstream has to defend itself against values it
    has never heard of.
    """
    from apps.identity.models import User

    client, user = me
    response = client.patch(
        "/api/auth/me/preferences/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 400, f"{payload} was accepted"

    user.refresh_from_db()
    assert not set(payload) & set(user.preferences or {}) or all(
        user.preferences.get(key) != value for key, value in payload.items()
    ), "the refusal did not prevent the write"


def test_the_account_endpoints_need_a_login(tenant):
    from django.test import Client

    anonymous = Client()
    for path in ("/api/auth/me/", "/api/auth/me/preferences/"):
        assert anonymous.get(path).status_code in (401, 403), path
