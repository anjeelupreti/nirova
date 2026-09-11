"""Staff administration: inviting, granting, revoking, deactivating.

The API this covers did not exist until now, and the guard it switches on --
"nobody may grant an authority they do not hold" -- had been written, committed
and **never executed**, because no caller passed `assigner_authorization`.
Every refusal below is therefore proved by making the call and reading the
status code, not by reading the guard.

Each test cleans up after itself. These run against the real demo tenant like
the rest of the suite, so a test that leaves a role assignment behind changes
what the next one measures.
"""

import json
import uuid

import pytest

pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)


DEMO = "manakamana"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(email, tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None, None
    token = RefreshToken.for_user(user).access_token
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    ), user


def _body(response):
    return json.loads(response.content.decode())


def _first_facility():
    from apps.organization.models import Facility

    return Facility.objects.first()


@pytest.fixture
def owner(tenant):
    client, user = _client(f"owner@{DEMO}.test", tenant)
    if client is None:
        pytest.skip("no owner account; run manage.py bootstrap")
    return client


@pytest.fixture
def throwaway(tenant, owner):
    """A member invited for one test and revoked afterwards.

    Invited through the API rather than built with `objects.create`, because a
    fixture that fabricates rows the endpoint would never produce is a fixture
    that tests something the product cannot do.
    """
    from apps.identity.models import Membership, User

    email = f"test-{uuid.uuid4().hex[:8]}@{DEMO}.test"
    response = owner.post(
        "/api/admin/staff/",
        data=json.dumps({"email": email, "full_name": "Test Person"}),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    user = User.objects.get(email=email)
    yield user

    from apps.rbac.models import RoleAssignment

    RoleAssignment.objects.filter(user_id=user.uuid).delete()
    Membership.objects.filter(user=user).delete()
    User.objects.filter(uuid=user.uuid).delete()


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------


def test_the_staff_list_joins_two_databases(tenant, owner):
    """Members come from the control plane, roles from the tenant."""
    body = _body(owner.get("/api/admin/staff/"))
    assert body["count"] >= 5, "the demo tenant should have several members"

    by_email = {row["email"]: row for row in body["results"]}
    doctor = by_email.get(f"doctor@{DEMO}.test")
    assert doctor is not None, "the demo doctor is missing from the staff list"
    # The demo doctor holds the role at two sites — the clinic, and since
    # `seed_demo_population` the hospital — so the check is that every
    # assignment arrived, not that there is exactly one.
    codes = [r["role_code"] for r in doctor["roles"]]
    assert codes and set(codes) == {"doctor"}, (
        "the doctor's role assignment lives in the tenant database and did "
        "not make it into the joined payload"
    )
    # The scope label names *where*, not just how far. See the serializer.
    for role in doctor["roles"]:
        assert "—" in role["scope_label"], role
    if len(doctor["roles"]) > 1:
        places = {role["scope_label"] for role in doctor["roles"]}
        assert len(places) == len(doctor["roles"]), (
            "two assignments at two facilities rendered as the same place"
        )


def test_the_list_costs_two_queries_not_one_per_person(tenant, owner):
    """The N+1 the module docstring promises to avoid.

    Asserted as an upper bound rather than an exact count: pagination, the
    session lookup and the permission resolution all issue queries of their
    own, and pinning the exact number makes this fail on unrelated changes.
    What matters is that it does not scale with the number of people.
    """
    from django.db import connections
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connections["default"]) as control:
        body = _body(owner.get("/api/admin/staff/"))

    people = len(body["results"])
    assert people >= 5
    assert len(control.captured_queries) < people, (
        f"{len(control.captured_queries)} control-plane queries for {people} "
        "people -- that is a query per person, which is the N+1 this was "
        "written to avoid"
    )


def test_a_leaver_is_hidden_by_default_and_findable_on_request(
    tenant, owner, throwaway,
):
    from apps.identity.models import Membership, MembershipStatus

    Membership.objects.filter(user=throwaway).update(
        status=MembershipStatus.REVOKED,
    )
    active = _body(owner.get("/api/admin/staff/"))
    assert throwaway.email not in {r["email"] for r in active["results"]}

    every = _body(owner.get("/api/admin/staff/?status=all"))
    assert throwaway.email in {r["email"] for r in every["results"]}, (
        "a revoked member could not be found at all, so nobody can answer "
        "'did we ever give them access?'"
    )


# ---------------------------------------------------------------------------
# Inviting
# ---------------------------------------------------------------------------


def test_inviting_creates_a_login_that_cannot_yet_sign_in(tenant, owner, throwaway):
    """An invitation is not a password.

    `set_unusable_password` means the account exists and cannot be used until
    its owner sets one. Issuing a password here would mean transmitting it.
    """
    assert not throwaway.has_usable_password(), (
        "the invitation set a usable password, so somebody other than the "
        "account holder knows a credential for it"
    )


def test_inviting_the_same_person_twice_is_refused(tenant, owner, throwaway):
    response = owner.post(
        "/api/admin/staff/",
        data=json.dumps(
            {"email": throwaway.email, "full_name": "Test Person"}
        ),
        content_type="application/json",
    )
    assert response.status_code == 400, response.content


