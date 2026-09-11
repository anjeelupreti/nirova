"""The record every test run leaves behind, and how to read it.

Written twice by the hooks in `conftest.py`:

* at session start — `{"complete": false, "pid": ..., "started_at": ...}`;
* at session finish — the counts, the failed test ids, pytest's exit status,
  and `"complete": true`.

A run killed in between never reaches the second write, so its record still
says `complete: false`. `verdict()` turns that into INCOMPLETE — or RUNNING,
if the process that wrote it is still alive — and never into PASS. The launch
tool's exit code is not consulted at all.

Writes are atomic (temporary file, then rename), so a reader never sees half a
record, and a crash mid-write leaves the previous one intact.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

#: Beside the backend, ignored by git.
RESULTS_DIR = Path(__file__).resolve().parent.parent / ".test-results"
RECORD = RESULTS_DIR / "last-run.json"

EXIT_NAMES = {
    0: "tests passed",
    1: "tests failed",
    2: "interrupted",
    3: "internal error",
    4: "usage error",
    5: "no tests collected",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(data: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    temporary = RECORD.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temporary, RECORD)


def _is_worker(session) -> bool:
    # Under pytest-xdist only the controller writes the record.
    return hasattr(session.config, "workerinput")


def record_start(session) -> None:
    if _is_worker(session):
        return
    # **One run at a time.** These tests run against the live demo database
    # (see `conftest.django_db_setup`), and some of them change it for a moment
    # — one switches on "require two-step sign-in" for the whole
    # organization. Two runs at once corrupt each other: found by starting a
    # focused run while the full suite was still going, which overwrote its
    # record and changed the rules under it.
    previous = load()
    if (
        previous
        and not previous.get("complete")
        and previous.get("pid") not in (None, os.getpid())
        and _alive(int(previous["pid"]))
    ):
        import pytest

        # Marked so `record_finish` leaves the running suite's record alone:
        # pytest still calls the finish hook for a run it refused to start.
        session.config._run_refused = True
        pytest.exit(
            f"Another test run is in progress (pid {previous['pid']}, started "
            f"{previous.get('started_at')}). These tests share the live demo "
            "database, so runs cannot overlap -- wait for it "
            "(python scripts/run_tests.py --wait) or stop it.",
            returncode=4,
        )
    session.config._run_started = time.monotonic()
    _write({
        "complete": False,
        "pid": os.getpid(),
        "started_at": _now(),
        "args": list(session.config.invocation_params.args),
    })


def record_finish(session, exitstatus) -> None:
    if _is_worker(session) or getattr(session.config, "_run_refused", False):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    stats = getattr(reporter, "stats", {}) if reporter else {}

    def ids(key):
        return [
            getattr(report, "nodeid", "")
            for report in stats.get(key, [])
            if getattr(report, "when", "call") in ("call", "setup", "teardown", None)
        ]

    status = int(exitstatus)
    started = getattr(session.config, "_run_started", None)
    _write({
        "complete": True,
        "pid": os.getpid(),
        "started_at": json.loads(RECORD.read_text(encoding="utf-8")).get("started_at")
        if RECORD.exists() else None,
        "finished_at": _now(),
        "duration_seconds": round(time.monotonic() - started, 1) if started else None,
        "args": list(session.config.invocation_params.args),
        "exit_status": status,
        "exit_meaning": EXIT_NAMES.get(status, "unknown"),
        "collected": session.testscollected,
        "passed": len(stats.get("passed", [])),
        "failed": sorted(set(ids("failed"))),
        "errors": sorted(set(ids("error"))),
        "skipped": len(stats.get("skipped", [])),
    })


# -- reading it -------------------------------------------------------------------


def _alive(pid: int) -> bool:
    """Whether a process is still running — without signalling it.

    On Windows `os.kill(pid, 0)` does not probe, it terminates; so the
    process is opened and its exit code read instead.
    """
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def verdict(record: dict | None) -> tuple[str, int, str]:
    """(label, exit code, explanation) for a record. Only PASS exits 0."""
    if record is None:
        return "NO RUN", 3, "No test run has been recorded here."
    if not record.get("complete"):
        started = record.get("started_at", "?")
        if record.get("pid") and _alive(int(record["pid"])):
            return "RUNNING", 4, f"Started {started}; pytest is still running (pid {record['pid']})."
        return (
            "INCOMPLETE", 2,
            f"The run started {started} never finished: pytest did not reach its "
            "summary, so the process was killed or crashed. Nothing it did counts "
            "as a result -- run it again.",
        )
    counts = (
        f"{record['passed']} passed, {len(record['failed'])} failed, "
        f"{len(record['errors'])} errors, {record['skipped']} skipped "
        f"of {record['collected']} collected, in {record.get('duration_seconds')}s"
    )
    if record["exit_status"] == 0 and not record["failed"] and not record["errors"]:
        return "PASS", 0, counts
    detail = "\n".join(f"  {test}" for test in (record["failed"] + record["errors"])[:40])
    return (
        "FAIL", 1,
        f"{counts}; pytest: {record['exit_meaning']}" + (f"\n{detail}" if detail else ""),
    )


def load() -> dict | None:
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
