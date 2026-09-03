"""The general ledger: the one place in the system where the books must balance.

Everything above this module records what happened to a patient, a drug or an
employee. This module records what happened to the money, and it has a
property none of the others do: it is checkable. A patient record can be
incomplete and still useful. A ledger that does not balance is not a partial
ledger, it is a wrong one.

Five rules, and each is enforced rather than intended.

**Every journal balances, or it does not exist.** `total_debit` and
`total_credit` live on the header and a database constraint requires them
equal. Balancing in the service layer alone means the first bulk import, data
migration or admin action writes an unbalanced entry, and from that moment
every report is wrong by an amount nobody can find.

**A posted journal is never edited or deleted.** It is reversed by a contra
journal that names it. The same rule as the stock ledger, the leave ledger and
the ICU fluid chart, and for the same reason: an edited history cannot be
audited, and the correction is itself a fact worth seeing.

**What happened and when it was recorded are two dates.** `document_date` is
when the transaction occurred; `posting_date` is the day it hit the books. A
December invoice found in February posts in February and still says it is a
December invoice. Systems that keep one date either refuse the late invoice or
silently reopen a closed month, and both are worse.

**A journal names the document that caused it, uniquely.** `source_type` plus
`source_reference` is a unique constraint, so posting the same invoice twice
is impossible — idempotency by the database, not by hoping a job runs once.

**Subledgers must reconcile to their control accounts, and the system proves
it rather than asserting it.** The receivables control account balance and the
sum of unpaid invoices are computed independently and compared. In most
systems these drift silently for years; here the difference is a number on a
screen.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# BaseModel: UUID, timestamps and soft delete. Published identifiers are UUIDs
# throughout — with a database per tenant, `id` 42 is a different row in every
# customer's database.
from apps.common.models import BaseModel
from apps.organization.models import Facility

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# The chart of accounts
# ---------------------------------------------------------------------------


class AccountType(models.TextChoices):
    """The five kinds of account, which decide what a debit means.

    Held as data rather than as knowledge in somebody's head: a debit
    increases an asset and decreases a liability, and a system that hard-codes
    that in each posting function gets it backwards exactly once.
    """

    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    EQUITY = "equity", "Equity"
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"


#: Which side increases each type of account.
#:
#: Assets and expenses are debit-normal; liabilities, equity and income are
#: credit-normal. This single mapping is why no posting function anywhere
#: needs to remember the convention.
NORMAL_BALANCE = {
    AccountType.ASSET: "debit",
    AccountType.EXPENSE: "debit",
    AccountType.LIABILITY: "credit",
    AccountType.EQUITY: "credit",
    AccountType.INCOME: "credit",
}


class ControlAccountKey(models.TextChoices):
    """Accounts the rest of the system posts into by name, not by number.

    A hospital's accountant renumbers the chart; the billing module must not
    care. Every automatic posting looks up its account by one of these keys,
    so re-pointing "where does patient revenue go" is one row in the database
    rather than a deployment.
    """

    RECEIVABLES = "receivables", "Accounts receivable (control)"
    PAYABLES = "payables", "Accounts payable (control)"
    CASH = "cash", "Cash in hand"
    BANK = "bank", "Bank"
    PATIENT_REVENUE = "patient_revenue", "Patient revenue"
    PHARMACY_REVENUE = "pharmacy_revenue", "Pharmacy revenue"
    DISCOUNTS = "discounts", "Discounts allowed"
    VAT_OUTPUT = "vat_output", "VAT payable"
    VAT_INPUT = "vat_input", "VAT recoverable"
    INVENTORY = "inventory", "Inventory"
    COST_OF_GOODS = "cost_of_goods", "Cost of goods sold"
    SALARIES = "salaries", "Salaries and wages"
    SALARIES_PAYABLE = "salaries_payable", "Salaries payable"
    TDS_PAYABLE = "tds_payable", "Tax deducted at source"
    SSF_PAYABLE = "ssf_payable", "Social security payable"
    PATIENT_DEPOSITS = "patient_deposits", "Patient deposits held"
    WRITE_OFF = "write_off", "Bad debts written off"
    ROUNDING = "rounding", "Rounding differences"
    SUSPENSE = "suspense", "Suspense"


class Account(BaseModel):
    """One line of the chart of accounts.

    A tree: `parent` gives the grouping an accountant reads, while postings
    only ever hit leaves. Posting to a parent would make the parent's own
    balance ambiguous — is it the total of its children, or the total plus
    what was posted directly?
    """

    code = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    account_type = models.CharField(max_length=12, choices=AccountType.choices)

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="children",
    )
    #: Only leaves take postings. Computed on save from whether the account
    #: has children, so it cannot disagree with the tree.
    is_postable = models.BooleanField(default=True)

    #: What the rest of the system calls this account, if anything. Nullable
    #: and unique, so exactly one account can be "the receivables control".
    control_key = models.CharField(
        max_length=32, choices=ControlAccountKey.choices,
        blank=True, db_index=True,
    )

    #: A control account is reconciled against a subledger. Marking it stops
    #: anybody posting a manual journal into it by hand, which is how the
    #: receivables balance stops matching the invoices.
    is_control = models.BooleanField(
        default=False,
        help_text="Reconciled against a subledger; no manual postings.",
    )

    #: Which facility's books, when a hospital keeps them separately. Null
    #: means shared across the organization.
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.CASCADE,
        related_name="accounts",
    )

    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["code"]
        indexes = [models.Index(fields=["account_type", "code"])]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uniq_account_code"),
            #: One account per control key. Two "cash" accounts and every
            #: automatic posting becomes a coin toss.
            models.UniqueConstraint(
                fields=["control_key"],
                condition=~models.Q(control_key=""),
                name="uniq_control_key",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def normal_balance(self) -> str:
        return NORMAL_BALANCE[AccountType(self.account_type)]

    def signed(self, debit: Decimal, credit: Decimal) -> Decimal:
        """Turn a debit and a credit into a balance in this account's terms.

        An asset with 100 debited and 30 credited has a balance of 70. A
        liability with the same movements has a balance of -70. Returning the
        signed figure here means no report has to remember which is which.
        """
        return (
            debit - credit if self.normal_balance == "debit" else credit - debit
        )


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


class PeriodStatus(models.TextChoices):
    OPEN = "open", "Open"
    #: Day-to-day posting stopped, corrections by an accountant still allowed.
    SOFT_CLOSED = "soft_closed", "Soft closed"
    LOCKED = "locked", "Locked"


class AccountingPeriod(BaseModel):
    """One month of the books, and whether anything may still post into it.

    Periods exist so that a report run today gives the same answer next week.
    Without them, a late journal silently changes a month that has already
    been reported to a bank or a board, and nobody finds out.
    """

    fiscal_year = models.CharField(max_length=16, db_index=True)
    #: 1-12 within the Nepali fiscal year: 1 is Shrawan.
    period_number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=64)
    starts_on = models.DateField()
    ends_on = models.DateField()

    status = models.CharField(
        max_length=12, choices=PeriodStatus.choices, default=PeriodStatus.OPEN,
        db_index=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by_name = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["starts_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "period_number"],
                name="uniq_period_per_year",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="period_ends_after_it_starts",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.fiscal_year})"

    @property
    def accepts_postings(self) -> bool:
        return self.status == PeriodStatus.OPEN


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------


class JournalStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    POSTED = "posted", "Posted"
    #: Reversed by a contra entry. The original stays exactly as it was.
    REVERSED = "reversed", "Reversed"


class JournalSource(models.TextChoices):
    """What caused the entry.

    Enumerated because the reconciliation reports are per source: "does the
    receivables account agree with the invoices" is a question about journals
    whose source is `invoice`.
    """

    MANUAL = "manual", "Manual journal"
    INVOICE = "invoice", "Patient or retail invoice"
    CREDIT_NOTE = "credit_note", "Credit note"
    PAYMENT = "payment", "Payment received"
    REFUND = "refund", "Refund"
    DEPOSIT = "deposit", "Patient deposit"
    GOODS_RECEIPT = "goods_receipt", "Goods receipt"
    SUPPLIER_INVOICE = "supplier_invoice", "Supplier invoice"
    SUPPLIER_PAYMENT = "supplier_payment", "Payment to a supplier"
    PAYROLL = "payroll", "Payroll run"
    STOCK = "stock", "Stock movement"
    EXPENSE = "expense", "Expense claim"
    DEPRECIATION = "depreciation", "Depreciation"
    OPENING = "opening", "Opening balance"
    REVERSAL = "reversal", "Reversal of another entry"


class JournalEntry(BaseModel):
    """One balanced transaction in the books.

    The header carries the totals so that "balances" is a database constraint
    rather than a promise. Checking it by summing the lines would mean the
    invariant only holds when somebody remembers to check.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    #: When the transaction happened.
    document_date = models.DateField(db_index=True)
    #: When it hit the books. Different when a document arrives late, and the
    #: difference is exactly what a period close is for.
    posting_date = models.DateField(db_index=True)
    period = models.ForeignKey(
        AccountingPeriod, on_delete=models.PROTECT, related_name="entries",
    )
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="journal_entries",
    )

    narration = models.CharField(max_length=512)
    source = models.CharField(
        max_length=20, choices=JournalSource.choices,
        default=JournalSource.MANUAL, db_index=True,
    )
    #: The document this entry accounts for: an invoice number, a payment
    #: reference, a payroll run. Unique with `source`, so the same document
    #: cannot be posted twice however many times the job runs.
    source_reference = models.CharField(max_length=64, blank=True, db_index=True)

    status = models.CharField(
        max_length=12, choices=JournalStatus.choices,
        default=JournalStatus.DRAFT, db_index=True,
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by_id = models.UUIDField(null=True, blank=True)
    posted_by_name = models.CharField(max_length=255, blank=True)

    total_debit = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    total_credit = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)

    #: The entry that reversed this one, and the entry this one reverses.
    #: Both directions, because a reversal must be findable from either end.
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="reversed_by",
    )
    reversal_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-posting_date", "-reference"]
        indexes = [
            models.Index(fields=["source", "source_reference"]),
            models.Index(fields=["period", "status"]),
        ]
        constraints = [
            #: The whole module in one line. An entry whose debits and credits
            #: differ cannot be stored, by anybody, through any code path.
            models.CheckConstraint(
                condition=models.Q(total_debit=models.F("total_credit")),
                name="journal_entry_balances",
            ),
            #: One entry per source document. Idempotency enforced rather
            #: than hoped for.
            models.UniqueConstraint(
                fields=["source", "source_reference"],
                condition=~models.Q(source_reference=""),
                name="uniq_journal_per_source_document",
            ),
        ]

    def __str__(self):
        return f"{self.reference} {self.narration[:40]}"

    @property
    def is_posted(self) -> bool:
        return self.status in (JournalStatus.POSTED, JournalStatus.REVERSED)


