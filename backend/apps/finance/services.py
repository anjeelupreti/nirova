"""Posting, closing, and proving the books agree with the documents.

The rules this layer keeps.

**Nothing posts into a closed period.** A document dated in a closed month is
posted in the next open one, keeping its own date. Refusing it outright means
the transaction is simply never recorded, which is worse than recording it
late.

**Automatic postings are idempotent by construction.** Every one is written
through `post_document`, which uses `get_or_create` on the source document's
own reference. A nightly job that runs twice, a retried webhook and a
double-clicked button all produce one entry.

**Nothing is edited.** A wrong entry is reversed by a contra entry that names
it, on a date in an open period. The original stays exactly as posted.

**Reconciliation compares two independent records and reports the
difference.** The receivables control balance comes from the ledger; the
receivables subledger comes from the invoices. Neither is derived from the
other, which is the only reason the comparison means anything.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.audit.models import AuditAction
# record: the ledger is the most audited thing in the building. Who posted a
# journal, who reversed one, and who closed a month are the three questions a
# statutory audit opens with.
from apps.audit.services import record
from apps.billing.fiscal import fiscal_year_bounds, fiscal_year_for
from apps.billing.models import Invoice, InvoiceStatus, Payment
from apps.catalog.keys import ModuleCode
from apps.common.exceptions import DomainError
from apps.entitlements.services import require_module
from apps.finance.models import (
    NORMAL_BALANCE,
    Account,
    AccountType,
    AccountingPeriod,
    BankAccount,
    ControlAccountKey,
    Expense,
    ExpenseStatus,
    JournalEntry,
    JournalLine,
    JournalSource,
    JournalStatus,
    PeriodStatus,
    StatementLine,
    SupplierInvoice,
    SupplierInvoiceStatus,
    validate_postable,
)
# tenant_atomic_method: a journal entry and its lines must be written together
# or not at all, and the transaction has to open on the tenant connection --
# the router refuses to guess, so a bare `transaction.atomic` would open on
# the control plane and protect nothing.
from apps.tenancy.db import tenant_atomic_method

logger = logging.getLogger("nirova.finance")

ZERO = Decimal("0.00")

#: The month names of the Bikram Sambat year, in order from Shrawan.
#:
#: The fiscal year starts in Shrawan, so period 1 is Shrawan and period 12 is
#: Ashadh. Holding the names here rather than deriving them keeps the period
#: list readable to a Nepali accountant without a conversion library.
BS_MONTHS = [
    "Shrawan", "Bhadra", "Ashwin", "Kartik", "Mangsir", "Poush",
    "Magh", "Falgun", "Chaitra", "Baisakh", "Jestha", "Ashadh",
]

#: The chart a hospital starts with. Not a fixture, because an accountant
#: renumbers it on day two -- these are the accounts the rest of the system
#: needs to exist, keyed so that renumbering does not break any posting.
STARTER_CHART = [
    ("1000", "Assets", AccountType.ASSET, None, ""),
    ("1100", "Current assets", AccountType.ASSET, "1000", ""),
    ("1110", "Cash in hand", AccountType.ASSET, "1100", ControlAccountKey.CASH),
    ("1120", "Bank", AccountType.ASSET, "1100", ControlAccountKey.BANK),
    ("1130", "Accounts receivable", AccountType.ASSET, "1100",
     ControlAccountKey.RECEIVABLES),
    ("1140", "Inventory", AccountType.ASSET, "1100", ControlAccountKey.INVENTORY),
    ("1150", "VAT recoverable", AccountType.ASSET, "1100",
     ControlAccountKey.VAT_INPUT),
    ("1900", "Suspense", AccountType.ASSET, "1000", ControlAccountKey.SUSPENSE),

    ("2000", "Liabilities", AccountType.LIABILITY, None, ""),
    ("2100", "Current liabilities", AccountType.LIABILITY, "2000", ""),
    ("2110", "Accounts payable", AccountType.LIABILITY, "2100",
     ControlAccountKey.PAYABLES),
    ("2120", "VAT payable", AccountType.LIABILITY, "2100",
     ControlAccountKey.VAT_OUTPUT),
    ("2130", "Salaries payable", AccountType.LIABILITY, "2100",
     ControlAccountKey.SALARIES_PAYABLE),
    ("2140", "Tax deducted at source", AccountType.LIABILITY, "2100",
     ControlAccountKey.TDS_PAYABLE),
    ("2150", "Social security payable", AccountType.LIABILITY, "2100",
     ControlAccountKey.SSF_PAYABLE),
    ("2160", "Patient deposits held", AccountType.LIABILITY, "2100",
     ControlAccountKey.PATIENT_DEPOSITS),

    ("3000", "Equity", AccountType.EQUITY, None, ""),
    ("3100", "Retained earnings", AccountType.EQUITY, "3000", ""),

    ("4000", "Income", AccountType.INCOME, None, ""),
    ("4100", "Patient revenue", AccountType.INCOME, "4000",
     ControlAccountKey.PATIENT_REVENUE),
    ("4200", "Pharmacy revenue", AccountType.INCOME, "4000",
     ControlAccountKey.PHARMACY_REVENUE),
    ("4900", "Discounts allowed", AccountType.INCOME, "4000",
     ControlAccountKey.DISCOUNTS),

    ("5000", "Expenses", AccountType.EXPENSE, None, ""),
    ("5100", "Cost of goods sold", AccountType.EXPENSE, "5000",
     ControlAccountKey.COST_OF_GOODS),
    ("5200", "Salaries and wages", AccountType.EXPENSE, "5000",
     ControlAccountKey.SALARIES),
    ("5300", "Utilities", AccountType.EXPENSE, "5000", ""),
    ("5400", "Rent", AccountType.EXPENSE, "5000", ""),
    ("5500", "Repairs and maintenance", AccountType.EXPENSE, "5000", ""),
    ("5600", "Travel and transport", AccountType.EXPENSE, "5000", ""),
    ("5700", "Professional fees", AccountType.EXPENSE, "5000", ""),
    ("5800", "Bad debts written off", AccountType.EXPENSE, "5000",
     ControlAccountKey.WRITE_OFF),
    ("5900", "Rounding differences", AccountType.EXPENSE, "5000",
     ControlAccountKey.ROUNDING),
]


class FinanceError(DomainError):
    """The books will not accept that."""


class PeriodClosed(FinanceError):
    """Nothing may post into that month any more."""


def money(value) -> Decimal:
    """Two places, half-up. The single rounding rule for the whole module."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# The chart
