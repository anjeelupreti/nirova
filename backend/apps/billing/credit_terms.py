"""When an invoice falls due, and why the default is "now".

`Invoice.due_date` has been on the model since billing was written and **no
code has ever set it**. Sixty-four issued invoices in the demo tenant, not one
with a due date — which means nothing can be overdue, receivables ageing is
measuring from something else, and the reminder that chases unpaid invoices
finds nothing to chase. That is the gap this closes.

**The default is due on issue, and that is deliberately the least
interesting choice available.** A Nepali hospital's counter is a cash counter:
the patient pays at discharge, and "due immediately" is what already happens.
Inventing net-30 as a default would be writing somebody's credit policy for
them, which is not a decision a billing module gets to make on its own.

**Terms vary by who pays, because that is the only axis on which they really
do.** A walk-in pays today; an insurer pays when it has adjudicated the claim,
which is weeks; a corporate account pays on a monthly cycle. So the setting is
per patient category, held in the ordinary configuration hierarchy, which means
a group can set it once and a single site can differ.

**Nothing is back-filled.** An invoice issued last March did not have a due
date, and inventing one now would fabricate an ageing history — a receivables
report that suddenly shows six months of overdue debt that nobody ever
recorded is worse than one that shows none. New invoices get a date; old ones
stay honestly blank, and the ageing report already handles that.
"""

from datetime import timedelta

from apps.organization.config import config_value

NAMESPACE = "billing"
KEY = "credit_days_by_category"

#: Days after issue that an invoice of each category falls due.
#:
#: Zero means due on issue, which is the status quo written down rather than a
#: policy chosen. The two non-zero entries are not credit terms this system is
#: granting -- they describe how long the *payer* takes, which is a fact about
#: insurers and corporate accounts rather than a decision about them.
DEFAULT_CREDIT_DAYS = {
    "general": 0,
    "staff": 0,
    "insurance": 45,
    "corporate": 30,
    "government": 45,
}


def credit_days(category: str, facility=None) -> int:
    """How many days this category gets, per the configuration in force.

    Falls back to the defaults above per key rather than wholesale, so an
    organization that configures only `insurance` does not silently lose the
    others.
    """
    configured = config_value(
        NAMESPACE, KEY, default=None, facility=facility,
    ) or {}
    if not isinstance(configured, dict):
        # A malformed setting must not take billing down, and must not silently
        # become "everything is due in ninety days" either. Ignored, and the
        # defaults stand.
        configured = {}
    value = configured.get(category, DEFAULT_CREDIT_DAYS.get(category, 0))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_CREDIT_DAYS.get(category, 0)


def due_date_for(invoice, issued_on):
    """The date this invoice falls due.

    `issued_on` is passed rather than read off the invoice so the caller
    decides what "today" means -- which matters for a backdated issue and for
    tests, and is the difference between a function you can reason about and
    one that reads the clock behind your back.
    """
    category = invoice.patient_category or "general"
    return issued_on + timedelta(days=credit_days(category, invoice.facility))
