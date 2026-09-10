"""A read permission is not a licence to write.

**What this suite is for.** DRF's `@action(methods=["post"])` inherits the
viewset's `permission_classes`. A viewset that declares
`HasPermission.of("encounter.read")` and adds a POST action therefore guards
that POST with a *read* permission, and the omission looks like nothing at all
-- the line that should be there simply is not. `manage.py audit_writes` counts
them: at the time this file was written it found **245 write routes whose
entire authority was a `.read` permission**.

**The subject is the auditor, and that is the whole design of this file.** The
`auditor` role describes itself as "read-only oversight across the
organization". It holds `encounter.read`, `patient.clinical.read`,
`invoice.read`, `stock.read`, `purchase.read`, `salary.read`, `sale.read` and
`finance.read` -- fourteen reads and no write. So for every route below, the
auditor is an actor for whom the missing write check is the *only* obstacle. A
test written as a receptionist would pass on some of these for the wrong
reason: refused for lack of the read permission, never reaching the write
check at all. That mistake has already been made in this codebase once, in the
stock-count self-approval test, and it is the reason this file names one actor
and keeps to it.

**Every case here was seen to fail before it was fixed.** Each parametrised
route returned a 2xx or a 400 to the auditor first -- a 400 counts as a
failure, because reaching validation means the guard let the request through
-- and returns 403 now.
"""

import json

import pytest

# `transaction=False` deliberately: these run against the shared development
# tenant (see `conftest.django_db_setup`), and `transaction=True` truncates it.
pytestmark = pytest.mark.django_db(databases="__all__", transaction=False)

DEMO = "manakamana"

#: Read-only oversight across the organization, and the only demo account for
#: which that claim is testable. Seeded by `manage.py seed_demo`.
AUDITOR_EMAIL = f"auditor@{DEMO}.test"

#: A refusal, whichever way the stack expresses it. 401 would mean the token
#: never arrived and is treated as a broken test rather than a pass.
REFUSED = {403}


def _client(email, tenant):
    """A signed-in Django test client for one demo account.

    Mints a token directly rather than POSTing to `/api/auth/login/`: the
    subject here is authorization, and routing every test through the login
    view would make a login regression look like twenty authorization
    failures.
    """
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        return None
    return Client(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANIZATION=tenant.slug,
    )


@pytest.fixture
def auditor(tenant):
    """The read-only account, skipping honestly if the seed predates it."""
    client = _client(AUDITOR_EMAIL, tenant)
    if client is None:
        pytest.skip(f"no {AUDITOR_EMAIL}; run `manage.py seed_demo`")
    return client


def _post(client, path, body=None):
    return client.post(
        path, data=json.dumps(body or {}), content_type="application/json"
    )


# ---------------------------------------------------------------------------
# The routes, and why each one is here
# ---------------------------------------------------------------------------
#
# Deliberately not every one of the 245. This is a *sample chosen to cover the
# distinct guards*, one per read permission the auditor holds, because 245
# near-identical assertions would be a wall nobody reads and would still only
# prove the same six things. `audit_writes` is what covers the rest, and it is
# asserted at zero findings by `test_no_write_route_is_guarded_only_by_a_read`
# below -- the two halves together are the coverage.
#
# The identifier in each path is a placeholder. That is on purpose and is
# *stronger* than using a real one: a 404 would mean the guard let the request
# through far enough to look the row up, so only a 403 passes. A guard that
# runs before the lookup is the guard being in the right place.
WRITES = [
    pytest.param(
        "/api/clinical/queue/call-next/", {"facility_uuid": "x"},
        id="call the next patient (encounter.read)",
    ),
    pytest.param(
        "/api/clinical/queue/00000000-0000-0000-0000-000000000000/complete/",
        None, id="complete a consultation (encounter.read)",
    ),
    pytest.param(
        "/api/icu/stays/00000000-0000-0000-0000-000000000000/discharge/",
        {}, id="discharge from intensive care (patient.clinical.read)",
    ),
    pytest.param(
        "/api/blood/units/00000000-0000-0000-0000-000000000000/discard/",
        {"reason": "audit probe"},
        id="discard a blood unit (patient.clinical.read)",
    ),
    pytest.param(
        "/api/ot/cases/00000000-0000-0000-0000-000000000000/cancel/",
        {"reason": "audit probe"},
        id="cancel a surgical case (patient.clinical.read)",
    ),
    pytest.param(
        "/api/diagnostics/orders/00000000-0000-0000-0000-000000000000/verify/",
        {}, id="verify a laboratory result (encounter.read)",
    ),
    pytest.param(
        "/api/procurement/orders/00000000-0000-0000-0000-000000000000/approve/",
        {}, id="approve a purchase order (purchase.read)",
    ),
    pytest.param(
        "/api/payroll/runs/00000000-0000-0000-0000-000000000000/submit/",
        {}, id="submit a payroll run (salary.read)",
    ),
    pytest.param(
        "/api/pos/sales/00000000-0000-0000-0000-000000000000/void/",
        {"reason": "audit probe"}, id="void a sale (sale.read)",
    ),
    pytest.param(
        "/api/referrals/create/", {"patient_uuid": "x"},
        id="raise a referral (encounter.read)",
    ),
]