# ---------------------------------------------------------------------------


@tenant_atomic_method
def build_chart(organization, actor=None) -> dict:
    """Create the starter chart, or leave an existing one alone.

    Idempotent: re-running adds only what is missing. A chart-building command
    that wipes and rebuilds would orphan every posting the first time somebody
    ran it on a live database.
    """
    require_module(organization, ModuleCode.FINANCE)

    created = 0
    for code, name, account_type, parent_code, key in STARTER_CHART:
        parent = Account.objects.filter(code=parent_code).first() if parent_code else None
        account, was_new = Account.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "parent": parent,
                "control_key": key or "",
                "is_control": key in (
                    ControlAccountKey.RECEIVABLES, ControlAccountKey.PAYABLES,
                ),
                "created_by_id": getattr(actor, "uuid", None),
            },
        )
        created += 1 if was_new else 0

    # A parent is not postable. Computed from the tree rather than declared,
    # so adding a child to a leaf reclassifies it automatically instead of
    # leaving an account that takes postings and also has children.
    parents = set(
        Account.objects.filter(parent__isnull=False)
        .values_list("parent_id", flat=True)
    )
    Account.objects.filter(id__in=parents).update(is_postable=False)
    Account.objects.exclude(id__in=parents).update(is_postable=True)

    return {
        "accounts": Account.objects.count(),
        "created": created,
        "postable": Account.objects.filter(is_postable=True).count(),
    }


def account_for(key: str) -> Account:
    """The account the rest of the system means by a control key.

    Fails loudly rather than posting to a suspense account. A missing mapping
    is a configuration error somebody must fix, and quietly absorbing it into
    suspense is how a hospital discovers six months of revenue in the wrong
    place.
    """
    account = Account.objects.filter(control_key=key, is_active=True).first()
    if account is None:
        raise FinanceError(
            f"No account is mapped to '{key}'. Set it on the chart of "
            "accounts before this can be posted.",
            detail={"control_key": key},
        )
    return account


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


@tenant_atomic_method
def open_year(on_date=None, actor=None) -> list:
    """Create the twelve periods of a fiscal year.

    Approximated as equal Gregorian months from the fiscal year's start, and
    named for the Bikram Sambat month they mostly cover. The seam is the same
    one `apps.billing.fiscal` documents: swap this for a real BS calendar and
    nothing above it changes.
    """
    on_date = on_date or timezone.localdate()
    year = fiscal_year_for(on_date)
    starts, ends = fiscal_year_bounds(on_date)

    periods = []
    cursor = starts
    for number in range(1, 13):
        if number == 12:
            finish = ends
        else:
            # Approximate month lengths: the BS months are 29-32 days and the
            # boundary only matters for reporting, not for numbering.
            finish = min(cursor + timedelta(days=30), ends)
        period, _ = AccountingPeriod.objects.get_or_create(
            fiscal_year=year,
            period_number=number,
            defaults={
                "name": BS_MONTHS[number - 1],
                "starts_on": cursor,
                "ends_on": finish,
                "created_by_id": getattr(actor, "uuid", None),
            },
        )
        periods.append(period)
        cursor = finish + timedelta(days=1)
        if cursor > ends:
            break
    return periods


def period_for(posting_date: date) -> AccountingPeriod:
    """The period a date belongs to."""
    period = AccountingPeriod.objects.filter(
        starts_on__lte=posting_date, ends_on__gte=posting_date,
    ).first()
    if period is None:
        raise FinanceError(
            f"No accounting period covers {posting_date}. Open the fiscal "
            "year first.",
            detail={"date": str(posting_date)},
        )
    return period


def resolve_posting_date(document_date: date) -> tuple[date, AccountingPeriod]:
    """Where a document actually lands.

    If its own month is open it posts there. If not, it posts on the first day
    of the earliest open period after it — a December invoice found in
    February posts in February and still says December.

    Refusing the late document instead would mean it is never recorded at all,
    and a ledger missing a real transaction is worse than one showing it late.
    """
    period = period_for(document_date)
    if period.accepts_postings:
        return document_date, period

    later = (
        AccountingPeriod.objects.filter(
            starts_on__gt=period.starts_on, status=PeriodStatus.OPEN,
        )
        .order_by("starts_on")
        .first()
    )
    if later is None:
        raise PeriodClosed(
            f"{period.name} {period.fiscal_year} is "
            f"{period.get_status_display().lower()} and no later period is "
            "open. Open the next period before posting.",
            detail={"period": period.name},
        )
    return max(later.starts_on, timezone.localdate()) if False else later.starts_on, later


@tenant_atomic_method
def close_period(
    period: AccountingPeriod, actor, status=PeriodStatus.SOFT_CLOSED,
    force: bool = False,
) -> AccountingPeriod:
    """Stop the month.

    Refuses while draft entries remain in it, because a draft in a closed
    period is an entry that can never be posted anywhere — its own month is
    shut and it has no other. The check is overridable, and overriding
    abandons those drafts explicitly rather than by accident.
    """
    drafts = period.entries.filter(status=JournalStatus.DRAFT).count()
    if drafts and not force:
        raise FinanceError(
            f"{drafts} draft journal{'s' if drafts != 1 else ''} still in "
            f"{period.name}. Post or discard them first — a draft in a closed "
            "period can never be posted.",
            detail={"drafts": drafts},
        )

    period.status = status
    period.closed_at = timezone.now()
    period.closed_by_name = getattr(actor, "full_name", "") or ""
    period.save(update_fields=[
        "status", "closed_at", "closed_by_name", "updated_at",
    ])
    record(
        AuditAction.UPDATE,
        entity_type="finance.AccountingPeriod",
        entity_id=period.uuid,
        entity_label=f"{period.name} {period.fiscal_year} {status}",
        reason=f"{drafts} drafts abandoned" if drafts else "",
    )
    return period


