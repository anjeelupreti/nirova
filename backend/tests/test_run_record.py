"""Reading a test run's record: only a finished, clean run is a pass.

The case this exists for is the first one: a run that was killed after it
started and before pytest wrote its summary. The launcher said "exit code 0";
the record says the run never finished, and the verdict must side with the
record.
"""

import os

from tests.run_record import verdict

#: A process id that is certainly not running: far above any real pid.
DEAD_PID = 2_000_000_000


def test_a_run_that_never_finished_is_not_a_pass():
    label, code, why = verdict({"complete": False, "pid": DEAD_PID, "started_at": "2026-09-12T10:00:00+00:00"})
    assert (label, code) == ("INCOMPLETE", 2)
    assert "never finished" in why


def test_a_run_still_going_is_reported_as_running():
    label, code, _ = verdict({"complete": False, "pid": os.getpid(), "started_at": "now"})
    assert (label, code) == ("RUNNING", 4)


def test_no_record_is_not_a_pass():
    assert verdict(None)[:2] == ("NO RUN", 3)


def _finished(**overrides):
    record = {
        "complete": True, "exit_status": 0, "exit_meaning": "tests passed",
        "collected": 10, "passed": 10, "failed": [], "errors": [], "skipped": 0,
        "duration_seconds": 1.0,
    }
    record.update(overrides)
    return record


def test_a_clean_finished_run_passes():
    assert verdict(_finished())[:2] == ("PASS", 0)


def test_a_failure_is_a_failure_and_is_named():
    label, code, why = verdict(_finished(exit_status=1, passed=9, failed=["tests/test_x.py::test_y"]))
    assert (label, code) == ("FAIL", 1)
    assert "tests/test_x.py::test_y" in why


def test_an_interrupted_run_is_not_a_pass():
    """Ctrl-C reaches `sessionfinish` with exit status 2 and no failures."""
    assert verdict(_finished(exit_status=2, exit_meaning="interrupted", passed=4))[:2] == ("FAIL", 1)


def test_errors_without_failures_are_not_a_pass():
    assert verdict(_finished(exit_status=1, errors=["tests/test_x.py::test_setup"]))[0] == "FAIL"
