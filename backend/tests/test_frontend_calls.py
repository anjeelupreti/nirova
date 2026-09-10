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


#: `api.get<T>("/path")`, `api.post(\`/path/${id}/\`)`, and the rest.
API_CALL = re.compile(
    r"""api\.(?:get|post|patch|del|put)[^(]*\(\s*([`"'])([^`"']*)""",
)


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

    offenders = []
    for file in sorted(root.rglob("*.tsx")) + sorted(root.rglob("*.ts")):
        if "lib/api" in str(file).replace("\\", "/"):
            continue
        for number, line in enumerate(
            file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            match = API_CALL.search(line)
            if match and match.group(2).startswith("/api/"):
                offenders.append(
                    f"{file.relative_to(root)}:{number}  {match.group(2)[:60]}"
                )

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

    offenders = []
    for file in sorted(root.rglob("*.tsx")) + sorted(root.rglob("*.ts")):
        if "lib/api" in str(file).replace("\\", "/"):
            continue
        for number, line in enumerate(
            file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            match = API_CALL.search(line)
            if not match:
                continue
            path = match.group(2)
            # An interpolation in the first position is a path built entirely
            # from a variable; there is nothing static to check.
            if not path or path.startswith("$"):
                continue
            if not path.startswith("/"):
                offenders.append(
                    f"{file.relative_to(root)}:{number}  {path[:60]}"
                )

    assert not offenders, (
        "these paths are relative and will resolve against the current "
        "route:\n  " + "\n  ".join(offenders)
    )
