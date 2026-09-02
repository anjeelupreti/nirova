/**
 * Procurement: what to buy, from whom, at what price, and what arrived.
 *
 * The chain is long — reorder → requisition → approval → quotations →
 * comparison → order → approval → delivery → quality check → stock — and the
 * screen's job is to make the *current* step obvious rather than to display
 * the whole chain at once. So the first tab is a work queue: what is waiting
 * on someone, not what exists.
 *
 * Two things the UI must not soften.
 *
 * **Quotations are ranked on blended cost per unit, never on total spend.** A
 * supplier quoting 4,600 for 600 units (100 of them free) beats one quoting
 * 4,300 for 500. The comparison shows both columns and sorts on the one that
 * is actually comparable, because a buyer who sorts by the total picks the
 * wrong supplier.
 *
 * **Choosing a dearer quotation requires a stated reason.** The backend
 * refuses without one; the form asks for it up front rather than letting the
 * buyer discover the rule by being rejected.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Ban,
  BadgeCheck,
  Building,
  CheckCircle2,
  ClipboardList,
  Clock,
  FileText,
  Gauge,
  Loader2,
  PackageCheck,
  Scale,
  ShieldAlert,
  Truck,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Facility,
  GoodsReceipt,
  Paginated,
  ProcurementDashboard,
  PurchaseOrder,
  PurchaseRequisition,
  QuotationComparison,
  StockLocation,
  Supplier,
  SupplierPerformance,
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
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "@/components/ui/primitives";

type Tab = "queue" | "requisitions" | "orders" | "receipts" | "suppliers";

const TABS: { id: Tab; label: string; icon: typeof FileText }[] = [
  { id: "queue", label: "Work queue", icon: Gauge },
  { id: "requisitions", label: "Requisitions", icon: ClipboardList },
  { id: "orders", label: "Orders", icon: FileText },
  { id: "receipts", label: "Deliveries", icon: Truck },
  { id: "suppliers", label: "Suppliers", icon: Building },
];

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/** Colour a status the way a buyer reads it: waiting, moving, or stuck. */
const STATUS_TONE: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "outline",
  submitted: "default",
  pending_approval: "default",
  approved: "secondary",
  ordered: "secondary",
  partially_received: "default",
  received: "secondary",
  quality_check: "default",
  accepted: "secondary",
  partially_rejected: "destructive",
  posted: "secondary",
  rejected: "destructive",
  cancelled: "destructive",
};

const label = (status: string) => status.replace(/_/g, " ");

