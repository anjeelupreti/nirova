/**
 * The books.
 *
 * A finance screen has one job the other screens do not: it must be
 * *checkable*. A ward board that is slightly wrong is still useful. A ledger
 * that is slightly wrong is not a ledger, so this screen leads with the two
 * proofs rather than burying them under a chart.
 *
 * **Does the ledger agree with the invoices?** That banner sits above
 * everything. In most hospital systems the receivables control account and the
 * actual unpaid invoices drift apart over years because nothing ever asks.
 * Here it is the first thing on the page, and when it disagrees it names the
 * invoices that were never posted.
 *
 * **Does the trial balance balance?** Stated as a sentence with the
 * difference, not implied by two columns that happen to look similar.
 *
 * The posting dialog shows a running difference that must reach zero before
 * the button enables — the same rule the database constraint enforces, made
 * visible while somebody types rather than reported after they submit.
 */

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Landmark,
  Loader2,
  Lock,
  Receipt,
  RotateCcw,
  Scale,
  Wallet,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AccountingPeriod,
  BalanceSheet,
  BankReconciliation,
  JournalEntry,
  LedgerAccount,
  LedgerBankAccount,
  Paginated,
  PayablesAgeing,
  ProfitAndLoss,
  ReceivablesAgeing,
  ReceivablesAgreement,
  TrialBalance,
  VatReturn,
} from "@/types";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "@/components/ui/primitives";

type Tab = "statements" | "owed" | "journals" | "periods" | "bank";

const TABS: { id: Tab; label: string; icon: typeof Scale }[] = [
  { id: "statements", label: "Statements", icon: Scale },
  { id: "owed", label: "Owed", icon: Receipt },
  { id: "journals", label: "Journals", icon: BookOpen },
  { id: "periods", label: "Periods", icon: CalendarDays },
  { id: "bank", label: "Bank", icon: Landmark },
];

const rupees = (value: string | number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  const formatted = Math.abs(number).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return number < 0 ? `(${formatted})` : formatted;
};

const humanise = (value: string) => value.replace(/_/g, " ");

const day = (value: string | null) =>
  value ? new Date(value).toLocaleDateString([], {
    day: "2-digit", month: "short", year: "2-digit",
  }) : "—";

const BUCKET_LABELS: Record<string, string> = {
  "0-30": "0–30 days",
  "31-60": "31–60",
  "61-90": "61–90",
  "91-180": "91–180",
  "181-plus": "over 180",
};

