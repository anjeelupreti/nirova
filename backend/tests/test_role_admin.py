"""Writing a role, and the four ways it must refuse.

**`role.manage` is a privilege-escalation primitive unless it is guarded**, and
that is the whole reason this file exists. Somebody who may edit roles can
write themselves one carrying `payroll.approve` and have it assigned; the only
thing standing between that and a hospital's payroll is
`_validate_role_write`. A guard nobody has watched fail is not a guard, so each
refusal below is exercised as the role that should be refused.

The four:

1. An unknown permission code. A `JSONField` stores a typo happily, it resolves
   to nothing at check time, and the result is a role that looks powerful in
   the editor and does nothing on the ward.
2. A segregation-of-duties conflict. The service has checked this since it was
   written and, until these endpoints existed, nothing ever called it.
3. Authority beyond the caller's own.
4. A system role, or one somebody holds, being deleted.
"""
import pytest

pytestmark = pytest.mark.django_db(databases="__all__")


def _client_for(email: str):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.get(email=email)
    token = RefreshToken.for_user(user).access_token
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture()
def owner(tenant):
    """The organization owner, who bypasses every permission check."""
    return _client_for("owner@manakamana.test")


@pytest.fixture()
def org_slug(tenant):
    """The demo tenant's slug.

    Taken from the `tenant` fixture rather than re-queried: `Organization`
    exists in both `apps.tenancy` (the control-plane row, which is this one)
    and `apps.organization` (the tenant-side row), and picking the wrong one
    is the two-database confusion `_organization` warns about in the view.
    """
    return tenant.slug


def _post(client, slug, body):
    return client.post(
        "/api/admin/roles/",
        data=body,
        content_type="application/json",
        HTTP_X_ORGANIZATION=slug,
    )


