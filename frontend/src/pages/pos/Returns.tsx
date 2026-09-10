/**
 * Taking back what the counter sold.
 *
 * **Four endpoints with no screen.** Raising a return, listing them, and
 * deciding one — all built, none reachable. A pharmacy could sell and could not
 * take anything back, which in practice means the counter does it in cash out of
 * the drawer and the stock ledger never hears about it.
 *
 * **A return is a request, not an act.** Whoever takes the goods back records
 * what came in and why; somebody else decides whether the money goes out. The
 * service refuses an approval by the person who raised it, and the two
 * permissions are separate — `sale.return` at the counter, `sale.return_approve`
 * for the manager. This screen shows the two halves as two steps rather than as
 * one form with an "approve" checkbox, because a refund is the classic route for
 * taking money out of a till.
 *
 * **`returnable_quantity` comes from the server.** A line already partly
 * returned can only give back the remainder, and computing that in the browser
 * would produce a number that disagrees with the one the service enforces — a
 * disagreement visible only as a rejected return, after the goods are back over
 * the counter.
 *
 * **Restocking is a separate question from refunding.** Money can go back
 * without the goods going back on the shelf: a returned cold-chain vial that sat
 * on a counter for an hour is refundable and not sellable. The two decisions sit
 * side by side rather than one implying the other.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, PackageX, Search, Undo2 } from "lucide-react";

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

type SaleLine = {
  uuid: string;
  product_name: string;
  batch_number: string;
  expires_on: string | null;
  quantity: string;
  returned_quantity: string;
  /** What is still available to give back. Computed by the server. */
  returnable_quantity: string;
  unit_price: string;
  total: string;
};

type Sale = {
  uuid: string;
  reference: string;
  customer_name: string;
  customer_phone: string;
  status: string;
  is_returnable: boolean;
  sold_at: string;
  sold_by_name: string;
  total: string;
  invoice_number: string;
  lines: SaleLine[];
};

type ReturnLine = {
  uuid: string;
  product_name: string;
  batch_number: string;
  quantity: string;
  refund_amount: string;
  condition_note: string;
};

type SaleReturn = {
  uuid: string;
  reference: string;
  sale_reference: string;
  status: string;
  reason: string;
  restock: boolean;
  restock_note: string;
  requested_by_name: string;
  approved_by_name: string;
  approved_at: string | null;
  decision_notes: string;
  refund_total: string;
  refund_method: string;
  credit_note_number: string;
  completed_at: string | null;
  lines: ReturnLine[];
};

const MONEY = (value: string) =>
  Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 });

const STATUS: Record<string, string> = {
  pending: "Waiting for a decision",
  approved: "Approved",
  rejected: "Refused",
  completed: "Refunded",
};

/* -------------------------------------------------------------------------- */
/* Screen                                                                      */
/* -------------------------------------------------------------------------- */

