"""Shapes the console should stop hand-rolling.

These read the frontend source, like `test_frontend_calls.py`, and they exist
because the same three complaints keep coming back from the people using it:
dialogs that only grow downward, and lists with no search, filter or page
controls.

**An allow-list that must shrink, not a rule with exceptions.** Each list below
names what is still to be converted. Adding to one is not forbidden -- it is
visible, and a screen added tomorrow with its own `fixed inset-0` fails these
instead of quietly joining the sixteen.
"""

import pathlib
import re

import pytest


def _frontend() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"


#: Files that legitimately position something over the page themselves.
OVERLAY_BY_DESIGN = {
    # The dialog primitive itself, and the two overlays that are not dialogs.
    "components/ui/modal.tsx",
    "components/ui/primitives.tsx",
    "components/shell/CommandPalette.tsx",
    "components/documents/DocumentPreview.tsx",
}

#: Still hand-rolled, and each one is a screen somebody has complained about.
#: Converting one means deleting its line here. When this set is empty, delete
#: it and keep only `OVERLAY_BY_DESIGN`.
TO_CONVERT = {
    "pages/Blood.tsx",
    "pages/Claims.tsx",
    "pages/Counter.tsx",
    "pages/Emergency.tsx",
    "pages/Finance.tsx",
    "pages/Icu.tsx",
    "pages/NurseWorkspace.tsx",
    "pages/Payroll.tsx",
    "pages/People.tsx",
    "pages/Portal.tsx",
    "pages/Referrals.tsx",
    "pages/SelfService.tsx",
    "pages/Theatre.tsx",
    "pages/Time.tsx",
    "pages/Wards.tsx",
}


def test_no_new_screen_hand_rolls_a_dialog():
    """`components/ui/modal.tsx` exists so that none of them has to.

    A hand-rolled dialog gets one dimension -- height -- so it grows downward
    until a discharge form is two screens tall on a monitor with 1200 unused
    pixels either side. The primitive takes a width, pins the header and the
    buttons, and scrolls its own body.
    """
    root = _frontend()
    if not root.exists():
        pytest.skip(f"frontend source not present at {root}")

    offenders = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.tsx")
        if "fixed inset-0" in path.read_text(encoding="utf-8")
    }
    unexpected = sorted(offenders - OVERLAY_BY_DESIGN - TO_CONVERT)

    assert not unexpected, (
        "these hand-roll a dialog instead of using `Modal`: "
        + ", ".join(unexpected)
    )

    # And the other direction: a file that has been converted must leave the
    # list, or the list stops describing anything.
    stale = sorted(TO_CONVERT - offenders)
    assert not stale, (
        "these no longer hand-roll a dialog -- remove them from TO_CONVERT: "
        + ", ".join(stale)
    )


#: Lists still rendering a bare `<Table>` with no search, filter or paging.
#: `components/ui/dataview.tsx` gives all three plus card and board shapes;
#: every name here is a screen that has not been moved onto it yet.
TABLES_TO_CONVERT = {
    "pages/Appointments.tsx", "pages/Billing.tsx", "pages/Blood.tsx",
    "pages/Claims.tsx", "pages/Counter.tsx", "pages/DataImport.tsx",
    "pages/Diagnostics.tsx", "pages/Emergency.tsx", "pages/Facilities.tsx",
    "pages/FacilityRequests.tsx", "pages/Finance.tsx", "pages/Icu.tsx",
    "pages/NurseWorkspace.tsx", "pages/Payroll.tsx",
    "pages/People.tsx", "pages/Pharmacy.tsx", "pages/Platform.tsx",
    "pages/Portal.tsx", "pages/Privacy.tsx", "pages/Procurement.tsx",
    "pages/Queue.tsx", "pages/Referrals.tsx", "pages/Reports.tsx",
    "pages/Sales.tsx", "pages/SelfService.tsx", "pages/Services.tsx",
    "pages/Staff.tsx", "pages/Theatre.tsx", "pages/Time.tsx",
    "pages/Wards.tsx", "pages/finance/Payables.tsx",
    "pages/pharmacy/Catalogue.tsx", "pages/pharmacy/Stockroom.tsx",
    "pages/pharmacy/Trace.tsx", "pages/wards/Setup.tsx",
    "components/MasterData.tsx", "pages/pos/Returns.tsx",
}

#: `DataView` is the thing that renders the table shape; it is what every name
#: above should be calling instead of reaching for `<Table>` itself.
TABLE_BY_DESIGN = {"components/ui/dataview.tsx"}


def test_no_new_list_is_a_bare_table():
    """A `<Table>` is a shape, not a list.

    It has no search, no filter, no paging and one view. `DataView` supplies
    all of them once, and remembers which shape each person chose for each
    screen. This does not force the thirty-six existing ones to move today; it
    stops the thirty-seventh being written.
    """
    root = _frontend()
    if not root.exists():
        pytest.skip(f"frontend source not present at {root}")

    pattern = re.compile(r"<Table>")
    offenders = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.tsx")
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    unexpected = sorted(offenders - TABLES_TO_CONVERT - TABLE_BY_DESIGN)

    assert not unexpected, (
        "these render a bare table instead of `DataView`, so they have no "
        "search, filter or paging: " + ", ".join(unexpected)
    )
