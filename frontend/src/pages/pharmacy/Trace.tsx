/**
 * Trace a batch: where it came from, where every unit went, who has it.
 *
 * The screen a recall is run from. Search by batch number or product, open a
 * batch, and read it top to bottom: whether the ledger reconciles, the flow
 * from receipt to shelf to people, the people it reached — patients it was
 * dispensed to and counter customers, net of anything they brought back — and
 * every movement in order, so any figure can be checked.
 *
 * Names and phone numbers appear only for somebody who may read patients; a
 * storekeeper sees the same flow with the identities withheld and a sentence
 * saying so.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Printer, Search } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { printElement } from "@/lib/export";
import { downloadWorkbook } from "@/lib/xlsx";
import { useSession } from "@/hooks/useSession";
import { StatusBadge } from "@/components/ui/status";
import { PrintableDocument } from "@/components/ui/export";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";

interface BatchHit {
  uuid: string;
  batch_number: string;
  product: string;
  product_code: string;
  expires_on: string;
  status: string;
  supplier: string;
  received_on: string;
}

interface Trace {
  batch: BatchHit;
  identities: "shown" | "restricted";
  totals: {
    received: string;
    to_people: string;
    returned: string;
    written_off: string;
    held: string;
    recipients: number;
    identified_recipients: number;
  };
  reconciles: boolean;
  discrepancy: string;
  origin: { at: string; kind: string; quantity: string; reference: string; supplier: string; unit_cost: string }[];
  recipients: {
    kind: string;
    at: string;
    reference: string;
    patient_mrn: string;
    name: string;
    phone: string;
    quantity: string;
  }[];
  holding: { location: string; location_name: string; quarantine: boolean; quantity: string }[];
  ledger: {
    at: string;
    movement: string;
    movement_label: string;
    direction: "in" | "out";
    quantity: string;
    balance_after: string;
    location: string;
    reference: string;
    by: string;
    patient: string;
  }[];
}

const qty = (value: string) => Number(value).toLocaleString("en-IN", { maximumFractionDigits: 3 });
const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function TracePanel() {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<BatchHit[] | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const { session } = useSession();

  useEffect(() => {
    const handle = window.setTimeout(() => {
      api
        .get<BatchHit[]>(`/pharmacy/stock/trace/?q=${encodeURIComponent(term.trim())}`)
        .then(setHits)
        .catch(() => setHits([]));
    }, 250);
    return () => window.clearTimeout(handle);
  }, [term]);

  const open = async (uuid: string) => {
    setLoading(true);
    setProblem(null);
    try {
      setTrace(await api.get<Trace>(`/pharmacy/batches/${uuid}/trace/`));
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "The trace did not load.");
    } finally {
      setLoading(false);
    }
  };

  const exportTrace = () => {
    if (!trace) return;
    const subtitle = `${trace.batch.product} · batch ${trace.batch.batch_number} · expires ${day(trace.batch.expires_on)}`;
    void downloadWorkbook(
      `trace-${trace.batch.batch_number}`,
      [
        {
          name: "Recipients",
          title: "Who it reached",
          subtitle,
          columns: [
            { header: "How" }, { header: "Date", kind: "date" }, { header: "Name" },
            { header: "MRN" }, { header: "Phone" }, { header: "Quantity", kind: "number" },
            { header: "Reference" },
          ],
          rows: trace.recipients.map((row) => [
            row.kind, row.at, row.name, row.patient_mrn, row.phone, row.quantity, row.reference,
          ]),
        },
        {
          name: "Movements",
          title: "Every movement",
          subtitle,
          columns: [
            { header: "When", kind: "date" }, { header: "Movement" }, { header: "In", kind: "number" },
            { header: "Out", kind: "number" }, { header: "Balance", kind: "number" },
            { header: "Location" }, { header: "Reference" }, { header: "By" },
          ],
          rows: trace.ledger.map((row) => [
            row.at, row.movement_label,
            row.direction === "in" ? row.quantity : null,
            row.direction === "out" ? row.quantity : null,
            row.balance_after, row.location, row.reference, row.by,
          ]),
        },
        {
          name: "On hand",
          title: "Where it is now",
          subtitle,
          columns: [{ header: "Location" }, { header: "Name" }, { header: "Quarantine" }, { header: "Quantity", kind: "number" }],
          rows: trace.holding.map((row) => [row.location, row.location_name, row.quarantine ? "Yes" : "No", row.quantity]),
          totals: ["Total", null, null, trace.totals.held],
        },
        {
          name: "Origin",
          title: "Where it came from",
          subtitle,
          columns: [
            { header: "Date", kind: "date" }, { header: "Kind" }, { header: "Supplier" },
            { header: "Receipt" }, { header: "Quantity", kind: "number" }, { header: "Unit cost", kind: "money" },
          ],
          rows: trace.origin.map((row) => [row.at, row.kind, row.supplier, row.reference, row.quantity, row.unit_cost]),
        },
      ],
      { organization: session?.organization?.display_name, generatedBy: session?.user.display_name },
    );
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <Card className="h-fit">
        <CardContent className="space-y-3 pt-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Batch number or product"
              className="pl-8"
              aria-label="Find a batch"
            />
          </div>
          <ul className="max-h-[32rem] space-y-1 overflow-y-auto">
            {(hits ?? []).map((hit) => (
              <li key={hit.uuid}>
                <button
                  type="button"
                  onClick={() => void open(hit.uuid)}
                  className={cn(
                    "w-full rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-accent",
                    trace?.batch.uuid === hit.uuid && "bg-accent",
                  )}
                >
                  <span className="block truncate font-medium">{hit.product}</span>
                  <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{hit.batch_number}</span>
                    <span>exp {day(hit.expires_on)}</span>
                  </span>
                </button>
              </li>
            ))}
            {hits && hits.length === 0 && (
              <li className="px-2.5 py-6 text-center text-sm text-muted-foreground">No batches match.</li>
            )}
          </ul>
        </CardContent>
      </Card>

      <div className="min-w-0 space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        {!trace ? (
          <Card>
            <CardContent className="py-16 text-center text-sm text-muted-foreground">
              {loading ? "Tracing…" : "Choose a batch to trace it."}
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{trace.batch.product}</h2>
                <p className="text-sm text-muted-foreground">
                  Batch <span className="font-mono">{trace.batch.batch_number}</span> · expires{" "}
                  {day(trace.batch.expires_on)} · {trace.batch.supplier || "supplier not recorded"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={trace.batch.status} />
                <Button variant="outline" size="sm" onClick={exportTrace}>
                  <Download className="h-4 w-4" />
                  Excel
                </Button>
                <Button variant="outline" size="sm" onClick={() => printElement(`recall-${trace.batch.uuid}`)}>
                  <Printer className="h-4 w-4" />
                  Recall list
                </Button>
              </div>
            </div>

            {trace.reconciles ? (
              <Alert>
                <CheckCircle2 className="h-4 w-4 text-good" />
                <AlertTitle>Reconciles</AlertTitle>
                <AlertDescription>Every unit received is accounted for.</AlertDescription>
              </Alert>
            ) : (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Does not reconcile</AlertTitle>
                <AlertDescription>
                  The locations hold {qty(trace.discrepancy)} more than the ledger explains. Count the
                  stock before relying on this trace.
                </AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                ["Received", trace.totals.received],
                ["To people", trace.totals.to_people],
                ["Returned", trace.totals.returned],
                ["Written off", trace.totals.written_off],
                ["On hand", trace.totals.held],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border bg-card px-3 py-2.5">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="text-lg font-semibold tabular-nums">{qty(value)}</p>
                </div>
              ))}
            </div>

            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm">Recipients ({trace.recipients.length})</CardTitle>
                {trace.identities === "restricted" && (
                  <Badge variant="secondary">Names withheld</Badge>
                )}
              </CardHeader>
              <CardContent className="overflow-x-auto p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>How</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Phone</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead>Date</TableHead>
                      <TableHead>Reference</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {trace.recipients.map((row, index) => (
                      <TableRow key={`${row.reference}-${index}`}>
                        <TableCell className="first-letter:uppercase">{row.kind}</TableCell>
                        <TableCell>
                          {row.name || <span className="text-muted-foreground">Restricted</span>}
                          {row.patient_mrn && (
                            <span className="block text-xs text-muted-foreground">{row.patient_mrn}</span>
                          )}
                        </TableCell>
                        <TableCell className="tabular-nums">{row.phone || "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{qty(row.quantity)}</TableCell>
                        <TableCell>{stamp(row.at)}</TableCell>
                        <TableCell className="font-mono text-xs">{row.reference}</TableCell>
                      </TableRow>
                    ))}
                    {trace.recipients.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                          None of this batch has left the pharmacy.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <div className="grid gap-4 xl:grid-cols-[18rem_1fr]">
              <Card className="h-fit">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">On hand</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1.5 text-sm">
                  {trace.holding.length === 0 ? (
                    <p className="text-muted-foreground">None left.</p>
                  ) : (
                    trace.holding.map((row) => (
                      <div key={row.location} className="flex items-center justify-between gap-2">
                        <span>
                          {row.location_name}
                          {row.quarantine && <Badge variant="warning" className="ml-1.5">Quarantine</Badge>}
                        </span>
                        <span className="tabular-nums">{qty(row.quantity)}</span>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Movements ({trace.ledger.length})</CardTitle>
                </CardHeader>
                <CardContent className="max-h-[26rem] overflow-auto p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>When</TableHead>
                        <TableHead>Movement</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead className="text-right">Balance</TableHead>
                        <TableHead>Where</TableHead>
                        <TableHead>By</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {trace.ledger.map((row, index) => (
                        <TableRow key={index}>
                          <TableCell className="whitespace-nowrap">{stamp(row.at)}</TableCell>
                          <TableCell>{row.movement_label}</TableCell>
                          <TableCell
                            className={cn(
                              "text-right tabular-nums",
                              row.direction === "in" ? "text-good" : "text-foreground",
                            )}
                          >
                            {row.direction === "in" ? "+" : "−"}
                            {qty(row.quantity)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{qty(row.balance_after)}</TableCell>
                          <TableCell>{row.location}</TableCell>
                          <TableCell className="text-muted-foreground">{row.by}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>

            {/* The recall list, printed alone. */}
            <div className="hidden print:block">
              <PrintableDocument
                id={`recall-${trace.batch.uuid}`}
                title="Recall contact list"
                reference={trace.batch.batch_number}
                organization={session?.organization?.display_name ?? "Nirova"}
                printedBy={session?.user.display_name}
                meta={[
                  { label: "Product", value: trace.batch.product },
                  { label: "Batch", value: trace.batch.batch_number },
                  { label: "Expires", value: day(trace.batch.expires_on) },
                  { label: "Supplier", value: trace.batch.supplier || "—" },
                ]}
              >
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left">
                      <th className="py-1.5">Name</th>
                      <th className="py-1.5">Phone</th>
                      <th className="py-1.5 text-right">Qty</th>
                      <th className="py-1.5">Date</th>
                      <th className="py-1.5">Contacted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trace.recipients.map((row, index) => (
                      <tr key={index} className="border-b">
                        <td className="py-1.5">{row.name || "Restricted"} {row.patient_mrn && `(${row.patient_mrn})`}</td>
                        <td className="py-1.5">{row.phone || "—"}</td>
                        <td className="py-1.5 text-right">{qty(row.quantity)}</td>
                        <td className="py-1.5">{day(row.at)}</td>
                        <td className="py-1.5">☐</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </PrintableDocument>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