export default function ProcurementPage() {
  const [tab, setTab] = useState<Tab>("queue");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const result = await api.get<Paginated<Facility>>("/org/facilities/");
        setFacilities(result.results);
        if (result.results[0]) setFacility(result.results[0].uuid);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Could not load facilities.",
        );
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Procurement</h1>
          <p className="text-sm text-muted-foreground">
            Requisition through to stock on the shelf.
          </p>
        </div>
        <Select
          className="h-9 w-auto"
          aria-label="Facility"
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

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex gap-1 border-b">
        {TABS.map(({ id, label: text, icon: Icon }) => (
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
            {text}
          </button>
        ))}
      </div>

      {tab === "queue" && <WorkQueue facility={facility} onGo={setTab} />}
      {tab === "requisitions" && <Requisitions facility={facility} />}
      {tab === "orders" && <Orders facility={facility} />}
      {tab === "receipts" && <Receipts facility={facility} />}
      {tab === "suppliers" && <Suppliers />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Work queue                                                                  */
/* -------------------------------------------------------------------------- */

function WorkQueue({
  facility,
  onGo,
}: {
  facility: string;
  onGo: (tab: Tab) => void;
}) {
  const [data, setData] = useState<ProcurementDashboard | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!facility) return;
    void (async () => {
      try {
        setData(
          await api.get<ProcurementDashboard>(
            `/procurement/dashboard/?facility=${facility}`,
          ),
        );
        setProblem(null);
      } catch (err) {
        setProblem(
          err instanceof ApiError ? err.message : "Could not load the queue.",
        );
      }
    })();
  }, [facility]);

  if (problem) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    );
  }
  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  // Ordered by who is being waited on, not by document type. A buyer opening
  // this screen wants to know what is stuck, and the top of the list should
  // be the thing nobody has touched.
  const queue = [
    {
      count: data.requisitions_awaiting_approval,
      label: "Requisitions waiting for approval",
      tab: "requisitions" as Tab,
      icon: ClipboardList,
      urgent: true,
    },
    {
      count: data.orders_awaiting_approval,
      label: "Orders waiting for approval",
      tab: "orders" as Tab,
      icon: FileText,
      urgent: true,
    },
    {
      count: data.receipts_awaiting_check,
      label: "Deliveries waiting for a quality check",
      tab: "receipts" as Tab,
      icon: ShieldAlert,
      urgent: true,
    },
    {
      count: data.receipts_awaiting_posting,
      label: "Checked deliveries not yet on the shelf",
      tab: "receipts" as Tab,
      icon: PackageCheck,
      urgent: true,
    },
    {
      count: data.requisitions_approved_unordered,
      label: "Approved requisitions with no order raised",
      tab: "requisitions" as Tab,
      icon: Clock,
      urgent: false,
    },
    {
      count: data.orders_overdue,
      label: "Orders past their delivery date",
      tab: "orders" as Tab,
      icon: AlertTriangle,
      urgent: true,
    },
  ].filter((row) => row.count > 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Open orders" value={String(data.orders_open)} />
        <Stat label="Committed" value={rupees(data.open_order_value)} />
        <Stat
          label="Overdue"
          value={String(data.orders_overdue)}
          tone={data.orders_overdue > 0 ? "text-destructive" : undefined}
        />
        <Stat
          label="Licences expiring"
          value={String(data.licences_expiring)}
          hint="within 60 days"
          tone={data.licences_expiring > 0 ? "text-amber-600" : undefined}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Waiting on someone</CardTitle>
          <CardDescription>
            What is stuck, rather than what exists.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {queue.length === 0 ? (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              Nothing is waiting. Every document has moved on.
            </div>
          ) : (
            <ul className="divide-y">
              {queue.map(({ count, label: text, tab, icon: Icon, urgent }) => (
                <li key={text}>
                  <button
                    type="button"
                    onClick={() => onGo(tab)}
                    className="flex w-full items-center gap-3 py-3 text-left hover:bg-muted/50"
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4",
                        urgent ? "text-amber-600" : "text-muted-foreground",
                      )}
                    />
                    <span className="flex-1 text-sm">{text}</span>
                    <Badge variant={urgent ? "default" : "secondary"}>
                      {count}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {data.overdue_orders.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Late deliveries</CardTitle>
            <CardDescription>
              Longest overdue first — these are the calls to make today.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Order</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Expected</TableHead>
                  <TableHead className="text-right">Late by</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.overdue_orders.map((row) => (
                  <TableRow key={row.reference}>
                    <TableCell className="font-medium">
                      {row.reference}
                    </TableCell>
                    <TableCell>{row.supplier}</TableCell>
                    <TableCell>{row.expected}</TableCell>
                    <TableCell className="text-right font-medium text-destructive">
                      {row.days_late} days
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.value)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Stat({
  label: text,
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
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {text}
        </p>
        <p className={cn("mt-1 text-2xl font-semibold tabular-nums", tone)}>
          {value}
        </p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Requisitions                                                                */
/* -------------------------------------------------------------------------- */

function Requisitions({ facility }: { facility: string }) {
  const [rows, setRows] = useState<PurchaseRequisition[]>([]);
  const [open, setOpen] = useState<PurchaseRequisition | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [locations, setLocations] = useState<StockLocation[]>([]);

  const load = useCallback(async () => {
    if (!facility) return;
    const page = await api.get<Paginated<PurchaseRequisition>>(
      `/procurement/requisitions/?facility=${facility}`,
    );
    setRows(page.results);
    setOpen((current) =>
      current ? page.results.find((r) => r.uuid === current.uuid) ?? null : null,
    );
  }, [facility]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<Paginated<StockLocation>>(`/pharmacy/locations/?facility=${facility}`)
      .then((page) => setLocations(page.results))
      .catch(() => setLocations([]));
  }, [facility]);

  const act = async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setProblem(null);
    setNotice(null);
    try {
      await fn();
      setNotice(success);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  const fromReorder = () => {
    const store =
      locations.find((row) => !row.is_dispensable) ?? locations[0];
    if (!store) {
      setProblem("No stock location to reorder from.");
      return;
    }
    void act(async () => {
      const created = await api.post<PurchaseRequisition | null>(
        "/procurement/requisitions/from-reorder/",
        { facility_uuid: facility, location_uuid: store.uuid },
      );
      // 204 means nothing needs ordering. An empty requisition would just be
      // noise in the approval queue, so the backend declines to make one.
      setNotice(
        created
          ? `${created.reference} raised from the reorder suggestions.`
          : "Nothing is below its reorder level. No requisition raised.",
      );
    }, "");
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_26rem]">
      <div className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        {notice && (
          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Requisitions</CardTitle>
              <CardDescription>
                A request to buy. Internal and reversible — an order is not.
              </CardDescription>
            </div>
            <Button size="sm" disabled={busy} onClick={fromReorder}>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ClipboardList className="h-4 w-4" />
              )}
              From reorder levels
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Raised by</TableHead>
                  <TableHead>Items</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.uuid}
                    className={cn(
                      "cursor-pointer",
                      open?.uuid === row.uuid && "bg-muted/50",
                    )}
                    onClick={() => setOpen(row)}
                  >
                    <TableCell className="font-medium">
                      {row.reference}
                      {row.is_urgent && (
                        <Badge variant="destructive" className="ml-2">
                          Urgent
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>{row.requested_by_name}</TableCell>
                    <TableCell>{row.lines.length}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                        {label(row.status)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="py-8 text-center text-sm text-muted-foreground"
                    >
                      Nothing has been requested at this facility.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {open ? (
        <RequisitionDetail
          requisition={open}
          busy={busy}
          onAct={act}
          onReload={load}
        />
      ) : (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            Select a requisition.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function RequisitionDetail({
  requisition,
  busy,
  onAct,
  onReload,
}: {
  requisition: PurchaseRequisition;
  busy: boolean;
  onAct: (fn: () => Promise<unknown>, success: string) => Promise<void>;
  onReload: () => Promise<void>;
}) {
  const [notes, setNotes] = useState("");
  const [comparison, setComparison] = useState<QuotationComparison | null>(null);

  useEffect(() => {
    setComparison(null);
    setNotes("");
  }, [requisition.uuid]);

  const compare = () =>
    void api
      .get<QuotationComparison>(
        `/procurement/requisitions/${requisition.reference}/compare/`,
      )
      .then(setComparison)
      .catch(() => setComparison(null));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{requisition.reference}</CardTitle>
          <CardDescription>
            {requisition.requested_by_name} ·{" "}
            {new Date(requisition.created_at).toLocaleDateString()}
            {requisition.required_by && ` · needed by ${requisition.required_by}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {requisition.justification && (
            <p className="rounded-md bg-muted/50 p-3 text-sm">
              {requisition.justification}
            </p>
          )}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">Want</TableHead>
                <TableHead className="text-right">On hand</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {requisition.lines.map((line) => (
                <TableRow key={line.uuid}>
                  <TableCell>
                    {line.product_name}
                    {Number(line.ordered_quantity) > 0 && (
                      <span className="block text-xs text-muted-foreground">
                        {line.ordered_quantity} ordered,{" "}
                        {line.outstanding_quantity} outstanding
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.quantity}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      Number(line.stock_on_hand) <= Number(line.reorder_level) &&
                        "font-medium text-destructive",
                    )}
                  >
                    {line.stock_on_hand}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">
            Stock shown is what the requester saw when they raised this, frozen
            on the line. Looking it up now could make an urgent request look
            unjustified because someone else's delivery landed in between.
          </p>
        </CardContent>
      </Card>

      {requisition.status === "draft" && (
        <Button
          className="w-full"
          disabled={busy}
          onClick={() =>
            void onAct(
              () =>
                api.post(
                  `/procurement/requisitions/${requisition.reference}/submit/`,
                ),
              `${requisition.reference} submitted for approval.`,
            )
          }
        >
          Submit for approval
        </Button>
      )}

      {requisition.status === "submitted" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Decision</CardTitle>
            <CardDescription>
              Whoever raised this cannot approve it.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              rows={2}
              placeholder="Notes for the record"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="flex-1"
                disabled={busy || !notes.trim()}
                onClick={() =>
                  void onAct(
                    () =>
                      api.post(
                        `/procurement/requisitions/${requisition.reference}/decide/`,
                        { approve: false, notes },
                      ),
                    `${requisition.reference} rejected.`,
                  )
                }
              >
                <Ban className="h-4 w-4" />
                Reject
              </Button>
              <Button
                className="flex-1"
                disabled={busy}
                onClick={() =>
                  void onAct(
                    () =>
                      api.post(
                        `/procurement/requisitions/${requisition.reference}/decide/`,
                        { approve: true, notes },
                      ),
                    `${requisition.reference} approved.`,
                  )
                }
              >
                <BadgeCheck className="h-4 w-4" />
                Approve
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              A rejection must say why; an approval need not.
            </p>
          </CardContent>
        </Card>
      )}

      {["approved", "quoting", "ordered"].includes(requisition.status) && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Quotations</CardTitle>
            <Button variant="outline" size="sm" onClick={compare}>
              <Scale className="h-4 w-4" />
              Compare
            </Button>
          </CardHeader>
          <CardContent>
            {comparison ? (
              <Comparison comparison={comparison} onReload={onReload} />
            ) : (
              <p className="py-4 text-sm text-muted-foreground">
                Compare ranks suppliers on what each unit actually costs, not on
                the headline total.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Comparison({
  comparison,
  onReload,
}: {
  comparison: QuotationComparison;
  onReload: () => Promise<void>;
}) {
  if (comparison.count === 0) {
    return (
      <p className="py-4 text-sm text-muted-foreground">
        No quotations recorded yet.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Supplier</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Units</TableHead>
              <TableHead className="text-right">Per unit</TableHead>
              <TableHead className="text-right">Lead</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {comparison.quotations.map((row) => {
              const winner = row.uuid === comparison.cheapest;
              return (
                <TableRow
                  key={row.uuid}
                  className={cn(winner && "bg-emerald-50 dark:bg-emerald-950/30")}
                >
                  <TableCell>
                    <span className="font-medium">{row.supplier}</span>
                    {winner && (
                      <Badge variant="secondary" className="ml-2">
                        Cheapest per unit
                      </Badge>
                    )}
                    {!row.can_order_from && (
                      <Badge variant="destructive" className="ml-2">
                        Cannot order
                      </Badge>
                    )}
                    {row.is_expired && (
                      <Badge variant="outline" className="ml-2">
                        Expired
                      </Badge>
                    )}
                    <span className="block text-xs text-muted-foreground">
                      {row.reference}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(row.total_value)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.total_units}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-medium tabular-nums",
                      winner && "text-emerald-700 dark:text-emerald-400",
                    )}
                  >
                    {rupees(row.cost_per_unit)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.quoted_lead_time_days ?? row.agreed_lead_time_days}d
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <Alert>
        <Scale className="h-4 w-4" />
        <AlertTitle>Ranked on cost per unit, not on the total</AlertTitle>
        <AlertDescription>
          Free units make totals incomparable: a higher headline price on more
          stock can be the cheaper buy. Choosing a dearer quotation is allowed
          and requires a stated reason.
        </AlertDescription>
      </Alert>

      {comparison.ineligible.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Not eligible to be the benchmark: {comparison.ineligible.join(", ")} —
          expired, or the supplier cannot be ordered from.
        </p>
      )}

      <Button variant="ghost" size="sm" onClick={() => void onReload()}>
        Refresh
      </Button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Orders                                                                      */
/* -------------------------------------------------------------------------- */

function Orders({ facility }: { facility: string }) {
  const [rows, setRows] = useState<PurchaseOrder[]>([]);
  const [open, setOpen] = useState<PurchaseOrder | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!facility) return;
    const page = await api.get<Paginated<PurchaseOrder>>(
      `/procurement/orders/?facility=${facility}`,
    );
    setRows(page.results);
    setOpen((current) =>
      current ? page.results.find((r) => r.uuid === current.uuid) ?? null : null,
    );
  }, [facility]);

  useEffect(() => {
    void load();
  }, [load]);

  const approve = async (order: PurchaseOrder) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/procurement/orders/${order.reference}/approve/`);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not approved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
      <div className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Purchase orders</CardTitle>
            <CardDescription>
              A commitment to a supplier. Separate from the requisition because
              one is internal and the other binds the organization.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Order</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Expected</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.uuid}
                    className={cn(
                      "cursor-pointer",
                      open?.uuid === row.uuid && "bg-muted/50",
                    )}
                    onClick={() => setOpen(row)}
                  >
                    <TableCell className="font-medium">{row.reference}</TableCell>
                    <TableCell>{row.supplier_name}</TableCell>
                    <TableCell
                      className={cn(row.is_overdue && "text-destructive")}
                    >
                      {row.expected_delivery ?? "—"}
                      {row.is_overdue && (
                        <span className="block text-xs">
                          {row.days_late} days late
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.total)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                        {label(row.status)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-8 text-center text-sm text-muted-foreground"
                    >
                      No orders at this facility.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {open ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{open.reference}</CardTitle>
            <CardDescription>
              {open.supplier_name}
              {open.requisition_reference && ` · from ${open.requisition_reference}`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Rate</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {open.lines.map((line) => (
                  <TableRow key={line.uuid}>
                    <TableCell>
                      {line.product_name}
                      {Number(line.free_quantity) > 0 && (
                        <span className="block text-xs text-emerald-600">
                          +{line.free_quantity} free
                        </span>
                      )}
                      {Number(line.received_quantity) > 0 && (
                        <span className="block text-xs text-muted-foreground">
                          {line.received_quantity} received,{" "}
                          {line.outstanding_quantity} outstanding
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {line.quantity}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {line.unit_price}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <div className="space-y-1 border-t pt-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Subtotal</span>
                <span className="tabular-nums">{rupees(open.subtotal)}</span>
              </div>
              {Number(open.tax_total) > 0 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Tax</span>
                  <span className="tabular-nums">{rupees(open.tax_total)}</span>
                </div>
              )}
              <div className="flex justify-between border-t pt-1 font-medium">
                <span>Total</span>
                <span className="tabular-nums">{rupees(open.total)}</span>
              </div>
            </div>

            {["draft", "pending_approval"].includes(open.status) && (
              <>
                <Button
                  className="w-full"
                  disabled={busy}
                  onClick={() => void approve(open)}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <BadgeCheck className="h-4 w-4" />
                  )}
                  Approve and send
                </Button>
                <p className="text-xs text-muted-foreground">
                  Refused for whoever raised it, and refused if the supplier's
                  drug licence has lapsed — re-checked now, not just when the
                  order was drafted.
                </p>
              </>
            )}

            {open.approved_by_name && (
              <p className="text-xs text-muted-foreground">
                Approved by {open.approved_by_name}
                {open.approved_at &&
                  ` on ${new Date(open.approved_at).toLocaleDateString()}`}
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            Select an order.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Deliveries                                                                  */
/* -------------------------------------------------------------------------- */

function Receipts({ facility }: { facility: string }) {
  const [rows, setRows] = useState<GoodsReceipt[]>([]);
  const [open, setOpen] = useState<GoodsReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [rejections, setRejections] = useState<
    Record<string, { quantity: string; reason: string }>
  >({});
  const [qualityNotes, setQualityNotes] = useState("");

  const load = useCallback(async () => {
    if (!facility) return;
    const page = await api.get<Paginated<GoodsReceipt>>(
      `/procurement/receipts/?facility=${facility}`,
    );
    setRows(page.results);
    setOpen((current) =>
      current ? page.results.find((r) => r.uuid === current.uuid) ?? null : null,
    );
  }, [facility]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setRejections({});
    setQualityNotes("");
  }, [open?.uuid]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_26rem]">
      <div className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Deliveries</CardTitle>
            <CardDescription>
              Quality check happens before posting, never after. Stock that
              failed inspection should never have been dispensable.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Receipt</TableHead>
                  <TableHead>Order</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.uuid}
                    className={cn(
                      "cursor-pointer",
                      open?.uuid === row.uuid && "bg-muted/50",
                    )}
                    onClick={() => setOpen(row)}
                  >
                    <TableCell className="font-medium">{row.reference}</TableCell>
                    <TableCell>{row.order_reference}</TableCell>
                    <TableCell>{row.supplier_name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.total_value)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                        {label(row.status)}
                      </Badge>
                      {row.invoice_matches === false && (
                        <Badge variant="destructive" className="ml-1">
                          Invoice differs
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-8 text-center text-sm text-muted-foreground"
                    >
                      Nothing has been delivered here yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {open ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{open.reference}</CardTitle>
            <CardDescription>
              {open.supplier_name} · into {open.location_code} ·{" "}
              {open.received_on}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {open.invoice_matches === false && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Supplier invoice does not match</AlertTitle>
                <AlertDescription>
                  Invoice {open.supplier_invoice_number} is{" "}
                  {rupees(open.supplier_invoice_amount ?? "0")} against{" "}
                  {rupees(open.total_value)} received. Reported, not blocked —
                  a discrepancy is a conversation with the supplier, not a
                  reason to leave stock off the shelf.
                </AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              {open.lines.map((line) => (
                <div key={line.uuid} className="rounded-md border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {line.product_name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        batch {line.batch_number} · expires {line.expires_on}
                      </p>
                    </div>
                    <div className="text-right text-sm">
                      <p className="tabular-nums">{line.received_quantity}</p>
                      {Number(line.free_quantity) > 0 && (
                        <p className="text-xs text-emerald-600">
                          +{line.free_quantity} free
                        </p>
                      )}
                    </div>
                  </div>

                  {open.status === "quality_check" ? (
                    <div className="mt-2 flex gap-2">
                      <Input
                        className="h-8 w-24"
                        inputMode="decimal"
                        placeholder="Reject"
                        value={rejections[line.uuid]?.quantity ?? ""}
                        onChange={(event) =>
                          setRejections((current) => ({
                            ...current,
                            [line.uuid]: {
                              quantity: event.target.value,
                              reason: current[line.uuid]?.reason ?? "",
                            },
                          }))
                        }
                      />
                      <Input
                        className="h-8 flex-1"
                        placeholder="Reason"
                        value={rejections[line.uuid]?.reason ?? ""}
                        onChange={(event) =>
                          setRejections((current) => ({
                            ...current,
                            [line.uuid]: {
                              quantity: current[line.uuid]?.quantity ?? "",
                              reason: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                  ) : (
                    Number(line.rejected_quantity) > 0 && (
                      <p className="mt-1 text-xs text-destructive">
                        {line.rejected_quantity} rejected —{" "}
                        {line.rejection_reason}
                      </p>
                    )
                  )}

                  {open.is_posted && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {line.accepted_quantity} accepted at{" "}
                      {rupees(line.effective_unit_cost)} a unit
                    </p>
                  )}
                </div>
              ))}
            </div>

            {open.status === "quality_check" && (
              <>
                <Textarea
                  rows={2}
                  placeholder="Inspection notes"
                  value={qualityNotes}
                  onChange={(event) => setQualityNotes(event.target.value)}
                />
                <Button
                  className="w-full"
                  disabled={busy}
                  onClick={() =>
                    void act(() =>
                      api.post(
                        `/procurement/receipts/${open.reference}/quality-check/`,
                        {
                          rejections: Object.entries(rejections)
                            .filter(([, v]) => Number(v.quantity) > 0)
                            .map(([uuid, v]) => ({
                              line_uuid: uuid,
                              quantity: v.quantity,
                              reason: v.reason,
                            })),
                          notes: qualityNotes,
                        },
                      ),
                    )
                  }
                >
                  <ShieldAlert className="h-4 w-4" />
                  Record the check
                </Button>
              </>
            )}

            {["accepted", "partially_rejected"].includes(open.status) && (
              <>
                <Button
                  className="w-full"
                  disabled={busy}
                  onClick={() =>
                    void act(() =>
                      api.post(`/procurement/receipts/${open.reference}/post/`),
                    )
                  }
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <PackageCheck className="h-4 w-4" />
                  )}
                  Post to stock
                </Button>
                <p className="text-xs text-muted-foreground">
                  Creates the batches and the ledger movements. Every batch on
                  a shelf traces back to this delivery, its order, its
                  quotation and its requisition.
                </p>
              </>
            )}

            {open.is_posted && (
              <Alert>
                <CheckCircle2 className="h-4 w-4" />
                <AlertDescription>
                  Posted to {open.location_code}
                  {open.posted_at &&
                    ` on ${new Date(open.posted_at).toLocaleDateString()}`}
                  .
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            Select a delivery.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Suppliers                                                                   */
/* -------------------------------------------------------------------------- */

function Suppliers() {
  const [rows, setRows] = useState<Supplier[]>([]);
  const [open, setOpen] = useState<Supplier | null>(null);
  const [performance, setPerformance] = useState<SupplierPerformance | null>(
    null,
  );

  useEffect(() => {
    void api
      .get<Paginated<Supplier>>("/procurement/suppliers/")
      .then((page) => setRows(page.results));
  }, []);

  useEffect(() => {
    setPerformance(null);
    if (!open) return;
    void api
      .get<SupplierPerformance>(
        `/procurement/suppliers/${open.uuid}/performance/`,
      )
      .then(setPerformance)
      .catch(() => setPerformance(null));
  }, [open]);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Suppliers</CardTitle>
          <CardDescription>
            A lapsed drug licence blocks ordering — caught before the order
            goes out, not discovered at delivery.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Supplier</TableHead>
                <TableHead>PAN</TableHead>
                <TableHead>Licence</TableHead>
                <TableHead>Terms</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={row.uuid}
                  className={cn(
                    "cursor-pointer",
                    open?.uuid === row.uuid && "bg-muted/50",
                  )}
                  onClick={() => setOpen(row)}
                >
                  <TableCell className="font-medium">
                    {row.name}
                    <span className="block text-xs text-muted-foreground">
                      {row.code} · {row.district}
                    </span>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {row.pan_number}
                  </TableCell>
                  <TableCell
                    className={cn(row.licence_expired && "text-destructive")}
                  >
                    {row.drug_licence_expires_on ?? "—"}
                    {row.licence_expired && (
                      <span className="block text-xs font-medium">expired</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {row.credit_days}d credit · {row.agreed_lead_time_days}d lead
                  </TableCell>
                  <TableCell>
                    {row.can_order_from ? (
                      <Badge variant="secondary">Orderable</Badge>
                    ) : (
                      <Badge variant="destructive">{label(row.status)}</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {open ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{open.name}</CardTitle>
            <CardDescription>
              {open.contact_person} · {open.phone}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!open.can_order_from && (
              <Alert variant="destructive">
                <Ban className="h-4 w-4" />
                <AlertTitle>Cannot order from this supplier</AlertTitle>
                <AlertDescription>
                  {open.licence_expired
                    ? "Their drug licence has expired. Buying medicines from an unlicensed distributor is a regulatory breach."
                    : open.status_reason || label(open.status)}
                </AlertDescription>
              </Alert>
            )}

            {performance ? (
              <>
                <div className="space-y-2 text-sm">
                  <Metric
                    label="Lead time"
                    value={
                      performance.measured_lead_time_days === null
                        ? "not measured yet"
                        : `${performance.measured_lead_time_days}d against ${performance.agreed_lead_time_days}d agreed`
                    }
                    tone={
                      (performance.lead_time_variance ?? 0) > 0
                        ? "text-destructive"
                        : undefined
                    }
                  />
                  <Metric
                    label="Fill rate"
                    value={
                      performance.fill_rate_percent === null
                        ? "—"
                        : `${performance.fill_rate_percent}%`
                    }
                  />
                  <Metric
                    label="Rejection rate"
                    value={
                      performance.rejection_rate_percent === null
                        ? "—"
                        : `${performance.rejection_rate_percent}%`
                    }
                    tone={
                      (performance.rejection_rate_percent ?? 0) > 5
                        ? "text-destructive"
                        : undefined
                    }
                  />
                  <Metric
                    label="Deliveries"
                    value={`${performance.receipts} · ${performance.orders_late} late`}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  Computed from receipts, never stored. A performance score
                  somebody typed is a performance score somebody chose.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                No deliveries recorded yet.
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            Select a supplier.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Metric({
  label: text,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{text}</span>
      <span className={cn("font-medium", tone)}>{value}</span>
    </div>
  );
}