export default function FinancePage() {
  const [tab, setTab] = useState<Tab>("statements");
  const [agreement, setAgreement] = useState<ReceivablesAgreement | null>(null);
  const [denied, setDenied] = useState(false);

  const loadAgreement = useCallback(() => {
    void api
      .get<ReceivablesAgreement>("/finance/reports/?report=reconcile_receivables")
      .then(setAgreement)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  useEffect(loadAgreement, [loadAgreement]);

  if (denied) {
    return (
      <Alert>
        <Scale className="h-4 w-4" />
        <AlertTitle>The books are not visible to you</AlertTitle>
        <AlertDescription>
          Reading the ledger needs reporting permissions.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Finance</h1>
        <p className="text-sm text-muted-foreground">
          The ledger, and the two questions it must be able to answer.
        </p>
      </div>

      {/* The headline. Not a tab, not a footnote. */}
      {agreement && (
        <Alert variant={agreement.agrees ? "default" : "destructive"}>
          {agreement.agrees ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : (
            <AlertTriangle className="h-4 w-4" />
          )}
          <AlertTitle>
            {agreement.agrees
              ? "The ledger agrees with the invoices"
              : `The ledger and the invoices disagree by Rs ${rupees(agreement.difference)}`}
          </AlertTitle>
          <AlertDescription>
            Unpaid invoices come to Rs {rupees(agreement.subledger)}; the
            receivables control account says Rs {rupees(agreement.ledger)}.
            {agreement.agrees ? (
              " Two records, computed independently — which is the only reason the comparison means anything."
            ) : (
              <>
                {" "}
                {agreement.invoices_not_posted_count} invoice
                {agreement.invoices_not_posted_count === 1 ? " has" : "s have"}{" "}
                no journal entry
                {agreement.invoices_not_posted.length > 0 && (
                  <span className="block font-mono text-xs">
                    {agreement.invoices_not_posted.slice(0, 8).join(", ")}
                  </span>
                )}
              </>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="flex gap-1 overflow-x-auto border-b">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
              tab === id
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === "statements" && <Statements />}
      {tab === "owed" && <Owed />}
      {tab === "journals" && <Journals onPosted={loadAgreement} />}
      {tab === "periods" && <Periods />}
      {tab === "bank" && <Bank />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Statements                                                                  */
/* -------------------------------------------------------------------------- */

function Statements() {
  const [which, setWhich] = useState<"trial_balance" | "profit_and_loss" | "balance_sheet">(
    "trial_balance",
  );
  const [trial, setTrial] = useState<TrialBalance | null>(null);
  const [pl, setPl] = useState<ProfitAndLoss | null>(null);
  const [sheet, setSheet] = useState<BalanceSheet | null>(null);
  const [vat, setVat] = useState<VatReturn | null>(null);

  useEffect(() => {
    void Promise.all([
      api.get<TrialBalance>("/finance/reports/?report=trial_balance"),
      api.get<ProfitAndLoss>("/finance/reports/?report=profit_and_loss"),
      api.get<BalanceSheet>("/finance/reports/?report=balance_sheet"),
      api.get<VatReturn>("/finance/reports/?report=vat"),
    ])
      .then(([a, b, c, d]) => {
        setTrial(a);
        setPl(b);
        setSheet(c);
        setVat(d);
      })
      .catch(() => undefined);
  }, []);

  if (!trial || !pl || !sheet) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            ["trial_balance", "Trial balance"],
            ["profit_and_loss", "Income and expenditure"],
            ["balance_sheet", "Balance sheet"],
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            size="sm"
            variant={which === value ? "default" : "outline"}
            onClick={() => setWhich(value)}
          >
            {label}
          </Button>
        ))}
      </div>

      {which === "trial_balance" && (
        <Card className={cn(!trial.balances && "border-destructive/60")}>
          <CardHeader>
            <CardTitle className="text-base">
              Trial balance as at {day(trial.as_at)}
            </CardTitle>
            <CardDescription>
              {trial.balances ? (
                <>
                  Rs {rupees(trial.total_debit)} debited against Rs{" "}
                  {rupees(trial.total_credit)} credited. It balances. Summed
                  from the lines, not restated from the entry headers — so this
                  is a real check on the data.
                </>
              ) : (
                <span className="text-destructive">
                  Out by Rs {rupees(trial.difference)}. Something has been
                  written into the ledger that did not go through the posting
                  service.
                </span>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Account</TableHead>
                  <TableHead className="text-right">Debit</TableHead>
                  <TableHead className="text-right">Credit</TableHead>
                  <TableHead className="text-right">Balance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trial.rows.map((row) => (
                  <TableRow key={row.code}>
                    <TableCell>
                      <span className="font-mono text-xs text-muted-foreground">
                        {row.code}
                      </span>{" "}
                      {row.name}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {row.type}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.debit)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.credit)}
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {rupees(row.balance)}
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow className="border-t-2 font-semibold">
                  <TableCell>Total</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(trial.total_debit)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(trial.total_credit)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      !trial.balances && "text-destructive",
                    )}
                  >
                    {rupees(trial.difference)}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {which === "profit_and_loss" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Income and expenditure
            </CardTitle>
            <CardDescription>
              {day(pl.from)} to {day(pl.to)}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Section title="Income" rows={pl.income} total={pl.total_income} />
            <Section
              title="Expenditure"
              rows={pl.expenses}
              total={pl.total_expense}
            />
            <div
              className={cn(
                "flex items-baseline justify-between border-t pt-3 text-lg font-semibold",
                Number(pl.surplus) < 0 && "text-destructive",
              )}
            >
              <span>{Number(pl.surplus) < 0 ? "Deficit" : "Surplus"}</span>
              <span className="tabular-nums">Rs {rupees(pl.surplus)}</span>
            </div>
            {vat && (
              <p className="text-xs text-muted-foreground">
                VAT for the same window: Rs {rupees(vat.output_tax)} collected,
                Rs {rupees(vat.input_tax)} recoverable, Rs{" "}
                {rupees(vat.payable)} payable. Output and input are held in
                separate accounts because the return asks for both figures and
                a single net number cannot be split back apart.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {which === "balance_sheet" && (
        <Card className={cn(!sheet.balances && "border-destructive/60")}>
          <CardHeader>
            <CardTitle className="text-base">
              Balance sheet as at {day(sheet.as_at)}
            </CardTitle>
            <CardDescription>
              {sheet.balances
                ? "Assets equal liabilities plus equity."
                : `Out by Rs ${rupees(sheet.difference)}.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-6 md:grid-cols-2">
            <Section
              title="Assets"
              rows={sheet.assets}
              total={sheet.total_assets}
            />
            <div className="space-y-4">
              <Section
                title="Liabilities"
                rows={sheet.liabilities}
                total={sheet.total_liabilities}
              />
              <Section
                title="Equity"
                rows={[
                  ...sheet.equity,
                  {
                    code: "—",
                    name: "Accumulated surplus",
                    amount: sheet.accumulated_surplus,
                  },
                ]}
                total={sheet.total_equity}
              />
              <p className="text-xs text-muted-foreground">
                The accumulated surplus is carried into equity without closing
                the year, because a balance sheet is something a manager wants
                in Poush and not only in Ashadh. This period alone contributed
                Rs {rupees(sheet.surplus_for_the_period)}.
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Section({
  title,
  rows,
  total,
}: {
  title: string;
  rows: { code: string; name: string; amount: string }[];
  total: string;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      {rows.length === 0 && (
        <p className="py-2 text-sm text-muted-foreground">Nothing posted.</p>
      )}
      {rows.map((row) => (
        <div
          key={`${row.code}-${row.name}`}
          className="flex justify-between gap-3 py-0.5 text-sm"
        >
          <span className="min-w-0 truncate">
            <span className="font-mono text-xs text-muted-foreground">
              {row.code}
            </span>{" "}
            {row.name}
          </span>
          <span className="shrink-0 tabular-nums">{rupees(row.amount)}</span>
        </div>
      ))}
      <div className="mt-1 flex justify-between gap-3 border-t pt-1 text-sm font-semibold">
        <span>Total</span>
        <span className="tabular-nums">{rupees(total)}</span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Owed, both ways                                                             */
/* -------------------------------------------------------------------------- */

function Owed() {
  const [receivables, setReceivables] = useState<ReceivablesAgeing | null>(null);
  const [payables, setPayables] = useState<PayablesAgeing | null>(null);

  useEffect(() => {
    void Promise.all([
      api.get<ReceivablesAgeing>("/finance/reports/?report=receivables"),
      api.get<PayablesAgeing>("/finance/reports/?report=payables"),
    ])
      .then(([a, b]) => {
        setReceivables(a);
        setPayables(b);
      })
      .catch(() => undefined);
  }, []);

  if (!receivables || !payables) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Owed to the hospital</CardTitle>
          <CardDescription>
            Rs {rupees(receivables.total)} outstanding, of which Rs{" "}
            {rupees(receivables.over_90)} has been owed for more than ninety
            days. Computed from the invoices rather than from the ledger, so
            that the two can be compared.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Buckets buckets={receivables.buckets} />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice</TableHead>
                <TableHead>Patient</TableHead>
                <TableHead className="text-right">Age</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Paid</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {receivables.invoices.slice(0, 40).map((row) => (
                <TableRow key={row.invoice}>
                  <TableCell className="font-mono text-xs">
                    {row.invoice}
                  </TableCell>
                  <TableCell>{row.patient}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.days > 90 && "text-destructive",
                    )}
                  >
                    {row.days}d
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.total)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.paid)}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {rupees(row.outstanding)}
                  </TableCell>
                </TableRow>
              ))}
              {receivables.invoices.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    Nothing outstanding.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">
            A negative outstanding is a credit note or an overpayment — money
            the hospital owes back. It stays in the list rather than being
            filtered out, because dropping it would make this total disagree
            with the control account by exactly that amount.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Owed by the hospital</CardTitle>
          <CardDescription>
            Rs {rupees(payables.total)} to suppliers, Rs{" "}
            {rupees(payables.overdue)} of it past its due date.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Buckets buckets={payables.buckets} />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Supplier</TableHead>
                <TableHead>Their number</TableHead>
                <TableHead>Due</TableHead>
                <TableHead className="text-right">Overdue by</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {payables.invoices.map((row) => (
                <TableRow key={row.invoice}>
                  <TableCell>
                    {row.supplier}
                    {row.disputed && (
                      <Badge variant="destructive" className="ml-2">
                        disputed
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {row.supplier_number}
                  </TableCell>
                  <TableCell>{day(row.due)}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.days_overdue > 0 && "text-destructive",
                    )}
                  >
                    {row.days_overdue > 0 ? `${row.days_overdue}d` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {rupees(row.outstanding)}
                  </TableCell>
                </TableRow>
              ))}
              {payables.invoices.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    Nothing owed.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function Buckets({ buckets }: { buckets: Record<string, string> }) {
  const entries = Object.entries(buckets);
  const peak = Math.max(1, ...entries.map(([, value]) => Math.abs(Number(value))));

  return (
    <div className="space-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center gap-2 text-sm">
          <span className="w-24 shrink-0 text-xs text-muted-foreground">
            {BUCKET_LABELS[key] ?? key}
          </span>
          <span className="flex h-3 flex-1 items-center">
            <span
              className={cn(
                "h-3 rounded-sm",
                key === "91-180" || key === "181-plus"
                  ? "bg-destructive/70"
                  : "bg-primary/60",
              )}
              style={{ width: `${(Math.abs(Number(value)) / peak) * 100}%` }}
            />
          </span>
          <span className="w-32 shrink-0 text-right tabular-nums">
            {rupees(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Journals                                                                    */
/* -------------------------------------------------------------------------- */

function Journals({ onPosted }: { onPosted: () => void }) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [reversing, setReversing] = useState<JournalEntry | null>(null);

  const load = useCallback(async () => {
    const page = await api.get<Paginated<JournalEntry>>("/finance/journals/");
    setEntries(page.results);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setPosting(true)}>
          <BookOpen className="h-4 w-4" />
          Post a journal
        </Button>
      </div>

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Reference</TableHead>
                <TableHead>Narration</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Posted</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => (
                <Fragment key={entry.uuid}>
                  <TableRow
                    className={cn(
                      "cursor-pointer",
                      entry.status === "reversed" && "opacity-60",
                    )}
                    onClick={() =>
                      setOpen(open === entry.reference ? null : entry.reference)
                    }
                  >
                    <TableCell className="font-mono text-xs">
                      {entry.reference}
                    </TableCell>
                    <TableCell className="max-w-xs truncate">
                      {entry.narration}
                      {entry.status === "reversed" && (
                        <Badge variant="secondary" className="ml-2">
                          reversed by {entry.reversed_by_reference}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{humanise(entry.source)}</Badge>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {day(entry.posting_date)}
                      {entry.posted_late && (
                        <span
                          className="ml-1 text-xs text-amber-600"
                          title={`Dated ${entry.document_date} — its own month was closed`}
                        >
                          (dated {day(entry.document_date)})
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(entry.total_debit)}
                    </TableCell>
                    <TableCell className="text-right">
                      {entry.status === "posted" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(event) => {
                            event.stopPropagation();
                            setReversing(entry);
                          }}
                        >
                          <RotateCcw className="h-3 w-3" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {open === entry.reference && (
                    <TableRow>
                      <TableCell colSpan={6} className="bg-muted/30">
                        <div className="space-y-1 py-1">
                          {entry.lines.map((line) => (
                            <div
                              key={line.uuid}
                              className="flex items-baseline gap-3 text-sm"
                            >
                              <span className="w-16 shrink-0 font-mono text-xs text-muted-foreground">
                                {line.account_code}
                              </span>
                              <span className="min-w-0 flex-1 truncate">
                                {line.account_name}
                                {line.party_name && (
                                  <span className="text-muted-foreground">
                                    {" "}
                                    · {line.party_name}
                                  </span>
                                )}
                              </span>
                              <span className="w-28 shrink-0 text-right tabular-nums">
                                {Number(line.debit) > 0 ? rupees(line.debit) : ""}
                              </span>
                              <span className="w-28 shrink-0 text-right tabular-nums">
                                {Number(line.credit) > 0
                                  ? rupees(line.credit)
                                  : ""}
                              </span>
                            </div>
                          ))}
                          {entry.reversal_reason && (
                            <p className="pt-1 text-xs text-muted-foreground">
                              {entry.reversal_reason}
                            </p>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        There is no edit and no delete. A wrong entry is reversed by a contra
        entry that names it, and both stay — an edited journal leaves a report
        that once said something else and no way to find out what.
      </p>

      {posting && (
        <PostDialog
          onClose={() => setPosting(false)}
          onDone={() => {
            setPosting(false);
            void load();
            onPosted();
          }}
        />
      )}
      {reversing && (
        <ReverseDialog
          entry={reversing}
          onClose={() => setReversing(null)}
          onDone={() => {
            setReversing(null);
            void load();
            onPosted();
          }}
        />
      )}
    </div>
  );
}

type DraftLine = { account: string; debit: string; credit: string; narration: string };

function PostDialog({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [accounts, setAccounts] = useState<LedgerAccount[]>([]);
  const [narration, setNarration] = useState("");
  const [documentDate, setDocumentDate] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [lines, setLines] = useState<DraftLine[]>([
    { account: "", debit: "", credit: "", narration: "" },
    { account: "", debit: "", credit: "", narration: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<LedgerAccount>>("/finance/accounts/?is_postable=true&is_active=true")
      .then((page) => setAccounts(page.results))
      .catch(() => setAccounts([]));
  }, []);

  const totals = useMemo(() => {
    const debit = lines.reduce((sum, line) => sum + (Number(line.debit) || 0), 0);
    const credit = lines.reduce((sum, line) => sum + (Number(line.credit) || 0), 0);
    return { debit, credit, difference: debit - credit };
  }, [lines]);

  const usable =
    narration.trim().length > 2 &&
    totals.debit > 0 &&
    totals.difference === 0 &&
    lines.filter((line) => line.account && (line.debit || line.credit)).length >= 2;

  const setLine = (index: number, key: keyof DraftLine, value: string) =>
    setLines((current) =>
      current.map((line, position) =>
        position === index ? { ...line, [key]: value } : line,
      ),
    );

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/finance/journals/post/", {
        narration,
        document_date: documentDate,
        lines: lines
          .filter((line) => line.account && (line.debit || line.credit))
          .map((line) => ({
            account: line.account,
            debit: line.debit || 0,
            credit: line.credit || 0,
            narration: line.narration,
          })),
      });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not posted.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-3xl">
        <CardHeader>
          <CardTitle>Post a journal</CardTitle>
          <CardDescription>
            The difference must reach zero before this can be posted — the same
            rule the database enforces, shown while you type rather than after
            you submit.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
            <div className="space-y-1">
              <Label htmlFor="j-narration">Narration</Label>
              <Input
                id="j-narration"
                value={narration}
                onChange={(event) => setNarration(event.target.value)}
                placeholder="What this entry is for"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="j-date">Document date</Label>
              <Input
                id="j-date"
                type="date"
                value={documentDate}
                onChange={(event) => setDocumentDate(event.target.value)}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            If that month is closed the entry posts into the next open one and
            keeps this date. Refusing it would mean the transaction is never
            recorded at all.
          </p>

          <div className="space-y-2">
            {lines.map((line, index) => (
              <div
                key={index}
                className="grid gap-2 sm:grid-cols-[1fr_7rem_7rem_2rem]"
              >
                <Select
                  aria-label="Account"
                  value={line.account}
                  onChange={(event) =>
                    setLine(index, "account", event.target.value)
                  }
                >
                  <option value="">Choose an account…</option>
                  {accounts.map((account) => (
                    <option key={account.uuid} value={account.uuid}>
                      {account.code} {account.name}
                    </option>
                  ))}
                </Select>
                <Input
                  inputMode="decimal"
                  placeholder="Debit"
                  value={line.debit}
                  onChange={(event) => {
                    setLine(index, "debit", event.target.value);
                    if (event.target.value) setLine(index, "credit", "");
                  }}
                />
                <Input
                  inputMode="decimal"
                  placeholder="Credit"
                  value={line.credit}
                  onChange={(event) => {
                    setLine(index, "credit", event.target.value);
                    if (event.target.value) setLine(index, "debit", "");
                  }}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setLines((current) =>
                      current.length > 2
                        ? current.filter((_, position) => position !== index)
                        : current,
                    )
                  }
                >
                  ×
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setLines((current) => [
                  ...current,
                  { account: "", debit: "", credit: "", narration: "" },
                ])
              }
            >
              Add a line
            </Button>
          </div>

          <div
            className={cn(
              "flex items-baseline justify-between rounded-md border p-3 text-sm",
              totals.difference === 0 && totals.debit > 0
                ? "border-emerald-500/50 bg-emerald-50/60 dark:bg-emerald-950/20"
                : "border-destructive/50 bg-destructive/5",
            )}
          >
            <span>
              Rs {rupees(totals.debit)} debited, Rs {rupees(totals.credit)}{" "}
              credited
            </span>
            <span className="font-semibold tabular-nums">
              {totals.difference === 0 && totals.debit > 0
                ? "balanced"
                : `out by Rs ${rupees(Math.abs(totals.difference))}`}
            </span>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || !usable}
              onClick={() => void submit()}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Post
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ReverseDialog({
  entry,
  onClose,
  onDone,
}: {
  entry: JournalEntry;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/finance/journals/${entry.reference}/reverse/`, { reason });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not reversed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Reverse {entry.reference}</CardTitle>
          <CardDescription>
            A contra entry is posted with every side swapped, on today's date.
            The original stays exactly as it was and points at the reversal.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}
          <p className="rounded-md border p-2 text-sm">
            {entry.narration} — Rs {rupees(entry.total_debit)}
          </p>
          <div className="space-y-1">
            <Label htmlFor="r-reason">Why</Label>
            <Textarea
              id="r-reason"
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Posted to the wrong account."
            />
          </div>
          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Keep it
            </Button>
            <Button
              className="flex-1"
              disabled={busy || reason.trim().length < 5}
              onClick={() => void submit()}
            >
              Reverse
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Periods                                                                     */
/* -------------------------------------------------------------------------- */

function Periods() {
  const [periods, setPeriods] = useState<AccountingPeriod[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    const page = await api.get<Paginated<AccountingPeriod>>("/finance/periods/");
    setPeriods(page.results);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (uuid: string, path: string, body: unknown) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/finance/periods/${uuid}/${path}/`, body);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Accounting periods</CardTitle>
          <CardDescription>
            Periods exist so that a report run today gives the same answer next
            week. Without them a late journal silently changes a month that has
            already gone to a bank or a board.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Period</TableHead>
                <TableHead>From</TableHead>
                <TableHead>To</TableHead>
                <TableHead className="text-right">Entries</TableHead>
                <TableHead>Status</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {periods.map((period) => (
                <TableRow key={period.uuid}>
                  <TableCell>
                    {period.name}
                    <span className="ml-1 text-xs text-muted-foreground">
                      {period.fiscal_year}
                    </span>
                  </TableCell>
                  <TableCell>{day(period.starts_on)}</TableCell>
                  <TableCell>{day(period.ends_on)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {period.entries}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        period.status === "open"
                          ? "outline"
                          : period.status === "locked"
                            ? "destructive"
                            : "secondary"
                      }
                    >
                      {period.status === "locked" && (
                        <Lock className="mr-1 h-3 w-3" />
                      )}
                      {humanise(period.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {period.status === "open" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void act(period.uuid, "close", {
                            status: "soft_closed",
                          })
                        }
                      >
                        Close
                      </Button>
                    ) : period.status === "soft_closed" ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => {
                          const reason = window.prompt(
                            "Reopening a closed month is a decision with consequences outside this system. Why?",
                          );
                          if (reason) void act(period.uuid, "reopen", { reason });
                        }}
                      >
                        Reopen
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        closed for good
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Closing refuses while draft journals remain, because a draft in a
        closed period can never be posted anywhere — its own month is shut and
        it has no other.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bank                                                                        */
/* -------------------------------------------------------------------------- */

function Bank() {
  const [accounts, setAccounts] = useState<LedgerBankAccount[]>([]);
  const [selected, setSelected] = useState("");
  const [state, setState] = useState<BankReconciliation | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<LedgerBankAccount>>("/finance/bank-accounts/")
      .then((page) => {
        setAccounts(page.results);
        setSelected(page.results[0]?.uuid ?? "");
      })
      .catch(() => setAccounts([]));
  }, []);

  useEffect(() => {
    if (!selected) return;
    void api
      .get<BankReconciliation>(
        `/finance/bank-accounts/${selected}/reconciliation/`,
      )
      .then(setState)
      .catch(() => setState(null));
  }, [selected]);

  if (accounts.length === 0) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-sm text-muted-foreground">
          No bank accounts configured.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Select
        className="h-9 w-auto"
        aria-label="Bank account"
        value={selected}
        onChange={(event) => setSelected(event.target.value)}
      >
        {accounts.map((row) => (
          <option key={row.uuid} value={row.uuid}>
            {row.bank_name} {row.account_number}
          </option>
        ))}
      </Select>

      {state && (
        <>
          <Card className={cn(Number(state.difference) !== 0 && "border-amber-500/50")}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Wallet className="h-4 w-4" />
                {state.bank_account}
              </CardTitle>
              <CardDescription>
                {day(state.from)} to {day(state.to)} · {state.statement_lines}{" "}
                statement lines, {state.matched} matched
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-3">
              <Fact label="Statement" value={rupees(state.statement_total)} />
              <Fact label="Ledger" value={rupees(state.ledger_total)} />
              <Fact
                label="Difference"
                value={rupees(state.difference)}
                tone={
                  Number(state.difference) !== 0 ? "text-amber-600" : undefined
                }
              />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  On the statement, not in the books
                </CardTitle>
                <CardDescription>
                  Usually a charge or a direct credit nobody knew about.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {state.unmatched_on_the_statement.length === 0 && (
                  <p className="py-2 text-muted-foreground">Nothing.</p>
                )}
                {state.unmatched_on_the_statement.map((row) => (
                  <div key={row.uuid} className="flex justify-between gap-2">
                    <span className="min-w-0 truncate">
                      {day(row.date)} · {row.description}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {rupees(row.amount)}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  In the books, not on the statement
                </CardTitle>
                <CardDescription>
                  Usually a cheque that has not cleared — or a payment that was
                  recorded and never actually made.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                {state.unmatched_in_the_ledger.length === 0 && (
                  <p className="py-2 text-muted-foreground">Nothing.</p>
                )}
                {state.unmatched_in_the_ledger.slice(0, 20).map((row) => (
                  <div key={row.uuid} className="flex justify-between gap-2">
                    <span className="min-w-0 truncate">
                      {day(row.date)} · {row.narration}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {rupees(row.amount)}
                    </span>
                  </div>
                ))}
                {state.unmatched_in_the_ledger.length > 20 && (
                  <p className="pt-1 text-xs text-muted-foreground">
                    and {state.unmatched_in_the_ledger.length - 20} more
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          <p className="text-xs text-muted-foreground">
            The statement is kept as its own record rather than imported into
            the ledger. Reconciliation is the comparison of two independent
            records; merging them would destroy the only thing that makes the
            exercise worth doing.
          </p>
        </>
      )}
    </div>
  );
}

function Fact({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("font-semibold tabular-nums", tone)}>Rs {value}</p>
    </div>
  );
}
