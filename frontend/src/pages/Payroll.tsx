/**
 * Payroll: running one, and explaining it afterwards.
 *
 * The screen is arranged around one belief: **a payroll figure nobody can
 * explain is a payroll figure nobody should pay.** So every number leads
 * somewhere. A run opens to its component breakdown; a payslip shows the rate
 * and base each line came from; the tax opens to the band-by-band derivation,
 * because "why is my tax 4,200?" is asked by somebody holding the payslip and
 * has to be answerable from it.
 *
 * Three things the screen refuses to soften.
 *
 * **An approved run offers no edit button.** The lock is in the service layer,
 * but a control the UI still shows is a control users learn to distrust.
 *
 * **Held payslips are shown, with the reason.** An employee missing from a run
 * is a payroll nobody can reconcile; one shown as held with "no contract in
 * force" is a problem somebody can fix.
 *
 * **Employer cost is displayed beside net, never inside it.** It is what the
 * organization spends and not what anybody is paid, and mixing the two is how
 * a board is told the wrong salary bill.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Banknote,
  Calculator,
  CheckCircle2,
  ChevronRight,
  FileSpreadsheet,
  Landmark,
  Loader2,
  Lock,
  Percent,
  Play,
  Receipt,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  BankFileRow,
  ContributionScheme,
  Facility,
  Paginated,
  PaymentBatch,
  Payslip,
  PayslipSummary,
  PayrollRun,
  PayrollSummary,
  StatutoryReturn,
  TaxSlab,
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
} from "@/components/ui/primitives";

type Tab = "runs" | "mine" | "rates";

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: "runs", label: "Runs", icon: Calculator },
  { id: "mine", label: "My payslips", icon: Receipt },
  { id: "rates", label: "Rates", icon: Percent },
];

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const humanise = (value: string) => value.replace(/_/g, " ");

const STATUS_TONE: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  draft: "outline",
  calculated: "default",
  pending_approval: "default",
  approved: "secondary",
  paid: "secondary",
  cancelled: "destructive",
};

export default function PayrollPage() {
  const [tab, setTab] = useState<Tab>("runs");
  const [openRun, setOpenRun] = useState<string | null>(null);

  if (openRun) {
    return <RunDetail reference={openRun} onBack={() => setOpenRun(null)} />;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Payroll</h1>
        <p className="text-sm text-muted-foreground">
          What people earn, what is deducted, and what they are paid.
        </p>
      </div>

      <div className="flex gap-1 border-b">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
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

      {tab === "runs" && <Runs onOpen={setOpenRun} />}
      {tab === "mine" && <MyPayslips />}
      {tab === "rates" && <Rates />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Runs                                                                        */
/* -------------------------------------------------------------------------- */