class JournalLine(BaseModel):
    """One side of one account's movement within an entry.

    Debit and credit are separate columns rather than a signed amount. A
    signed amount looks simpler until somebody has to answer "what was the
    total debited to cash in Poush", which is not the same question as "what
    was cash's net movement".
    """

    entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="lines",
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="lines",
    )
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    narration = models.CharField(max_length=512, blank=True)

    #: What this line is about, for the subledger. A receivables line carries
    #: the invoice number; a payables line carries the supplier. Without it,
    #: an ageing report has to guess.
    party_type = models.CharField(max_length=24, blank=True)
    party_reference = models.CharField(max_length=64, blank=True, db_index=True)
    party_name = models.CharField(max_length=255, blank=True)

    #: Cost centre, so a department's expenses can be read without a separate
    #: chart of accounts per department.
    cost_centre = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["account", "entry"]),
            models.Index(fields=["party_type", "party_reference"]),
        ]
        constraints = [
            #: A line is a debit or a credit, never both and never neither.
            #: Both is meaningless; neither is a line somebody meant to fill
            #: in and did not, which then silently balances.
            models.CheckConstraint(
                condition=(
                    models.Q(debit__gt=0, credit=0)
                    | models.Q(credit__gt=0, debit=0)
                ),
                name="journal_line_is_one_sided",
            ),
        ]

    def __str__(self):
        side = f"Dr {self.debit}" if self.debit else f"Cr {self.credit}"
        return f"{self.account_id} {side}"


