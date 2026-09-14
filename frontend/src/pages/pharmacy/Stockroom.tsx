/**
 * The stockroom: receiving a delivery, counting the shelf, and the ledger.
 *
 * **Thirteen endpoints with no screen.** Receiving stock, adjusting it, the
 * movement ledger, valuation, reconciliation, batch quarantine and recall
 * exposure, and stock counts with their record-and-approve pair — all built,
 * all tested, and unreachable. A pharmacy could dispense from stock it had no
 * way of putting there.
 *
 * **Receiving is where a batch is born.** There is no "create batch" anywhere
 * in this system, deliberately: a batch exists because something arrived, with
 * an expiry and a price, and creating one without a receipt would produce stock
 * that came from nowhere. So this form is the only door.
 *
 * **A count is two people, and the screen shows that.** Whoever counts cannot
 * approve their own variances — the service refuses it — so the approve step is
 * presented as a separate act with its own button and its own explanation
 * rather than as the last field of the counting form. A control the interface
 * hides is a control people route around.
 *
 * **Blind counting is the default, and the API enforces it rather than this
 * screen.** `StockCountLineSerializer` nulls `expected_quantity` while a blind
 * count is open, so the number never reaches the browser at all — it cannot be
 * read out of the network tab either. The screen also omits the column while
 * counting, which is belt and braces rather than the control: showing the
 * expected quantity to whoever is counting is how a count comes back agreeing
 * with the system that was wrong.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ClipboardList,
  Coins,
  PackagePlus,
  ScrollText,
} from "lucide-react";

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
import { formatDate, formatDateTime } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

type Product = {
  uuid: string;
  code: string;
  generic_name: string;
  brand_name: string;
  strength: string;
  base_unit: string;
  display_name?: string;
};

type CountLine = {
  uuid: string;
  product_name: string;
  batch_number: string;
  expected_quantity: string | null;
  counted_quantity: string | null;
  recount_quantity: string | null;
  variance: string;
  has_variance: boolean;
  variance_reason: string;
  is_approved: boolean;
};

type StockCount = {
  uuid: string;
  reference: string;
  location_code: string;
  count_type: string;
  is_blind: boolean;
  status: string;
  started_at: string;
  completed_at: string | null;
  approved_at: string | null;
  approval_notes: string;
  lines: CountLine[];
};

type LedgerEntry = {
  uuid: string;
  created_at: string;
  movement_type: string;
  quantity: string;
  balance_after: string;
  reason: string;
  batch_number?: string;
  product_name?: string;
  actor_name?: string;
};

/**
 * Movement types a person may choose when adjusting by hand.
 *
 * Deliberately not the full `MovementType` list. `purchase` belongs to
 * receiving, `dispense` to the counter, `count_adjustment` to an approved
 * count — offering those here would let somebody book a purchase without a
 * batch or "dispense" stock to nobody, and both would be indistinguishable in
 * the ledger from the real thing.
 */
const ADJUSTMENTS: { value: string; label: string; help: string }[] = [
  { value: "damage", label: "Damaged", help: "Broken, spilt or contaminated." },
  { value: "expiry", label: "Expired", help: "Past its expiry and withdrawn." },
  { value: "loss", label: "Lost", help: "Missing, with no known destination." },
  { value: "return_supplier", label: "Returned to supplier", help: "Sent back." },
  { value: "found", label: "Found", help: "Stock present that the system did not know about." },
];

//: The server's own `StockCountStatus`, read rather than guessed. I wrote
//: `open` and the value is `counting`; a status map missing the state every
//: new count is in would have labelled every open count with a raw string.
const COUNT_STATUS: Record<string, string> = {
  draft: "Draft",
  counting: "Counting",
  review: "Variances to review",
  approved: "Approved",
  applied: "Adjustments applied",
  cancelled: "Cancelled",
};

/* -------------------------------------------------------------------------- */
/* Receiving                                                                   */
/* -------------------------------------------------------------------------- */

