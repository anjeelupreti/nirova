"""Run the backend suite, and say whether it passed — truthfully.

    python scripts/run_tests.py [pytest args...]            run, then print the verdict
    python scripts/run_tests.py --detach [pytest args...]   start in the background
    python scripts/run_tests.py --status                    the verdict of the last run
    python scripts/run_tests.py --wait                      wait for a detached run

The verdict comes from the record pytest writes (`tests/run_record.py`), not
from how the process ended. A run that is killed part-way leaves a record that
says "incomplete", and this reports INCOMPLETE with a non-zero exit code — the
failure mode it exists for is a suite that stopped at 40% being read as green.

`--detach` starts pytest in its own process group, outside whatever launched
it, writing to `.test-results/last-run.log`. For environments that end the
processes they start — a tool sandbox under memory pressure, a CI step with a
short timeout — the run carries on, and `--status` / `--wait` read the result.

Exit codes: 0 pass · 1 fail · 2 incomplete · 3 no run recorded · 4 still running.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.run_record import RESULTS_DIR, load, verdict  # noqa: E402

LOG = RESULTS_DIR / "last-run.log"


def report() -> int:
    label, code, explanation = verdict(load())
    print(f"{label}: {explanation}")
    return code


def pytest_command(args: list[str]) -> list[str]:
    return [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args]


def detach(args: list[str]) -> int:
    RESULTS_DIR.mkdir(exist_ok=True)
    log = LOG.open("w", encoding="utf-8")
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(
        pytest_command(args), cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, **options,
    )
    print(f"Started pytest (pid {process.pid}); log: {LOG}")
    print("Read the result with: python scripts/run_tests.py --wait")
    return 0


def wait(timeout: float = 3600) -> int:
    deadline = time.monotonic() + timeout
    # A detached run writes its "started" record a moment after launch.
    time.sleep(2)
    while time.monotonic() < deadline:
        label, _, _ = verdict(load())
        if label != "RUNNING":
            break
        time.sleep(5)
    return report()


def main(argv: list[str]) -> int:
    if argv[:1] == ["--status"]:
        return report()
    if argv[:1] == ["--wait"]:
        return wait()
    if argv[:1] == ["--detach"]:
        return detach(argv[1:])
    subprocess.call(pytest_command(argv), cwd=BACKEND)
    # Deliberately not pytest's own return code: that is exactly what a killed
    # wrapper misreports. The record decides.
    print()
    return report()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
