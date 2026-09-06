"""What is waiting for this person, gathered from the modules that know.

§96. Every module in this system has a screen showing what is pending in it,
and somebody who approves purchase orders, signs off tills and reviews leave has
to remember to visit three of them. This is the one place that answers "what
needs me today?"

Four rules, and the fourth is the one that matters.

**It aggregates; it does not decide.** Each module already knows what is pending
in it and which permission it takes to act. This asks them. Reimplementing
"which requisitions are awaiting approval" here would produce a second answer
that disagrees with the procurement screen inside a month -- the same argument
the report registry makes for adding no arithmetic of its own.

**An item you cannot act on does not appear.** Not greyed, absent. A report
library lists what you cannot run because knowing the report exists is useful;
a work queue is the opposite -- a list of things you can only look at teaches
people that the queue is not really theirs, and then they stop reading it.

**Counts are counts of what is shown**, for the same reason as everywhere else.

**A source that fails is reported broken, not skipped.** This is the important
one. Every other list in this system degrades acceptably to empty; this one does
not, because **an empty approval queue is a positive claim that there is nothing
to approve.** A source that raises and is quietly dropped tells somebody with
twenty-two requisitions waiting that their afternoon is free. So a failure is
carried out to the caller as a named, broken source, and the summary says the
total is incomplete.
"""

from dataclasses import dataclass
from typing import Callable

from apps.rbac.permissions import Scope


@dataclass(frozen=True)
class Waiting:
    """One kind of thing that waits for a person's decision."""

    code: str
    label: str
    #: The permission it takes to *act*, not to look. This is a work queue.
    permission: str
    #: The scope that permission is required at. `facility.approve_change` is
    #: an organization-level authority and asking for it at facility scope
    #: would quietly show the queue to nobody.
    scope: str
    #: `(request) -> list[dict]`. Raising is allowed; it is caught and reported.
    find: Callable
    #: Where to go and deal with it.
    screen: str
    #: Roughly how bad it is to leave this sitting. Used for ordering, not for
    #: colour: a till unreconciled overnight is a cash control failure, an
    #: unread leave request is a slightly annoyed nurse.
    urgency: int = 5


_SOURCES: dict = {}


def register(source: Waiting) -> Waiting:
    if source.code in _SOURCES:
        raise ValueError(f"'{source.code}' is already a workspace source")
    _SOURCES[source.code] = source
    return source


def all_sources() -> list:
    return sorted(_SOURCES.values(), key=lambda s: (-s.urgency, s.label))


def _item(uuid, title, detail, when=None, reference=""):
    """One waiting thing, in the shape every source returns."""
    return {
        "uuid": str(uuid),
        "reference": reference,
        "title": title,
        "detail": detail,
        "waiting_since": when.isoformat() if when else None,
    }


