"""Every screen in somebody's sidebar must actually open for them.

A menu of doors that do not open teaches people to distrust the menu -- and
before this the sidebar showed all twenty-eight screens to everybody, so a
doctor was offered eleven that answer 403.

**Both halves are checked**, because only one of them is obvious. Shown-but-shut
is the visible failure. Hidden-but-open is the dangerous one: quietly removing a
screen somebody is entitled to use, which nobody reports as a bug because they
never knew it was there.

The permission *and the scope* come from the screen's own endpoints. Scope is
not optional here: `encounter.read` at department scope and the same permission
at facility scope are different answers, and checking only the name put eleven
dead links in a doctor's sidebar.
"""
import json
import re
import pathlib
import pytest

pytestmark = pytest.mark.django_db(databases="__all__")

# The screen's main endpoint, so "can they open it" is a real question.
PROBE = {
    "/patients": "/api/clinical/patients/",
    "/queue": "/api/clinical/encounters/",
    "/portal": "/api/portal/accounts/",
    "/emergency": "/api/ed/arrivals/",
    "/wards": "/api/ipd/wards/",
    "/nurse-workspace": "/api/ipd/nurse-workspace/summary/",
    "/icu": "/api/icu/stays/",
    "/theatre": "/api/ot/cases/",
    "/diagnostics": "/api/diagnostics/orders/",
    "/blood": "/api/blood/units/",
    "/referrals": "/api/referrals/",
    "/pharmacy": "/api/pharmacy/dispenses/",
    "/counter": "/api/pos/sales/",
    "/procurement": "/api/procurement/suppliers/",
    "/billing": "/api/billing/invoices/",
    "/claims": "/api/insurance/claims/",
    "/finance": "/api/finance/accounts/",
    "/people": "/api/hr/employees/",
    "/time": "/api/hr/attendance/",
    "/payroll": "/api/payroll/runs/",
    "/reports": "/api/reports/",
    "/privacy": "/api/privacy/grants/",
    "/facilities": "/api/org/facilities/",
    "/capacity": "/api/org/facilities/capacity/",
    "/facility-requests": "/api/org/facility-requests/",
    "/staff": "/api/admin/staff/",
    # Added when the "every route needs a probe" guard below was written. All
    # five had been in the navigation for weeks and none had ever been opened
    # by this test, because a route missing from this map was silently
    # skipped rather than reported.
    # `None` means "deliberately not probed", and it is not the same as being
    # absent: the guard below requires every route to appear here, so a
    # decision has to be made and written down. Configuration is an aggregate
    # of eight master-data lists with eight different permissions, and no
    # single endpoint represents it -- probing `/org/departments/` reported
    # the screen as under-protected when what it had actually found was that
    # a doctor may read the list of departments, which is correct.
    "/configuration": None,
    # The kind catalogue rather than the batch list: both need `data.import`,
    # and the catalogue is what the screen loads first, so it is the endpoint
    # whose refusal would actually be seen.
    "/import": "/api/import/kinds/",
    "/services": "/api/billing/services/",
    "/workspace": "/api/me/workspace/",
    "/notifications": "/api/notifications/summary/",
    "/self-service": "/api/hr/me/summary/",
}


def _nav():
    app = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.tsx"
    if not app.exists():
        # **Skip, do not crash.** This test reads the frontend source, which
        # sits beside the backend in the repository and *not* inside the
        # backend container image -- the image ships the backend only, by
        # design. Letting the FileNotFoundError through made the container
        # suite report a failure that says nothing about the code, and a red
        # result nobody can act on is worse than an honest skip.
        pytest.skip(f"frontend source not present at {app}; nothing to parse")
    text = app.read_text(encoding="utf-8")
    items = []
    for match in re.finditer(r'\{\s*to:\s*"(/[^"]*)"[^}]*\}', text):
        entry = match.group(0)
        needs = re.search(r'needs:\s*"([a-z_.]+)"', entry)
        scope = re.search(r'scope:\s*"([a-z_]+)"', entry)
        items.append((match.group(1),
                      needs.group(1) if needs else None,
                      scope.group(1) if scope else "own"))
    return items


def test_every_visible_screen_opens_for_the_role_that_sees_it(tenant):
    from django.test import Client
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.identity.models import User

    items = _nav()
    assert len(items) > 20, (
        f"only {len(items)} navigation items parsed out of App.tsx; the "
        "pattern has stopped matching and this test checks nothing"
    )

    # **Every nav route needs a probe.**
    #
    # The loop below does `probe = PROBE.get(route)` and `continue`s when
    # there is none, so a screen missing from the map is not checked and the
    # test still passes. That is what happened when `/staff` was added: the
    # whole test went green without ever opening the new screen. A silent skip
    # in a test whose job is to catch silent breakage is worse than no test.
    unmapped = sorted(
        route for route, _, _ in items
        if route not in PROBE and not route.startswith("/platform")
    )
    assert not unmapped, (
        "these navigation entries have no endpoint to probe, so nobody is "
        f"checking that they open: {', '.join(unmapped)}"
    )
    problems = []

    for email in ("doctor@manakamana.test", "counter@manakamana.test",
                  "pharmacy@manakamana.test", "manager@manakamana.test",
                  "prakash@manakamana.test"):
        user = User.objects.filter(email=email).first()
        if user is None:
            continue
        client = Client(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
            HTTP_X_ORGANIZATION=tenant.slug,
            raise_request_exception=False,
        )
        auth = json.loads(client.get("/api/auth/session/").content.decode())
        held = set((auth.get("authorization") or {}).get("permissions", {}))
        owner = (auth.get("authorization") or {}).get("is_organization_owner")

        shown, hidden_but_open, shown_but_shut = [], [], []
        for route, needs, want in items:
            granted = ((auth.get("authorization") or {})
                       .get("permissions", {}).get(needs) if needs else None)
            if owner or not needs:
                visible = True
            elif granted is None:
                visible = False
            else:
                ladder = ["own", "own_patients", "unit", "department",
                          "facility", "multi_facility", "organization"]
                visible = (ladder.index(granted["scope"])
                           >= ladder.index(want)) if (
                    granted["scope"] in ladder and want in ladder) else True
            probe = PROBE.get(route)
            if probe is None:
                continue
            code = client.get(probe).status_code
            # Any 2xx, not just 200. `/api/hr/me/summary/` answers **204** to
            # somebody who has no employee record -- a counter assistant hired
            # as a user but not as staff -- and that is a successful answer to
            # a reasonable question, not a refusal. The question this test asks
            # is "does it open or is the caller turned away", and 204 is not
            # being turned away.
            opens = 200 <= code < 300
            if visible:
                shown.append(route)
                if not opens:
                    shown_but_shut.append(f"{route} ({probe} -> {code})")
            elif opens:
                hidden_but_open.append(route)
        assert shown, f"{email} sees no navigation at all"
        problems.extend(
            f"{email}: shown but refused -- {entry}"
            for entry in shown_but_shut
        )
        # `/reports` is hidden from somebody without `report.read` on
        # purpose: the library opens for anybody signed in and shows them
        # a page on which every report is greyed out. A screen with
        # nothing on it is not worth a menu entry.
        problems.extend(
            f"{email}: hidden but open -- {entry}"
            for entry in hidden_but_open
            if entry != "/reports"
        )

    assert not problems, chr(10).join(problems)