@tenant_atomic_method
def reopen_period(period: AccountingPeriod, actor, reason: str) -> AccountingPeriod:
    """Open a closed month again, loudly.

    Never available for a locked period. Reopening a month that has been
    reported is a decision with consequences outside this system, so it
    demands a reason and is written into the audit trail.
    """
    if period.status == PeriodStatus.LOCKED:
        raise FinanceError(
            f"{period.name} {period.fiscal_year} is locked. A locked period "
            "is closed for good; post a correcting entry in an open period "
            "instead."
        )
    if not reason.strip():
        raise FinanceError("Reopening a closed period must say why.")

    period.status = PeriodStatus.OPEN
    period.notes = f"{period.notes}\nReopened: {reason}".strip()
    period.save(update_fields=["status", "notes", "updated_at"])
    record(
        AuditAction.UPDATE,
        entity_type="finance.AccountingPeriod",
        entity_id=period.uuid,
        entity_label=f"{period.name} {period.fiscal_year} reopened",
        reason=reason,
    )
    return period


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def _next_reference(prefix: str = "JV") -> str:
    """A readable journal reference, unique per fiscal year.

    Derived from the count rather than a sequence table because a gap here is
    harmless — unlike an invoice number, a journal reference carries no
    statutory meaning and nobody audits its continuity.
    """
    year = fiscal_year_for()
    count = JournalEntry.objects.filter(
        reference__startswith=f"{prefix}-{year.replace('/', '')}"
    ).count()
    return f"{prefix}-{year.replace('/', '')}-{count + 1:06d}"


@tenant_atomic_method
def post_entry(
    lines: list,
    narration: str,
    actor,
    document_date=None,
    facility=None,
    source: str = JournalSource.MANUAL,
    source_reference: str = "",
    post: bool = True,
) -> JournalEntry:
    """Write a balanced entry.

    `lines` are dicts of `account` (an `Account` or a control key), `debit` or
    `credit`, and optionally `narration`, `party_type`, `party_reference`,
    `party_name` and `cost_centre`.

    Balancing is checked here so the error is a sentence rather than an
    IntegrityError — but the database constraint is what makes it true.
    """
    document_date = document_date or timezone.localdate()
    posting_date, period = resolve_posting_date(document_date)

    prepared = []
    total_debit = ZERO
    total_credit = ZERO

    for line in lines:
        account = line["account"]
        if isinstance(account, str):
            account = account_for(account)
        validate_postable(account)

        debit = money(line.get("debit", 0))
        credit = money(line.get("credit", 0))
        if debit and credit:
            raise FinanceError(
                f"A line cannot be both a debit and a credit ({account.code})."
            )
        if not debit and not credit:
            # Skipped rather than refused: a posting routine that computes a
            # zero tax line should not have to filter it out itself.
            continue

        total_debit += debit
        total_credit += credit
        prepared.append((account, debit, credit, line))

    if not prepared:
        raise FinanceError("An entry with no lines is not an entry.")
    if total_debit != total_credit:
        raise FinanceError(
            f"The entry does not balance: {total_debit} debited against "
            f"{total_credit} credited, a difference of "
            f"{abs(total_debit - total_credit)}.",
            detail={"debit": str(total_debit), "credit": str(total_credit)},
        )

    entry = JournalEntry.objects.create(
        reference=_next_reference(),
        document_date=document_date,
        posting_date=posting_date,
        period=period,
        facility=facility,
        narration=narration,
        source=source,
        source_reference=source_reference,
        total_debit=total_debit,
        total_credit=total_credit,
        status=JournalStatus.POSTED if post else JournalStatus.DRAFT,
        posted_at=timezone.now() if post else None,
        posted_by_id=getattr(actor, "uuid", None) if post else None,
        posted_by_name=(getattr(actor, "full_name", "") or "") if post else "",
        created_by_id=getattr(actor, "uuid", None),
    )
    JournalLine.objects.bulk_create([
        JournalLine(
            entry=entry,
            account=account,
            debit=debit,
            credit=credit,
            narration=line.get("narration", ""),
            party_type=line.get("party_type", ""),
            party_reference=line.get("party_reference", ""),
            party_name=line.get("party_name", ""),
            cost_centre=line.get("cost_centre", ""),
        )
        for account, debit, credit, line in prepared
    ])

    if posting_date != document_date:
        logger.info(
            "Journal %s dated %s posted into %s (%s was closed)",
            entry.reference, document_date, period.name, document_date,
        )
    return entry


def post_document(
    source: str,
    source_reference: str,
    lines: list,
    narration: str,
    actor,
    document_date=None,
    facility=None,
) -> tuple[JournalEntry, bool]:
    """Post an entry for a source document, exactly once.

    Returns the entry and whether it was created. Every automatic posting goes
    through here, so re-running a nightly job, retrying a webhook or
    double-clicking a button all produce one entry — enforced by the unique
    constraint on (source, source_reference) rather than by a lock or a flag.
    """
    existing = JournalEntry.objects.filter(
        source=source, source_reference=source_reference,
    ).first()
    if existing is not None:
        return existing, False

    entry = post_entry(
        lines, narration, actor,
        document_date=document_date, facility=facility,
        source=source, source_reference=source_reference,
    )
    return entry, True


