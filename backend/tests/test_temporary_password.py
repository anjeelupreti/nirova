"""An administrator can get somebody signed in — and cannot reach further.

Until `issue_temporary_password` existed, a person created by an invitation or
by onboarding had an unusable password and no route to a usable one: an
organization could be onboarded and its owner could never log in.
"""

import json

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"
DEMO_PASSWORD = "NirovaDemo!2026"
OWNER = f"owner@{DEMO}.test"
TARGET = f"reception@{DEMO}.test"
#: Holds `user.read`-level access at most; not `user.deactivate`.
DOCTOR = f"doctor@{DEMO}.test"


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        pytest.skip(f"no {email}; run manage.py seed_demo")
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
        raise_request_exception=False,
    )


@pytest.fixture
def target(tenant):
    """The receptionist, put back exactly as the demo expects afterwards."""
    from apps.identity.models import User

    user = User.objects.filter(email=TARGET).first()
    if user is None:
        pytest.skip(f"no {TARGET}")
    yield user
    user.refresh_from_db()
    user.set_password(DEMO_PASSWORD)
    user.must_change_password = False
    user.save(update_fields=["password", "password_changed_at", "must_change_password"])


def _issue(client, user):
    return client.post(f"/api/admin/staff/{user.uuid}/password/",
                       data=json.dumps({"reason": "Forgot it"}),
                       content_type="application/json")


def test_the_owner_can_issue_one_and_it_must_be_changed(tenant, target):
    response = _issue(_client(OWNER, tenant), target)
    assert response.status_code == 200, response.content[:300]
    temporary = json.loads(response.content)["temporary_password"]
    assert len(temporary) >= 12

    target.refresh_from_db()
    assert target.must_change_password is True
    assert target.check_password(temporary), "the password handed over does not work"
    assert not target.check_password(DEMO_PASSWORD), "the old password still works"


def test_the_password_is_not_written_to_the_audit_trail(tenant, target):
    from apps.audit.models import AuditEvent

    response = _issue(_client(OWNER, tenant), target)
    temporary = json.loads(response.content)["temporary_password"]
    event = AuditEvent.objects.filter(entity_id=target.uuid).order_by("-occurred_at").first()
    assert event is not None, "issuing a password left no trace"
    assert temporary not in json.dumps(event.metadata, default=str)
    assert temporary not in (event.entity_label or "")


def test_somebody_without_the_permission_is_refused(tenant, target):
    assert _issue(_client(DOCTOR, tenant), target).status_code == 403


def test_nobody_resets_their_own_through_the_admin_path(tenant):
    from apps.identity.models import User

    owner = User.objects.get(email=OWNER)
    response = _issue(_client(OWNER, tenant), owner)
    assert response.status_code == 400


def test_a_person_in_two_organizations_cannot_be_reset_by_one(tenant, target):
    """The account spans both; one organization must not hold the other's keys."""
    from apps.identity.models import Membership, MembershipStatus
    from apps.tenancy.models import Organization

    # A bare control-plane row is enough: the refusal is decided by the
    # membership, before anything touches the other organization's database.
    other, made = Organization.objects.get_or_create(
        slug="second-org-for-reset-test",
        defaults={"legal_name": "Second Org", "display_name": "Second Org"},
    )
    membership = Membership.objects.create(
        user=target, organization=other, status=MembershipStatus.ACTIVE,
    )
    try:
        response = _issue(_client(OWNER, tenant), target)
        assert response.status_code == 400, response.content[:300]
        assert "another organization" in response.content.decode()
    finally:
        membership.delete()
        if made:
            other.delete()


# -- the lock is on the server, not only in the browser -------------------------


def test_a_temporary_password_opens_nothing_but_the_way_out(tenant, target):
    """Until it is replaced, the token it signed in with reaches three doors.

    The console showed only the choose-a-password screen, but the API served
    everything — the patient list, prescribing, dispensing — to anybody holding
    the token. Measured before the fix: the patient list returned 200.
    """
    response = _issue(_client(OWNER, tenant), target)
    temporary = json.loads(response.content)["temporary_password"]
    locked = _client(TARGET, tenant)

    refused = locked.get("/api/clinical/patients/")
    assert refused.status_code == 403, refused.content[:300]
    assert json.loads(refused.content)["error"]["code"] == "password_change_required"

    assert locked.get("/api/auth/me/").status_code == 200, "cannot see who they are"
    assert locked.patch(
        "/api/auth/me/", data=json.dumps({"full_name": "Someone else"}),
        content_type="application/json",
    ).status_code == 403, "a locked session could edit the profile"

    changed = locked.post(
        "/api/auth/me/password/",
        data=json.dumps({"current_password": temporary, "new_password": "Kathmandu-Ward-7-Round"}),
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.content[:300]
    assert _client(TARGET, tenant).get("/api/clinical/patients/").status_code == 200, (
        "the lock did not lift once the password was chosen"
    )
