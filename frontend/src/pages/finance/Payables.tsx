/**
 * What the hospital owes: expenses claimed, and invoices from suppliers.
 *
 * **Six endpoints with no screen.** Claiming an expense, approving one,
 * recording a supplier invoice and approving that — all built, none reachable.
 * A hospital could keep a ledger it had no way of putting a bill into.
 *
 * **Both halves are a maker-checker pair, and the screen says so out loud.**
 * An expense cannot be approved by whoever claimed it; a supplier invoice needs
 * `purchase.approve`, which is a different permission from the one that records
 * it. Neither control is discoverable from a form with a Save button, so each
 * approval is a separate act with the reason for it written beside the button.
 *
 * **Approving a supplier invoice posts it in the same step, deliberately.** An
 * approved invoice that is not in the books is a liability the hospital does not
 * know it has, and the gap between two actions is exactly where that lives. The
 * screen therefore does not offer "approve" and "post" as separate buttons, even
 * though that would look more flexible.
 *
 * **Nothing here edits a posted document.** A mistake is reversed, and the
 * reversal is itself a fact worth seeing — the same rule the journal follows.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Receipt, Wallet } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Section, ScrollX, StatGrid } from "@/components/ui/layout";
import { EmptyState, TableSkeleton } from "@/components/ui/feedback";
import { StatTile } from "@/components/ui/data";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
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

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

type Account = {
  uuid: string;
  code: string;
  name: string;
  account_type: string;
  is_postable: boolean;
};

type Expense = {
  uuid: string;
  reference: string;
  facility: string;
  spent_on: string;
  account: string;
  account_name: string;
  cost_centre: string;
  description: string;
  amount: string;
  tax_amount: string;
  claimed_by_name: string;
  payment_method: string;
  receipt_number: string;
  has_receipt: boolean;
  status: string;
  approved_by_name: string;
  approved_at: string | null;
  rejection_reason: string;
};

type SupplierInvoice = {
  uuid: string;
  reference: string;
  supplier_invoice_number: string;
  supplier_name: string;
  facility: string;
  invoice_date: string;
  due_date: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  paid_amount: string;
  outstanding: string;
  is_overdue: boolean;
  status: string;
  approved_by_name: string;
  variance: string;
  variance_notes: string;
  notes: string;
};

type Facility = { uuid: string; name: string; status: string };

type Supplier = { uuid: string; code: string; name: string };

const MONEY = (value: string) =>
  Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 });

/* -------------------------------------------------------------------------- */
/* Expenses                                                                    */
/* -------------------------------------------------------------------------- */