function Runs({ onOpen }: { onOpen: (reference: string) => void }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [denied, setDenied] = useState(false);
  const [opening, setOpening] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await api.get<Paginated<PayrollRun>>("/payroll/runs/");
      setRuns(page.results);
      setDenied(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setDenied(true);
    }
  }, []);

  useEffect(() => {
    void load();
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .catch(() => setFacilities([]));
  }, [load]);

  if (denied) {
    return (
      <Alert>
        <Lock className="h-4 w-4" />
        <AlertTitle>Payroll is not visible to you</AlertTitle>
        <AlertDescription>
          Seeing what people are paid needs a separate permission from seeing
          the directory. Your own payslips are on the next tab.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <div className="flex justify-end">
        <Button size="sm" onClick={() => setOpening(true)}>
          <Play className="h-4 w-4" />
          Open a run
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Payroll runs</CardTitle>
          <CardDescription>
            One live run per facility per period. A second would pay everybody
            twice, and the way that happens is somebody clicking twice.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Period</TableHead>
                <TableHead className="text-right">People</TableHead>
                <TableHead className="text-right">Net</TableHead>
                <TableHead className="text-right">Total cost</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((row) => (
                <TableRow
                  key={row.uuid}
                  className="cursor-pointer"
                  onClick={() => onOpen(row.reference)}
                >
                  <TableCell className="font-medium">
                    {row.reference}
                    {row.corrects && (
                      <Badge variant="outline" className="ml-2">
                        supplementary
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {row.period_label}
                    <span className="block text-xs text-muted-foreground">
                      {row.facility_name}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.employee_count}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.net_total)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {rupees(row.total_cost)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                      {humanise(row.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ))}
              {runs.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No payroll has been run yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <p className="mt-3 text-xs text-muted-foreground">
            Total cost is net pay plus the employer's statutory contributions —
            what the organization spends, which is not what anybody is paid.
          </p>
        </CardContent>
      </Card>

      {opening && (
        <OpenRunDialog
          facilities={facilities}
          onClose={() => setOpening(false)}
          onOpened={(reference) => {
            setOpening(false);
            onOpen(reference);
          }}
          onProblem={setProblem}
        />
      )}
    </div>
  );
}

function OpenRunDialog({
  facilities,
  onClose,
  onOpened,
  onProblem,
}: {
  facilities: Facility[];
  onClose: () => void;
  onOpened: (reference: string) => void;
  onProblem: (message: string) => void;
}) {
  const now = new Date();
  const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
    .toISOString()
    .slice(0, 10);
  const [form, setForm] = useState({
    facility: facilities[0]?.uuid ?? "",
    period_start: firstOfMonth,
    period_end: now.toISOString().slice(0, 10),
    period_label: "",
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!form.facility && facilities[0]) {
      setForm((f) => ({ ...f, facility: facilities[0].uuid }));
    }
  }, [facilities, form.facility]);

  const submit = async () => {
    setBusy(true);
    try {
      const run = await api.post<PayrollRun>("/payroll/runs/", form);
      onOpened(run.reference);
    } catch (err) {
      onProblem(err instanceof ApiError ? err.message : "Not opened.");
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Open a payroll run</CardTitle>
          <CardDescription>
            Nothing is calculated yet. A run is a draft until you calculate it,
            and immutable once approved.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="p-facility">Facility</Label>
            <Select
              id="p-facility"
              value={form.facility}
              onChange={(event) =>
                setForm((f) => ({ ...f, facility: event.target.value }))
              }
            >
              {facilities.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="p-from">From</Label>
              <Input
                id="p-from"
                type="date"
                value={form.period_start}
                onChange={(event) =>
                  setForm((f) => ({ ...f, period_start: event.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-to">To</Label>
              <Input
                id="p-to"
                type="date"
                value={form.period_end}
                onChange={(event) =>
                  setForm((f) => ({ ...f, period_end: event.target.value }))
                }
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="p-label">Period name</Label>
            <Input
              id="p-label"
              placeholder="Shrawan 2083"
              value={form.period_label}
              onChange={(event) =>
                setForm((f) => ({ ...f, period_label: event.target.value }))
              }
            />
            <p className="text-xs text-muted-foreground">
              Payroll in Nepal runs on the Bikram Sambat month, so the period
              is named as well as dated.
            </p>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || !form.facility}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Open
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One run                                                                     */
/* -------------------------------------------------------------------------- */

function RunDetail({
  reference,
  onBack,
}: {
  reference: string;
  onBack: () => void;
}) {
  const [run, setRun] = useState<PayrollRun | null>(null);
  const [summary, setSummary] = useState<PayrollSummary | null>(null);
  const [statutory, setStatutory] = useState<StatutoryReturn | null>(null);
  const [slips, setSlips] = useState<PayslipSummary[]>([]);
  const [batches, setBatches] = useState<PaymentBatch[]>([]);
  const [openSlip, setOpenSlip] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [detail, sum, slipRows, batchRows] = await Promise.all([
      api.get<PayrollRun>(`/payroll/runs/${reference}/`),
      api.get<PayrollSummary>(`/payroll/runs/${reference}/summary/`),
      api.get<PayslipSummary[]>(`/payroll/runs/${reference}/payslips/`),
      api.get<PaymentBatch[]>(`/payroll/runs/${reference}/batches/`),
    ]);
    setRun(detail);
    setSummary(sum);
    setSlips(slipRows);
    setBatches(batchRows);
    if (["approved", "paid"].includes(detail.status)) {
      setStatutory(
        await api.get<StatutoryReturn>(`/payroll/runs/${reference}/statutory/`),
      );
    }
  }, [reference]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/payroll/runs/${reference}/${path}/`, body);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  if (!run || !summary) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← All runs
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {run.reference}
          </h1>
          <p className="text-sm text-muted-foreground">
            {run.period_label} · {run.facility_name} · {run.period_start} →{" "}
            {run.period_end}
          </p>
        </div>
        <Badge variant={STATUS_TONE[run.status] ?? "outline"}>
          {humanise(run.status)}
        </Badge>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {/* The workflow, as buttons that appear only when they apply. */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 pt-6">
          {run.status === "draft" && (
            <Button disabled={busy} onClick={() => void act("calculate")}>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Calculator className="h-4 w-4" />
              )}
              Calculate
            </Button>
          )}
          {run.status === "calculated" && (
            <>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void act("calculate")}
              >
                <Calculator className="h-4 w-4" />
                Recalculate
              </Button>
              <Button disabled={busy} onClick={() => void act("submit")}>
                Send for approval
              </Button>
            </>
          )}
          {run.status === "pending_approval" && (
            <>
              <Button
                disabled={busy}
                onClick={() => void act("approve", { notes: "Approved." })}
              >
                <BadgeCheck className="h-4 w-4" />
                Approve
              </Button>
              <span className="text-sm text-muted-foreground">
                Refused if you are the person who ran it.
              </span>
            </>
          )}
          {run.status === "approved" && (
            <>
              <Button
                disabled={busy}
                onClick={() => void act("batches", { method: "bank_transfer" })}
              >
                <Banknote className="h-4 w-4" />
                Prepare a payment batch
              </Button>
              <span className="flex items-center gap-1 text-sm text-muted-foreground">
                <Lock className="h-3.5 w-3.5" />
                Approved and immutable — correct it with a supplementary run.
              </span>
            </>
          )}
          {run.status === "paid" && (
            <span className="flex items-center gap-1 text-sm text-emerald-600">
              <CheckCircle2 className="h-4 w-4" />
              Paid{run.paid_at && ` on ${new Date(run.paid_at).toLocaleDateString()}`}
            </span>
          )}
          {run.approved_by_name && (
            <span className="ml-auto text-sm text-muted-foreground">
              Approved by {run.approved_by_name}
            </span>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="People" value={String(summary.employees)} />
        <Stat label="Gross" value={rupees(summary.gross)} />
        <Stat
          label="Deductions"
          value={rupees(summary.deductions)}
          hint={`incl. tax ${rupees(summary.tax)}`}
        />
        <Stat label="Net pay" value={rupees(summary.net)} />
        <Stat
          label="Total cost"
          value={rupees(summary.total_cost)}
          hint={`+${rupees(summary.employer_cost)} employer`}
        />
      </div>

      {summary.held > 0 && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {summary.held} {summary.held === 1 ? "payslip is" : "payslips are"}{" "}
            held
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-1 space-y-0.5">
              {summary.held_reasons.map(([name, reason]) => (
                <li key={name}>
                  <span className="font-medium">{name}</span> — {reason}
                </li>
              ))}
            </ul>
            They stay in the run rather than disappearing from it: a payroll
            with fewer people than the facility employs is one nobody can
            reconcile.
          </AlertDescription>
        </Alert>
      )}

      {summary.missing_bank_details > 0 && (
        <Alert>
          <Landmark className="h-4 w-4" />
          <AlertDescription>
            {summary.missing_bank_details} people have no bank account on
            record and cannot be paid by transfer.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Payslips</CardTitle>
            <CardDescription>
              Open one to see how every figure was arrived at.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Employee</TableHead>
                  <TableHead className="text-right">Days</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                  <TableHead className="text-right">Tax</TableHead>
                  <TableHead className="text-right">Net</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {slips.map((slip) => (
                  <TableRow
                    key={slip.uuid}
                    className={cn(
                      "cursor-pointer",
                      slip.is_held && "opacity-60",
                    )}
                    onClick={() => setOpenSlip(slip.reference)}
                  >
                    <TableCell>
                      <span className="font-medium">{slip.employee_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {slip.employee_code}
                        {slip.position_title && ` · ${slip.position_title}`}
                      </span>
                      {slip.is_held && (
                        <Badge variant="destructive" className="mt-1">
                          held: {slip.hold_reason}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {slip.payable_days}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(slip.gross)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(slip.tax)}
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {rupees(slip.net)}
                    </TableCell>
                  </TableRow>
                ))}
                {slips.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-10 text-center text-sm text-muted-foreground"
                    >
                      Nothing calculated yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <div className="space-y-4">
          {statutory && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">To remit</CardTitle>
                <CardDescription>
                  Filed separately and on different schedules, so shown
                  separately.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <Row label="Income tax" value={statutory.income_tax} />
                <Row
                  label="From employees"
                  value={statutory.employee_contributions}
                />
                <Row
                  label="From the employer"
                  value={statutory.employer_contributions}
                />
                <div className="flex justify-between border-t pt-2 font-medium">
                  <span>Contributions</span>
                  <span className="tabular-nums">
                    {rupees(statutory.total_contributions)}
                  </span>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">By component</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {summary.by_component.map((row) => (
                <div key={row.code} className="flex justify-between gap-2">
                  <span className="min-w-0 truncate text-muted-foreground">
                    {row.name}
                  </span>
                  <span
                    className={cn(
                      "tabular-nums",
                      row.component_type === "deduction" ||
                        row.component_type === "tax"
                        ? "text-destructive"
                        : row.component_type === "employer"
                          ? "text-muted-foreground"
                          : undefined,
                    )}
                  >
                    {rupees(row.total)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          {batches.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Payments</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {batches.map((batch) => (
                  <BatchRow key={batch.uuid} batch={batch} onDone={load} />
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {openSlip && (
        <PayslipDialog
          reference={openSlip}
          onClose={() => setOpenSlip(null)}
        />
      )}
    </div>
  );
}

function BatchRow({
  batch,
  onDone,
}: {
  batch: PaymentBatch;
  onDone: () => Promise<void>;
}) {
  const [rows, setRows] = useState<BankFileRow[] | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="font-medium">{batch.reference}</span>
          <span className="block text-xs text-muted-foreground">
            {batch.count} payslips · {humanise(batch.method)}
          </span>
        </div>
        <span className="tabular-nums">{rupees(batch.total)}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            void api
              .get<BankFileRow[]>(`/payroll/batches/${batch.reference}/rows/`)
              .then(setRows)
          }
        >
          <FileSpreadsheet className="h-3.5 w-3.5" />
          Rows
        </Button>
        {batch.status !== "confirmed" && (
          <Button
            size="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.post(
                  `/payroll/batches/${batch.reference}/confirm/`,
                  {},
                );
                await onDone();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            Confirm paid
          </Button>
        )}
        {batch.status === "confirmed" && (
          <Badge variant="secondary">confirmed</Badge>
        )}
      </div>

      {rows && (
        <ul className="mt-2 space-y-1 border-t pt-2 text-xs">
          {rows.map((row) => (
            <li
              key={row.reference}
              className={cn("flex justify-between gap-2", row.problem && "text-destructive")}
            >
              <span className="min-w-0 truncate">
                {row.employee_name}
                {row.problem && ` — ${row.problem}`}
              </span>
              <span className="tabular-nums">{row.amount}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One payslip                                                                 */
/* -------------------------------------------------------------------------- */

function PayslipDialog({
  reference,
  onClose,
}: {
  reference: string;
  onClose: () => void;
}) {
  const [slip, setSlip] = useState<Payslip | null>(null);
  const [showTax, setShowTax] = useState(false);

  useEffect(() => {
    void api
      .get<Payslip>(`/payroll/payslips/${reference}/`)
      .then(setSlip)
      .catch(() => setSlip(null));
  }, [reference]);

  if (!slip) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <Loader2 className="h-6 w-6 animate-spin text-white" />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-2xl">
        <CardHeader>
          <CardTitle>{slip.employee_name}</CardTitle>
          <CardDescription>
            {slip.reference} · {slip.period_label}
            {slip.position_title && ` · ${slip.position_title}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {slip.is_held && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Held</AlertTitle>
              <AlertDescription>{slip.hold_reason}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-3 rounded-md bg-muted/40 p-3 text-sm sm:grid-cols-4">
            <Fact label="Payable days" value={slip.payable_days} />
            <Fact label="Present" value={slip.days_present} />
            <Fact label="Paid leave" value={slip.days_paid_leave} />
            <Fact
              label="Unpaid / absent"
              value={`${slip.days_unpaid_leave} / ${slip.days_absent}`}
            />
          </div>

          <PayslipLines slip={slip} />

          {Number(slip.tax) > 0 && (
            <div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowTax((value) => !value)}
              >
                <Percent className="h-3.5 w-3.5" />
                {showTax ? "Hide" : "How was the tax worked out?"}
              </Button>
              {showTax && <TaxWorkings slip={slip} />}
            </div>
          )}

          <Button variant="outline" className="w-full" onClick={onClose}>
            Close
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function PayslipLines({ slip }: { slip: Payslip }) {
  const earnings = slip.lines.filter((line) =>
    ["earning", "reimbursement"].includes(line.component_type),
  );
  const deductions = slip.lines.filter((line) =>
    ["deduction", "tax"].includes(line.component_type),
  );
  const employer = slip.lines.filter(
    (line) => line.component_type === "employer",
  );

  return (
    <div className="space-y-3 text-sm">
      <Group title="Earnings" lines={earnings} />
      <Group title="Deductions" lines={deductions} negative />

      <div className="flex justify-between border-t pt-2 text-base font-semibold">
        <span>Net pay</span>
        <span className="tabular-nums">{rupees(slip.net)}</span>
      </div>

      {employer.length > 0 && (
        <>
          <Group title="Paid by the employer" lines={employer} muted />
          <p className="text-xs text-muted-foreground">
            Not deducted from pay and not part of net — a cost to the
            organization, shown because it is remitted with the same return.
          </p>
        </>
      )}
    </div>
  );
}

function Group({
  title,
  lines,
  negative,
  muted,
}: {
  title: string;
  lines: Payslip["lines"];
  negative?: boolean;
  muted?: boolean;
}) {
  if (lines.length === 0) return null;
  const total = lines.reduce((sum, line) => sum + Number(line.amount), 0);
  return (
    <div>
      <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <ul className="space-y-1">
        {lines.map((line) => (
          <li key={line.uuid} className="flex justify-between gap-3">
            <span className={cn("min-w-0", muted && "text-muted-foreground")}>
              {line.name}
              {line.explanation && (
                <span className="block text-xs text-muted-foreground">
                  {line.explanation}
                </span>
              )}
            </span>
            <span
              className={cn(
                "shrink-0 tabular-nums",
                negative && "text-destructive",
                muted && "text-muted-foreground",
              )}
            >
              {negative ? "−" : ""}
              {rupees(line.amount)}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-1 flex justify-between border-t pt-1 font-medium">
        <span className={cn(muted && "text-muted-foreground")}>{title}</span>
        <span className={cn("tabular-nums", muted && "text-muted-foreground")}>
          {negative ? "−" : ""}
          {rupees(total)}
        </span>
      </div>
    </div>
  );
}

function TaxWorkings({ slip }: { slip: Payslip }) {
  const workings = slip.tax_workings;
  if (!workings || !workings.bands) return null;

  return (
    <div className="mt-3 space-y-3 rounded-md border p-3 text-sm">
      <p className="text-xs text-muted-foreground">
        A progressive rate applied to one month's pay would put everybody in
        the wrong band twelve times over, so the tax is computed on the
        projected year and divided back down.
      </p>

      <div className="space-y-1">
        <Row label="Annual taxable pay" value={workings.annual_gross ?? "0"} />
        {workings.retirement && (
          <Row
            label={`Retirement contribution (capped by the ${workings.retirement.binding_cap})`}
            value={`−${workings.retirement.deductible}`}
          />
        )}
        {workings.insurance && Number(workings.insurance.total) > 0 && (
          <Row
            label="Insurance premiums"
            value={`−${workings.insurance.total}`}
          />
        )}
        {Number(workings.remote_area_allowance ?? 0) > 0 && (
          <Row
            label="Remote-area allowance"
            value={`−${workings.remote_area_allowance}`}
          />
        )}
        <div className="flex justify-between border-t pt-1 font-medium">
          <span>Taxable income</span>
          <span className="tabular-nums">
            {rupees(workings.taxable_income ?? "0")}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Band</TableHead>
              <TableHead className="text-right">Taxed</TableHead>
              <TableHead className="text-right">Rate</TableHead>
              <TableHead className="text-right">Tax</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workings.bands.map((band) => (
              <TableRow key={band.band}>
                <TableCell className="text-xs">
                  {band.band}
                  {band.waived && (
                    <span className="block text-emerald-600">
                      {band.waiver_reason}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {Number(band.amount_taxed).toLocaleString("en-IN")}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {band.rate_percent}%
                </TableCell>
                <TableCell
                  className={cn(
                    "text-right tabular-nums",
                    band.waived && "text-emerald-600 line-through",
                  )}
                >
                  {Number(band.tax).toLocaleString("en-IN")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex justify-between border-t pt-2 font-medium">
        <span>Annual tax ÷ {workings.months_projected ?? 12} months</span>
        <span className="tabular-nums">{rupees(slip.tax)}</span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* My payslips                                                                 */
/* -------------------------------------------------------------------------- */

function MyPayslips() {
  const [slips, setSlips] = useState<Payslip[]>([]);
  const [noRecord, setNoRecord] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Payslip[] | null>("/payroll/payslips/mine/")
      .then((rows) => {
        if (rows === null) setNoRecord(true);
        else setSlips(rows);
      })
      .catch(() => setNoRecord(true));
  }, []);

  if (noRecord) {
    return (
      <Alert>
        <Users className="h-4 w-4" />
        <AlertTitle>You have no employee record</AlertTitle>
        <AlertDescription>
          Payslips hang off the employee record, and not every login has one.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">My payslips</CardTitle>
          <CardDescription>
            Only approved runs. A draft payslip is a working figure and showing
            it would have you querying a number that is about to change.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Period</TableHead>
                <TableHead className="text-right">Gross</TableHead>
                <TableHead className="text-right">Deductions</TableHead>
                <TableHead className="text-right">Tax</TableHead>
                <TableHead className="text-right">Net</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {slips.map((slip) => (
                <TableRow
                  key={slip.uuid}
                  className="cursor-pointer"
                  onClick={() => setOpen(slip.reference)}
                >
                  <TableCell>
                    <span className="font-medium">{slip.period_label}</span>
                    <span className="block text-xs text-muted-foreground">
                      {slip.reference}
                    </span>
                    {slip.is_held && (
                      <Badge variant="destructive" className="mt-1">
                        held: {slip.hold_reason}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(slip.gross)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(slip.deductions)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(slip.tax)}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {rupees(slip.net)}
                  </TableCell>
                </TableRow>
              ))}
              {slips.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No payslips yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {open && (
        <PayslipDialog reference={open} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Rates                                                                       */
/* -------------------------------------------------------------------------- */

function Rates() {
  const [slabs, setSlabs] = useState<TaxSlab[]>([]);
  const [schemes, setSchemes] = useState<ContributionScheme[]>([]);
  const [regime, setRegime] = useState<"individual" | "couple">("individual");
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    void Promise.all([
      api.get<Paginated<TaxSlab>>("/payroll/tax-slabs/"),
      api.get<Paginated<ContributionScheme>>("/payroll/schemes/"),
    ])
      .then(([slabPage, schemePage]) => {
        setSlabs(slabPage.results);
        setSchemes(schemePage.results);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  if (denied) {
    return (
      <Alert>
        <Lock className="h-4 w-4" />
        <AlertDescription>
          The rate tables are visible to payroll staff only.
        </AlertDescription>
      </Alert>
    );
  }

  const shown = slabs.filter((row) => row.regime === regime);

  return (
    <div className="space-y-4">
      <Alert>
        <Percent className="h-4 w-4" />
        <AlertTitle>These are rows, not code</AlertTitle>
        <AlertDescription>
          Nepal's slabs move with every budget. Holding them as data means a
          rate change is an edit, not a deployment — and last year's payroll
          stays explicable against last year's table.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="text-base">Income tax bands</CardTitle>
            <CardDescription>
              Each band taxes only the part of income inside it.
            </CardDescription>
          </div>
          <Select
            className="h-9 w-auto"
            value={regime}
            onChange={(event) =>
              setRegime(event.target.value as "individual" | "couple")
            }
          >
            <option value="individual">Individual</option>
            <option value="couple">Married, assessed jointly</option>
          </Select>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Band</TableHead>
                <TableHead className="text-right">From</TableHead>
                <TableHead className="text-right">To</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                <TableHead>Year</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((row) => (
                <TableRow key={row.uuid}>
                  <TableCell>
                    {row.label || `Band ${row.sequence}`}
                    {row.waived_for_ssf_contributors && (
                      <span className="block text-xs text-emerald-600">
                        waived for SSF contributors — the contribution replaces
                        it
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Number(row.lower_bound).toLocaleString("en-IN")}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.upper_bound
                      ? Number(row.upper_bound).toLocaleString("en-IN")
                      : "—"}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {row.rate_percent}%
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {row.fiscal_year}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Contribution schemes</CardTitle>
          <CardDescription>
            Computed on basic salary, not gross. On gross they
            over-contribute for everybody, every month.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scheme</TableHead>
                <TableHead className="text-right">Employee</TableHead>
                <TableHead className="text-right">Employer</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead>Base</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schemes.map((row) => (
                <TableRow key={row.uuid}>
                  <TableCell>
                    <span className="font-medium">{row.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {row.fiscal_year}
                      {row.replaces_social_security_tax &&
                        " · replaces the 1% social security tax"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.employee_percent}%
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.employer_percent}%
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {row.total_percent}%
                  </TableCell>
                  <TableCell className="text-xs">
                    {row.on_basic ? "Basic" : "Gross"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bits                                                                        */
/* -------------------------------------------------------------------------- */

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="min-w-0 text-muted-foreground">{label}</span>
      <span className="shrink-0 tabular-nums">
        {value.startsWith("−")
          ? `−${rupees(value.slice(1))}`
          : rupees(value)}
      </span>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="font-medium tabular-nums">{value}</p>
    </div>
  );
}