# ---------------------------------------------------------------------------
# Cash and bank
# ---------------------------------------------------------------------------


class BankAccount(BaseModel):
    """A real account at a real bank, mapped to a ledger account.

    Separate from `Account` because a bank account has facts the ledger does
    not care about — a number, a branch, a statement — and because the
    reconciliation is between the two.
    """

    name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    branch = models.CharField(max_length=255, blank=True)
    account_number = models.CharField(max_length=64)
    account = models.OneToOneField(
        Account, on_delete=models.PROTECT, related_name="bank_account",
    )
    facility = models.ForeignKey(
        Facility, null=True, blank=True, on_delete=models.PROTECT,
        related_name="bank_accounts",
    )
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["bank_name", "account_number"],
                name="uniq_bank_account_number",
            ),
        ]

    def __str__(self):
        return f"{self.bank_name} {self.account_number}"


class StatementLine(BaseModel):
    """One line off a bank statement, and what it was matched to.

    The bank's own record, kept separately from the ledger's. Reconciliation
    is the comparison of two independent records; importing the statement
    *into* the ledger would destroy the only thing that makes the exercise
    worth doing.
    """

    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="statement_lines",
    )
    transaction_date = models.DateField(db_index=True)
    description = models.CharField(max_length=512)
    reference = models.CharField(max_length=128, blank=True)
    #: Positive money in, negative money out — the bank's own sign convention,
    #: preserved rather than translated, so a line can be checked against the
    #: paper statement without arithmetic.
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    balance_after = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True,
    )

    matched_line = models.ForeignKey(
        JournalLine, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="statement_matches",
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    matched_by_name = models.CharField(max_length=255, blank=True)
    #: Set when a statement line has no counterpart in the ledger and one has
    #: been created for it — a bank charge nobody knew about, typically.
    created_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="from_statement_lines",
    )

    class Meta:
        ordering = ["transaction_date", "id"]
        indexes = [models.Index(fields=["bank_account", "transaction_date"])]
        constraints = [
            #: The same line imported twice is the commonest reconciliation
            #: error, and it is invisible: the balance simply stops matching.
            models.UniqueConstraint(
                fields=["bank_account", "transaction_date", "amount", "reference"],
                name="uniq_statement_line",
            ),
        ]

    def __str__(self):
        return f"{self.transaction_date} {self.amount}"

    @property
    def is_matched(self) -> bool:
        return self.matched_line_id is not None or self.created_entry_id is not None


