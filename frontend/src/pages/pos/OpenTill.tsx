/**
 * Opening a till.
 *
 * **The dropdown was empty, and nothing said why.** The screen listed every
 * pharmacy, clinic and hospital, picked the first — alphabetically the clinic,
 * which has no dispensary — and then offered "Sells from" with nothing in it
 * and a disabled button. A cashier at the pharmacy saw a broken form; the
 * actual answer ("choose the pharmacy") was one dropdown up and invisible.
 *
 * So the facilities are derived from where a till can actually sell: every
 * active, dispensable stock location, grouped by its facility. A facility with
 * no dispensary is not offered, because there is nothing it could do. If none
 * exists anywhere, the screen says so and says what would fix it.
 *
 * Two more things a real counter needs before it opens:
 *
 *  - **Which tills are already open here.** Opening COUNTER-1 while a colleague
 *    is on it is refused by the server, correctly — the screen should say so
 *    before the cashier types it, and suggest a free one.
 *  - **Counting the drawer by note.** The float is what the end-of-shift
 *    variance is measured against, and cashiers count it note by note. A
 *    single amount box invites a guess; a denomination count produces the
 *    figure and shows the working.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Calculator,
  Loader2,
  LockKeyhole,
  MapPin,
  Store,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CounterSession, Paginated, StockLocation } from "@/types";
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
} from "@/components/ui/primitives";
import { Avatar } from "@/components/ui/data";
import { EmptyState, Skeleton } from "@/components/ui/feedback";

/** Nepali notes and coins, largest first — the order a drawer is counted in. */
const DENOMINATIONS = [1000, 500, 100, 50, 20, 10, 5, 2, 1] as const;

type Located = StockLocation & { facility: string; facility_name: string };