@tenant_atomic_method
def post_opening_balances(
    balances: dict, actor, on_date=None, facility=None,
) -> tuple[JournalEntry, bool]:
    """The position the hospital was in on the day it started using this system.

    `balances` maps a control key or an `Account` to a signed amount in that
    account's own terms: 250000 of cash is an asset of 250000, and 80000 owed
    to suppliers is a liability of 80000.

    Whatever does not balance goes to retained earnings, which is exactly
    right — the difference between what a business owns and what it owes on
    the day the books open *is* its accumulated result. Forcing the operator
    to make it balance by hand instead produces a suspense entry nobody ever
    clears.

    Without this, a new ledger shows negative cash from the first refund,
    because the money that was in the drawer beforehand was never recorded.
    """
    on_date = on_date or timezone.localdate()

    lines = []
    net = ZERO
    for key, amount in balances.items():
        account = key if isinstance(key, Account) else account_for(key)
        amount = money(amount)
        if amount == 0:
            continue
        # A signed balance in the account's own terms becomes a debit or a
        # credit according to which side that account is normally on.
        if account.normal_balance == "debit":
            lines.append({"account": account, "debit": amount} if amount > 0
                         else {"account": account, "credit": -amount})
            net += amount
        else:
            lines.append({"account": account, "credit": amount} if amount > 0
                         else {"account": account, "debit": -amount})
            net -= amount

    retained = Account.objects.filter(code="3100").first()
    if retained is None:
        raise FinanceError("No retained earnings account (3100) in the chart.")
    if net > 0:
        lines.append({"account": retained, "credit": net})
    elif net < 0:
        lines.append({"account": retained, "debit": -net})

    return post_document(
        JournalSource.OPENING, f"OPENING-{on_date:%Y%m%d}", lines,
        f"Opening balances as at {on_date}", actor,
        document_date=on_date, facility=facility,
    )


@tenant_atomic_method
def reverse_entry(entry: JournalEntry, actor, reason: str, on_date=None) -> JournalEntry:
    """Undo an entry by posting its mirror image.

    The original is untouched. Its status becomes `reversed` and it points at
    the contra entry, so a reader sees both — which is the point. An edited or
    deleted journal leaves a report that once said something else and no way
    to find out what.
    """
    if entry.status == JournalStatus.DRAFT:
        raise FinanceError(
            "A draft has not been posted; discard it rather than reversing it."
        )
    if entry.status == JournalStatus.REVERSED:
        raise FinanceError(
            f"{entry.reference} was already reversed by "
            f"{entry.reversed_by.reference}."
        )
    if not reason.strip():
        raise FinanceError("A reversal must say why.")

    on_date = on_date or timezone.localdate()
    posting_date, period = resolve_posting_date(on_date)

    contra = JournalEntry.objects.create(
        reference=_next_reference("RV"),
        document_date=on_date,
        posting_date=posting_date,
        period=period,
        facility=entry.facility,
        narration=f"Reversal of {entry.reference}: {reason}",
        source=JournalSource.REVERSAL,
        source_reference=entry.reference,
        total_debit=entry.total_credit,
        total_credit=entry.total_debit,
        status=JournalStatus.POSTED,
        posted_at=timezone.now(),
        posted_by_id=getattr(actor, "uuid", None),
        posted_by_name=getattr(actor, "full_name", "") or "",
        reverses=entry,
        reversal_reason=reason,
        created_by_id=getattr(actor, "uuid", None),
    )
    JournalLine.objects.bulk_create([
        JournalLine(
            entry=contra,
            account=line.account,
            # Swapped. That is the whole of a reversal.
            debit=line.credit,
            credit=line.debit,
            narration=line.narration,
            party_type=line.party_type,
            party_reference=line.party_reference,
            party_name=line.party_name,
            cost_centre=line.cost_centre,
        )
        for line in entry.lines.all()
    ])

    entry.status = JournalStatus.REVERSED
    entry.reversal_reason = reason
    entry.save(update_fields=["status", "reversal_reason", "updated_at"])

    record(
        AuditAction.UPDATE,
        entity_type="finance.JournalEntry",
        entity_id=entry.uuid,
        entity_label=f"{entry.reference} reversed by {contra.reference}",
        reason=reason,
    )
    return contra


# ---------------------------------------------------------------------------
# Posting from the rest of the system
# ---------------------------------------------------------------------------


#: Invoice statuses that represent a document the books must know about.
#:
#: A draft has no number and no legal existence; a cancelled one was voided
#: before issue. Everything else happened -- including an invoice later
#: reversed by a credit note, whose revenue was recognised and must be
#: recognised again in reverse rather than never recorded at all.
POSTABLE_INVOICE_STATUSES = (
    InvoiceStatus.ISSUED,
    InvoiceStatus.PARTIALLY_PAID,
    InvoiceStatus.PAID,
    InvoiceStatus.CREDITED,
    InvoiceStatus.WRITTEN_OFF,
)


