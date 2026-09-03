/**
 * Claims.
 *
 * The screen is built around one observation: the hospital's claim and the
 * payer's answer are different records, and the gap between them is the
 * business. So nothing here shows a single "amount" — every claim carries all
 * four figures side by side, and the shortfall between claimed and approved is
 * drawn as a number rather than left to be worked out.
 *
 * Three things it refuses to soften.
 *
 * **The submission deadline is a countdown, not a discovery.** Every claim
 * shows how many days are left in its own payer's window, in amber under a
 * week and red once gone. Missing it is the commonest way a valid claim
 * becomes worthless.
 *
 * **A deduction cannot be recorded without a reason from the list.** The
 * dialog serves the vocabulary from the API rather than hard-coding it, and
 * the button stays disabled until every deducted line has one.
 *
 * **The claim's history is the claim.** A claim is a conversation conducted
 * over months by people who leave, so the detail leads with the event
 * timeline and not with the current status.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CalendarClock,
  ClipboardCheck,
  FileWarning,
  Gavel,
  Loader2,
  ShieldCheck,
  TrendingDown,
  Wallet,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Claim,
  ClaimSummary,
  ClaimsAgeing,
  DeductionAnalysis,
  DeductionReason,
  ExpiringPreAuth,
  Paginated,
  PayerPerformance,
  PreAuthorisation,
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

type Tab = "claims" | "preauth" | "payers" | "analysis";

const TABS: { id: Tab; label: string; icon: typeof Wallet }[] = [
  { id: "claims", label: "Claims", icon: Wallet },
  { id: "preauth", label: "Pre-authorisations", icon: ShieldCheck },
  { id: "payers", label: "Payers", icon: ClipboardCheck },
  { id: "analysis", label: "Why we are cut", icon: TrendingDown },
];

const STATUS_TONE: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  draft: "outline",
  submitted: "secondary",
  queried: "default",
  approved: "secondary",
  partially_approved: "default",
  rejected: "destructive",
  appealed: "default",
  settled: "secondary",
  written_off: "destructive",
};

const rupees = (value: string | number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
};

const humanise = (value: string) => value.replace(/_/g, " ");

const day = (value: string | null) =>
  value
    ? new Date(value).toLocaleDateString([], {
        day: "2-digit",
        month: "short",
        year: "2-digit",
      })
    : "—";

export default function ClaimsPage() {
  const [tab, setTab] = useState<Tab>("claims");
  const [open, setOpen] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [expiring, setExpiring] = useState<ExpiringPreAuth[]>([]);

  const loadExpiring = useCallback(() => {
    void api
      .get<ExpiringPreAuth[]>("/insurance/preauthorisations/expiring/?days=7")
      .then(setExpiring)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  useEffect(loadExpiring, [loadExpiring]);

  if (denied) {
    return (
      <Alert>
        <Wallet className="h-4 w-4" />
        <AlertTitle>Claims are not visible to you</AlertTitle>
        <AlertDescription>
          Seeing what payers owe needs billing permissions.
        </AlertDescription>
      </Alert>
    );
  }

  if (open) {
    return <ClaimDetail reference={open} onBack={() => setOpen(null)} />;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Claims</h1>
        <p className="text-sm text-muted-foreground">
          What was asked for, what was allowed, and the difference.
        </p>
      </div>

      {/* Predictable a week ahead, so it is said a week ahead. */}
      {expiring.length > 0 && (
        <Alert variant="destructive">
          <CalendarClock className="h-4 w-4" />
          <AlertTitle>
            {expiring.length} approval{expiring.length === 1 ? "" : "s"} about
            to become worthless
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-1 space-y-0.5">
              {expiring.slice(0, 5).map((row) => (
                <li key={row.reference}>
                  {row.reference} · {row.patient} · {row.treatment} —{" "}
                  {row.expired
                    ? `expired ${day(row.valid_until)}`
                    : `${row.days_left} day${row.days_left === 1 ? "" : "s"} left`}
                </li>
              ))}
            </ul>
            Treating against an expired approval is rejected as unauthorised.
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

      {tab === "claims" && <ClaimList onOpen={setOpen} />}
      {tab === "preauth" && <PreAuths />}
      {tab === "payers" && <Payers />}
      {tab === "analysis" && <Analysis />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The list                                                                    */
/* -------------------------------------------------------------------------- */

function ClaimList({ onOpen }: { onOpen: (reference: string) => void }) {
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    void api
      .get<Paginated<ClaimSummary>>(
        `/insurance/claims/${status ? `?status=${status}` : ""}`,
      )
      .then((page) => setClaims(page.results))
      .catch(() => setClaims([]))
      .finally(() => setLoading(false));
  }, [status]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Label htmlFor="c-status" className="text-sm">
          Status
        </Label>
        <Select
          id="c-status"
          className="h-9 w-auto"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">All</option>
          {[
            "draft",
            "submitted",
            "queried",
            "approved",
            "partially_approved",
            "rejected",
            "appealed",
            "settled",
            "written_off",
          ].map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </Select>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Claim</TableHead>
                  <TableHead>Payer</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Claimed</TableHead>
                  <TableHead className="text-right">Approved</TableHead>
                  <TableHead className="text-right">Cut</TableHead>
                  <TableHead className="text-right">Settled</TableHead>
                  <TableHead>Deadline</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {claims.map((claim) => (
                  <TableRow
                    key={claim.uuid}
                    className="cursor-pointer"
                    onClick={() => onOpen(claim.reference)}
                  >
                    <TableCell>
                      <span className="font-mono text-xs">
                        {claim.reference}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {claim.patient_name} · {claim.invoice_number}
                      </span>
                    </TableCell>
                    <TableCell className="max-w-[10rem] truncate">
                      {claim.payer_name}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[claim.status] ?? "outline"}>
                        {humanise(claim.status)}
                      </Badge>
                      {claim.submission_count > 1 && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          ×{claim.submission_count}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(claim.claimed_amount)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(claim.approved_amount)}
                      {Number(claim.shortfall) > 0 &&
                        claim.status !== "submitted" && (
                          <span className="block text-xs text-destructive">
                            −{rupees(claim.shortfall)}
                          </span>
                        )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {Number(claim.deducted_amount) > 0
                        ? rupees(claim.deducted_amount)
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(claim.settled_amount)}
                    </TableCell>
                    <TableCell>
                      <Deadline deadline={claim.deadline} status={claim.status} />
                    </TableCell>
                  </TableRow>
                ))}
                {claims.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className="py-10 text-center text-sm text-muted-foreground"
                    >
                      {loading ? (
                        <Loader2 className="inline h-4 w-4 animate-spin" />
                      ) : (
                        "No claims."
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Claimed, approved, cut and settled are four different numbers, shown
        together on purpose. The differences between them are the entire
        subject of the hospital's relationship with the payer.
      </p>
    </div>
  );
}

function Deadline({
  deadline,
  status,
}: {
  deadline: { days_left: number; expired: boolean; urgent: boolean; deadline: string };
  status: string;
}) {
  // Once a claim is out of the door the window no longer matters, and showing
  // a red countdown on a settled claim would train people to ignore red.
  if (!["draft"].includes(status)) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  if (deadline.expired) {
    return (
      <span className="text-xs font-medium text-destructive">
        closed {day(deadline.deadline)}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "text-xs tabular-nums",
        deadline.urgent ? "font-medium text-destructive" : "text-muted-foreground",
      )}
    >
      {deadline.days_left}d left
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* One claim                                                                   */
/* -------------------------------------------------------------------------- */

function ClaimDetail({
  reference,
  onBack,
}: {
  reference: string;
  onBack: () => void;
}) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [dialog, setDialog] = useState<
    null | "response" | "settle" | "appeal" | "writeoff" | "query"
  >(null);

  const load = useCallback(async () => {
    setClaim(await api.get<Claim>(`/insurance/claims/${reference}/`));
  }, [reference]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/insurance/claims/${reference}/${path}/`, body);
      await load();
      return true;
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!claim) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back to the claims
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {claim.reference}
            <Badge
              variant={STATUS_TONE[claim.status] ?? "outline"}
              className="ml-2 align-middle"
            >
              {humanise(claim.status)}
            </Badge>
          </h1>
          <p className="text-sm text-muted-foreground">
            {claim.patient_name} · {claim.patient_mrn} · {claim.payer_name}
            {claim.policy_number && ` · ${claim.policy_number}`}
          </p>
          <p className="text-sm">
            {claim.diagnosis} · treated {day(claim.service_date)}
            {claim.invoice_number && ` · ${claim.invoice_number}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {claim.status === "draft" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void act("submit")}
            >
              Submit
            </Button>
          )}
          {["submitted", "queried"].includes(claim.status) && (
            <>
              <Button size="sm" onClick={() => setDialog("response")}>
                Record the answer
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setDialog("query")}
              >
                Log a query
              </Button>
            </>
          )}
          {["rejected", "partially_approved"].includes(claim.status) && (
            <Button size="sm" onClick={() => setDialog("appeal")}>
              <Gavel className="h-4 w-4" />
              Appeal
            </Button>
          )}
          {["approved", "partially_approved"].includes(claim.status) &&
            Number(claim.outstanding) > 0 && (
              <Button size="sm" onClick={() => setDialog("settle")}>
                Record a settlement
              </Button>
            )}
          {claim.status !== "written_off" && claim.status !== "settled" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDialog("writeoff")}
            >
              <Ban className="h-4 w-4" />
              Write off
            </Button>
          )}
        </div>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {claim.status === "draft" && claim.deadline.expired && (
        <Alert variant="destructive">
          <CalendarClock className="h-4 w-4" />
          <AlertTitle>The submission window has closed</AlertTitle>
          <AlertDescription>
            {claim.payer_name} allows {claim.deadline.window_days} days from
            the date of service; that closed on {day(claim.deadline.deadline)}.
            Submitting now will be rejected as late.
          </AlertDescription>
        </Alert>
      )}

      {claim.status === "queried" && (
        <Alert>
          <FileWarning className="h-4 w-4" />
          <AlertTitle>The payer has asked something</AlertTitle>
          <AlertDescription>
            {claim.query_text}
            <span className="block text-xs">
              Raised {day(claim.query_raised_at)} — the claim is neither being
              processed nor rejected; the hospital owes an answer.
            </span>
          </AlertDescription>
        </Alert>
      )}

      {claim.rejection_reason && (
        <Alert variant="destructive">
          <Ban className="h-4 w-4" />
          <AlertTitle>Rejected</AlertTitle>
          <AlertDescription>{claim.rejection_reason}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Fact label="Claimed" value={rupees(claim.claimed_amount)} />
        <Fact
          label="Approved"
          value={rupees(claim.approved_amount)}
          hint={
            Number(claim.shortfall) > 0
              ? `${rupees(claim.shortfall)} short`
              : undefined
          }
          tone={Number(claim.shortfall) > 0 ? "text-destructive" : undefined}
        />
        <Fact
          label="Deducted"
          value={rupees(claim.deducted_amount)}
          hint="with reasons"
        />
        <Fact label="Settled" value={rupees(claim.settled_amount)} />
        <Fact
          label="Patient owes"
          value={rupees(claim.patient_liability)}
          hint="quoted at the time"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">The bill, line by line</CardTitle>
            <CardDescription>
              Copied onto the claim rather than referenced. The invoice is a
              statutory document that cannot change; the payer's decision has
              to live somewhere that can.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Claimed</TableHead>
                  <TableHead className="text-right">Allowed</TableHead>
                  <TableHead>Cut because</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {claim.lines.map((line) => (
                  <TableRow
                    key={line.uuid}
                    className={cn(
                      Number(line.deducted_amount) > 0 && "bg-destructive/5",
                    )}
                  >
                    <TableCell className="max-w-[14rem] truncate">
                      {line.description}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {humanise(line.category)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(line.claimed_amount)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(line.approved_amount)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {line.deduction_reason ? (
                        <>
                          <span className="text-destructive">
                            {humanise(line.deduction_reason)}
                          </span>
                          {line.deduction_notes && (
                            <span className="block text-muted-foreground">
                              {line.deduction_notes}
                            </span>
                          )}
                        </>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">What has happened</CardTitle>
            <CardDescription>
              A claim is a conversation conducted over months by people who
              leave. The status says where it is; this says how it got there.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="relative space-y-3 border-l pl-5">
              {claim.events.map((event, index) => (
                <li key={index} className="relative text-sm">
                  <span className="absolute -left-[1.45rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" />
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{humanise(event.event)}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {day(event.happened_at)}
                    </span>
                  </div>
                  {event.detail && (
                    <p className="text-xs text-muted-foreground">
                      {event.detail}
                    </p>
                  )}
                  {event.amount && (
                    <p className="text-xs tabular-nums">
                      Rs {rupees(event.amount)}
                    </p>
                  )}
                  {event.actor_name && (
                    <p className="text-xs text-muted-foreground">
                      {event.actor_name}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      {dialog === "response" && (
        <ResponseDialog
          claim={claim}
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await act("response", body)) setDialog(null);
          }}
        />
      )}
      {dialog === "settle" && (
        <AmountDialog
          title="Record a settlement"
          description="Part settlements are normal — a payer pays a batch with one transfer and short-pays some of them."
          maximum={claim.outstanding}
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (amount, note) => {
            if (
              await act("settle", { amount, payment_reference: note })
            )
              setDialog(null);
          }}
        />
      )}
      {dialog === "appeal" && (
        <ReasonDialog
          title="Appeal"
          description="Its own state, so the appeal rate is countable. A hospital that never appeals is one whose deductions are never tested."
          placeholder="Room rate was pre-agreed in the tariff dated 12 Shrawan."
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            if (await act("appeal", { reason })) setDialog(null);
          }}
        />
      )}
      {dialog === "query" && (
        <ReasonDialog
          title="Log the payer's query"
          description="A queried claim is neither being processed nor rejected. Recording it is how it stops sitting for four months."
          placeholder="Discharge summary and operation notes not attached."
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            if (await act("query", { reason })) setDialog(null);
          }}
        />
      )}
      {dialog === "writeoff" && (
        <ReasonDialog
          title="Write this claim off"
          description="An explicit outcome. A claim quietly abandoned is revenue nobody records losing, and the annual write-off per payer decides whether to keep the contract."
          placeholder="Appeal refused twice; below the cost of pursuing it."
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (reason) => {
            if (await act("write-off", { reason })) setDialog(null);
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Dialogs                                                                     */
/* -------------------------------------------------------------------------- */

function Shell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-2xl">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">{children}</CardContent>
      </Card>
    </div>
  );
}

function ResponseDialog({
  claim,
  busy,
  onClose,
  onSubmit,
}: {
  claim: Claim;
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [reasons, setReasons] = useState<DeductionReason[]>([]);
  const [rows, setRows] = useState<Record<string, { amount: string; reason: string; notes: string }>>(
    {},
  );
  const [rejecting, setRejecting] = useState(false);
  const [rejection, setRejection] = useState("");
  const [payerReference, setPayerReference] = useState(claim.payer_reference);

  useEffect(() => {
    void api
      .get<DeductionReason[]>("/insurance/reports/?report=reasons")
      .then(setReasons)
      .catch(() => setReasons([]));
  }, []);

  const deductions = useMemo(
    () =>
      Object.entries(rows)
        .filter(([, row]) => Number(row.amount) > 0)
        .map(([uuid, row]) => ({
          line: uuid,
          amount: row.amount,
          reason: row.reason,
          notes: row.notes,
        })),
    [rows],
  );

  // The same rule the service enforces, shown while somebody types: a
  // deduction nobody can aggregate cannot be argued with.
  const missingReasons = deductions.filter((row) => !row.reason);
  const usable = rejecting
    ? rejection.trim().length > 5
    : missingReasons.length === 0;

  const setRow = (uuid: string, key: string, value: string) =>
    setRows((current) => ({
      ...current,
      [uuid]: {
        ...{ amount: "", reason: "", notes: "" },
        ...current[uuid],
        [key]: value,
      },
    }));

  return (
    <Shell
      title={`What ${claim.payer_name} decided`}
      description="Line by line. Every deduction needs a reason from the list, because the only useful thing about a deduction is the aggregate."
    >
      <div className="space-y-1">
        <Label htmlFor="r-ref">Their reference</Label>
        <Input
          id="r-ref"
          value={payerReference}
          onChange={(event) => setPayerReference(event.target.value)}
          placeholder="SHK/CLM/2026/1182"
        />
      </div>

      {rejecting ? (
        <div className="space-y-2">
          <Alert variant="destructive">
            <Ban className="h-4 w-4" />
            <AlertTitle>Recording an outright rejection</AlertTitle>
            <AlertDescription>
              The payer's own words, so that an appeal has something to argue
              against.
            </AlertDescription>
          </Alert>
          <Textarea
            rows={3}
            value={rejection}
            onChange={(event) => setRejection(event.target.value)}
            placeholder="Treatment not covered: condition within the waiting period."
          />
        </div>
      ) : (
        <div className="space-y-2">
          {claim.lines.map((line) => {
            const row = rows[line.uuid] ?? { amount: "", reason: "", notes: "" };
            const cut = Number(row.amount) > 0;
            return (
              <div
                key={line.uuid}
                className={cn(
                  "rounded-md border p-2",
                  cut && !row.reason && "border-destructive/60",
                )}
              >
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate">{line.description}</span>
                  <span className="shrink-0 tabular-nums">
                    {rupees(line.claimed_amount)}
                  </span>
                </div>
                <div className="mt-1 grid gap-2 sm:grid-cols-[7rem_1fr]">
                  <Input
                    className="h-8"
                    inputMode="decimal"
                    placeholder="Cut"
                    value={row.amount}
                    onChange={(event) =>
                      setRow(line.uuid, "amount", event.target.value)
                    }
                  />
                  <Select
                    className="h-8"
                    aria-label="Reason"
                    disabled={!cut}
                    value={row.reason}
                    onChange={(event) =>
                      setRow(line.uuid, "reason", event.target.value)
                    }
                  >
                    <option value="">Why was it cut?</option>
                    {reasons.map((reason) => (
                      <option key={reason.key} value={reason.key}>
                        {reason.label}
                      </option>
                    ))}
                  </Select>
                </div>
                {cut && !row.reason && (
                  <p className="mt-1 text-xs text-destructive">
                    A deduction without a reason is a number nobody can argue
                    with and nobody can aggregate.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex gap-2">
        <Button
          variant="outline"
          className="flex-1"
          onClick={() => (rejecting ? setRejecting(false) : onClose())}
        >
          {rejecting ? "Back" : "Cancel"}
        </Button>
        {!rejecting && (
          <Button variant="outline" onClick={() => setRejecting(true)}>
            Rejected outright
          </Button>
        )}
        <Button
          className="flex-1"
          disabled={busy || !usable}
          onClick={() =>
            onSubmit(
              rejecting
                ? {
                    approved_amount: "0",
                    rejection_reason: rejection,
                    payer_reference: payerReference,
                  }
                : { deductions, payer_reference: payerReference },
            )
          }
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Record
        </Button>
      </div>
    </Shell>
  );
}

function AmountDialog({
  title,
  description,
  maximum,
  busy,
  onClose,
  onSubmit,
}: {
  title: string;
  description: string;
  maximum: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (amount: string, note: string) => void;
}) {
  const [amount, setAmount] = useState(maximum);
  const [note, setNote] = useState("");
  const over = Number(amount) > Number(maximum);

  return (
    <Shell title={title} description={description}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="a-amount">Amount</Label>
          <Input
            id="a-amount"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
          <p
            className={cn(
              "text-xs",
              over ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {over
              ? `Above the outstanding ${rupees(maximum)}. Record the excess as a separate credit.`
              : `Outstanding: ${rupees(maximum)}`}
          </p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="a-note">Payment reference</Label>
          <Input
            id="a-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="NABIL/TT/44192"
          />
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy || over || !(Number(amount) > 0)}
          onClick={() => onSubmit(amount, note)}
        >
          Record
        </Button>
      </div>
    </Shell>
  );
}

function ReasonDialog({
  title,
  description,
  placeholder,
  busy,
  onClose,
  onSubmit,
}: {
  title: string;
  description: string;
  placeholder: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Shell title={title} description={description}>
      <Textarea
        rows={3}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder={placeholder}
      />
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy || reason.trim().length < 6}
          onClick={() => onSubmit(reason)}
        >
          Record
        </Button>
      </div>
    </Shell>
  );
}

/* -------------------------------------------------------------------------- */
/* Pre-authorisations                                                          */
/* -------------------------------------------------------------------------- */

function PreAuths() {
  const [rows, setRows] = useState<PreAuthorisation[]>([]);

  useEffect(() => {
    void api
      .get<Paginated<PreAuthorisation>>("/insurance/preauthorisations/")
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pre-authorisations</CardTitle>
        <CardDescription>
          A promise with an amount and an expiry, and both are routinely lost.
          Approving less than was asked is its own state, because "approved"
          does not say that the hospital is carrying the difference.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.map((row) => (
          <div
            key={row.uuid}
            className={cn(
              "rounded-md border p-3",
              row.status === "partially_approved" && "border-amber-500/50",
              row.status === "rejected" && "border-destructive/50",
            )}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">
                <span className="mr-2 font-mono text-xs text-muted-foreground">
                  {row.reference}
                </span>
                {row.planned_treatment}
              </span>
              <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                {humanise(row.status)}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {row.patient_name} · {row.payer_name} · {row.policy_number}
              {row.payer_reference && ` · ${row.payer_reference}`}
            </p>
            <p className="text-sm tabular-nums">
              asked {rupees(row.estimated_amount)} · approved{" "}
              {rupees(row.approved_amount)}
              {Number(row.estimated_amount) > Number(row.approved_amount) &&
                Number(row.approved_amount) > 0 && (
                  <span className="text-destructive">
                    {" "}
                    · {rupees(
                      String(
                        Number(row.estimated_amount) -
                          Number(row.approved_amount),
                      ),
                    )}{" "}
                    at the hospital's risk
                  </span>
                )}
              {row.valid_until && ` · valid to ${day(row.valid_until)}`}
            </p>
            {row.conditions && (
              <p className="text-xs text-muted-foreground">{row.conditions}</p>
            )}
            {row.rejection_reason && (
              <p className="text-xs text-destructive">{row.rejection_reason}</p>
            )}
            {row.warnings.map((warning) => (
              <p key={warning} className="mt-1 text-xs text-amber-600">
                ! {warning}
              </p>
            ))}
          </div>
        ))}
        {rows.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Nothing requested.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Payers                                                                      */
/* -------------------------------------------------------------------------- */

function Payers() {
  const [rows, setRows] = useState<PayerPerformance[]>([]);

  useEffect(() => {
    void api
      .get<PayerPerformance[]>("/insurance/payers/performance/")
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Which payers are worth it</CardTitle>
        <CardDescription>
          A contract is renegotiated on these four numbers. A hospital that
          cannot produce them renegotiates on impressions.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Payer</TableHead>
                <TableHead className="text-right">Claims</TableHead>
                <TableHead className="text-right">Claimed</TableHead>
                <TableHead className="text-right">Approved</TableHead>
                <TableHead className="text-right">Approval</TableHead>
                <TableHead className="text-right">Rejected</TableHead>
                <TableHead className="text-right">Resubmitted</TableHead>
                <TableHead className="text-right">Days to answer</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.payer}>
                  <TableCell>
                    {row.payer}
                    <span className="block text-xs text-muted-foreground">
                      {humanise(row.kind)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.claims}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.claimed)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.approved)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      Number(row.approval_percent ?? 100) < 80 &&
                        "text-destructive",
                    )}
                  >
                    {row.approval_percent === null
                      ? "—"
                      : `${row.approval_percent}%`}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.rejection_percent > 10 && "text-destructive",
                    )}
                  >
                    {row.rejection_percent}%
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.resubmitted}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.median_days_to_respond ?? "—"}
                    <span className="block text-xs text-muted-foreground">
                      promised {row.promised_days}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.outstanding)}
                    {Number(row.written_off) > 0 && (
                      <span className="block text-xs text-destructive">
                        {rupees(row.written_off)} written off
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={9}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No claims in the window.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Analysis                                                                    */
/* -------------------------------------------------------------------------- */

function Analysis() {
  const [ageing, setAgeing] = useState<ClaimsAgeing | null>(null);
  const [deductions, setDeductions] = useState<DeductionAnalysis | null>(null);

  useEffect(() => {
    void Promise.all([
      api.get<ClaimsAgeing>("/insurance/reports/?report=ageing"),
      api.get<DeductionAnalysis>("/insurance/reports/?report=deductions"),
    ])
      .then(([a, b]) => {
        setAgeing(a);
        setDeductions(b);
      })
      .catch(() => undefined);
  }, []);

  if (!ageing || !deductions) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  const peak = Math.max(
    1,
    ...deductions.by_reason.map((row) => Number(row.amount)),
  );

  return (
    <div className="space-y-4">
      <Card className={cn(Number(ageing.overdue) > 0 && "border-amber-500/50")}>
        <CardHeader>
          <CardTitle className="text-base">Waiting to be paid</CardTitle>
          <CardDescription>
            Rs {rupees(ageing.total)} outstanding, Rs {rupees(ageing.overdue)}{" "}
            of it past the payer's own promised days — not a generic thirty, so
            "overdue" means the payer broke its own terms.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            {Object.entries(ageing.buckets).map(([key, value]) => (
              <div key={key} className="flex items-center gap-2 text-sm">
                <span className="w-20 shrink-0 text-xs text-muted-foreground">
                  {humanise(key)} days
                </span>
                <span className="flex h-3 flex-1 items-center">
                  <span
                    className={cn(
                      "h-3 rounded-sm",
                      key === "91-plus" ? "bg-destructive/70" : "bg-primary/60",
                    )}
                    style={{
                      width: `${
                        (Number(value) /
                          Math.max(
                            1,
                            ...Object.values(ageing.buckets).map(Number),
                          )) *
                        100
                      }%`,
                    }}
                  />
                </span>
                <span className="w-28 shrink-0 text-right tabular-nums">
                  {rupees(value)}
                </span>
              </div>
            ))}
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Claim</TableHead>
                <TableHead>Payer</TableHead>
                <TableHead className="text-right">Waiting</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ageing.claims.slice(0, 15).map((row) => (
                <TableRow key={row.claim}>
                  <TableCell className="font-mono text-xs">
                    {row.claim}
                    <span className="block font-sans text-muted-foreground">
                      {row.patient}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-[10rem] truncate">
                    {row.payer}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.past_promise && "font-medium text-destructive",
                    )}
                  >
                    {row.days}d of {row.promised_days}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.outstanding)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingDown className="h-4 w-4" />
            Why claims are being cut
          </CardTitle>
          <CardDescription>
            Rs {rupees(deductions.total_deducted)} deducted since{" "}
            {day(deductions.since)}. A hospital that learns 40% of its
            deductions are one thing can change what it bills; one with a
            thousand free-text reasons can change nothing.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {deductions.by_reason.map((row) => (
            <div key={row.reason} className="flex items-center gap-2 text-sm">
              <span className="w-44 shrink-0 truncate">
                {humanise(row.reason)}
              </span>
              <span className="flex h-3 flex-1 items-center">
                <span
                  className="h-3 rounded-sm bg-destructive/60"
                  style={{ width: `${(Number(row.amount) / peak) * 100}%` }}
                />
              </span>
              <span className="w-24 shrink-0 text-right tabular-nums">
                {rupees(row.amount)}
              </span>
              <span className="w-14 shrink-0 text-right text-xs text-muted-foreground">
                {row.share_percent}%
              </span>
            </div>
          ))}
          {deductions.by_reason.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Nothing has been deducted.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bits                                                                        */
/* -------------------------------------------------------------------------- */

function Fact({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("text-lg font-semibold tabular-nums", tone)}>
        Rs {value}
      </p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
