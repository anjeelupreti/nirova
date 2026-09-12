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
    "/sales": "/api/pos/report/",
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
    # The diary, not the availability view: availability is open to anybody who
    # can read a facility, so probing it would report the screen as open to
    # people who in fact see an empty page.
    "/appointments": "/api/clinical/appointments/",
    "/services": "/api/billing/services/",
    "/workspace": "/api/me/workspace/",
    "/notifications": "/api/notifications/summary/",
    "/self-service": "/api/hr/me/summary/",
    # The dashboard is deliberately not probed. It has no endpoint of its own:
    # it is composed of panels that each read a summary the viewer may or may
    # not be entitled to, and each panel declares its permission and is not
    # rendered when the answer is no. Probing any one of them would report the
    # screen as closed to somebody who in fact opens it and sees the panels
    # they are allowed -- which is the whole design. `/me/workspace/`, the one
    # source every signed-in user can read, is already probed via `/workspace`.
    "/dashboard": None,
    # The settings hub, and deliberately not probed for the same reason as the
    # dashboard: it has no endpoint of its own. It is an index of destinations,
    # each of which is gated on the permission that governs *it*, and a section
    # nobody can open is not rendered. Every one of those destinations is
    # probed on its own row below. Open to anybody signed in, because "your
    # profile and your preferences" is not an administrative act.
    "/settings": None,
    # Roles and permissions. `/admin/roles/` rather than `/admin/staff/`: the
    # role catalogue is what the screen loads first and what it is *about*, and
    # a person who can list staff but not roles would see an empty studio.
    "/access": "/api/admin/roles/",
}


def _nav():
    # The navigation moved out of `App.tsx` into `components/shell/nav.ts` when
    # the command palette was built, because three things now consume it -- the
    # rail, the narrow strip and the palette -- and a second copy would be a
    # rail and a palette that disagree about what the product contains.
    #
    # This test failed loudly on the move rather than silently passing, which is
    # what the `len(items) > 20` assertion below is for: a parser that stops
    # matching must not look like a product with no screens.
    app = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "shell" / "nav.ts"
    )
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
        needs = re.search(r'(?<!also)needs:\s*"([a-z_.]+)"', entry)
        # A screen at the meeting point of two jobs names a second permission
        # (`mayOpen` in nav.ts). Parsed here too, or this test would think the
        # counter assistant sees Sales -- the rail does not -- and would then
        # report the report endpoint's correct refusal as a defect.
        also = re.search(r'alsoNeeds:\s*"([a-z_.]+)"', entry)
        scope = re.search(r'scope:\s*"([a-z_]+)"', entry)
        items.append((match.group(1),
                      needs.group(1) if needs else None,
                      scope.group(1) if scope else "own",
                      also.group(1) if also else None))
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
        route for route, *_ in items
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
        ladder = ["own", "own_patients", "unit", "department",
                  "facility", "multi_facility", "organization"]

        def holds(code, want):
            if owner:
                return True
            granted = ((auth.get("authorization") or {})
                       .get("permissions", {}).get(code))
            if granted is None:
                return False
            if granted["scope"] in ladder and want in ladder:
                return ladder.index(granted["scope"]) >= ladder.index(want)
            return True

        for route, needs, want, also in items:
            visible = (not needs or holds(needs, want)) and (
                not also or holds(also, want)
            )
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