@tenant_atomic_method
def post_invoice(invoice: Invoice, actor) -> tuple[JournalEntry, bool]:
    """Revenue recognised, and a debt owed — or the reverse, for a credit note.

    Debit receivables for what is owed; credit revenue for the net; credit VAT
    for the tax, which is the government's money and never the hospital's;
    debit discounts allowed for what was given away. The discount is an
    expense of doing business, not a reduction in revenue, because a hospital
    that nets it off cannot answer "how much did we discount last year".

    A credit note is the same entry with every side swapped. Billing keeps it
    in the same table with a negative total and shares the numbering sequence,
    which is right; the ledger cannot store a negative debit, so the sign
    decides the direction and the amounts are posted positive.
    """
    if invoice.status == InvoiceStatus.DRAFT or not invoice.number:
        raise FinanceError(
            "That invoice is still a draft. Revenue is recognised when it is "
            "issued."
        )
    if invoice.status == InvoiceStatus.CANCELLED:
        raise FinanceError(
            f"{invoice.number} was cancelled before issue and never happened."
        )

    receivable = money(invoice.total)
    discount = money(invoice.discount_total)
    tax = money(invoice.tax_total)
    # Revenue is the gross before the discount, so that both figures are
    # visible in the accounts rather than one netted into the other.
    revenue = receivable + discount - tax
    is_credit = invoice.is_credit_note or receivable < 0

    party = {
        "party_type": "patient",
        "party_reference": invoice.number,
        "party_name": getattr(invoice.patient, "full_name", "") or "Walk-in",
    }
    if is_credit:
        lines = [
            {**party, "account": ControlAccountKey.RECEIVABLES,
             "credit": abs(receivable),
             "narration": f"Credit note {invoice.number}"},
            {"account": ControlAccountKey.DISCOUNTS, "credit": abs(discount)},
            {"account": ControlAccountKey.PATIENT_REVENUE, "debit": abs(revenue)},
            {"account": ControlAccountKey.VAT_OUTPUT, "debit": abs(tax)},
        ]
    else:
        lines = [
            {**party, "account": ControlAccountKey.RECEIVABLES,
             "debit": receivable,
             "narration": f"Invoice {invoice.number}"},
            {"account": ControlAccountKey.DISCOUNTS, "debit": discount},
            {"account": ControlAccountKey.PATIENT_REVENUE, "credit": revenue},
            {"account": ControlAccountKey.VAT_OUTPUT, "credit": tax},
        ]

    return post_document(
        JournalSource.CREDIT_NOTE if is_credit else JournalSource.INVOICE,
        invoice.number, lines,
        f"{'Credit note' if is_credit else 'Invoice'} {invoice.number}", actor,
        document_date=invoice.issued_at.date() if invoice.issued_at else None,
        facility=invoice.facility,
    )


@tenant_atomic_method
def post_payment(payment: Payment, actor) -> tuple[JournalEntry, bool]:
    """Cash in, debt down — or the reverse, when it is a refund.

    Billing records a refund as a payment with a negative amount, sharing the
    receipt sequence with the payment it reverses. That is right for billing
    and wrong for the ledger: a journal line is a debit or a credit, never a
    negative debit. So the sign decides the direction and the amount is always
    posted positive.

    The database caught this the first time the seed ran, which is the
    argument for the `journal_line_is_one_sided` constraint. A negative debit
    sums correctly in every report and is indefensible in every audit, so it
    would have survived for years.

    Which asset account moves depends on how they paid: cash to the drawer,
    everything else to the bank. Wallets and cards settle a day or two later,
    and treating them as cash means the drawer never reconciles.
    """
    destination = (
        ControlAccountKey.CASH if payment.method == "cash"
        else ControlAccountKey.BANK
    )
    signed = money(payment.amount)
    amount = abs(signed)
    is_refund = signed < 0
    invoice_number = getattr(payment.invoice, "number", "") or ""
    party = getattr(payment.patient, "full_name", "") or ""

    cash_line = {
        "account": destination,
        "narration": f"{payment.get_method_display()} {payment.receipt_number}",
    }
    receivable_line = {
        "account": ControlAccountKey.RECEIVABLES,
        "party_type": "patient",
        "party_reference": invoice_number,
        "party_name": party,
        "narration": (
            f"Refund against {invoice_number}" if is_refund
            else f"Payment against {invoice_number}"
        ),
    }
    if is_refund:
        cash_line["credit"] = amount
        receivable_line["debit"] = amount
    else:
        cash_line["debit"] = amount
        receivable_line["credit"] = amount

    return post_document(
        JournalSource.REFUND if is_refund else JournalSource.PAYMENT,
        payment.receipt_number,
        [cash_line, receivable_line],
        f"{'Refund' if is_refund else 'Payment'} {payment.receipt_number}",
        actor,
        document_date=payment.received_at.date() if payment.received_at else None,
        facility=payment.facility,
    )


@tenant_atomic_method
def post_supplier_invoice(
    invoice: SupplierInvoice, actor,
) -> tuple[JournalEntry, bool]:
    """What was bought, and what is owed for it.

    Goods go to inventory rather than straight to expense: the cost belongs to
    the period the stock is sold in, not the period it arrived in, and a
    hospital that expenses purchases on receipt shows a loss every time it
    restocks.
    """
    if invoice.status == SupplierInvoiceStatus.DRAFT:
        raise FinanceError(
            f"{invoice.reference} has not been approved for payment."
        )

    lines = [
        {
            "account": ControlAccountKey.INVENTORY,
            "debit": money(invoice.subtotal),
        },
        {"account": ControlAccountKey.VAT_INPUT, "debit": money(invoice.tax_amount)},
        {
            "account": ControlAccountKey.PAYABLES,
            "credit": money(invoice.total),
            "party_type": "supplier",
            "party_reference": invoice.reference,
            "party_name": invoice.supplier_name,
        },
    ]
    return post_document(
        JournalSource.SUPPLIER_INVOICE, invoice.reference, lines,
        f"{invoice.supplier_name} {invoice.supplier_invoice_number}", actor,
        document_date=invoice.invoice_date, facility=invoice.facility,
    )


@tenant_atomic_method
def post_expense(expense: Expense, actor) -> tuple[JournalEntry, bool]:
    """A cost, and the cash or bank it came out of."""
    if expense.status not in (ExpenseStatus.APPROVED, ExpenseStatus.PAID):
        raise FinanceError(
            f"{expense.reference} has not been approved."
        )

    total = money(expense.amount) + money(expense.tax_amount)
    source_account = (
        ControlAccountKey.CASH if expense.payment_method == "cash"
        else ControlAccountKey.BANK
    )
    lines = [
        {
            "account": expense.account,
            "debit": money(expense.amount),
            "cost_centre": expense.cost_centre,
            "narration": expense.description,
        },
        {"account": ControlAccountKey.VAT_INPUT, "debit": money(expense.tax_amount)},
        {"account": source_account, "credit": total},
    ]
    return post_document(
        JournalSource.EXPENSE, expense.reference, lines,
        expense.description[:200], actor,
        document_date=expense.spent_on, facility=expense.facility,
    )