def _patch(client, slug, uuid, body):
    return client.patch(
        f"/api/admin/roles/{uuid}/",
        data=body,
        content_type="application/json",
        HTTP_X_ORGANIZATION=slug,
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def test_permission_catalogue_is_served(owner, org_slug):
    """`grouped_permissions()` existed for the role editor and had no endpoint.

    Its docstring has said "for rendering the role editor" since the catalogue
    was written. Until this route, the console grouped permissions by parsing
    the code's prefix -- which gets `patient.clinical.read` into "Patients" by
    luck and would get a new module wrong.
    """
    response = owner.get(
        "/api/admin/permissions/", HTTP_X_ORGANIZATION=org_slug,
    )
    assert response.status_code == 200, response.content

    body = response.json()
    assert body["count"] > 50, "the catalogue is implausibly small"
    assert body["groups"], "no groups returned"

    first = body["groups"][0]["permissions"][0]
    for field in ("code", "label", "description", "is_sensitive", "conflicts_with"):
        assert field in first, f"{field} missing from a catalogue entry"

    # Every code the groups list must be unique across groups: a permission in
    # two groups renders twice in the editor and can be ticked in one place and
    # cleared in the other.
    codes = [
        permission["code"]
        for group in body["groups"]
        for permission in group["permissions"]
    ]
    assert len(codes) == len(set(codes)), "a permission appears in two groups"


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


def test_owner_can_create_a_role(owner, org_slug):
    response = _post(owner, org_slug, {
        "name": "Ward sister",
        "description": "Runs a ward.",
        "permissions": ["patient.read", "encounter.read"],
        "max_scope": "department",
    })
    assert response.status_code == 201, response.content

    body = response.json()
    assert body["code"] == "ward-sister", "the code should derive from the name"
    assert sorted(body["permissions"]) == ["encounter.read", "patient.read"]
    assert body["max_scope"] == "department"
    # Never through this door: a role marked as shipping with the product could
    # not then be deleted, and there is no way back without a migration.
    assert body["is_system"] is False
    assert body["is_superuser_role"] is False


def test_a_duplicate_code_is_refused(owner, org_slug):
    """Two roles with one code is a delegation rule pointing at either."""
    first = _post(owner, org_slug, {
        "name": "Night coordinator",
        "permissions": ["patient.read"],
    })
    assert first.status_code == 201, first.content

    again = _post(owner, org_slug, {
        "name": "Night coordinator",
        "permissions": ["patient.read"],
    })
    assert again.status_code == 400, again.content
    assert again.json()["error"]["code"] == "role_exists"


def test_an_unknown_permission_is_refused(owner, org_slug):
    """Fails closed, and names the typo.

    A `JSONField` stores `patient.raed` without complaint; it resolves to
    nothing at check time and the role silently does less than the editor
    showed. A typo must be a 400, not a mystery.
    """
    response = _post(owner, org_slug, {
        "name": "Typo role",
        "permissions": ["patient.read", "patient.raed"],
    })
    assert response.status_code == 400, response.content

    error = response.json()["error"]
    assert error["code"] == "unknown_permission"
    assert error["detail"]["unknown_permissions"] == ["patient.raed"], (
        "the refusal must name which code was wrong; 'invalid permissions' "
        "sends somebody back to re-check forty checkboxes"
    )


def test_a_segregation_of_duties_conflict_is_refused(owner, org_slug):
    """The design-time half of maker-checker, finally reachable.

    `check_segregation_of_duties` has been correct since it was written and had
    never once been called from an API, because no API ever saved a role.
    """
    from apps.rbac.permissions import PERMISSIONS

    pair = next(
        (
            (definition.code, definition.conflicts_with[0])
            for definition in PERMISSIONS
            if definition.conflicts_with
        ),
        None,
    )
    assert pair is not None, (
        "no permission declares a conflict, so this test asserts nothing -- "
        "the conflict table has been emptied"
    )

    response = _post(owner, org_slug, {
        "name": "Maker and checker",
        "permissions": list(pair),
    })
    assert response.status_code == 403, response.content

    error = response.json()["error"]
    assert error["code"] == "segregation_of_duties"
    assert error["detail"]["conflicts"], "the conflicting pair must be named"


# ---------------------------------------------------------------------------
# The escalation guard
# ---------------------------------------------------------------------------


def test_a_role_cannot_carry_permissions_the_author_does_not_hold(org_slug):
    """**The guard that stops `role.manage` being a way to grant yourself anything.**

    Run as somebody who is not the owner, because the owner bypasses every
    check and would pass this for the wrong reason -- the same mistake
    `test_write_authority.py` documents for the auditor.
    """
    from apps.identity.models import User
    from apps.rbac.models import Role
    from apps.rbac.services import assign_role

    # A user whose only administrative authority is over roles. Deliberately
    # minimal: the point is that `role.manage` alone must not be enough to
    # reach `payroll.approve`.
    editor, _ = User.objects.get_or_create(
        email="roleeditor@manakamana.test",
        defaults={"full_name": "Role Editor", "is_active": True},
    )
    editor.set_password("NirovaDemo!2026")
    editor.save()

    from apps.identity.models import Membership, MembershipStatus
    from apps.tenancy.models import Organization

    organization = Organization.objects.get(slug=org_slug)
    Membership.objects.get_or_create(
        user=editor,
        organization=organization,
        defaults={"status": MembershipStatus.ACTIVE},
    )

    narrow = Role.objects.create(
        code="role-editor-only",
        name="Role editor",
        permissions=["role.read", "role.manage", "patient.read"],
        max_scope="organization",
    )
    assign_role(editor, narrow.code, scope="organization")

    client = _client_for(editor.email)

    # Something they *do* hold: allowed.
    allowed = _post(client, org_slug, {
        "name": "Reader",
        "permissions": ["patient.read"],
    })
    assert allowed.status_code == 201, allowed.content

    # Something they do not: refused, and the refusal names it.
    refused = _post(client, org_slug, {
        "name": "Escalation",
        "permissions": ["patient.read", "payroll.approve"],
    })
    assert refused.status_code == 403, refused.content

    error = refused.json()["error"]
    assert error["code"] == "permission_denied"
    assert "payroll.approve" in error["detail"]["beyond_your_authority"], (
        "the refusal must name the permission that put the role out of reach, "
        "so an administrator knows what to ask their own administrator for"
    )


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_patch_merges_rather_than_blanking(owner, org_slug):
    """A PATCH of one field must not empty the others.

    The obvious implementation is `partial=True` on the serializer, which lets
    `{"name": "x"}` through with `permissions` defaulting to `[]` -- silently
    stripping every permission from the role. The view merges the stored values
    first and validates the whole thing, which also means the segregation check
    always sees the final set rather than the delta.
    """
    created = _post(owner, org_slug, {
        "name": "Merge me",
        "permissions": ["patient.read", "encounter.read"],
        "max_scope": "facility",
    })
    assert created.status_code == 201, created.content
    uuid = created.json()["uuid"]

    renamed = _patch(owner, org_slug, uuid, {"name": "Renamed"})
    assert renamed.status_code == 200, renamed.content

    body = renamed.json()
    assert body["name"] == "Renamed"
    assert sorted(body["permissions"]) == ["encounter.read", "patient.read"], (
        "a rename emptied the role's permissions"
    )
    assert body["max_scope"] == "facility"


def test_the_code_cannot_be_renamed(owner, org_slug):
    """Seeds and `grantable_roles` reference a role by code."""
    created = _post(owner, org_slug, {
        "name": "Stable code",
        "permissions": ["patient.read"],
    })
    uuid = created.json()["uuid"]
    original = created.json()["code"]

    response = _patch(owner, org_slug, uuid, {"code": "something-else"})
    assert response.status_code == 200, response.content
    assert response.json()["code"] == original, "the code was allowed to change"


# ---------------------------------------------------------------------------
# Retiring
# ---------------------------------------------------------------------------


def test_a_system_role_cannot_be_deleted(owner, org_slug):
    from apps.rbac.models import Role

    system = Role.objects.filter(is_system=True).first()
    assert system is not None, "no system roles are seeded; this asserts nothing"

    response = owner.delete(
        f"/api/admin/roles/{system.uuid}/", HTTP_X_ORGANIZATION=org_slug,
    )
    assert response.status_code == 403, response.content
    system.refresh_from_db()
    assert system.is_active is True


def test_a_held_role_cannot_be_deleted(owner, org_slug):
    """Forty people losing access in one edit is not a role change.

    Refused so that each revocation is recorded against the person it affects.
    Without it the audit shows a role edit where it should show forty
    revocations.
    """
    from apps.identity.models import User
    from apps.rbac.services import assign_role

    created = _post(owner, org_slug, {
        "name": "Held role",
        "permissions": ["patient.read"],
    })
    uuid = created.json()["uuid"]
    code = created.json()["code"]

    # Facility scope: the role was created with the default ceiling, and
    # `assign_role` refuses a grant wider than a role permits — which is the
    # ceiling doing its job, not a problem with this test.
    from apps.organization.models import Facility

    assign_role(
        User.objects.get(email="owner@manakamana.test"),
        code,
        scope="facility",
        facility=Facility.objects.first(),
    )

    response = owner.delete(
        f"/api/admin/roles/{uuid}/", HTTP_X_ORGANIZATION=org_slug,
    )
    assert response.status_code == 400, response.content

    error = response.json()["error"]
    assert error["code"] == "role_in_use"
    assert error["detail"]["holders"] >= 1
    assert "1 person holds" in error["message"] or "people hold" in error["message"], (
        "the message must say how many hold it -- 'revoke it from four people "
        "first' is actionable and 'could not delete' is not"
    )


def test_an_unheld_custom_role_retires_rather_than_vanishing(owner, org_slug):
    """Deactivated, not deleted. A role is referenced by past assignments."""
    from apps.rbac.models import Role

    created = _post(owner, org_slug, {
        "name": "Retire me",
        "permissions": ["patient.read"],
    })
    uuid = created.json()["uuid"]

    response = owner.delete(
        f"/api/admin/roles/{uuid}/", HTTP_X_ORGANIZATION=org_slug,
    )
    assert response.status_code == 204, response.content

    role = Role.objects.get(uuid=uuid)
    assert role.is_active is False, "the row should survive, deactivated"

    listed = owner.get("/api/admin/roles/", HTTP_X_ORGANIZATION=org_slug)
    assert all(entry["uuid"] != str(uuid) for entry in listed.json()), (
        "a retired role should not be offered for assignment"
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_role_list_reports_holders_without_a_query_per_role(owner, org_slug):
    """One aggregate, not one count per row.

    The obvious implementation looks fine against fifteen seeded roles and is a
    query per row on a customer who has written forty of their own.
    """
    from django.db import connections
    from django.test.utils import CaptureQueriesContext

    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.models import Organization

    alias = context_for_organization(
        Organization.objects.get(slug=org_slug),
    ).database_alias

    with CaptureQueriesContext(connections[alias]) as captured:
        response = owner.get("/api/admin/roles/", HTTP_X_ORGANIZATION=org_slug)
    assert response.status_code == 200, response.content

    body = response.json()
    assert body, "no roles returned"
    assert all("holders" in entry for entry in body)

    # A generous ceiling: the point is that it does not scale with the number
    # of roles, not that it is any particular number.
    assert len(captured.captured_queries) < 15, (
        f"{len(captured.captured_queries)} tenant queries for {len(body)} roles "
        "— the holder count is being fetched per row"
    )