export function ReceivePanel({
  locationUuid,
  onReceived,
}: {
  locationUuid: string;
  onReceived?: () => void;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState({
    product_uuid: "",
    batch_number: "",
    expires_on: "",
    quantity: "",
    manufactured_on: "",
    purchase_price: "",
    selling_price: "",
    mrp: "",
    supplier_name: "",
    receipt_reference: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<{ results: Product[] }>("/pharmacy/products/?page_size=200")
      .then((page) => setProducts(page.results))
      .catch(() => setProducts([]));
  }, []);

  const set = (field: string, value: string) =>
    setForm((current) => ({ ...current, [field]: value }));

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      const result = await api.post<{ batch: { batch_number: string } }>(
        "/pharmacy/stock/receive/",
        {
          ...form,
          location_uuid: locationUuid,
          // Empty strings are not dates, and an optional date field sent as ""
          // fails validation with a message about the format rather than about
          // being blank.
          manufactured_on: form.manufactured_on || null,
          purchase_price: form.purchase_price || 0,
          selling_price: form.selling_price || 0,
          mrp: form.mrp || 0,
        },
      );
      setDone(`Booked in as batch ${result.batch.batch_number}.`);
      setForm((current) => ({
        ...current,
        // The batch and quantity change per line; the supplier and receipt
        // reference do not. A delivery is a dozen lines from one supplier, and
        // retyping their name a dozen times is how the twelfth one gets a typo
        // and becomes a second supplier.
        batch_number: "",
        expires_on: "",
        quantity: "",
        manufactured_on: "",
      }));
      onReceived?.();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not receive.");
    } finally {
      setBusy(false);
    }
  };

  const ready =
    form.product_uuid && form.batch_number && form.expires_on && form.quantity;

  return (
    <Section
      title="Receive a delivery"
      description="A batch exists because something arrived. This is the only way to create one."
    >
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not go in</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}
      {done && (
        <Alert>
          <AlertTitle>{done}</AlertTitle>
          <AlertDescription>
            The supplier and receipt reference are kept for the next line.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="receive-product">Product</Label>
          <Select
            id="receive-product"
            value={form.product_uuid}
            onChange={(event) => set("product_uuid", event.target.value)}
          >
            <option value="">— choose —</option>
            {products.map((product) => (
              <option key={product.uuid} value={product.uuid}>
                {product.display_name ||
                  `${product.generic_name} ${product.strength}`.trim()}{" "}
                ({product.code})
              </option>
            ))}
          </Select>
        </div>

        <Field
          id="receive-batch"
          label="Batch number"
          value={form.batch_number}
          onChange={(value) => set("batch_number", value)}
        />
        <Field
          id="receive-expiry"
          label="Expires on"
          type="date"
          value={form.expires_on}
          onChange={(value) => set("expires_on", value)}
        />
        <Field
          id="receive-manufactured"
          label="Manufactured on"
          type="date"
          value={form.manufactured_on}
          onChange={(value) => set("manufactured_on", value)}
        />
        <Field
          id="receive-quantity"
          label="Quantity"
          type="number"
          help="In the product's stock unit, not in packs."
          value={form.quantity}
          onChange={(value) => set("quantity", value)}
        />
        <Field
          id="receive-purchase"
          label="Cost per unit"
          type="number"
          value={form.purchase_price}
          onChange={(value) => set("purchase_price", value)}
        />
        <Field
          id="receive-selling"
          label="Selling price"
          type="number"
          value={form.selling_price}
          onChange={(value) => set("selling_price", value)}
        />
        <Field
          id="receive-mrp"
          label="Printed MRP"
          type="number"
          help="The selling price may not exceed this."
          value={form.mrp}
          onChange={(value) => set("mrp", value)}
        />
        <Field
          id="receive-supplier"
          label="Supplier"
          value={form.supplier_name}
          onChange={(value) => set("supplier_name", value)}
        />
        <Field
          id="receive-reference"
          label="Receipt reference"
          help="The supplier's invoice or challan number."
          value={form.receipt_reference}
          onChange={(value) => set("receipt_reference", value)}
        />

        <div className="flex items-end sm:col-span-2 lg:col-span-3">
          <Button disabled={!ready || busy || !locationUuid} onClick={() => void submit()}>
            <PackagePlus className="mr-2 h-4 w-4" />
            Book in
          </Button>
          {!locationUuid && (
            <span className="ml-3 text-sm text-muted-foreground">
              Choose a location first.
            </span>
          )}
        </div>
      </div>
    </Section>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  help,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  help?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Counting                                                                    */
/* -------------------------------------------------------------------------- */

export function CountPanel({
  facilityUuid,
  locationUuid,
}: {
  facilityUuid: string;
  locationUuid: string;
}) {
  const [counts, setCounts] = useState<StockCount[]>([]);
  const [open, setOpen] = useState<StockCount | null>(null);
  const [entered, setEntered] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.get<{ results: StockCount[] }>("/pharmacy/counts/");
      setCounts(page.results);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not load counts.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  const start = () =>
    void act(async () => {
      const started = await api.post<StockCount>("/pharmacy/counts/", {
        facility_uuid: facilityUuid,
        location_uuid: locationUuid,
        count_type: "cycle",
        is_blind: true,
      });
      setOpen(started);
      setEntered({});
    });

  const record = (count: StockCount) =>
    void act(async () => {
      const lines = Object.entries(entered)
        .filter(([, value]) => value !== "")
        .map(([line_uuid, counted_quantity]) => ({
          line_uuid,
          counted_quantity,
          ...(reasons[line_uuid] ? { variance_reason: reasons[line_uuid] } : {}),
        }));
      if (lines.length === 0) return;
      const updated = await api.post<StockCount>(
        `/pharmacy/counts/${count.uuid}/record/`,
        { lines },
      );
      setOpen(updated);
    });

  const approve = (count: StockCount) =>
    void act(async () => {
      await api.post(`/pharmacy/counts/${count.uuid}/approve/`, { notes });
      setOpen(null);
      setNotes("");
    });

  const shown =
    open ??
    counts.find((c) => !["approved", "applied", "cancelled"].includes(c.status)) ??
    null;

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <Section
        title="Stock counts"
        description="Counting the shelf against the system, and posting what the difference was."
        actions={
          <Button
            size="sm"
            disabled={busy || !facilityUuid || !locationUuid}
            onClick={start}
          >
            <ClipboardList className="mr-2 h-4 w-4" />
            Start a count
          </Button>
        }
      >
        {loading ? (
          <TableSkeleton rows={3} />
        ) : counts.length === 0 ? (
          <EmptyState
            illustration="stock"
            title="Nothing has been counted yet"
            description="A count freezes what the system believes is on the shelf, then somebody counts it. The difference is posted as an adjustment once a second person approves it."
          />
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Lines</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {counts.map((count) => (
                  <TableRow key={count.uuid}>
                    <TableCell className="font-mono text-xs">
                      {count.reference}
                    </TableCell>
                    <TableCell>{count.location_code}</TableCell>
                    <TableCell>
                      {formatDate(count.started_at)}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {count.lines.length}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          count.status === "approved" ? "secondary" : "outline"
                        }
                      >
                        {COUNT_STATUS[count.status] ?? count.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setOpen(count);
                          setEntered({});
                        }}
                      >
                        Open
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}
      </Section>

      {shown && (
        <CountSheet
          count={shown}
          entered={entered}
          reasons={reasons}
          notes={notes}
          busy={busy}
          onEnter={(line, value) =>
            setEntered((current) => ({ ...current, [line]: value }))
          }
          onReason={(line, value) =>
            setReasons((current) => ({ ...current, [line]: value }))
          }
          onNotes={setNotes}
          onRecord={() => record(shown)}
          onApprove={() => approve(shown)}
        />
      )}
    </div>
  );
}

/**
 * One count sheet, in whichever of its two states it is in.
 *
 * Counting and reviewing are different jobs, usually different people, and the
 * sheet shows different columns for each: while counting there is no expected
 * quantity on screen at all, and while reviewing the variance is the only
 * column that matters.
 */
function CountSheet({
  count,
  entered,
  reasons,
  notes,
  busy,
  onEnter,
  onReason,
  onNotes,
  onRecord,
  onApprove,
}: {
  count: StockCount;
  entered: Record<string, string>;
  reasons: Record<string, string>;
  notes: string;
  busy: boolean;
  onEnter: (line: string, value: string) => void;
  onReason: (line: string, value: string) => void;
  onNotes: (value: string) => void;
  onRecord: () => void;
  onApprove: () => void;
}) {
  const counting = count.status === "counting";
  const reviewing = count.status === "review";
  const variances = count.lines.filter((line) => line.has_variance);

  return (
    <Section
      title={`${count.reference} — ${COUNT_STATUS[count.status] ?? count.status}`}
      description={
        counting
          ? count.is_blind
            ? "Blind count: the expected quantity is deliberately not shown. A count that can see the answer agrees with it."
            : "The expected quantity is visible on this count."
          : "What was counted against what was expected."
      }
    >
      {reviewing && (
        <StatGrid>
          <StatTile label="Lines" value={count.lines.length} />
          <StatTile
            label="With a variance"
            value={variances.length}
            intent={variances.length ? "bad" : "good"}
          />
          <StatTile
            label="Counted short"
            value={variances.filter((l) => Number(l.variance) < 0).length}
          />
          <StatTile
            label="Counted over"
            value={variances.filter((l) => Number(l.variance) > 0).length}
          />
        </StatGrid>
      )}

      <ScrollX>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead>Batch</TableHead>
              {!counting && <TableHead className="text-right">Expected</TableHead>}
              <TableHead className="text-right">Counted</TableHead>
              {!counting && <TableHead className="text-right">Variance</TableHead>}
              <TableHead>Why</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {count.lines.map((line) => (
              <TableRow key={line.uuid}>
                <TableCell>{line.product_name}</TableCell>
                <TableCell className="font-mono text-xs">
                  {line.batch_number}
                </TableCell>
                {!counting && (
                  <TableCell className="text-right tabular-nums">
                    {line.expected_quantity ?? "—"}
                  </TableCell>
                )}
                <TableCell className="text-right">
                  {counting ? (
                    <Input
                      type="number"
                      aria-label={`Counted quantity for ${line.product_name}`}
                      className="ml-auto h-8 w-24 text-right"
                      value={entered[line.uuid] ?? ""}
                      onChange={(event) => onEnter(line.uuid, event.target.value)}
                    />
                  ) : (
                    <span className="tabular-nums">
                      {line.counted_quantity ?? "—"}
                    </span>
                  )}
                </TableCell>
                {!counting && (
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      line.has_variance && "font-semibold text-destructive",
                    )}
                  >
                    {line.variance}
                  </TableCell>
                )}
                <TableCell>
                  {counting || reviewing ? (
                    <Input
                      aria-label={`Reason for ${line.product_name}`}
                      className="h-8"
                      placeholder={line.has_variance ? "Required" : "Optional"}
                      value={reasons[line.uuid] ?? line.variance_reason}
                      onChange={(event) => onReason(line.uuid, event.target.value)}
                    />
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      {line.variance_reason}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </ScrollX>

      {counting && (
        <div className="flex items-center gap-3">
          <Button disabled={busy} onClick={onRecord}>
            Submit the count
          </Button>
          <span className="text-sm text-muted-foreground">
            Nothing is adjusted yet — this sends the numbers for review.
          </span>
        </div>
      )}

      {reviewing && (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="count-notes">Approval note</Label>
            <Textarea
              id="count-notes"
              rows={2}
              value={notes}
              placeholder="What explains the variances."
              onChange={(event) => onNotes(event.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={busy} onClick={onApprove}>
              Approve and post the adjustments
            </Button>
            <span className="text-sm text-muted-foreground">
              Whoever counted cannot approve it. Approving posts every variance
              to the ledger as an adjustment.
            </span>
          </div>
        </div>
      )}
    </Section>
  );
}

/* -------------------------------------------------------------------------- */
/* Adjusting, the ledger and valuation                                         */
/* -------------------------------------------------------------------------- */

export function LedgerPanel({ locationUuid }: { locationUuid: string }) {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  // **The server's field names, read rather than assumed.** I wrote `total`
  // and the endpoint answers `value_at_cost`, `value_at_retail`,
  // `potential_margin` and `expired_value_at_cost` — four figures, and the
  // interesting one is the fourth: stock that has expired and is still being
  // valued as if it were sellable.
  const [valuation, setValuation] = useState<{
    value_at_cost: string;
    value_at_retail: string;
    potential_margin: string;
    expired_value_at_cost: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!locationUuid) return;
    setLoading(true);
    // Settled independently: the ledger is worth reading without the valuation
    // and the valuation without the ledger.
    void Promise.allSettled([
      api.get<{ entries?: LedgerEntry[]; results?: LedgerEntry[] }>(
        `/pharmacy/stock/ledger/?location=${locationUuid}`,
      ),
      api.get<{
        value_at_cost: string;
        value_at_retail: string;
        potential_margin: string;
        expired_value_at_cost: string;
      }>(`/pharmacy/stock/valuation/?location=${locationUuid}`),
    ]).then(([ledger, value]) => {
      if (ledger.status === "fulfilled") {
        setEntries(ledger.value.entries ?? ledger.value.results ?? []);
      }
      if (value.status === "fulfilled") setValuation(value.value);
      setLoading(false);
    });
  }, [locationUuid]);

  if (loading) return <TableSkeleton rows={6} />;

  return (
    <div className="space-y-4">
      {valuation && (
        <StatGrid>
          <StatTile
            label="At cost"
            value={valuation.value_at_cost}
            hint="what it was bought for"
            icon={<Coins className="h-4 w-4" />}
          />
          <StatTile
            label="At retail"
            value={valuation.value_at_retail}
            hint="what it would sell for"
          />
          <StatTile
            label="Margin in the stock"
            value={valuation.potential_margin}
            hint="retail less cost, if all of it sells"
          />
          {/* The one worth acting on: stock past its expiry is still counted
              in the two figures above, and is worth nothing. Shown as bad
              whenever it is not zero. */}
          <StatTile
            label="Expired, at cost"
            value={valuation.expired_value_at_cost}
            hint="already written off in practice"
            intent={
              Number(valuation.expired_value_at_cost) > 0 ? "bad" : "neutral"
            }
          />
        </StatGrid>
      )}

      <Section
        title="Movement ledger"
        description="Every change to this location's stock, and who made it."
      >
        {entries.length === 0 ? (
          <EmptyState
            illustration="stock"
            title="No movements recorded here"
            description="Receiving a delivery, dispensing, an adjustment or an approved count all write a line here."
          />
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead>Batch</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead className="text-right">Balance</TableHead>
                  <TableHead>Why</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.uuid}>
                    <TableCell className="whitespace-nowrap text-xs">
                      {formatDateTime(entry.created_at)}
                    </TableCell>
                    <TableCell className="capitalize">
                      {entry.movement_type.replace(/_/g, " ")}
                    </TableCell>
                    <TableCell>{entry.product_name ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {entry.batch_number ?? "—"}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        Number(entry.quantity) < 0 && "text-destructive",
                      )}
                    >
                      {entry.quantity}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {entry.balance_after}
                    </TableCell>
                    <TableCell className="max-w-[18rem] truncate text-sm text-muted-foreground">
                      {entry.reason}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}
      </Section>
    </div>
  );
}

/**
 * Adjust one batch by hand, with a reason.
 *
 * The reason is required by the API with a minimum length, and that is right:
 * an adjustment is stock appearing or disappearing without a transaction behind
 * it, and "adjustment" as a reason explains nothing to whoever reads the ledger
 * afterwards.
 */
export function AdjustPanel({
  locationUuid,
  batches,
  onAdjusted,
}: {
  locationUuid: string;
  batches: { uuid: string; label: string }[];
  onAdjusted?: () => void;
}) {
  const [batch, setBatch] = useState("");
  const [type, setType] = useState(ADJUSTMENTS[0].value);
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const chosen = ADJUSTMENTS.find((entry) => entry.value === type);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    setDone(false);
    try {
      await api.post("/pharmacy/stock/adjust/", {
        batch_uuid: batch,
        location_uuid: locationUuid,
        movement_type: type,
        quantity,
        reason: reason.trim(),
      });
      setDone(true);
      setQuantity("");
      setReason("");
      onAdjusted?.();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not adjust.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      title="Adjust a batch"
      description="Stock appearing or disappearing with no transaction behind it. Always with a reason."
    >
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}
      {done && (
        <Alert>
          <AlertTitle>Adjusted</AlertTitle>
          <AlertDescription>
            It is on the ledger with your name against it.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="adjust-batch">Batch</Label>
          <Select
            id="adjust-batch"
            value={batch}
            onChange={(event) => setBatch(event.target.value)}
          >
            <option value="">— choose —</option>
            {batches.map((entry) => (
              <option key={entry.uuid} value={entry.uuid}>
                {entry.label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="adjust-type">What happened</Label>
          <Select
            id="adjust-type"
            value={type}
            onChange={(event) => setType(event.target.value)}
          >
            {ADJUSTMENTS.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </Select>
          {chosen && (
            <p className="text-xs text-muted-foreground">{chosen.help}</p>
          )}
        </div>

        <Field
          id="adjust-quantity"
          label="Quantity"
          type="number"
          help="Positive. What happened decides the direction."
          value={quantity}
          onChange={setQuantity}
        />

        <div className="space-y-1.5">
          <Label htmlFor="adjust-reason">Reason</Label>
          <Textarea
            id="adjust-reason"
            rows={2}
            value={reason}
            placeholder="What happened, in enough words that somebody reading the ledger next year understands it."
            onChange={(event) => setReason(event.target.value)}
          />
        </div>

        <div className="sm:col-span-2">
          <Button
            disabled={
              busy || !batch || !quantity || reason.trim().length < 5 || !locationUuid
            }
            onClick={() => void submit()}
          >
            <ScrollText className="mr-2 h-4 w-4" />
            Post the adjustment
          </Button>
        </div>
      </div>
    </Section>
  );
}