def load() -> None:
    """Register every source. Called once from the app's `ready()`."""
    if _SOURCES:
        return

    from apps.common.permissions import apply_scope_filter

    def requisitions(request):
        from apps.procurement.models import PurchaseRequisition, RequisitionStatus

        rows = apply_scope_filter(
            PurchaseRequisition.objects.filter(
                status=RequisitionStatus.SUBMITTED,
            ),
            request, "purchase.approve",
        ).select_related("facility")[:25]
        return [
            _item(row.uuid, f"Requisition {row.reference}",
                  " · ".join(filter(None, [
                      row.facility.name if row.facility_id else "",
                      row.requested_by_name,
                  ])),
                  row.created_at, row.reference)
            for row in rows
        ]

    def purchase_orders(request):
        from apps.procurement.models import PurchaseOrder, PurchaseOrderStatus

        rows = apply_scope_filter(
            PurchaseOrder.objects.filter(
                status=PurchaseOrderStatus.PENDING_APPROVAL,
            ),
            request, "purchase.approve",
        ).select_related("facility", "supplier")[:25]
        return [
            _item(row.uuid, f"Purchase order {row.reference}",
                  " · ".join(filter(None, [
                      row.supplier.name if row.supplier_id else "",
                      f"NPR {row.total}",
                  ])),
                  row.created_at, row.reference)
            for row in rows
        ]

    def leave(request):
        from apps.hr.models import LeaveRequest

        rows = apply_scope_filter(
            LeaveRequest.objects.filter(status="pending"),
            request, "leave.approve", employee_attr="employee",
        ).select_related("employee")[:25]
        return [
            # `starts_on`/`ends_on`, not `start_date`/`end_date`. The first
            # draft guessed, the source raised, and -- because a broken source
            # is reported rather than skipped -- it came back as a named
            # failure instead of a queue that said there was no leave to
            # approve. That rule paid for itself on its first run.
            _item(row.uuid, f"Leave: {row.employee.full_name}",
                  f"{row.starts_on} to {row.ends_on}"
                  f" · {row.working_days} working days",
                  row.applied_at, row.reference)
            for row in rows
        ]

    def shift_swaps(request):
        from apps.hr.models import ShiftSwapRequest

        rows = apply_scope_filter(
            ShiftSwapRequest.objects.select_related(
                "requester", "target_employee",
            ).filter(status="pending_manager"),
            request, "leave.approve", employee_attr="requester",
        )[:25]
        return [
            _item(row.uuid,
                  f"Shift swap: {row.requester.full_name}"
                  f" and {row.target_employee.full_name}",
                  row.reason or "", row.peer_decided_at or row.created_at)
            for row in rows
        ]

    def tills(request):
        from apps.pos.models import CounterSession

        rows = apply_scope_filter(
            CounterSession.objects.filter(status="closed"),
            request, "till.reconcile",
        ).select_related("facility")[:25]
        return [
            _item(row.uuid, f"Till to sign off: {row.reference}",
                  " · ".join(filter(None, [
                      row.cashier_name,
                      row.facility.name if row.facility_id else "",
                  ])),
                  row.created_at, row.reference)
            for row in rows
        ]

    def facility_changes(request):
        from apps.provisioning.models import (
            ChangeRequestStatus,
            FacilityChangeRequest,
        )

        rows = FacilityChangeRequest.objects.filter(
            status=ChangeRequestStatus.ORG_REVIEW,
        )[:25]
        return [
            _item(row.uuid, f"Facility change {row.reference}",
                  getattr(row, "summary", "") or getattr(row, "reason", "") or "",
                  row.created_at, row.reference)
            for row in rows
        ]

    def break_glass(request):
        from apps.rbac.models import BreakGlassGrant

        rows = BreakGlassGrant.objects.filter(reviewed_at__isnull=True)[:25]
        return [
            _item(row.uuid,
                  f"Emergency access: {row.user_label} opened "
                  f"{row.patient_label}",
                  # The stated reason, verbatim. This queue exists so somebody
                  # reads what was typed at the time; summarising it here would
                  # defeat the only control the override has.
                  row.reason,
                  row.granted_at)
            for row in rows
        ]

    def payroll_runs(request):
        from apps.payroll.models import PayrollRun, RunStatus

        rows = apply_scope_filter(
            PayrollRun.objects.filter(status=RunStatus.PENDING_APPROVAL),
            request, "payroll.approve",
        )[:25]
        return [
            _item(row.uuid, f"Payroll run {row.reference}",
                  f"{row.employee_count} employees · NPR {row.net_total}",
                  row.created_at, row.reference)
            for row in rows
        ]

    for source in [
        # Ordered by what it costs to leave it sitting. A till unreconciled
        # overnight is a cash control failure and an unreviewed emergency
        # access is a privacy one; an unread leave request is a slightly
        # annoyed nurse.
        Waiting("break_glass", "Emergency access to review", "privacy.review",
                Scope.OWN, break_glass, "/privacy", urgency=9),
        Waiting("tills", "Tills awaiting sign-off", "till.reconcile",
                Scope.FACILITY, tills, "/counter", urgency=8),
        Waiting("payroll_runs", "Payroll awaiting approval", "payroll.approve",
                Scope.FACILITY, payroll_runs, "/payroll", urgency=8),
        Waiting("facility_changes", "Facility changes awaiting approval",
                "facility.approve_change", Scope.ORGANIZATION,
                facility_changes, "/facility-requests", urgency=6),
        Waiting("purchase_orders", "Purchase orders awaiting approval",
                "purchase.approve", Scope.FACILITY, purchase_orders,
                "/procurement", urgency=6),
        Waiting("requisitions", "Requisitions awaiting approval",
                "purchase.approve", Scope.FACILITY, requisitions,
                "/procurement", urgency=5),
        Waiting("leave", "Leave awaiting approval", "leave.approve",
                Scope.FACILITY, leave, "/time", urgency=4),
        Waiting("shift_swaps", "Shift swaps awaiting a manager",
                "leave.approve", Scope.FACILITY, shift_swaps, "/time",
                urgency=4),
    ]:
        register(source)