@tenant_atomic_method
def post_payroll(run, actor, statutory: dict) -> tuple[JournalEntry, bool]:
    """Gross pay as a cost; net pay and every deduction as liabilities.

    Tax and social security withheld are not the hospital's money and never
    were. Crediting them to salaries payable along with the net would mean the
    bank balance looks large enough to pay everybody, right up to the day the
    tax is remitted.
    """
    gross = money(statutory.get("gross", 0))
    net = money(statutory.get("net", 0))
    tds = money(statutory.get("tds", 0))
    ssf = money(statutory.get("ssf", 0))
    other = gross - net - tds - ssf

    lines = [
        {"account": ControlAccountKey.SALARIES, "debit": gross},
        {"account": ControlAccountKey.SALARIES_PAYABLE, "credit": net},
        {"account": ControlAccountKey.TDS_PAYABLE, "credit": tds},
        {"account": ControlAccountKey.SSF_PAYABLE, "credit": ssf},
        # Anything left is a deduction the payroll knows about and the ledger
        # does not yet have an account for. It goes to suspense visibly rather
        # than being absorbed into net pay, where nobody would ever find it.
        {"account": ControlAccountKey.SUSPENSE, "credit": other},
    ]
    return post_document(
        JournalSource.PAYROLL, run.reference, lines,
        f"Payroll {run.reference}", actor,
        document_date=getattr(run, "period_end", None),
        facility=getattr(run, "facility", None),
    )


# ---------------------------------------------------------------------------
# Reading the books
# ---------------------------------------------------------------------------


def _posted_lines(until=None, since=None, facility=None):
    """Every line that counts. Draft entries do not; reversals do.

    A reversal is a real movement — it is how the correction reaches the
    accounts — so both the original and its contra are included and cancel
    out. Excluding reversed entries instead would make the totals right and
    the transaction history a lie.
    """
    rows = JournalLine.objects.filter(
        entry__status__in=(JournalStatus.POSTED, JournalStatus.REVERSED),
    )
    if since:
        rows = rows.filter(entry__posting_date__gte=since)
    if until:
        rows = rows.filter(entry__posting_date__lte=until)
    if facility:
        rows = rows.filter(entry__facility=facility)
    return rows


def trial_balance(until=None, facility=None) -> dict:
    """Every account's debits and credits, and the proof they agree.

    The totals must be equal. They are computed from the lines rather than
    from the entry headers, so this is a genuine check on the data and not a
    restatement of the constraint that produced it.
    """
    until = until or timezone.localdate()
    totals = (
        _posted_lines(until=until, facility=facility)
        .values("account__code", "account__name", "account__account_type")
        .annotate(debit=models.Sum("debit"), credit=models.Sum("credit"))
        .order_by("account__code")
    )

    rows = []
    total_debit = ZERO
    total_credit = ZERO
    for row in totals:
        debit = money(row["debit"])
        credit = money(row["credit"])
        total_debit += debit
        total_credit += credit
        account_type = row["account__account_type"]
        balance = (
            debit - credit
            if NORMAL_BALANCE[AccountType(account_type)] == "debit"
            else credit - debit
        )
        rows.append({
            "code": row["account__code"],
            "name": row["account__name"],
            "type": account_type,
            "debit": debit,
            "credit": credit,
            "balance": balance,
        })

    return {
        "as_at": until,
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "difference": total_debit - total_credit,
        "balances": total_debit == total_credit,
    }


def account_ledger(account: Account, since=None, until=None) -> dict:
    """One account's movements in order, with a running balance."""
    until = until or timezone.localdate()
    lines = (
        _posted_lines(since=since, until=until)
        .filter(account=account)
        .select_related("entry")
        .order_by("entry__posting_date", "entry__reference", "id")
    )

    opening = ZERO
    if since:
        before = (
            _posted_lines(until=since - timedelta(days=1))
            .filter(account=account)
            .aggregate(d=models.Sum("debit"), c=models.Sum("credit"))
        )
        opening = account.signed(money(before["d"]), money(before["c"]))

    running = opening
    rows = []
    for line in lines:
        running += account.signed(line.debit, line.credit)
        rows.append({
            "date": line.entry.posting_date,
            "reference": line.entry.reference,
            "narration": line.narration or line.entry.narration,
            "source": line.entry.source,
            "party": line.party_name,
            "debit": line.debit,
            "credit": line.credit,
            "balance": running,
        })

    return {
        "account": f"{account.code} {account.name}",
        "opening": opening,
        "closing": running,
        "rows": rows,
    }


def profit_and_loss(since=None, until=None, facility=None) -> dict:
    """Income against expenses for a window.

    Income and expenses only; the balance sheet accounts are a different
    report. Reported by account so a line can be traced, and the surplus is
    computed rather than stored.
    """
    until = until or timezone.localdate()
    since = since or fiscal_year_bounds(until)[0]

    rows = (
        _posted_lines(since=since, until=until, facility=facility)
        .filter(account__account_type__in=(AccountType.INCOME, AccountType.EXPENSE))
        .values("account__code", "account__name", "account__account_type")
        .annotate(debit=models.Sum("debit"), credit=models.Sum("credit"))
        .order_by("account__code")
    )

    income = []
    expense = []
    total_income = ZERO
    total_expense = ZERO
    for row in rows:
        debit = money(row["debit"])
        credit = money(row["credit"])
        entry = {
            "code": row["account__code"],
            "name": row["account__name"],
        }
        if row["account__account_type"] == AccountType.INCOME:
            entry["amount"] = credit - debit
            total_income += entry["amount"]
            income.append(entry)
        else:
            entry["amount"] = debit - credit
            total_expense += entry["amount"]
            expense.append(entry)

    return {
        "from": since,
        "to": until,
        "income": income,
        "expenses": expense,
        "total_income": total_income,
        "total_expense": total_expense,
        "surplus": total_income - total_expense,
    }