export function ExpensesPanel({ facilityUuid }: { facilityUuid: string }) {
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [list, chart] = await Promise.allSettled([
      api.get<{ results: Expense[] }>("/finance/expenses/"),
      api.get<{ results: Account[] }>("/finance/accounts/?page_size=300"),
    ]);
    if (list.status === "fulfilled") setExpenses(list.value.results);
    if (chart.status === "fulfilled") {
      // Only postable accounts. A heading in the chart of accounts cannot hold
      // a posting, and offering one produces a refusal at save time for a
      // choice the screen invited.
      setAccounts(chart.value.results.filter((row) => row.is_postable));
    }
    if (list.status === "rejected") {
      const reason = list.reason;
      setProblem(reason instanceof ApiError ? reason.message : "Could not load.");
    } else {
      setProblem(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const approve = async (expense: Expense) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/finance/expenses/${expense.reference}/approve/`, {});
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not approve.");
    } finally {
      setBusy(false);
    }
  };

  const totals = useMemo(() => {
    const pending = expenses.filter((row) => row.status === "draft" || row.status === "submitted");
    return {
      waiting: pending.length,
      value: pending.reduce((sum, row) => sum + Number(row.amount), 0),
      noReceipt: pending.filter((row) => !row.has_receipt).length,
    };
  }, [expenses]);

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <StatGrid>
        <StatTile
          label="Waiting for approval"
          value={totals.waiting}
          icon={<Wallet className="h-4 w-4" />}
        />
        <StatTile label="Value waiting" value={MONEY(String(totals.value))} />
        <StatTile
          label="Without a receipt"
          value={totals.noReceipt}
          hint="claimed with nothing attached"
          intent={totals.noReceipt ? "bad" : "neutral"}
        />
        <StatTile label="Recorded" value={expenses.length} />
      </StatGrid>

      <Section
        title="Expenses"
        description="Money spent that is not a supplier invoice: taxi fares, small repairs, refreshments."
        actions={
          <Button size="sm" onClick={() => setClaiming((open) => !open)}>
            {claiming ? "Close" : "Claim an expense"}
          </Button>
        }
      >
        {claiming && (
          <ClaimForm
            accounts={accounts}
            facilityUuid={facilityUuid}
            onClaimed={() => {
              setClaiming(false);
              void load();
            }}
          />
        )}

        {loading ? (
          <TableSkeleton rows={5} />
        ) : expenses.length === 0 ? (
          <EmptyState
            illustration="money"
            title="Nothing claimed yet"
            description="An expense is money already spent. Recording it here puts it in the ledger once somebody other than the claimant approves it."
          />
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Spent on</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>Account</TableHead>
                  <TableHead>Claimed by</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {expenses.map((expense) => (
                  <TableRow key={expense.uuid}>
                    <TableCell className="font-mono text-xs">
                      {expense.reference}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {expense.spent_on}
                    </TableCell>
                    <TableCell className="max-w-[16rem] truncate">
                      {expense.description}
                      {!expense.has_receipt && (
                        <span className="ml-2 text-xs text-amber-600">
                          no receipt
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {expense.account_name}
                    </TableCell>
                    <TableCell>{expense.claimed_by_name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {MONEY(expense.amount)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          expense.status === "approved" ? "secondary" : "outline"
                        }
                      >
                        {expense.status}
                      </Badge>
                      {expense.approved_by_name && (
                        <div className="text-xs text-muted-foreground">
                          by {expense.approved_by_name}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {expense.status !== "approved" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => void approve(expense)}
                        >
                          <Check className="mr-1 h-4 w-4" />
                          Approve
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}

        <p className="text-xs text-muted-foreground">
          An expense cannot be approved by the person who claimed it. Approving
          posts it to the ledger in the same step.
        </p>
      </Section>
    </div>
  );
}

function ClaimForm({
  accounts,
  facilityUuid,
  onClaimed,
}: {
  accounts: Account[];
  facilityUuid: string;
  onClaimed: () => void;
}) {
  const [form, setForm] = useState({
    spent_on: new Date().toISOString().slice(0, 10),
    account: "",
    description: "",
    amount: "",
    tax_amount: "",
    cost_centre: "",
    payment_method: "cash",
    receipt_number: "",
    has_receipt: true,
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const set = (field: string, value: string | boolean) =>
    setForm((current) => ({ ...current, [field]: value }));

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/finance/expenses/", {
        ...form,
        facility: facilityUuid,
        tax_amount: form.tax_amount || "0",
      });
      onClaimed();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not record it.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2 lg:grid-cols-3">
      {problem && (
        <div className="sm:col-span-2 lg:col-span-3">
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="expense-date">Spent on</Label>
        <Input
          id="expense-date"
          type="date"
          value={form.spent_on}
          onChange={(event) => set("spent_on", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="expense-account">Account</Label>
        <Select
          id="expense-account"
          value={form.account}
          onChange={(event) => set("account", event.target.value)}
        >
          <option value="">— choose —</option>
          {accounts.map((account) => (
            <option key={account.uuid} value={account.uuid}>
              {account.code} · {account.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="expense-amount">Amount</Label>
        <Input
          id="expense-amount"
          type="number"
          value={form.amount}
          onChange={(event) => set("amount", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="expense-tax">Tax included</Label>
        <Input
          id="expense-tax"
          type="number"
          value={form.tax_amount}
          onChange={(event) => set("tax_amount", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="expense-cost-centre">Cost centre</Label>
        <Input
          id="expense-cost-centre"
          value={form.cost_centre}
          onChange={(event) => set("cost_centre", event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="expense-receipt">Receipt number</Label>
        <Input
          id="expense-receipt"
          value={form.receipt_number}
          onChange={(event) => set("receipt_number", event.target.value)}
        />
      </div>

      <div className="space-y-1.5 sm:col-span-2 lg:col-span-3">
        <Label htmlFor="expense-description">What it was for</Label>
        <Textarea
          id="expense-description"
          rows={2}
          value={form.description}
          onChange={(event) => set("description", event.target.value)}
        />
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.has_receipt}
          onChange={(event) => set("has_receipt", event.target.checked)}
        />
        A receipt is attached
      </label>

      <div className="sm:col-span-2 lg:col-span-3">
        <Button
          disabled={
            busy || !form.account || !form.amount || !form.description.trim()
          }
          onClick={() => void submit()}
        >
          Record the claim
        </Button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Supplier invoices                                                           */
/* -------------------------------------------------------------------------- */

export function SupplierInvoicesPanel({ facilityUuid }: { facilityUuid: string }) {
  const [invoices, setInvoices] = useState<SupplierInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.get<{ results: SupplierInvoice[] }>(
        "/finance/supplier-invoices/",
      );
      setInvoices(page.results);
      setProblem(null);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not load.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const approve = async (invoice: SupplierInvoice) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(
        `/finance/supplier-invoices/${invoice.reference}/approve/`,
        {},
      );
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not approve.");
    } finally {
      setBusy(false);
    }
  };

  const totals = useMemo(() => {
    const open = invoices.filter((row) => Number(row.outstanding) > 0);
    return {
      outstanding: open.reduce((sum, row) => sum + Number(row.outstanding), 0),
      overdue: open.filter((row) => row.is_overdue).length,
      draft: invoices.filter((row) => row.status === "draft").length,
      variances: invoices.filter((row) => Number(row.variance) !== 0).length,
    };
  }, [invoices]);

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <StatGrid>
        <StatTile
          label="Outstanding"
          value={MONEY(String(totals.outstanding))}
          hint="owed to suppliers"
          icon={<Receipt className="h-4 w-4" />}
        />
        <StatTile
          label="Overdue"
          value={totals.overdue}
          intent={totals.overdue ? "bad" : "good"}
        />
        <StatTile label="Awaiting approval" value={totals.draft} />
        <StatTile
          label="With a variance"
          value={totals.variances}
          hint="invoice against goods received"
          intent={totals.variances ? "bad" : "neutral"}
        />
      </StatGrid>

      <Section
        title="Supplier invoices"
        description="Bills from suppliers, matched against what was actually received."
        actions={
          <Button size="sm" onClick={() => setRecording((open) => !open)}>
            {recording ? "Close" : "Record an invoice"}
          </Button>
        }
      >
        {recording && (
          <InvoiceForm
            facilityUuid={facilityUuid}
            onRecorded={() => {
              setRecording(false);
              void load();
            }}
          />
        )}

        {loading ? (
          <TableSkeleton rows={5} />
        ) : invoices.length === 0 ? (
          <EmptyState
            illustration="money"
            title="No supplier invoices"
            description="A bill from a supplier is recorded here, matched against the goods receipt, and posted to the ledger when it is approved."
          />
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Their number</TableHead>
                  <TableHead>Due</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Outstanding</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoices.map((invoice) => (
                  <TableRow key={invoice.uuid}>
                    <TableCell className="font-mono text-xs">
                      {invoice.reference}
                    </TableCell>
                    <TableCell>{invoice.supplier_name}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {invoice.supplier_invoice_number}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-nowrap",
                        invoice.is_overdue && "font-medium text-destructive",
                      )}
                    >
                      {invoice.due_date}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {MONEY(invoice.total)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {MONEY(invoice.outstanding)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          invoice.status === "draft" ? "outline" : "secondary"
                        }
                      >
                        {invoice.status}
                      </Badge>
                      {Number(invoice.variance) !== 0 && (
                        <div className="text-xs text-amber-600">
                          variance {MONEY(invoice.variance)}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {invoice.status === "draft" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => void approve(invoice)}
                        >
                          <Check className="mr-1 h-4 w-4" />
                          Approve
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}

        <p className="text-xs text-muted-foreground">
          Approving posts the invoice to the ledger in the same step. An approved
          invoice that is not in the books is a liability nobody knows about.
        </p>
      </Section>
    </div>
  );
}

function InvoiceForm({
  facilityUuid,
  onRecorded,
}: {
  facilityUuid: string;
  onRecorded: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [form, setForm] = useState({
    supplier_uuid: "",
    supplier_invoice_number: "",
    invoice_date: today,
    due_date: today,
    subtotal: "",
    tax_amount: "",
    total: "",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    // **A supplier is chosen, not typed.** `supplier_uuid` is required, and
    // the model makes it unique with the invoice number -- which is what stops
    // the same bill being entered twice under two spellings of one supplier's
    // name. A free-text field would have produced a new supplier every time
    // somebody typed "Test Distributors Pvt." instead of "Test Distributors".
    void api
      .get<{ results: Supplier[] }>("/procurement/suppliers/?page_size=200")
      .then((page) => setSuppliers(page.results))
      .catch(() => setSuppliers([]));
  }, []);

  const set = (field: string, value: string) =>
    setForm((current) => ({ ...current, [field]: value }));

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const supplier = suppliers.find((row) => row.uuid === form.supplier_uuid);
      await api.post("/finance/supplier-invoices/", {
        ...form,
        supplier_name: supplier?.name ?? "",
        facility: facilityUuid,
        tax_amount: form.tax_amount || "0",
        // Computed rather than typed: a total that disagrees with its own
        // subtotal and tax is a document nobody can reconcile, and asking a
        // clerk to add up three numbers correctly every time is asking for the
        // one time they do not.
        total: String(Number(form.subtotal || 0) + Number(form.tax_amount || 0)),
      });
      onRecorded();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not record it.");
    } finally {
      setBusy(false);
    }
  };

  const total = Number(form.subtotal || 0) + Number(form.tax_amount || 0);

  return (
    <div className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2 lg:grid-cols-3">
      {problem && (
        <div className="sm:col-span-2 lg:col-span-3">
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="invoice-supplier">Supplier</Label>
        <Select
          id="invoice-supplier"
          value={form.supplier_uuid}
          onChange={(event) => set("supplier_uuid", event.target.value)}
        >
          <option value="">— choose —</option>
          {suppliers.map((supplier) => (
            <option key={supplier.uuid} value={supplier.uuid}>
              {supplier.name} ({supplier.code})
            </option>
          ))}
        </Select>
      </div>

      {[
        { id: "supplier_invoice_number", label: "Their invoice number", type: "text" },
        { id: "invoice_date", label: "Invoice date", type: "date" },
        { id: "due_date", label: "Due date", type: "date" },
        { id: "subtotal", label: "Subtotal", type: "number" },
        { id: "tax_amount", label: "Tax", type: "number" },
      ].map((field) => (
        <div key={field.id} className="space-y-1.5">
          <Label htmlFor={`invoice-${field.id}`}>{field.label}</Label>
          <Input
            id={`invoice-${field.id}`}
            type={field.type}
            value={form[field.id as keyof typeof form]}
            onChange={(event) => set(field.id, event.target.value)}
          />
        </div>
      ))}

      <div className="space-y-1.5 sm:col-span-2 lg:col-span-3">
        <Label htmlFor="invoice-notes">Notes</Label>
        <Textarea
          id="invoice-notes"
          rows={2}
          value={form.notes}
          onChange={(event) => set("notes", event.target.value)}
        />
      </div>

      <div className="flex items-center gap-4 sm:col-span-2 lg:col-span-3">
        <Button
          disabled={busy || !form.supplier_uuid || !form.subtotal}
          onClick={() => void submit()}
        >
          Record the invoice
        </Button>
        <span className="text-sm text-muted-foreground">
          Total <span className="font-medium tabular-nums">{MONEY(String(total))}</span>{" "}
          — subtotal plus tax, added up here rather than typed.
        </span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The tab                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Both halves of what the hospital owes, with the facility they belong to.
 *
 * The facility selector lives here rather than on the Finance screen because
 * the rest of that screen is organization-wide -- a trial balance and a period
 * are not per branch. An expense and a supplier invoice are: they are posted
 * against a facility, and a group running four branches needs to say which.
 */
export function PayablesPanel() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");

  useEffect(() => {
    void api
      .get<{ results: Facility[] }>("/org/facilities/")
      .then((page) => {
        const usable = page.results.filter((row) => row.status === "active");
        setFacilities(usable);
        if (usable[0]) setFacility(usable[0].uuid);
      })
      .catch(() => setFacilities([]));
  }, []);

  return (
    <div className="space-y-6">
      {facilities.length > 1 && (
        <div className="flex items-center gap-2">
          <Label htmlFor="payables-facility" className="text-sm">
            Facility
          </Label>
          <Select
            id="payables-facility"
            className="h-9 w-auto"
            value={facility}
            onChange={(event) => setFacility(event.target.value)}
          >
            {facilities.map((row) => (
              <option key={row.uuid} value={row.uuid}>
                {row.name}
              </option>
            ))}
          </Select>
        </div>
      )}

      <SupplierInvoicesPanel facilityUuid={facility} />
      <ExpensesPanel facilityUuid={facility} />
    </div>
  );
}