const rupees = (value: number) =>
  `Rs ${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const since = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/** COUNTER-1, COUNTER-2, … — the first not currently open. */
function freeTill(open: CounterSession[]): string {
  const taken = new Set(open.map((session) => session.counter.toUpperCase()));
  for (let n = 1; n < 50; n += 1) {
    if (!taken.has(`COUNTER-${n}`)) return `COUNTER-${n}`;
  }
  return "COUNTER-1";
}

export function OpenTill({
  onOpened,
  error,
}: {
  onOpened: (session: CounterSession) => void;
  error: string | null;
}) {
  const [locations, setLocations] = useState<Located[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [facility, setFacility] = useState("");
  const [location, setLocation] = useState("");
  const [sessions, setSessions] = useState<CounterSession[] | null>(null);
  const [counter, setCounter] = useState("COUNTER-1");
  const [counterTouched, setCounterTouched] = useState(false);
  const [float, setFloat] = useState("2000.00");
  const [counting, setCounting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // -- where a till can sell from ------------------------------------------
  useEffect(() => {
    void (async () => {
      try {
        const result = await api.get<Paginated<Located>>(
          "/pharmacy/locations/?is_active=true&page_size=200",
        );
        const dispensable = result.results.filter((row) => row.is_dispensable);
        setLocations(dispensable);
        if (dispensable[0]) setFacility(dispensable[0].facility);
      } catch (err) {
        setLocations([]);
        setLoadProblem(
          err instanceof ApiError && err.status === 403
            ? "Your role cannot see the stock locations a till sells from. Ask an administrator for stock visibility."
            : err instanceof ApiError
              ? err.message
              : "The stock locations did not load.",
        );
      }
    })();
  }, []);

  const facilities = useMemo(() => {
    const byFacility = new Map<string, { name: string; count: number }>();
    for (const row of locations ?? []) {
      const entry = byFacility.get(row.facility) ?? { name: row.facility_name, count: 0 };
      entry.count += 1;
      byFacility.set(row.facility, entry);
    }
    return [...byFacility.entries()].map(([uuid, entry]) => ({ uuid, ...entry }));
  }, [locations]);

  const here = useMemo(
    () => (locations ?? []).filter((row) => row.facility === facility),
    [locations, facility],
  );

  useEffect(() => {
    setLocation(here[0]?.uuid ?? "");
  }, [here]);

  // -- who is already on a till here ---------------------------------------
  useEffect(() => {
    if (!facility) return;
    setSessions(null);
    void (async () => {
      try {
        const result = await api.get<Paginated<CounterSession>>(
          `/pos/sessions/?facility=${facility}&page_size=12`,
        );
        setSessions(result.results);
      } catch {
        // Not being able to see colleagues' tills is not a reason to stop
        // somebody opening their own; the server still refuses a clash.
        setSessions([]);
      }
    })();
  }, [facility]);

  const openNow = useMemo(
    () => (sessions ?? []).filter((row) => row.status === "open" || row.status === "closing"),
    [sessions],
  );
  const closedToday = useMemo(() => {
    const today = new Date().toDateString();
    return (sessions ?? []).filter(
      (row) => row.closed_at && new Date(row.closed_at).toDateString() === today,
    );
  }, [sessions]);

  useEffect(() => {
    if (!counterTouched) setCounter(freeTill(openNow));
  }, [openNow, counterTouched]);

  // Stable, because the note count reports its total from an effect and a
  // fresh function every render would re-run that effect every render.
  const takeCount = useCallback((total: number) => setFloat(total.toFixed(2)), []);

  const clash = openNow.find(
    (row) => row.counter.toUpperCase() === counter.trim().toUpperCase(),
  );

  const open = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const created = await api.post<CounterSession>("/pos/sessions/open/", {
        facility,
        location,
        counter: counter.trim(),
        opening_float: float,
      });
      onOpened(created);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not open the till.");
    } finally {
      setBusy(false);
    }
  };

  // -- states ---------------------------------------------------------------
  if (locations === null) {
    return (
      <div className="mx-auto grid max-w-5xl gap-4 py-6 lg:grid-cols-[1fr_20rem]">
        <Skeleton className="h-[26rem] rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  if (facilities.length === 0) {
    return (
      <Card className="mx-auto max-w-xl">
        <EmptyState
          illustration={loadProblem ? "warning" : "documents"}
          title={loadProblem ? "The till cannot see where to sell from" : "Nothing to sell from yet"}
          description={
            loadProblem ??
            "A till sells from a stock location marked as dispensable — a dispensary counter, not a store room. None is set up in any facility yet."
          }
          action={
            !loadProblem && (
              <Button asChild variant="outline" size="sm">
                <Link to="/pharmacy">Set up stock locations</Link>
              </Button>
            )
          }
        />
      </Card>
    );
  }

  return (
    <div className="mx-auto grid max-w-5xl gap-4 py-6 lg:grid-cols-[1fr_20rem]">
      <Card className="overflow-hidden">
        <CardHeader className="border-b bg-muted/30">
          <CardTitle className="flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary">
              <LockKeyhole className="h-[18px] w-[18px]" />
            </span>
            Open a till
          </CardTitle>
          <CardDescription>
            Count the drawer before you start. The float you enter is what the
            end-of-shift variance is measured against.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5 pt-5">
          {(problem || error) && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Not opened</AlertTitle>
              <AlertDescription>{problem ?? error}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="till-facility">Facility</Label>
              <Select
                id="till-facility"
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
            <div className="space-y-2">
              <Label htmlFor="till-location">Sells from</Label>
              <Select
                id="till-location"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
              >
                {here.map((row) => (
                  <option key={row.uuid} value={row.uuid}>
                    {row.name} · {row.code}
                  </option>
                ))}
              </Select>
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <MapPin className="h-3 w-3" />
                Stock sold here comes off this location, earliest expiry first.
              </p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="till-counter">Till</Label>
              <Input
                id="till-counter"
                value={counter}
                onChange={(event) => {
                  setCounterTouched(true);
                  setCounter(event.target.value);
                }}
                aria-invalid={Boolean(clash)}
                className={cn(clash && "border-destructive focus-visible:ring-destructive")}
              />
              {clash ? (
                <p className="text-xs text-destructive">
                  {clash.counter} is open under {clash.cashier_name}. Use{" "}
                  <button
                    type="button"
                    className="font-medium underline underline-offset-2"
                    onClick={() => {
                      setCounterTouched(false);
                      setCounter(freeTill(openNow));
                    }}
                  >
                    {freeTill(openNow)}
                  </button>{" "}
                  instead.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  The name on the drawer. Each open till is one cashier's.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="till-float">Counted float</Label>
                <button
                  type="button"
                  onClick={() => setCounting((value) => !value)}
                  className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  aria-expanded={counting}
                >
                  <Calculator className="h-3 w-3" />
                  {counting ? "Type the total" : "Count by note"}
                </button>
              </div>
              <Input
                id="till-float"
                inputMode="decimal"
                value={float}
                readOnly={counting}
                onChange={(event) => setFloat(event.target.value)}
                className={cn("tabular-nums", counting && "bg-muted/50")}
              />
            </div>
          </div>

          {counting && <NoteCount onTotal={takeCount} />}

          <Button
            className="w-full"
            size="lg"
            onClick={() => void open()}
            disabled={busy || !facility || !location || !counter.trim() || Boolean(clash)}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
            Open {counter.trim() || "till"} with {rupees(Number(float) || 0)}
          </Button>
        </CardContent>
      </Card>

      <TillsHere open={openNow} closed={closedToday} loading={sessions === null} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function NoteCount({ onTotal }: { onTotal: (total: number) => void }) {
  const [counts, setCounts] = useState<Record<number, string>>({});
  const total = DENOMINATIONS.reduce(
    (sum, note) => sum + note * (Number.parseInt(counts[note] ?? "", 10) || 0),
    0,
  );

  useEffect(() => {
    onTotal(total);
  }, [total, onTotal]);

  return (
    <div className="rounded-lg border bg-muted/20 p-3">
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
        {DENOMINATIONS.map((note) => (
          <label
            key={note}
            className="flex flex-col gap-1 rounded-md border bg-background px-2 py-1.5 focus-within:ring-2 focus-within:ring-ring"
          >
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Rs {note} {note >= 5 ? "note" : "coin"}
            </span>
            <input
              inputMode="numeric"
              value={counts[note] ?? ""}
              placeholder="0"
              onChange={(event) =>
                setCounts((prev) => ({ ...prev, [note]: event.target.value.replace(/\D/g, "") }))
              }
              className="w-full bg-transparent text-sm font-semibold tabular-nums outline-none"
              aria-label={`Number of Rs ${note}`}
            />
          </label>
        ))}
      </div>
      <p className="mt-2 text-right text-sm">
        <span className="text-muted-foreground">Drawer holds </span>
        <span className="font-semibold tabular-nums">{rupees(total)}</span>
      </p>
    </div>
  );
}

function TillsHere({
  open,
  closed,
  loading,
}: {
  open: CounterSession[];
  closed: CounterSession[];
  loading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Store className="h-4 w-4 text-muted-foreground" />
          Tills here today
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : open.length === 0 && closed.length === 0 ? (
          <p className="text-muted-foreground">
            No till has opened here today. You are first on.
          </p>
        ) : (
          <>
            {open.length > 0 && (
              <ul className="space-y-2">
                {open.map((row) => (
                  <li key={row.uuid} className="flex items-center gap-2.5">
                    <Avatar name={row.cashier_name} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{row.cashier_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {row.counter} · since {since(row.opened_at)}
                      </p>
                    </div>
                    <Badge variant="success">Open</Badge>
                  </li>
                ))}
              </ul>
            )}
            {closed.length > 0 && (
              <div className="space-y-2 border-t pt-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Cashed up
                </p>
                {closed.map((row) => {
                  const variance = Number(row.variance ?? 0);
                  return (
                    <div key={row.uuid} className="flex items-center justify-between gap-2">
                      <span className="truncate">
                        {row.counter} · {row.cashier_name}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 text-xs font-medium tabular-nums",
                          variance === 0 ? "text-good" : "text-critical",
                        )}
                        title="Counted against expected cash"
                      >
                        {variance === 0 ? "Balanced" : `${variance > 0 ? "+" : ""}${variance.toFixed(2)}`}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
