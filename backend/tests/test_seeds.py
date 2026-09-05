"""Run every demo seed twice, in sequence.

This is the most valuable test in the project, and it is barely a test at all:
it just runs the seeds and asserts they do not raise.

The justification is the record. Across two sessions, running the suite twice
by hand found six defects that nothing else had noticed:

* a table missing two columns its model declared, so a whole feature -- model,
  four service functions, API, two user interfaces -- could not store a row;
* a partial unique constraint that disagreed with its own manager, silently
  killing every future notification under a dedupe key;
* a seed whose shift swap broke its own setup on the second run;
* a seed that looked a prescription up by encounter, when an encounter is
  allowed several;
* a seed that guaranteed an admission row but not that the patient was still
  admitted;
* and one that applied for leave dated today, so it passed Sunday to Friday
  and failed every Saturday -- for as long as it had existed.

Every one of those was found by running things a second time. None of them
would have been found by a unit test, because each was a disagreement between
two layers that a mock removes.

**Order matters and is deliberate.** The seeds are run in dependency order and
each is run against what the previous ones left behind, because that is where
the interactions live -- the prescription collision only appears when the
nursing seed runs after the clinical seeds.
"""

import pytest
from django.core.management import call_command

pytestmark = [
    pytest.mark.django_db(databases="__all__"),
    pytest.mark.seeds,
]


#: Dependency order. Not alphabetical: the clinical seeds must run before the
#: modules that read encounters, and the notification seed last because it
#: reads what everything else raised.
SEEDS = [
    "seed_billing_demo",
    "seed_bloodbank_demo",
    "seed_diagnostics_demo",
    "seed_emergency_demo",
    "seed_consultation_demo",
    "seed_finance_demo",
    "seed_attendance_demo",
    "seed_ess_demo",
    "seed_icu_demo",
    "seed_inpatient_demo",
    "seed_nurse_demo",
    "seed_insurance_demo",
    "seed_clinical_demo",
    "seed_payroll_demo",
    "seed_pharmacy_demo",
    "seed_portal_demo",
    "seed_pos_demo",
    "seed_procurement_demo",
    "seed_referrals_demo",
    "seed_theatre_demo",
    "seed_notifications_demo",
]


@pytest.mark.parametrize("command", SEEDS)
def test_seed_runs(command, organization, capsys):
    """Each seed completes against whatever the previous ones left."""
    call_command(command)


@pytest.mark.parametrize("command", SEEDS)
def test_seed_runs_again(command, organization, capsys):
    """And completes a second time.

    Split from the first pass rather than looped inside it, so that a failure
    names which half broke. "Works once, fails twice" and "never worked" are
    different bugs and the report should say which one it found.
    """
    call_command(command)


def test_sweeps_are_repeatable(organization, capsys):
    """The expiry sweep raises once and then reports nothing new.

    The sweep's own report claimed `raised 1` on every run until this was
    checked, because `notify` returns the existing notification on a dedupe hit
    and nothing in the return value distinguishes that from a new one.
    """
    from apps.notifications.sweeps import sweep_expiring_credentials
    from apps.tenancy.connections import context_for_organization
    from apps.tenancy.context import tenant_context

    with tenant_context(context_for_organization(organization)):
        first = sweep_expiring_credentials()
        second = sweep_expiring_credentials()

    assert second["raised"] == 0, (
        "the second sweep raised something new, so the dedupe key is not "
        f"holding: {second}"
    )
    assert second["standing"] == first["raised"] + first["standing"], (
        "what the first run raised should still be standing on the second"
    )