export function ReturnsPanel() {
  const [returns, setReturns] = useState<SaleReturn[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [raising, setRaising] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.get<{ results: SaleReturn[] }>("/pos/returns/");
      setReturns(page.results);
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

  const decide = async (
    entry: SaleReturn,
    approve: boolean,
    notes: string,
    method: string,
  ) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/pos/returns/${entry.reference}/decide/`, {
        approve,
        refund_method: method,
        decision_notes: notes,
      });
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  const pending = returns.filter((entry) => entry.status === "pending");
  const refunded = returns.filter(
    (entry) => entry.status === "approved" || entry.status === "completed",
  );

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
          label="Waiting for a decision"
          value={pending.length}
          intent={pending.length ? "bad" : "neutral"}
          icon={<Undo2 className="h-4 w-4" />}
        />
        <StatTile
          label="Refunded"
          value={MONEY(
            String(refunded.reduce((sum, e) => sum + Number(e.refund_total), 0)),
          )}
          hint="approved returns"
        />
        <StatTile
          label="Refused"
          value={returns.filter((e) => e.status === "rejected").length}
        />
        <StatTile
          label="Not put back on the shelf"
          value={refunded.filter((e) => !e.restock).length}
          hint="refunded but not resellable"
        />
      </StatGrid>

      <Section
        title="Returns"
        description="Goods brought back to the counter, and what was decided about them."
        actions={
          <Button size="sm" onClick={() => setRaising((open) => !open)}>
            {raising ? "Close" : "Take something back"}
          </Button>
        }
      >
        {raising && (
          <RaiseReturn
            onRaised={() => {
              setRaising(false);
              void load();
            }}
          />
        )}

        {loading ? (
          <TableSkeleton rows={4} />
        ) : returns.length === 0 ? (
          <EmptyState
            illustration="stock"
            title="Nothing has been returned"
            description="A return records what came back over the counter and why. The refund is a separate decision, made by somebody other than whoever took the goods."
          />
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Sale</TableHead>
                  <TableHead>What came back</TableHead>
                  <TableHead>Why</TableHead>
                  <TableHead className="text-right">Refund</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {returns.map((entry) => (
                  <ReturnRow
                    key={entry.uuid}
                    entry={entry}
                    busy={busy}
                    onDecide={decide}
                  />
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}

        <p className="text-xs text-muted-foreground">
          A return cannot be approved by whoever raised it, and approving is what
          releases the refund and puts the stock back.
        </p>
      </Section>
    </div>
  );
}

function ReturnRow({
  entry,
  busy,
  onDecide,
}: {
  entry: SaleReturn;
  busy: boolean;
  onDecide: (
    entry: SaleReturn,
    approve: boolean,
    notes: string,
    method: string,
  ) => void;
}) {
  const [deciding, setDeciding] = useState(false);
  const [notes, setNotes] = useState("");
  const [method, setMethod] = useState("cash");

  return (
    <>
      <TableRow>
        <TableCell className="font-mono text-xs">{entry.reference}</TableCell>
        <TableCell className="font-mono text-xs">
          {entry.sale_reference}
        </TableCell>
        <TableCell className="max-w-[18rem]">
          {entry.lines.map((line) => (
            <div key={line.uuid} className="text-sm">
              {line.quantity} × {line.product_name}
              {line.batch_number && (
                <span className="text-muted-foreground"> ({line.batch_number})</span>
              )}
            </div>
          ))}
          {!entry.restock && (
            <span className="text-xs text-amber-600">not put back on the shelf</span>
          )}
        </TableCell>
        <TableCell className="max-w-[14rem] truncate text-sm">
          {entry.reason}
        </TableCell>
        <TableCell className="text-right tabular-nums">
          {MONEY(entry.refund_total)}
        </TableCell>
        <TableCell>
          <Badge variant={entry.status === "pending" ? "outline" : "secondary"}>
            {STATUS[entry.status] ?? entry.status}
          </Badge>
          {entry.approved_by_name && (
            <div className="text-xs text-muted-foreground">
              by {entry.approved_by_name}
            </div>
          )}
        </TableCell>
        <TableCell className="text-right">
          {entry.status === "pending" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDeciding((open) => !open)}
            >
              Decide
            </Button>
          )}
        </TableCell>
      </TableRow>

      {deciding && entry.status === "pending" && (
        <TableRow>
          <TableCell colSpan={7} className="bg-muted/30">
            <div className="grid gap-3 py-2 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor={`method-${entry.uuid}`}>Refund as</Label>
                <Select
                  id={`method-${entry.uuid}`}
                  value={method}
                  onChange={(event) => setMethod(event.target.value)}
                >
                  <option value="cash">Cash</option>
                  <option value="card">Card</option>
                  <option value="credit_note">Credit note</option>
                  <option value="original">Back to the original method</option>
                </Select>
              </div>

              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor={`notes-${entry.uuid}`}>Decision note</Label>
                <Textarea
                  id={`notes-${entry.uuid}`}
                  rows={2}
                  value={notes}
                  placeholder="Required when refusing."
                  onChange={(event) => setNotes(event.target.value)}
                />
              </div>

              <div className="flex gap-2 sm:col-span-3">
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => onDecide(entry, true, notes, method)}
                >
                  Approve the refund
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  // A refusal must say why: the customer is standing there and
                  // will be told something, and it may as well be the reason
                  // that was recorded.
                  disabled={busy || !notes.trim()}
                  onClick={() => onDecide(entry, false, notes, method)}
                >
                  Refuse
                </Button>
                {!notes.trim() && (
                  <span className="self-center text-xs text-muted-foreground">
                    A refusal needs a reason.
                  </span>
                )}
              </div>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Raising one                                                                 */
/* -------------------------------------------------------------------------- */

function RaiseReturn({ onRaised }: { onRaised: () => void }) {
  const [term, setTerm] = useState("");
  const [sale, setSale] = useState<Sale | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [conditions, setConditions] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [restock, setRestock] = useState(true);
  const [restockNote, setRestockNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const find = async () => {
    if (!term.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      const found = await api.get<Sale>(`/pos/sales/${term.trim()}/`);
      setSale(found);
      setQuantities({});
    } catch (err) {
      setSale(null);
      setProblem(
        err instanceof ApiError ? err.message : "No sale with that reference.",
      );
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!sale) return;
    const entries = Object.entries(quantities)
      .filter(([, value]) => Number(value) > 0)
      .map(([sale_line, quantity]) => ({
        sale_line,
        quantity,
        condition_note: conditions[sale_line] ?? "",
      }));
    if (entries.length === 0) return;

    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/pos/sales/${sale.reference}/return/`, {
        entries,
        reason: reason.trim(),
        restock,
        restock_note: restockNote.trim(),
      });
      onRaised();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not raise it.");
    } finally {
      setBusy(false);
    }
  };

  const chosen = Object.values(quantities).filter((v) => Number(v) > 0).length;

  return (
    <div className="space-y-4 rounded-xl border p-4">
      {problem && (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="return-sale">Sale reference</Label>
        <div className="flex gap-2">
          <Input
            id="return-sale"
            value={term}
            placeholder="The reference on the receipt"
            onChange={(event) => setTerm(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void find();
              }
            }}
          />
          <Button variant="outline" disabled={busy} onClick={() => void find()}>
            <Search className="mr-2 h-4 w-4" />
            Find
          </Button>
        </div>
      </div>

      {sale && !sale.is_returnable && (
        <Alert variant="destructive">
          <PackageX className="h-4 w-4" />
          <AlertTitle>Nothing on this sale can be returned</AlertTitle>
          <AlertDescription>
            It may be voided, already fully returned, or past the window this
            pharmacy allows.
          </AlertDescription>
        </Alert>
      )}

      {sale && sale.is_returnable && (
        <>
          <div className="text-sm text-muted-foreground">
            {sale.reference} · {new Date(sale.sold_at).toLocaleString()} ·{" "}
            {sale.customer_name || "no customer recorded"} · sold by{" "}
            {sale.sold_by_name} · {MONEY(sale.total)}
          </div>

          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead>Batch</TableHead>
                  <TableHead className="text-right">Sold</TableHead>
                  <TableHead className="text-right">Already back</TableHead>
                  <TableHead className="text-right">Can come back</TableHead>
                  <TableHead className="text-right">Returning</TableHead>
                  <TableHead>Condition</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sale.lines.map((line) => {
                  const available = Number(line.returnable_quantity);
                  return (
                    <TableRow
                      key={line.uuid}
                      className={cn(available <= 0 && "text-muted-foreground")}
                    >
                      <TableCell>{line.product_name}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {line.batch_number}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {line.quantity}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {line.returned_quantity}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {line.returnable_quantity}
                      </TableCell>
                      <TableCell className="text-right">
                        <Input
                          type="number"
                          aria-label={`Quantity returning of ${line.product_name}`}
                          className="ml-auto h-8 w-24 text-right"
                          // The server's number, not one worked out here: a
                          // line already partly returned can only give back the
                          // remainder, and a browser-side subtraction would
                          // disagree with the service at the worst moment.
                          max={line.returnable_quantity}
                          disabled={available <= 0}
                          value={quantities[line.uuid] ?? ""}
                          onChange={(event) =>
                            setQuantities((current) => ({
                              ...current,
                              [line.uuid]: event.target.value,
                            }))
                          }
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          aria-label={`Condition of ${line.product_name}`}
                          className="h-8"
                          placeholder="Seal broken, cold chain lost…"
                          disabled={available <= 0}
                          value={conditions[line.uuid] ?? ""}
                          onChange={(event) =>
                            setConditions((current) => ({
                              ...current,
                              [line.uuid]: event.target.value,
                            }))
                          }
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </ScrollX>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="return-reason">Why it is coming back</Label>
              <Textarea
                id="return-reason"
                rows={2}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={restock}
                  onChange={(event) => setRestock(event.target.checked)}
                />
                Put it back on the shelf
              </label>
              <p className="text-xs text-muted-foreground">
                Refunding and restocking are separate questions. A vial that sat
                on the counter for an hour is refundable and not sellable.
              </p>
              {!restock && (
                <Textarea
                  aria-label="Why it is not going back on the shelf"
                  rows={2}
                  value={restockNote}
                  placeholder="Why it cannot be sold again."
                  onChange={(event) => setRestockNote(event.target.value)}
                />
              )}
            </div>
          </div>

          <Button
            disabled={busy || chosen === 0 || !reason.trim()}
            onClick={() => void submit()}
          >
            <Undo2 className="mr-2 h-4 w-4" />
            Raise the return
          </Button>
          {chosen === 0 && (
            <span className="ml-3 text-sm text-muted-foreground">
              Enter a quantity against at least one line.
            </span>
          )}
        </>
      )}
    </div>
  );
}