def balance_sheet(until=None) -> dict:
    """Assets against liabilities and equity, with the current surplus.

    The surplus for the year is added to equity rather than being posted
    there, because posting it would mean closing the year — and a balance
    sheet is something a manager wants in Poush, not only in Ashadh.
    """
    until = until or timezone.localdate()
    rows = (
        _posted_lines(until=until)
        .values("account__code", "account__name", "account__account_type")
        .annotate(debit=models.Sum("debit"), credit=models.Sum("credit"))
        .order_by("account__code")
    )

    sides = {AccountType.ASSET: [], AccountType.LIABILITY: [], AccountType.EQUITY: []}
    totals = {AccountType.ASSET: ZERO, AccountType.LIABILITY: ZERO,
              AccountType.EQUITY: ZERO}

    for row in rows:
        account_type = row["account__account_type"]
        if account_type not in sides:
            continue
        debit = money(row["debit"])
        credit = money(row["credit"])
        amount = (
            debit - credit
            if NORMAL_BALANCE[AccountType(account_type)] == "debit"
            else credit - debit
        )
        sides[account_type].append({
            "code": row["account__code"],
            "name": row["account__name"],
            "amount": amount,
        })
        totals[account_type] += amount

    # Two surpluses, and using the wrong one is how a balance sheet stops
    # balancing. `accumulated` is every income and expense ever posted; that
    # is what equity actually owns, because this system does not post
    # year-end closing entries into retained earnings. `this_year` is the
    # figure a manager wants beside it. The first run of this report used the
    # fiscal-year surplus for both and was out by exactly the prior year's
    # result -- which was a single late water bill.
    accumulated = profit_and_loss(since=date(1900, 1, 1), until=until)["surplus"]
    this_year = profit_and_loss(until=until)["surplus"]
    equity_total = totals[AccountType.EQUITY] + accumulated
    left = totals[AccountType.ASSET]
    right = totals[AccountType.LIABILITY] + equity_total

    return {
        "as_at": until,
        "assets": sides[AccountType.ASSET],
        "liabilities": sides[AccountType.LIABILITY],
        "equity": sides[AccountType.EQUITY],
        "total_assets": left,
        "total_liabilities": totals[AccountType.LIABILITY],
        "total_equity": equity_total,
        "surplus_for_the_period": this_year,
        "accumulated_surplus": accumulated,
        "difference": left - right,
        "balances": left == right,
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


#: Ageing buckets, in days. Data rather than a chain of comparisons so a
#: hospital whose terms are 45 days can change them without touching code.
AGEING_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, 180), (181, None)]


def receivables_ageing(until=None) -> dict:
    """What is owed, by how long it has been owed.

    Computed from the invoices, not from the ledger. That is deliberate: this
    figure and the receivables control account are then two independent
    records, and `reconcile_receivables` compares them. Deriving one from the
    other would make the comparison meaningless and it is the comparison that
    catches the errors.
    """
    until = until or timezone.localdate()
    invoices = Invoice.objects.filter(
        status__in=POSTABLE_INVOICE_STATUSES, issued_at__date__lte=until,
    ).select_related("patient")

    buckets = {f"{low}-{high or 'plus'}": ZERO for low, high in AGEING_BUCKETS}
    rows = []
    total = ZERO

    for invoice in invoices:
        outstanding = money(invoice.total) - money(invoice.amount_paid)
        # Zero is settled. Negative is a credit note or an overpayment, and it
        # stays in: it is money the hospital owes back, and dropping it makes
        # the subledger disagree with the control account by exactly that
        # amount -- which is how a receivables balance silently goes wrong.
        if outstanding == 0:
            continue
        days = (until - invoice.issued_at.date()).days
        for low, high in AGEING_BUCKETS:
            if days >= low and (high is None or days <= high):
                buckets[f"{low}-{high or 'plus'}"] += outstanding
                break
        total += outstanding
        rows.append({
            "invoice": invoice.number,
            "patient": getattr(invoice.patient, "full_name", "") or "Walk-in",
            "issued": invoice.issued_at.date(),
            "days": days,
            "total": money(invoice.total),
            "paid": money(invoice.amount_paid),
            "outstanding": outstanding,
        })

    rows.sort(key=lambda row: -row["days"])
    return {
        "as_at": until,
        "buckets": buckets,
        "total": total,
        "invoices": rows,
        "over_90": sum(
            value for key, value in buckets.items()
            if key in ("91-180", "181-plus")
        ),
    }


def payables_ageing(until=None) -> dict:
    """What is owed to suppliers, by how overdue it is."""
    until = until or timezone.localdate()
    invoices = SupplierInvoice.objects.filter(
        status__in=(
            SupplierInvoiceStatus.APPROVED, SupplierInvoiceStatus.PART_PAID,
            SupplierInvoiceStatus.DISPUTED,
        ),
        invoice_date__lte=until,
    )

    buckets = {f"{low}-{high or 'plus'}": ZERO for low, high in AGEING_BUCKETS}
    rows = []
    total = ZERO

    for invoice in invoices:
        outstanding = invoice.outstanding
        if outstanding <= 0:
            continue
        days = (until - invoice.due_date).days
        bucket_days = max(0, days)
        for low, high in AGEING_BUCKETS:
            if bucket_days >= low and (high is None or bucket_days <= high):
                buckets[f"{low}-{high or 'plus'}"] += outstanding
                break
        total += outstanding
        rows.append({
            "invoice": invoice.reference,
            "supplier": invoice.supplier_name,
            "supplier_number": invoice.supplier_invoice_number,
            "due": invoice.due_date,
            "days_overdue": days,
            "outstanding": outstanding,
            "disputed": invoice.status == SupplierInvoiceStatus.DISPUTED,
        })

    rows.sort(key=lambda row: -row["days_overdue"])
    return {
        "as_at": until,
        "buckets": buckets,
        "total": total,
        "invoices": rows,
        "overdue": sum(row["outstanding"] for row in rows if row["days_overdue"] > 0),
    }