@pytest.mark.parametrize("path,body", WRITES)
def test_read_only_oversight_cannot_change_anything(auditor, path, body):
    """The auditor is refused every write, before the row is even looked up.

    Not "the auditor gets an error" -- a 400 would be an error and would mean
    the request reached serializer validation, which is past the guard. Only
    403 passes.
    """
    # **A mistyped path would pass this test for the worst reason.** The
    # first draft probed `/api/lab/orders/.../verify/`; the route is under
    # `/api/diagnostics/`, so it 404ed -- and a 404 is not a 403, so the
    # failure was loud. Had the assertion been "not 2xx" it would have been
    # green forever against a URL that does not exist. Resolving the path
    # first makes a typo a broken test rather than a false guarantee.
    from django.urls import Resolver404, resolve

    try:
        resolve(path)
    except Resolver404:  # pragma: no cover -- a typo in WRITES
        pytest.fail(
            f"{path} matches no route. This suite proves refusals, and a "
            "path that does not exist refuses everybody for the wrong reason."
        )

    response = _post(auditor, path, body)
    assert response.status_code in REFUSED, (
        f"{path} answered {response.status_code} to an account whose role is "
        "read-only oversight. A read permission is not a licence to write."
    )


def test_the_auditor_can_still_read(auditor):
    """The other half, and the reason it must be in the same file.

    A fix that refused the auditor everything would pass every assertion
    above. Oversight that cannot see the books is not oversight, so the same
    suite that proves the writes are shut proves the reads are open.
    """
    for path in (
        "/api/finance/journals/",
        "/api/clinical/queue/statistics/?facility=",
        "/api/procurement/orders/",
        "/api/payroll/runs/",
    ):
        response = auditor.get(path)
        assert response.status_code != 403, (
            f"{path} refused a read to the auditor. The role exists to read."
        )


def test_no_write_route_is_guarded_only_by_a_read():
    """`audit_writes` finds nothing, which is what makes the sample above safe.

    The parametrised cases cover the distinct guards; this covers the count.
    Without it, a new viewset with a POST action and a read permission would
    reintroduce the whole class silently, and the sample would keep passing
    because it names routes rather than describing the shape of the mistake.

    The command's own `OPEN_BY_DESIGN` table is the escape hatch, and it takes
    a written reason -- which is the point: an exception somebody argued for
    is different from one nobody noticed.
    """
    import io

    from django.core.management import call_command

    output = io.StringIO()
    call_command("audit_writes", stdout=output, no_color=True)
    report = output.getvalue()
    tail = [line for line in report.splitlines() if "write route(s)" in line]
    assert tail, f"audit_writes printed no summary:\n{report}"
    assert tail[0].startswith("0 write route(s)"), (
        "audit_writes found write endpoints whose only guard is a read "
        f"permission:\n{report}"
    )