def test_invite_and_grant_in_one_act(tenant, owner):
    from apps.identity.models import Membership, User
    from apps.rbac.models import RoleAssignment

    email = f"test-{uuid.uuid4().hex[:8]}@{DEMO}.test"
    facility = _first_facility()
    response = owner.post(
        "/api/admin/staff/",
        data=json.dumps({
            "email": email,
            "full_name": "Granted On Invite",
            "role_code": "receptionist",
            "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert [r["role_code"] for r in _body(response)["roles"]] == ["receptionist"]

    user = User.objects.get(email=email)
    RoleAssignment.objects.filter(user_id=user.uuid).delete()
    Membership.objects.filter(user=user).delete()
    User.objects.filter(uuid=user.uuid).delete()


# ---------------------------------------------------------------------------
# The escalation guard, over HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def facility_manager(tenant, owner):
    """Somebody who may assign roles but does not hold everything.

    The organization owner is exempt from the escalation rules -- they hold
    every permission, so checking them against themselves proves nothing. A
    facility manager is the smallest role that can grant anything at all, and
    is therefore the only account these tests can be run as.
    """
    from apps.identity.models import Membership, User
    from apps.rbac.models import RoleAssignment

    email = f"fm-{uuid.uuid4().hex[:8]}@{DEMO}.test"
    facility = _first_facility()
    response = owner.post(
        "/api/admin/staff/",
        data=json.dumps({
            "email": email,
            "full_name": "Facility Manager",
            "role_code": "facility_manager",
            "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content

    user = User.objects.get(email=email)
    client, _ = _client(email, tenant)
    yield client, user

    RoleAssignment.objects.filter(user_id=user.uuid).delete()
    Membership.objects.filter(user=user).delete()
    User.objects.filter(uuid=user.uuid).delete()


def test_a_manager_may_grant_the_roles_they_are_allowed_to_delegate(
    tenant, facility_manager, throwaway,
):
    """The rule that makes `role.assign` usable at all.

    Before `grantable_roles` existed, the guard read "you may not grant a
    permission you do not hold", and a facility manager could grant exactly
    one role -- their own. They could not give a nurse a nurse's access,
    because a manager does not personally hold `encounter.create`.
    """
    client, _ = facility_manager
    facility = _first_facility()
    response = client.post(
        f"/api/admin/staff/{throwaway.uuid}/roles/",
        data=json.dumps({
            "role_code": "nurse",
            "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert _body(response)["role_code"] == "nurse"


def test_a_manager_may_not_grant_a_role_beyond_their_authority(
    tenant, facility_manager, throwaway,
):
    client, _ = facility_manager
    response = client.post(
        f"/api/admin/staff/{throwaway.uuid}/roles/",
        data=json.dumps(
            {"role_code": "organization_admin", "scope": "organization"}
        ),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    message = _body(response)["error"]["message"]
    assert "delegate" in message, message


def test_nobody_may_grant_a_role_to_themselves(tenant, facility_manager):
    """Without this, delegation is escalation with an extra step.

    A facility manager may grant `doctor`. If they could grant it to their own
    account they would acquire clinical permissions they are not entitled to,
    and the audit log would name one person doing it to themselves.
    """
    client, user = facility_manager
    facility = _first_facility()
    response = client.post(
        f"/api/admin/staff/{user.uuid}/roles/",
        data=json.dumps({
            "role_code": "doctor",
            "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    assert "yourself" in _body(response)["error"]["message"]


def test_the_reach_rule_refuses_a_scope_wider_than_your_own(tenant):
    """Called at the service layer, because no seeded role can reach it.

    Every role a facility manager may delegate caps at facility scope, so the
    role's own `max_scope` check refuses an organization-scoped grant first
    and this branch never runs over HTTP. That is exactly the situation this
    project keeps finding bugs in -- a guard nothing has executed -- so it is
    executed here directly, against a role built for the purpose.
    """
    from apps.common.exceptions import PermissionDeniedError
    from apps.rbac.models import Role
    from apps.rbac.permissions import Scope
    from apps.rbac.services import GrantedPermission, UserAuthorization, _assert_may_grant

    wide = Role(
        code="test_wide", name="Test Wide", max_scope=Scope.ORGANIZATION,
        permissions=["patient.read"], grantable_roles=[],
    )
    narrow_assigner = UserAuthorization(
        user_id=str(uuid.uuid4()),
        organization_id="x",
        permissions={
            # Holds everything the role carries, so rule 1 passes and rule 2
            # is the only thing left that can refuse.
            "patient.read": GrantedPermission(
                code="patient.read", scope=Scope.FACILITY, sources=["test"],
            ),
        },
    )
    with pytest.raises(PermissionDeniedError) as refused:
        _assert_may_grant(
            narrow_assigner, wide, Scope.ORGANIZATION,
            target_user=type("U", (), {"uuid": uuid.uuid4()})(),
        )
    assert "does not reach that far" in str(refused.value)


# ---------------------------------------------------------------------------
# Revoking and deactivating
# ---------------------------------------------------------------------------


def test_revoking_keeps_the_row_and_stamps_when(tenant, owner, throwaway):
    """Revoked, not deleted -- "who could approve this in March?" stays
    answerable."""
    from apps.rbac.models import AssignmentStatus, RoleAssignment

    facility = _first_facility()
    granted = owner.post(
        f"/api/admin/staff/{throwaway.uuid}/roles/",
        data=json.dumps({
            "role_code": "receptionist", "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    assert granted.status_code == 201, granted.content
    assignment_uuid = _body(granted)["uuid"]

    removed = owner.delete(
        f"/api/admin/staff/{throwaway.uuid}/roles/{assignment_uuid}/"
    )
    assert removed.status_code == 204, removed.content

    row = RoleAssignment.objects.get(uuid=assignment_uuid)
    assert row.status == AssignmentStatus.REVOKED
    assert row.revoked_at is not None, (
        "revoked_at was never set, so the record cannot say when access ended"
    )


def test_deactivating_revokes_every_role_they_held(tenant, owner, throwaway):
    """A membership revoked while its roles stay active is somebody who comes
    back with authority nobody reviewed."""
    from apps.identity.models import Membership, MembershipStatus
    from apps.rbac.models import AssignmentStatus, RoleAssignment

    facility = _first_facility()
    owner.post(
        f"/api/admin/staff/{throwaway.uuid}/roles/",
        data=json.dumps({
            "role_code": "receptionist", "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    assert RoleAssignment.objects.filter(
        user_id=throwaway.uuid, status=AssignmentStatus.ACTIVE,
    ).exists()

    response = owner.post(
        f"/api/admin/staff/{throwaway.uuid}/deactivate/",
        data=json.dumps({"reason": "Left the organization"}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content

    assert Membership.objects.get(
        user=throwaway,
    ).status == MembershipStatus.REVOKED
    assert not RoleAssignment.objects.filter(
        user_id=throwaway.uuid, status=AssignmentStatus.ACTIVE,
    ).exists(), "the leaver kept their roles"


def test_reactivating_does_not_restore_their_old_roles(tenant, owner, throwaway):
    """Deliberately not the inverse. Authority held a year ago is not
    authority anybody has reviewed today."""
    from apps.rbac.models import AssignmentStatus, RoleAssignment

    facility = _first_facility()
    owner.post(
        f"/api/admin/staff/{throwaway.uuid}/roles/",
        data=json.dumps({
            "role_code": "receptionist", "scope": "facility",
            "facility_uuid": str(facility.uuid),
        }),
        content_type="application/json",
    )
    owner.post(f"/api/admin/staff/{throwaway.uuid}/deactivate/")
    back = owner.post(f"/api/admin/staff/{throwaway.uuid}/deactivate/?undo=1")
    assert back.status_code == 200, back.content
    assert not RoleAssignment.objects.filter(
        user_id=throwaway.uuid, status=AssignmentStatus.ACTIVE,
    ).exists(), (
        "reactivation silently restored roles nobody reviewed"
    )


def test_you_cannot_deactivate_yourself(tenant, owner):
    from apps.identity.models import User

    me = User.objects.get(email=f"owner@{DEMO}.test")
    response = owner.post(f"/api/admin/staff/{me.uuid}/deactivate/")
    assert response.status_code == 403, response.content
    assert "your own account" in _body(response)["error"]["message"]


def test_the_organization_owner_cannot_be_deactivated(tenant, owner):
    """Even by somebody who holds `user.deactivate`.

    Not a permission check -- an owner passes one. This is the invariant that
    an organization always has somebody who can administer it.
    """
    from apps.identity.models import Membership

    membership = Membership.objects.filter(
        organization__slug=DEMO, is_organization_owner=True,
    ).exclude(user__email=f"owner@{DEMO}.test").first()
    if membership is None:
        pytest.skip("only one owner in the demo tenant; covered by the self test")

    response = owner.post(
        f"/api/admin/staff/{membership.user.uuid}/deactivate/"
    )
    assert response.status_code == 400, response.content


# ---------------------------------------------------------------------------
# Who may use any of this
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email,path,method,expected",
    [
        # A doctor holds none of the administration permissions.
        (f"doctor@{DEMO}.test", "/api/admin/staff/", "get", 403),
        (f"doctor@{DEMO}.test", "/api/admin/roles/", "get", 403),
        # An HR manager may see colleagues and invite, but not assign roles.
        (f"manager@{DEMO}.test", "/api/admin/staff/", "get", 200),
        (f"manager@{DEMO}.test", "/api/admin/roles/", "get", 403),
    ],
)
def test_administration_is_refused_to_those_without_it(
    tenant, email, path, method, expected,
):
    """`user.read` and `role.read` are separate codes, and it shows here.

    An HR manager who can see who works here cannot see the role catalogue,
    because they cannot assign one. Collapsing the two codes into one would
    have made this row impossible to express.
    """
    client, _ = _client(email, tenant)
    if client is None:
        pytest.skip(f"no {email} account")
    response = getattr(client, method)(path)
    assert response.status_code == expected, (
        f"{email} {method.upper()} {path} -> {response.status_code}, "
        f"expected {expected}"
    )