def reconcile_receivables(until=None) -> dict:
    """Do the invoices and the ledger agree?

    Two independent records: the sum of unpaid invoices, and the balance on
    the receivables control account. In most hospital systems these drift
    apart over years and nobody notices, because nothing ever asks. Here the
    difference is a number, and when it is not zero the report says which
    invoices have no journal entry — which is almost always the answer.
    """
    until = until or timezone.localdate()
    subledger = receivables_ageing(until)["total"]

    control = account_for(ControlAccountKey.RECEIVABLES)
    totals = (
        _posted_lines(until=until)
        .filter(account=control)
        .aggregate(d=models.Sum("debit"), c=models.Sum("credit"))
    )
    ledger = control.signed(money(totals["d"]), money(totals["c"]))

    # Which invoices never made it into the books. Cheap to compute and it is
    # the explanation nine times in ten.
    posted = set(
        JournalEntry.objects.filter(
            source__in=(JournalSource.INVOICE, JournalSource.CREDIT_NOTE)
        ).values_list("source_reference", flat=True)
    )
    unposted = [
        invoice.number
        for invoice in Invoice.objects.filter(
            status__in=POSTABLE_INVOICE_STATUSES, issued_at__date__lte=until,
        )
        if invoice.number and invoice.number not in posted
    ]

    return {
        "as_at": until,
        "subledger": subledger,
        "ledger": ledger,
        "difference": subledger - ledger,
        "agrees": subledger == ledger,
        "invoices_not_posted": unposted[:50],
        "invoices_not_posted_count": len(unposted),
    }


@tenant_atomic_method
def match_statement_line(
    line: StatementLine, journal_line: JournalLine, actor,
) -> StatementLine:
    """Tie a bank statement line to the ledger line that should be it.

    Refuses when the amounts differ. A tolerance here would be a kindness that
    hides exactly the errors reconciliation exists to find — a transposed
    figure is a small difference and a real problem.
    """
    if line.is_matched:
        raise FinanceError("That statement line is already matched.")

    ledger_amount = journal_line.debit - journal_line.credit
    if abs(ledger_amount) != abs(line.amount):
        raise FinanceError(
            f"The statement says {abs(line.amount)} and the ledger line is "
            f"{abs(ledger_amount)}. They are not the same transaction.",
            detail={
                "statement": str(line.amount),
                "ledger": str(ledger_amount),
            },
        )

    line.matched_line = journal_line
    line.matched_at = timezone.now()
    line.matched_by_name = getattr(actor, "full_name", "") or ""
    line.save(update_fields=[
        "matched_line", "matched_at", "matched_by_name", "updated_at",
    ])
    return line


def reconciliation(bank_account: BankAccount, since=None, until=None) -> dict:
    """What the bank has that the books do not, and the reverse.

    Both directions, because they mean different things. A statement line with
    no ledger entry is usually a charge or a direct credit nobody knew about.
    A ledger line with no statement line is usually a cheque that has not
    cleared — or a payment that was recorded and never actually made.
    """
    until = until or timezone.localdate()
    since = since or (until - timedelta(days=30))

    statement = bank_account.statement_lines.filter(
        transaction_date__gte=since, transaction_date__lte=until,
    )
    ledger_lines = (
        _posted_lines(since=since, until=until)
        .filter(account=bank_account.account)
        .select_related("entry")
    )

    matched_ids = set(
        statement.exclude(matched_line__isnull=True)
        .values_list("matched_line_id", flat=True)
    )

    unmatched_statement = [
        {
            "uuid": str(row.uuid),
            "date": row.transaction_date,
            "description": row.description,
            "reference": row.reference,
            "amount": row.amount,
        }
        for row in statement if not row.is_matched
    ]
    unmatched_ledger = [
        {
            "uuid": str(row.uuid),
            "date": row.entry.posting_date,
            "reference": row.entry.reference,
            "narration": row.narration or row.entry.narration,
            "amount": row.debit - row.credit,
        }
        for row in ledger_lines if row.id not in matched_ids
    ]

    statement_total = sum((row.amount for row in statement), ZERO)
    ledger_total = sum(
        (row.debit - row.credit for row in ledger_lines), ZERO
    )

    return {
        "bank_account": str(bank_account),
        "from": since,
        "to": until,
        "statement_lines": statement.count(),
        "statement_total": money(statement_total),
        "ledger_total": money(ledger_total),
        "difference": money(statement_total - ledger_total),
        "unmatched_on_the_statement": unmatched_statement,
        "unmatched_in_the_ledger": unmatched_ledger,
        "matched": len(matched_ids),
    }


def vat_return(since=None, until=None) -> dict:
    """Output tax against input tax for a period.

    The two are kept in separate accounts rather than netted, because the
    return itself asks for both figures and a single net number cannot be
    split back apart.
    """
    until = until or timezone.localdate()
    since = since or fiscal_year_bounds(until)[0]

    def total(key):
        account = account_for(key)
        row = (
            _posted_lines(since=since, until=until)
            .filter(account=account)
            .aggregate(d=models.Sum("debit"), c=models.Sum("credit"))
        )
        return account.signed(money(row["d"]), money(row["c"]))

    output = total(ControlAccountKey.VAT_OUTPUT)
    recoverable = total(ControlAccountKey.VAT_INPUT)

    return {
        "from": since,
        "to": until,
        "output_tax": output,
        "input_tax": recoverable,
        "payable": output - recoverable,
    }
