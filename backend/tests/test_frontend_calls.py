"""Static checks on the calls the frontend makes.

No database, no HTTP: these read the frontend source and assert things about
it that are cheap to check and expensive to find any other way.

**Why these live in the Python suite.** The frontend has no test runner, and
adding one to catch two rules would be a large amount of machinery for a small
amount of checking. These rules are about the *contract between* the two
halves, which is exactly the seam a repository-wide suite is for.
"""

import pathlib
import re

import pytest


def _frontend() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"


#: The one definition, shared with the audits.
#:
#: This file used to carry its own copy, which drifted: the shared pattern
#: gained `\s*` around the dot after 102 chained calls turned out to be
#: invisible, and this copy did not. Two regexes for one rule is the failure
#: `apps/common/screens.py` was extracted to prevent.
from apps.common.screens import API_CALL


def _calls():
    """Every `api.*` call in the frontend, as `(file, line number, path)`.

    **Scans each file whole rather than line by line.** The console writes
    promise chains as `void api` on one line and `.get<T>("/path")` on the
    next, and a line-based search cannot see `api` and the path together --
    102 calls were invisible to this test and to every audit built on the same
    pattern. The line number is recovered from the match offset so failures
    still point at a line somebody can open.
    """
    root = _frontend()
    for file in sorted(root.rglob("*.tsx")) + sorted(root.rglob("*.ts")):
        if "lib/api" in str(file).replace("\\", "/"):
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        for match in API_CALL.finditer(text):
            line = text.count(chr(10), 0, match.start()) + 1
            yield file.relative_to(root), line, match.group(1)


def test_no_call_prefixes_api_twice():
    """`request()` already adds `/api`. Adding it again 404s every time.

    **This has happened twice and cost a screen each time.** Every one of the
    19 calls in `SelfService.tsx` was `/api/...` (log 236), and every one of
    the 12 in `NurseWorkspace.tsx` was too -- so the entire nurse workspace
    had never worked, from the day it was written.

    The second one was missed by a sweep I ran and reported clean. The sweep
    was a shell grep whose pattern contained a backtick inside a double-quoted
    string; bash consumed the backtick, template literals never matched, and
    the search found nothing. **That is why this is a test and not a grep** --
    a check that lives in the suite is run by machinery that cannot be
    defeated by quoting, and it runs again tomorrow.
    """
    root = _frontend()
    if not root.exists():
        pytest.skip(f"frontend source not present at {root}")

    offenders = [
        f"{file}:{number}  {path[:60]}"
        for file, number, path in _calls()
        if path.startswith("/api/")
    ]

    assert not offenders, (
        "these calls will request /api/api/… and 404 every time:\n  "
        + "\n  ".join(offenders)
    )


def test_every_call_starts_with_a_slash():
    """A relative path resolves against the current route, not the API.

    `api.get("clinical/patients/")` from `/wards/3` requests
    `/api/wards/clinical/patients/`. It fails differently depending on which
    screen you were on when you clicked, which is the worst kind of bug to be
    told about second-hand.
    """
    root = _frontend()
    if not root.exists():
        pytest.skip(f"frontend source not present at {root}")

    offenders = [
        f"{file}:{number}  {path[:60]}"
        for file, number, path in _calls()
        # An interpolation in the first position is a path built entirely from
        # a variable; there is nothing static to check.
        if path and not path.startswith("$") and not path.startswith("/")
    ]

    assert not offenders, (
        "these paths are relative and will resolve against the current "
        "route:\n  " + "\n  ".join(offenders)
    )


def test_a_consultation_link_carries_an_encounter_not_a_patient():
    """`/consultation/:uuid` loads `/clinical/encounters/<uuid>/`.

    The doctor's own board linked every row with the *patient's* id -- the
    waiting list and the unfinished consultations both -- so the most-repeated
    link on a clinic day answered "the requested resource does not exist".
    Caught by opening one, not by reading the code, which is why this is a
    test: the two identifiers are both uuids and look identical in a diff.
    """
    root = _frontend()
    if not root.exists():
        pytest.skip(f"frontend source not present at {root}")

    pattern = re.compile(r"/consultation/\$\{([^}]+)\}")
    offenders = []
    for file in sorted(root.rglob("*.tsx")):
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            for expression in pattern.findall(line):
                # `encounter.uuid`, `detail.uuid`, a bare `uuid` are right.
                # Anything naming a patient is the bug this test exists for.
                if "patient" in expression.lower():
                    offenders.append(f"{file.relative_to(root)}:{number}  {expression}")

    assert not offenders, (
        "these links pass a patient to a route that loads an encounter, and "
        "will 404 every time: " + "; ".join(offenders)
    )
