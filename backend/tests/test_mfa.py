"""Two-step sign-in.

`mfa_enabled` existed from the first migration and nothing read it: an account
marked as having a second factor signed in with a password alone. These tests
hold the three properties the module promises — standard codes, single use,
secrets and recovery codes unreadable at rest — and the flow a person actually
goes through.
"""

import base64
import json

import pytest

from apps.identity import mfa

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO_PASSWORD = "NirovaDemo!2026"
PERSON = "reception@manakamana.test"

#: RFC 6238 appendix B — the SHA-1 secret is the ASCII "12345678901234567890".
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    "unix_time, expected",
    [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
     (1234567890, "005924"), (2000000000, "279037")],
)
def test_codes_match_the_rfc(unix_time, expected):
    """The last six digits of the RFC's eight-digit vectors."""
    assert mfa.code_at(RFC_SECRET, unix_time // 30) == expected


def test_a_code_is_accepted_once():
    secret = mfa.new_secret()
    now = 1_700_000_000
    code = mfa.code_at(secret, now // 30)
    step = mfa.verify(secret, code, at=now)
    assert step == now // 30
    assert mfa.verify(secret, code, last_step=step, at=now) is None, "a code was replayed"


def test_the_secret_is_not_stored_as_itself():
    secret = mfa.new_secret()
    sealed = mfa.seal(secret)
    assert secret not in sealed
    assert mfa.unseal(sealed) == secret
    assert mfa.unseal(sealed[:-4] + "AAAA") is None, "a tampered secret decrypted"


@pytest.fixture
def person(tenant):
    from apps.identity.models import User

    user = User.objects.filter(email=PERSON).first()
    if user is None:
        pytest.skip(f"no {PERSON}")
    yield user
    user.refresh_from_db()
    user.mfa_enabled = False
    user.mfa_enabled_at = None
    user.mfa_secret = ""
    user.mfa_last_step = None
    user.mfa_recovery_codes = []
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save()


def _signed_in(user, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def _enrol(user, tenant):
    client = _signed_in(user, tenant)
    begun = json.loads(_post(client, "/api/auth/me/mfa/", {"action": "begin"}).content)
    assert begun["uri"].startswith("otpauth://totp/")
    secret = begun["secret"]
    confirmed = _post(client, "/api/auth/me/mfa/", {
        "action": "confirm", "code": mfa.code_at(secret, mfa.current_step()),
    })
    assert confirmed.status_code == 200, confirmed.content[:300]
    return client, secret, json.loads(confirmed.content)["recovery_codes"]


def test_signing_in_needs_the_code_once_it_is_on(tenant, person):
    from django.test import Client

    _, secret, recovery = _enrol(person, tenant)
    assert len(recovery) == 10

    person.refresh_from_db()
    assert person.mfa_enabled
    assert secret not in person.mfa_secret, "the secret is stored in the clear"
    assert all(code not in json.dumps(person.mfa_recovery_codes) for code in recovery)

    anonymous = Client(raise_request_exception=False)
    first = json.loads(_post(anonymous, "/api/auth/login/", {"email": PERSON, "password": DEMO_PASSWORD}).content)
    assert first.get("mfa_required") is True
    assert "access" not in first, "a token was issued on the password alone"

    wrong = _post(anonymous, "/api/auth/login/verify/", {"challenge": first["challenge"], "code": "000000"})
    assert wrong.status_code == 401

    # The code used to confirm enrolment cannot be replayed; the next one works.
    replay = _post(anonymous, "/api/auth/login/verify/", {
        "challenge": first["challenge"], "code": mfa.code_at(secret, mfa.current_step()),
    })
    assert replay.status_code == 401, "the enrolment code was accepted again"

    ok = _post(anonymous, "/api/auth/login/verify/", {
        "challenge": first["challenge"], "code": mfa.code_at(secret, mfa.current_step() + 1),
    })
    assert ok.status_code == 200, ok.content[:300]
    assert "access" in json.loads(ok.content)


def test_a_recovery_code_works_once(tenant, person):
    from django.test import Client

    _, _, recovery = _enrol(person, tenant)
    anonymous = Client(raise_request_exception=False)

    def attempt():
        challenge = json.loads(_post(anonymous, "/api/auth/login/", {
            "email": PERSON, "password": DEMO_PASSWORD,
        }).content)["challenge"]
        return _post(anonymous, "/api/auth/login/verify/", {"challenge": challenge, "code": recovery[0]})

    first = attempt()
    assert first.status_code == 200, first.content[:300]
    assert json.loads(first.content)["recovery_codes_left"] == 9
    assert attempt().status_code == 401, "a recovery code worked twice"


def test_a_forged_challenge_is_refused(tenant, person):
    from django.test import Client

    _enrol(person, tenant)
    response = _post(Client(raise_request_exception=False), "/api/auth/login/verify/", {
        "challenge": "not-a-real-challenge", "code": "123456",
    })
    assert response.status_code == 401
    assert json.loads(response.content)["error"]["code"] == "challenge_expired"


def test_turning_it_off_needs_the_password_and_a_code(tenant, person):
    client, secret, _ = _enrol(person, tenant)
    refused = _post(client, "/api/auth/me/mfa/", {
        "action": "disable", "password": "wrong", "code": mfa.code_at(secret, mfa.current_step() + 1),
    })
    assert refused.status_code == 400
    person.refresh_from_db()
    assert person.mfa_enabled, "switched off with the wrong password"

    done = _post(client, "/api/auth/me/mfa/", {
        "action": "disable", "password": DEMO_PASSWORD, "code": mfa.code_at(secret, mfa.current_step() + 1),
    })
    assert done.status_code == 200, done.content[:300]
    person.refresh_from_db()
    assert not person.mfa_enabled and person.mfa_secret == ""


def test_an_administrator_can_reset_a_lost_second_factor(tenant, person):
    from apps.identity.models import User

    _enrol(person, tenant)
    owner = User.objects.get(email="owner@manakamana.test")
    admin = _signed_in(owner, tenant)

    no_reason = _post(admin, f"/api/admin/staff/{person.uuid}/mfa-reset/", {})
    assert no_reason.status_code == 400, "reset without a reason"

    done = _post(admin, f"/api/admin/staff/{person.uuid}/mfa-reset/", {
        "reason": "Lost phone; identity checked in person at the ward.",
    })
    assert done.status_code == 200, done.content[:300]
    person.refresh_from_db()
    assert not person.mfa_enabled and person.mfa_secret == "" and person.mfa_recovery_codes == []


def test_a_doctor_cannot_reset_a_colleagues_second_factor(tenant, person):
    from apps.identity.models import User

    _enrol(person, tenant)
    doctor = User.objects.get(email="doctor@manakamana.test")
    response = _post(_signed_in(doctor, tenant), f"/api/admin/staff/{person.uuid}/mfa-reset/", {
        "reason": "Trying it",
    })
    assert response.status_code == 403, response.content[:300]
    person.refresh_from_db()
    assert person.mfa_enabled


# -- the organization-wide rule -----------------------------------------------------


@pytest.fixture
def owner(tenant):
    from apps.identity.models import User

    user = User.objects.get(email="owner@manakamana.test")
    yield user
    # Leave the demo organization exactly as it was: rule off, owner unenrolled.
    from apps.identity.authentication import forget_policy
    from apps.organization.models import ConfigSetting

    ConfigSetting.objects.filter(namespace="security", key="require_mfa").delete()
    forget_policy(tenant.slug)
    user.refresh_from_db()
    user.mfa_enabled = False
    user.mfa_enabled_at = None
    user.mfa_secret = ""
    user.mfa_last_step = None
    user.mfa_recovery_codes = []
    user.save()


def _require(client, on=True):
    return client.put(
        "/api/org/settings/",
        data=json.dumps({"code": "security.require_mfa", "value": on}),
        content_type="application/json",
    )


def test_the_rule_cannot_be_turned_on_by_someone_without_it(tenant, owner):
    refused = _require(_signed_in(owner, tenant))
    assert refused.status_code == 400, refused.content[:300]
    assert json.loads(refused.content)["error"]["code"] == "enrol_first"


def test_the_rule_holds_the_unenrolled_to_enrolment(tenant, owner, person):
    admin, _, _ = _enrol(owner, tenant)
    assert _require(admin).status_code == 200

    unenrolled = _signed_in(person, tenant)
    refused = unenrolled.get("/api/clinical/patients/")
    assert refused.status_code == 403, refused.content[:300]
    assert json.loads(refused.content)["error"]["code"] == "mfa_enrolment_required"

    session = json.loads(unenrolled.get("/api/auth/session/").content)
    assert session["mfa_enrolment_required"] is True

    # The way through is open: enrolling works, and then so does everything.
    _enrol(person, tenant)
    assert _signed_in(person, tenant).get("/api/clinical/patients/").status_code == 200

    # And the enrolled administrator was never held.
    assert admin.get("/api/clinical/patients/").status_code == 200