# ---------------------------------------------------------------------------
# Payables and expenses
# ---------------------------------------------------------------------------


class SupplierInvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved for payment"
    PART_PAID = "part_paid", "Partly paid"
    PAID = "paid", "Paid"
    DISPUTED = "disputed", "Disputed"
    CANCELLED = "cancelled", "Cancelled"


class SupplierInvoice(BaseModel):
    """What a supplier says is owed, which is not always what was received.

    Kept as its own document rather than derived from the goods receipt,
    because the two disagree often — a short delivery, a price that moved, a
    credit not applied. The difference between them is the thing worth
    seeing, and deriving one from the other would hide it.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    #: The supplier's own number, which is what they will quote on the phone.
    supplier_invoice_number = models.CharField(max_length=64)
    supplier_uuid = models.UUIDField(db_index=True)
    supplier_name = models.CharField(max_length=255)

    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="supplier_invoices",
    )
    invoice_date = models.DateField()
    due_date = models.DateField(db_index=True)
    received_on = models.DateField(default=timezone.localdate)

    subtotal = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    tax_amount = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    paid_amount = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)

    #: The goods receipts this invoice claims to cover, by reference. A list
    #: rather than a foreign key: one invoice routinely covers several
    #: deliveries, and one delivery is sometimes invoiced twice.
    goods_receipts = models.JSONField(default=list, blank=True)
    #: Difference between what was received and what is being billed for.
    #: Stored because it is the reason an invoice is held, and recomputing it
    #: later against changed stock records would give a different answer.
    variance = models.DecimalField(max_digits=16, decimal_places=2, default=ZERO)
    variance_notes = models.CharField(max_length=512, blank=True)

    status = models.CharField(
        max_length=12, choices=SupplierInvoiceStatus.choices,
        default=SupplierInvoiceStatus.DRAFT, db_index=True,
    )
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-invoice_date"]
        indexes = [models.Index(fields=["supplier_uuid", "status"])]
        constraints = [
            #: The same supplier invoice entered twice is how a hospital pays
            #: twice. The supplier's own number is the natural key.
            models.UniqueConstraint(
                fields=["supplier_uuid", "supplier_invoice_number"],
                name="uniq_supplier_invoice_number",
            ),
        ]

    def __str__(self):
        return f"{self.reference} {self.supplier_name}"

    @property
    def outstanding(self) -> Decimal:
        return self.total - self.paid_amount

    @property
    def is_overdue(self) -> bool:
        return self.outstanding > 0 and self.due_date < timezone.localdate()


class ExpenseStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    PAID = "paid", "Paid"


class Expense(BaseModel):
    """Money spent outside the purchasing process.

    Fuel, a taxi, an emergency part bought with cash. Small individually and
    the commonest place a hospital's costs go unrecorded, because the amount
    never justifies a purchase order.
    """

    reference = models.CharField(max_length=32, unique=True, db_index=True)
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="expenses",
    )
    spent_on = models.DateField(db_index=True)
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="expenses",
    )
    cost_centre = models.CharField(max_length=64, blank=True)
    description = models.CharField(max_length=512)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    claimed_by_id = models.UUIDField(null=True, blank=True)
    claimed_by_name = models.CharField(max_length=255, blank=True)
    payment_method = models.CharField(max_length=24, default="cash")
    #: A receipt number, or the fact that there is not one. An expense with no
    #: receipt is claimable and is also the one a tax inspection asks about.
    receipt_number = models.CharField(max_length=64, blank=True)
    has_receipt = models.BooleanField(default=True)

    status = models.CharField(
        max_length=12, choices=ExpenseStatus.choices,
        default=ExpenseStatus.SUBMITTED, db_index=True,
    )
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_name = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-spent_on"]
        indexes = [models.Index(fields=["facility", "status"])]

    def __str__(self):
        return f"{self.reference} {self.description[:40]}"


def validate_postable(account: Account) -> None:
    """Refuse a posting to an account that cannot take one.

    A service-layer check rather than a constraint, because the message
    matters: posting to a parent account is a mistake with a clear fix, and a
    foreign-key error would not say what it was.
    """
    if not account.is_postable:
        raise ValidationError(
            f"{account.code} {account.name} is a grouping, not a posting "
            "account. Post to one of its children."
        )
    if not account.is_active:
        raise ValidationError(f"{account.code} {account.name} is closed.")
