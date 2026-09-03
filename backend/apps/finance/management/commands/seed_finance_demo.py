"""Post the hospital's real documents into the books, and check they agree.

The seed does not invent transactions. It takes the invoices and payments the
other seeds already produced, posts them, and then asks the two questions that
matter: does the trial balance balance, and does the receivables control
account agree with the invoices that are actually unpaid?

Those two questions are the whole point of a general ledger. A seed that
posted made-up numbers would answer them trivially.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceStatus, Payment
from apps.finance.models import (
    Account,
    AccountingPeriod,
    BankAccount,
    ControlAccountKey,
    Expense,
    ExpenseStatus,
    JournalEntry,
    JournalSource,
    PeriodStatus,
    StatementLine,
    SupplierInvoice,
    SupplierInvoiceStatus,
)
from apps.finance.services import (
    POSTABLE_INVOICE_STATUSES,
    account_for,
    account_ledger,
    balance_sheet,
    build_chart,
    close_period,
    open_year,
    payables_ageing,
    period_for,
    post_document,
    post_expense,
    post_opening_balances,
    post_invoice,
    post_payment,
    post_supplier_invoice,
    profit_and_loss,
    receivables_ageing,
    reconciliation,
    reconcile_receivables,
    reverse_entry,
    trial_balance,
    vat_return,
)
from apps.identity.models import User
from apps.organization.models import Facility
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Build the chart, post the hospital's documents, and prove the books."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.get(slug=options["org"])
        with tenant_context(context_for_organization(organization)):
            self.run(organization)

    def say(self, text=""):
        self.stdout.write(text)

    def step(self, number, title):
        self.say("")
        self.say(self.style.MIGRATE_HEADING(f"{number}. {title}"))

    def expect(self, claim, expected, actual):
        agrees = str(expected) == str(actual)
        self.say(
            f"   {claim}: expected {expected}, got {actual}"
            f"{'  ' if agrees else '  <-- DISAGREES'}"
        )

    def run(self, organization):
        actor = User.objects.filter(email="owner@manakamana.test").first()
        facility = Facility.objects.filter(facility_type="hospital").first()
        today = timezone.localdate()

        self.step(1, "The chart of accounts")
        chart = build_chart(organization, actor=actor)
        self.say(f"   {chart['accounts']} accounts, {chart['postable']} of them "
                 f"postable ({chart['created']} created this run).")
        self.say("   Parents are groupings and take no postings. Posting to a "
                 "parent would make its balance ambiguous — is it the total of")
        self.say("   its children, or the total plus what was posted directly?")

        receivables = account_for(ControlAccountKey.RECEIVABLES)
        self.expect("the receivables control account", "1130", receivables.code)
        self.say("   Every automatic posting finds its account by key, never by "
                 "number, so an accountant can renumber the whole chart.")

        self.step(2, "The fiscal year")
        # Both this year and the last. A hospital going live has history, and
        # the closed-month demonstration below needs a month that is genuinely
        # behind us rather than one invented for the occasion.
        previous = open_year(today - timedelta(days=200), actor=actor)
        periods = open_year(actor=actor)
        self.say(f"   {len(previous)} periods in {previous[0].fiscal_year}, "
                 f"{len(periods)} in {periods[0].fiscal_year}: "
                 f"{periods[0].name} to {periods[-1].name}.")

        self.step(3, "Opening balances")
        # Without this the drawer goes negative on the first refund, because
        # the money that was in it beforehand was never recorded. A ledger
        # showing minus fifty thousand in cash is not a rounding problem; it
        # is a ledger that started in the middle.
        opening, was_new = post_opening_balances(
            {
                ControlAccountKey.CASH: Decimal("250000.00"),
                ControlAccountKey.BANK: Decimal("1850000.00"),
                ControlAccountKey.INVENTORY: Decimal("620000.00"),
                ControlAccountKey.PAYABLES: Decimal("180000.00"),
            },
            actor=actor,
            on_date=periods[0].starts_on,
            facility=facility,
        )
        self.say(f"   {opening.reference}: Rs {opening.total_debit} either "
                 f"side{'' if was_new else ' (already posted)'}.")
        self.say("   What does not balance goes to retained earnings, which is "
                 "right: the difference between what a business owns and owes")
        self.say("   on the day the books open is its accumulated result.")

        self.step(4, "Posting the invoices that already exist")
        # Everything that was ever issued, including invoices later reversed
        # by a credit note and the credit notes themselves. Recognising the
        # revenue and then reversing it is the correct record; never
        # recognising it leaves the month it was earned in permanently wrong.
        invoices = list(
            Invoice.objects.filter(
                status__in=POSTABLE_INVOICE_STATUSES,
            ).select_related("patient", "facility")
        )
        posted = 0
        already = 0
        credit_notes = 0
        for invoice in invoices:
            _, was_new = post_invoice(invoice, actor=actor)
            posted += 1 if was_new else 0
            already += 0 if was_new else 1
            credit_notes += 1 if invoice.is_credit_note else 0
        self.say(f"   {len(invoices)} documents ({credit_notes} of them credit "
                 f"notes): {posted} newly posted, {already} already there.")

        # Idempotency is the property worth demonstrating, because every
        # nightly job in this system will eventually run twice.
        before = JournalEntry.objects.filter(source=JournalSource.INVOICE).count()
        for invoice in invoices[:5]:
            post_invoice(invoice, actor=actor)
        after = JournalEntry.objects.filter(source=JournalSource.INVOICE).count()
        self.expect("journal entries after re-posting five invoices", before, after)
        self.say("   Enforced by a unique constraint on (source, document), not "
                 "by a flag somebody has to remember to check.")

        self.step(5, "Posting the payments")
        # Completed *and* refunded. A payment later refunded still happened:
        # the cash came in, and the refund is its own negative row. Posting
        # only the completed ones records the refunds with nothing to reverse,
        # which is how the drawer ends up owing money it never took.
        payments = list(
            Payment.objects.filter(status__in=("completed", "refunded"))
            .select_related("invoice", "patient", "facility")
        )
        new_payments = sum(
            1 for payment in payments if post_payment(payment, actor=actor)[1]
        )
        self.say(f"   {len(payments)} payments, {new_payments} newly posted.")
        self.say("   Cash goes to the drawer and everything else to the bank: "
                 "a wallet settles a day or two later, and treating it as cash")
        self.say("   means the drawer never reconciles.")

        self.step(6, "A supplier invoice, and the variance nobody wants to see")
        supplier_invoice, _ = SupplierInvoice.objects.get_or_create(
            supplier_uuid=facility.uuid,
            supplier_invoice_number="SUR-2026-0417",
            defaults={
                "reference": "SI-000001",
                "supplier_name": "Surya Pharma Distributors",
                "facility": facility,
                "invoice_date": today - timedelta(days=40),
                "due_date": today - timedelta(days=10),
                "subtotal": Decimal("184000.00"),
                "tax_amount": Decimal("23920.00"),
                "total": Decimal("207920.00"),
                "goods_receipts": ["GRN-000012", "GRN-000013"],
                "variance": Decimal("4200.00"),
                "variance_notes": "Two cartons short on GRN-000013.",
                "status": SupplierInvoiceStatus.APPROVED,
                "approved_by_name": getattr(actor, "full_name", "") or "",
                "approved_at": timezone.now(),
            },
        )
        post_supplier_invoice(supplier_invoice, actor=actor)
        self.say(f"   {supplier_invoice.reference}: "
                 f"Rs {supplier_invoice.total} owed, "
                 f"Rs {supplier_invoice.variance} disputed.")
        self.say("   Goods go to inventory, not to expense. The cost belongs to "
                 "the period the stock is sold in — a hospital that expenses")
        self.say("   purchases on receipt shows a loss every time it restocks.")

        self.step(7, "Expenses")
        utilities = Account.objects.get(code="5300")
        transport = Account.objects.get(code="5600")
        for reference, account, amount, description, receipt in [
            ("EX-000001", utilities, Decimal("48200.00"),
             "Electricity, Bhadra", True),
            ("EX-000002", transport, Decimal("1850.00"),
             "Ambulance fuel", True),
            ("EX-000003", transport, Decimal("600.00"),
             "Taxi, urgent blood collection", False),
        ]:
            expense, _ = Expense.objects.get_or_create(
                reference=reference,
                defaults={
                    "facility": facility,
                    "spent_on": today - timedelta(days=6),
                    "account": account,
                    "description": description,
                    "amount": amount,
                    "has_receipt": receipt,
                    "status": ExpenseStatus.APPROVED,
                    "approved_by_name": getattr(actor, "full_name", "") or "",
                    "approved_at": timezone.now(),
                    "cost_centre": "operations",
                },
            )
            post_expense(expense, actor=actor)
        self.say("   Three expenses posted, one without a receipt — recorded as "
                 "such, because that is the one a tax inspection asks about.")

        self.step(8, "Does the trial balance balance?")
        balance = trial_balance()
        self.say(f"   {len(balance['rows'])} accounts with movement.")
        self.expect("total debits equal total credits", True, balance["balances"])
        self.say(f"   Rs {balance['total_debit']} debited, "
                 f"Rs {balance['total_credit']} credited, "
                 f"difference Rs {balance['difference']}.")
        self.say("   Computed by summing the lines, not by restating the header "
                 "totals the constraint already guarantees — so this is a real")
        self.say("   check on the data.")

        for row in balance["rows"][:12]:
            self.say(f"     {row['code']}  {row['name'][:32]:32} "
                     f"Dr {row['debit']:>12}  Cr {row['credit']:>12}")

        self.step(9, "Does the ledger agree with the invoices?")
        agreement = reconcile_receivables()
        self.say(f"   Subledger (unpaid invoices):  Rs {agreement['subledger']}")
        self.say(f"   Ledger (control account):     Rs {agreement['ledger']}")
        self.expect("the two agree", True, agreement["agrees"])
        if not agreement["agrees"]:
            self.say(f"   Difference: Rs {agreement['difference']}")
            self.say(f"   Invoices with no journal entry: "
                     f"{agreement['invoices_not_posted_count']}")
            for number in agreement["invoices_not_posted"][:5]:
                self.say(f"     {number}")
        self.say("   Two independent records. The ageing is computed from the "
                 "invoices and the balance from the journals, so the comparison")
        self.say("   means something — in most systems these drift apart for "
                 "years because nothing ever asks.")

        self.step(10, "Who owes what, and for how long")
        ageing = receivables_ageing()
        self.say(f"   Rs {ageing['total']} outstanding across "
                 f"{len(ageing['invoices'])} invoices.")
        for bucket, amount in ageing["buckets"].items():
            self.say(f"     {bucket:12} days  Rs {amount}")
        self.say(f"   Over ninety days: Rs {ageing['over_90']}")

        payables = payables_ageing()
        self.say(f"   Owed to suppliers: Rs {payables['total']}, "
                 f"of which Rs {payables['overdue']} is overdue.")

        self.step(11, "A mistake, and how it is corrected")
        # Given a source reference so that re-running the seed does not post a
        # second diesel bill. Every seed in this project must survive its own
        # second run; a ledger seed that does not is a ledger that grows a
        # little more wrong each time somebody demonstrates it.
        wrong, was_new = post_document(
            JournalSource.MANUAL, "SEED-DIESEL",
            [
                {"account": utilities, "debit": Decimal("9500.00")},
                {"account": ControlAccountKey.CASH, "credit": Decimal("9500.00")},
            ],
            "Generator diesel — wrong account",
            actor=actor,
            facility=facility,
        )
        self.say(f"   {'Posted' if was_new else 'Already posted'} "
                 f"{wrong.reference} for Rs {wrong.total_debit}.")

        contra = (
            wrong.reversed_by if hasattr(wrong, "reversed_by")
            else reverse_entry(
                wrong, actor=actor,
                reason="Diesel belongs to repairs and maintenance, not "
                       "utilities.",
            )
        )
        wrong.refresh_from_db()
        self.expect("the original entry's status", "reversed", wrong.status)
        self.expect("the contra entry's totals",
                    f"Dr {wrong.total_credit} Cr {wrong.total_debit}",
                    f"Dr {contra.total_debit} Cr {contra.total_credit}")
        self.say("   The original is untouched and points at its reversal. An "
                 "edited journal leaves a report that once said something else")
        self.say("   and no way to find out what.")

        after_reversal = trial_balance()
        self.expect("the trial balance still balances", True,
                    after_reversal["balances"])

        self.step(12, "A late document, and a closed month")
        # Close the period two months back, then post something dated inside
        # it. The point is what happens next.
        old_date = today - timedelta(days=75)
        old_period = period_for(old_date)
        close_period(old_period, actor=actor, force=True)
        self.say(f"   {old_period.name} {old_period.fiscal_year} closed "
                 f"({old_period.starts_on} to {old_period.ends_on}).")

        late, _ = post_document(
            JournalSource.MANUAL, "SEED-WATER",
            [
                {"account": utilities, "debit": Decimal("3100.00")},
                {"account": ControlAccountKey.CASH, "credit": Decimal("3100.00")},
            ],
            "Water bill found in a drawer",
            actor=actor,
            document_date=old_date,
            facility=facility,
        )
        self.expect("the document's own date", old_date, late.document_date)
        self.say(f"   Posted into {late.period.name} on {late.posting_date}.")
        self.expect("posted into the closed month?", False,
                    late.period_id == old_period.id)
        self.say("   It keeps its own date and lands in the next open period. "
                 "Refusing it would mean the transaction is never recorded at")
        self.say("   all, and a ledger missing a real payment is worse than one "
                 "showing it late.")

        self.step(13, "Bank reconciliation")
        bank_account, _ = BankAccount.objects.get_or_create(
            bank_name="Nabil Bank",
            account_number="0102000123456",
            defaults={
                "name": "Manakamana operating account",
                "branch": "Durbar Marg",
                "account": account_for(ControlAccountKey.BANK),
                "facility": facility,
            },
        )
        # A statement with one line the books have never seen: a bank charge.
        for day, description, amount, reference in [
            (3, "Service charge", Decimal("-450.00"), "CHG-0901"),
            (2, "Cash deposit", Decimal("25000.00"), "DEP-4471"),
        ]:
            StatementLine.objects.get_or_create(
                bank_account=bank_account,
                transaction_date=today - timedelta(days=day),
                amount=amount,
                reference=reference,
                defaults={"description": description},
            )
        state = reconciliation(bank_account)
        self.say(f"   {state['statement_lines']} statement lines, "
                 f"{state['matched']} matched.")
        self.say(f"   Statement Rs {state['statement_total']} against ledger "
                 f"Rs {state['ledger_total']}, "
                 f"difference Rs {state['difference']}.")
        self.say(f"   On the statement but not in the books: "
                 f"{len(state['unmatched_on_the_statement'])}")
        for row in state["unmatched_on_the_statement"]:
            self.say(f"     {row['date']}  {row['description']:24} "
                     f"Rs {row['amount']}")
        self.say(f"   In the books but not on the statement: "
                 f"{len(state['unmatched_in_the_ledger'])}")
        self.say("   Both directions, because they mean different things. A "
                 "statement line with no journal is usually a charge nobody knew")
        self.say("   about; a journal with no statement line is a cheque that "
                 "has not cleared — or a payment that was never actually made.")

        self.step(14, "The statements")
        pl = profit_and_loss()
        self.say(f"   Income Rs {pl['total_income']}, "
                 f"expenses Rs {pl['total_expense']}, "
                 f"surplus Rs {pl['surplus']}.")
        for row in pl["income"]:
            self.say(f"     income   {row['name'][:30]:30} Rs {row['amount']}")
        for row in pl["expenses"][:6]:
            self.say(f"     expense  {row['name'][:30]:30} Rs {row['amount']}")

        sheet = balance_sheet()
        self.say(f"   Assets Rs {sheet['total_assets']}, liabilities "
                 f"Rs {sheet['total_liabilities']}, equity "
                 f"Rs {sheet['total_equity']}.")
        self.expect("the balance sheet balances", True, sheet["balances"])
        self.say(f"   Surplus for the period, carried into equity without "
                 f"closing the year: Rs {sheet['surplus_for_the_period']}")

        tax = vat_return()
        self.say(f"   VAT: Rs {tax['output_tax']} collected, "
                 f"Rs {tax['input_tax']} recoverable, "
                 f"Rs {tax['payable']} payable.")
        self.say("   Output and input are kept in separate accounts because the "
                 "return asks for both figures, and a single net number cannot")
        self.say("   be split back apart.")

        self.step(15, "One account, read as a ledger")
        cash = account_ledger(
            account_for(ControlAccountKey.CASH),
            since=today - timedelta(days=30),
        )
        self.say(f"   {cash['account']}: opened Rs {cash['opening']}, "
                 f"closed Rs {cash['closing']} over "
                 f"{len(cash['rows'])} movements.")
        for row in cash["rows"][:6]:
            self.say(f"     {row['date']}  {row['reference']:20} "
                     f"{row['narration'][:28]:28} Rs {row['balance']}")

        self.say("")
        self.say(self.style.SUCCESS("Finance seed complete."))
