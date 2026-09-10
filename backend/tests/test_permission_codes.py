"""Every permission code the application asks for has to exist.

**Why this file exists.** `UserAuthorization.require(code, scope)` takes a
string and asks whether the caller holds it. It does not check that the code
is one the catalogue defines, and `HasPermission.of("...")` does not either. A
code with a typo in it therefore does not raise, does not warn, and does not
appear in any report: it is simply a permission nobody holds, so the guard
refuses **everybody, forever**, and the endpoint behind it is dead.

That is the worst possible failure mode for a permission check, because it
looks exactly like security working. It was found by probing the running stack
as an auditor -- a role that should have been refused -- and noticing that the
refusals were too uniform to be real. Three codes, eight call sites:

* `pharmacy.dispense` (six sites) had every write in the blood bank behind it.
  Donor registration, collection, grouping, screening, separation, release,
  issue, discard: the whole module, unusable by anybody.
* `facility.manage` guarded provider schedules, so no one could define a
  consultant's clinic.
* `report.view` guarded the ICU unit summary, so no one could open it.

Each of the module's own tests passed throughout, because they run as the
organization owner, who is exempt from every permission check by design.

**A guard that refuses everybody is not a guard, it is an outage.** This test
is the cheap, permanent version of the probe that found them.
"""

import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
APPS = BACKEND / "apps"
CATALOGUE_FILE = APPS / "rbac" / "permissions.py"

#: Every syntax that names a permission code. Kept as a list of patterns
#: rather than one clever regex, because the point is to be obviously
#: complete: a reader can check each line against the way the codebase writes
#: its checks.
REFERENCES = [
    re.compile(r'HasPermission\.of\(\s*"([a-z][a-z._]*)"'),
    re.compile(r'write\s*=\s*"([a-z][a-z._]*)"'),
    re.compile(r'\.require\(\s*"([a-z][a-z._]*)"'),
    re.compile(r'\.has\(\s*"([a-z][a-z._]*)"'),
    re.compile(r'\.has_any\(([^)]*)\)'),
    re.compile(r'\.has_all\(([^)]*)\)'),
    re.compile(r'accessible_facility_ids\(\s*"([a-z][a-z._]*)"'),
    re.compile(r'accessible_department_ids\(\s*"([a-z][a-z._]*)"'),
]

#: A code must look like `resource.action`. A bare word matched by the
#: patterns above is something else -- a field name, a status -- and is not a
#: permission reference.
LOOKS_LIKE_A_CODE = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")


def _catalogue() -> set:
    """The declared codes, read from the source rather than imported.

    Reading the file keeps this test runnable without a database or a tenant,
    which matters: an invariant that only holds when the whole stack is up is
    one people skip.
    """
    return set(
        re.findall(r'_p\(\s*"([a-z][a-z._]*)"', CATALOGUE_FILE.read_text("utf-8"))
    )


def _references() -> dict:
    """Every code named in `apps/`, mapped to where it is named."""
    found: dict = {}
    for path in sorted(APPS.rglob("*.py")):
        if path == CATALOGUE_FILE:
            continue
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            for pattern in REFERENCES:
                for match in pattern.findall(line):
                    # `has_any`/`has_all` take several codes in one call, so
                    # the captured group is an argument list rather than one
                    # string.
                    for code in re.findall(r'"([a-z][a-z._]*)"', match) or [match]:
                        if LOOKS_LIKE_A_CODE.match(code):
                            found.setdefault(code, []).append(
                                f"{path.relative_to(BACKEND)}:{number}"
                            )
    return found


def test_every_permission_code_the_code_checks_is_declared():
    """No guard names a permission the catalogue does not define."""
    catalogue = _catalogue()
    assert catalogue, "read no permission codes at all; the parser is wrong"

    undefined = {
        code: places
        for code, places in _references().items()
        if code not in catalogue
    }
    assert not undefined, (
        "These permission codes are checked but never declared, so the guards "
        "using them refuse everybody and the endpoints behind them are dead:\n"
        + "\n".join(
            f"  {code}\n" + "\n".join(f"      {p}" for p in places)
            for code, places in sorted(undefined.items())
        )
    )


def test_every_declared_permission_is_granted_to_somebody_or_deliberately_not():
    """A permission no seeded role holds is a question worth asking once.

    Not a failure -- `theatre.override` and `discharge.override` are meant to
    be granted deliberately by a customer rather than shipped in a role, and
    the platform-side codes have no tenant role at all. The value is that
    adding a permission and forgetting to grant it produces a *named* list
    rather than an endpoint that quietly works for nobody, which is the same
    outage as an undeclared code arriving by a different road.
    """
    from apps.rbac.services import SYSTEM_ROLES

    granted = set()
    for role in SYSTEM_ROLES:
        granted |= set(role.get("permissions", ()))

    #: Held by nobody on purpose. Each line is a claim somebody made.
    UNGRANTED_BY_DESIGN = {
        "theatre.override": "granted case by case, not shipped in a role",
        "discharge.override": "granted case by case, not shipped in a role",
        "patient.merge": "a destructive one-way operation; granted explicitly",
        "data.import": "sensitive; granted for a migration and taken back",
        "audit.export": "granted to a named auditor for a named engagement",
        "user.deactivate": "granted with the administrator role a customer builds",
        "employee.separate": "the same, and deliberately not in `hr_manager`",
    }

    orphans = sorted(
        code for code in _catalogue()
        if code not in granted and code not in UNGRANTED_BY_DESIGN
    )
    assert not orphans, (
        "These permissions exist but no seeded role grants them, so nothing "
        "they guard can be reached by a demo tenant. Either grant them or "
        "add them to UNGRANTED_BY_DESIGN with the reason:\n  "
        + "\n  ".join(orphans)
    )
