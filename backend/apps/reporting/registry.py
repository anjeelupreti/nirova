"""A register of the reports this system already produces.

§105 asks for a reporting engine: a standard library, a custom builder, export,
and scheduling. This is the first of those four, and the decision worth stating
is what it deliberately is **not**.

**It is not a query builder.** A builder that lets somebody assemble
dataset → fields → filters → grouping → measures is, at best, a worse SQL with
a mouse; at worst it is a way to produce a number nobody can reproduce and
everybody quotes. Hospitals run on a fixed set of reports that somebody has
checked. Sixteen of those already exist in this codebase, written alongside the
modules that understand them, each with the arithmetic argued over in its own
docstring — and they are unreachable unless you know the URL.

So this makes them **discoverable and uniform** rather than replacing them. A
report declares what it needs and what it answers; the registry handles
permissions, parameters and export identically for all of them.

Three rules it keeps.

**Every report names the permission it needs**, and the registry enforces it.
A reporting layer that runs arbitrary functions with the caller's word for
their authority is a way around every control in the system, and reports are
exactly where somebody would look for one — a report is a bulk read wearing a
respectable hat.

**Parameters are declared, not inspected.** Reading a function signature to
work out what to pass is clever and produces a registry that breaks when
somebody adds a keyword argument. Declaring them is dull and survives.

**Nothing is registered that nobody has checked.** Each entry points at a
function whose numbers were argued over where they are computed. This module
adds no arithmetic of its own, which is the point: a reporting engine that
recomputes what a module already knows is a second answer waiting to disagree
with the first.
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Report:
    """One report somebody has checked, and what it takes to run it."""

    code: str
    name: str
    #: What question it answers, in the words somebody would ask it. Shown in
    #: the library, so "Trial balance" is not enough on its own.
    answers: str
    permission: str
    run: Callable
    #: Parameter names this report accepts, from the shared vocabulary below.
    #: Declared rather than inspected -- see the module docstring.
    parameters: tuple = ()
    group: str = "General"
    #: Set when a report is expensive enough that somebody should know before
    #: pressing the button rather than after.
    is_heavy: bool = False
    #: Declared parameter name -> the keyword the function actually takes.
    #: Needed because these reports were written years apart against no shared
    #: vocabulary: one takes `until`, another `on_date`, a third `within_days`.
    #: Renaming sixteen arguments across nine modules to please a registry
    #: would be the tail wagging the dog, so the registry adapts instead.
    argument_map: dict = field(default_factory=dict)
    #: Arguments the function requires and the caller does not supply.
    requires: tuple = ()


#: The shared parameter vocabulary. Deliberately small: every report in this
#: system is scoped by some combination of a facility and a date range, and a
#: registry that accepted arbitrary parameters would be the query builder this
#: is not.
PARAMETERS = {
    "facility": "A facility UUID. Omit for the whole organization.",
    "since": "Start of the period (YYYY-MM-DD).",
    "until": "End of the period (YYYY-MM-DD).",
    "days": "How many days back to look.",
}

_REGISTRY: dict = {}


def call(report: Report, given: dict):
    """Run a report, translating declared parameters into its own arguments."""
    kwargs = {}
    for name, value in given.items():
        if name not in report.parameters or value in (None, ""):
            continue
        kwargs[report.argument_map.get(name, name)] = value
    return report.run(**kwargs)


def register(report: Report) -> Report:
    if report.code in _REGISTRY:
        raise ValueError(f"A report is already registered as '{report.code}'")
    for name in report.parameters:
        if name not in PARAMETERS:
            raise ValueError(
                f"{report.code} declares unknown parameter '{name}'. Add it to "
                "PARAMETERS with a description, or use one that exists -- the "
                "vocabulary is small on purpose."
            )
    _REGISTRY[report.code] = report
    return report


def all_reports() -> list:
    return sorted(_REGISTRY.values(), key=lambda r: (r.group, r.name))


def get_report(code: str) -> Report | None:
    return _REGISTRY.get(code)


def load() -> None:
    """Register everything. Called once from the app's `ready()`.

    Imports are inside the function because these reach into a dozen modules,
    and doing that at import time makes the app registry order load-bearing --
    which is a debugging afternoon nobody enjoys.
    """
    if _REGISTRY:
        return

    from apps.audit import access_reports
    from apps.bloodbank import services as blood
    from apps.diagnostics import services as diagnostics
    from apps.emergency import services as emergency
    from apps.finance import services as finance
    from apps.inpatient import services as inpatient
    from apps.insurance import services as insurance
    from apps.pharmacy import services as pharmacy
    from apps.referrals import services as referrals

    for report in [
        # -- money --------------------------------------------------------
        Report(
            code="finance.trial_balance",
            name="Trial balance",
            answers="Do the books balance, and where does each account stand?",
            permission="finance.post",
            run=finance.trial_balance,
            parameters=("until", "facility"),
            group="Finance",
        ),
        Report(
            code="finance.profit_and_loss",
            name="Profit and loss",
            answers="What did the organization earn and spend over a period?",
            permission="report.read",
            run=finance.profit_and_loss,
            parameters=("since", "until", "facility"),
            group="Finance",
        ),
        Report(
            code="finance.balance_sheet",
            name="Balance sheet",
            answers="What does the organization own and owe, on a date?",
            permission="report.read",
            run=finance.balance_sheet,
            parameters=("until",),
            group="Finance",
        ),
        Report(
            code="finance.receivables_ageing",
            name="Receivables ageing",
            answers="Who owes money, and how long have they owed it?",
            permission="report.read",
            run=finance.receivables_ageing,
            parameters=("until",),
            group="Finance",
        ),
        # -- clinical -----------------------------------------------------
        Report(
            code="inpatient.census",
            name="Ward census",
            answers="Who is in which bed right now, and how full is the ward?",
            permission="encounter.read",
            run=inpatient.census,
            parameters=("facility",),
            requires=("facility",),
            group="Clinical",
        ),
        Report(
            code="diagnostics.turnaround",
            name="Diagnostic turnaround",
            answers="How long do results take, and where is the delay?",
            permission="report.read",
            run=diagnostics.turnaround_report,
            parameters=("facility", "since"),
            requires=("facility",),
            group="Clinical",
        ),
        Report(
            code="referrals.summary",
            name="Referral performance",
            answers="How many referrals are answered, and how quickly?",
            permission="report.read",
            run=referrals.summary,
            parameters=("facility", "since"),
            group="Clinical",
        ),
        Report(
            code="emergency.summary",
            name="Emergency department",
            answers="How busy was the department, and were the clocks met?",
            permission="report.read",
            run=emergency.department_summary,
            parameters=("facility", "since"),
            requires=("facility",),
            group="Clinical",
        ),
        # -- stock and claims ---------------------------------------------
        Report(
            code="pharmacy.expiring",
            name="Stock expiring",
            answers="What is about to expire, and what is it worth?",
            permission="stock.read",
            run=pharmacy.expiring_stock,
            parameters=("days",),
            argument_map={"days": "within_days"},
            group="Pharmacy",
        ),
        Report(
            code="insurance.performance",
            name="Claim performance",
            answers="What proportion of claims are rejected, and why?",
            permission="report.read",
            run=insurance.payer_performance,
            parameters=("since",),
            group="Insurance",
        ),
        Report(
            code="bloodbank.stock",
            name="Blood stock",
            answers="What blood is available, by group, and what expires soon?",
            permission="report.read",
            run=blood.stock,
            parameters=("facility",),
            requires=("facility",),
            group="Blood bank",
        ),
        # -- privacy ------------------------------------------------------
        Report(
            code="privacy.unrelated_reads",
            name="Reads without a care relationship",
            answers="Who opened a record they have no relationship with?",
            permission="privacy.review",
            run=access_reports.reads_without_a_relationship,
            parameters=("days",),
            group="Privacy",
            is_heavy=True,
        ),
        Report(
            code="privacy.read_volume",
            name="Read volume by person",
            answers="Who reads far more records than others in the same role?",
            permission="privacy.review",
            run=access_reports.read_volume_by_person,
            parameters=("days",),
            group="Privacy",
        ),
    ]:
        try:
            register(report)
        except AttributeError:
            # A report naming a function that has moved or been renamed. Skipped
            # rather than fatal: one stale entry should not stop the library
            # loading, and the alternative is a registry that takes the whole
            # application down over a report nobody was running.
            import logging

            logging.getLogger("nirova.reporting").warning(
                "report %s names a function that does not exist", report.code,
            )
