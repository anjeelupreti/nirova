/**
 * The retail counter.
 *
 * This screen is used more than every other screen in the product combined,
 * by someone with a queue in front of them. Three things follow from that.
 *
 * **It is keyboard-first.** The search box holds focus and returns to it after
 * every action. Enter adds the top match, F2 opens payment, Escape backs out.
 * A cashier serving a queue never reaches for the mouse, and a barcode scanner
 * is a keyboard that types very fast and presses Enter.
 *
 * **The total comes from the server.** Every basket change re-quotes. The
 * figure the customer is asked for is rounded to the whole rupee on the
 * invoice, and a screen doing its own arithmetic would eventually ask for a
 * rupee the receipt does not mention.
 *
 * **Nothing is hidden until it is too late.** Short stock, prescription-only
 * items and expiry dates are on the line as it is added — not surfaced as a
 * rejected submission after the customer has counted out their money.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  CalendarClock,
  Check,
  CornerDownLeft,
  CreditCard,
  Loader2,
  LockKeyhole,
  Minus,
  Plus,
  Printer,
  Receipt as ReceiptIcon,
  RotateCcw,
  Search,
  ShoppingCart,
  Smartphone,
  Trash2,
  Wallet,
  X,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  CounterProduct,
  CounterSession,
  Facility,
  Paginated,
  Sale,
  SaleQuote,
  SalesSummary,
  SessionTakings,
  StockLocation,
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

/** One line in the basket, before it is anything the server knows about. */
interface BasketItem {
  product: CounterProduct;
  quantity: number;
  discountPercent: number;
}

interface Tender {
  method: string;
  amount: string;
}

const METHODS: { id: string; label: string; icon: typeof Banknote }[] = [
  { id: "cash", label: "Cash", icon: Banknote },
  { id: "esewa", label: "eSewa", icon: Smartphone },
  { id: "khalti", label: "Khalti", icon: Wallet },
  { id: "fonepay", label: "Fonepay", icon: Smartphone },
  { id: "card", label: "Card", icon: CreditCard },
];

/** Notes a Nepali till actually holds, for one-tap exact tender. */
const NOTES = [10, 20, 50, 100, 500, 1000];

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const daysUntil = (date: string | null) => {
  if (!date) return null;
  const ms = new Date(date).getTime() - Date.now();
  return Math.floor(ms / 86_400_000);
};

export default function CounterPage() {
  const [session, setSession] = useState<CounterSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"sell" | "sales" | "close">("sell");

  const loadSession = useCallback(async () => {
    setLoading(true);
    try {
      // 204 means no open session — a distinct answer, not an empty list.
      const active = await api.get<CounterSession | null>(
        "/pos/sessions/active/",
      );
      setSession(active);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the till.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  if (loading) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Opening the counter…
      </p>
    );
  }

  if (!session) {
    return <OpenTill onOpened={setSession} error={error} />;
  }

  return (
    <div className="space-y-4">
      <TillBar
        session={session}
        view={view}
        onView={setView}
      />
      {view === "sell" && <SellView session={session} />}
      {view === "sales" && <SalesView session={session} />}
      {view === "close" && (
        <CloseTill session={session} onClosed={() => void loadSession()} />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Opening                                                                     */
/* -------------------------------------------------------------------------- */

function OpenTill({
  onOpened,
  error,
}: {
  onOpened: (session: CounterSession) => void;
  error: string | null;
}) {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [locations, setLocations] = useState<StockLocation[]>([]);
  const [facility, setFacility] = useState("");
  const [location, setLocation] = useState("");
  const [counter, setCounter] = useState("COUNTER-1");
  const [float, setFloat] = useState("2000.00");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const result = await api.get<Paginated<Facility>>("/org/facilities/");
      const pharmacies = result.results.filter((row) =>
        ["pharmacy", "clinic", "hospital"].includes(row.facility_type),
      );
      setFacilities(pharmacies);
      if (pharmacies[0]) setFacility(pharmacies[0].uuid);
    })();
  }, []);

  useEffect(() => {
    if (!facility) return;
    void (async () => {
      const result = await api.get<Paginated<StockLocation>>(
        `/pharmacy/locations/?facility=${facility}`,
      );
      const dispensable = result.results.filter((row) => row.is_dispensable);
      setLocations(dispensable);
      setLocation(dispensable[0]?.uuid ?? "");
    })();
  }, [facility]);

  const open = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const created = await api.post<CounterSession>("/pos/sessions/open/", {
        facility,
        location,
        counter,
        opening_float: float,
      });
      onOpened(created);
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "Could not open the till.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg space-y-4 py-8">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LockKeyhole className="h-5 w-5" />
            Open the till
          </CardTitle>
          <CardDescription>
            Count the drawer before you start. The float you enter is what the
            end-of-shift variance is measured against — carrying yesterday's
            figure forward would make an unexplained shortage disappear.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {(problem || error) && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Not opened</AlertTitle>
              <AlertDescription>{problem ?? error}</AlertDescription>
            </Alert>
          )}

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
              {locations.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.code} — {row.name}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="till-counter">Till</Label>
              <Input
                id="till-counter"
                value={counter}
                onChange={(event) => setCounter(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="till-float">Counted float</Label>
              <Input
                id="till-float"
                inputMode="decimal"
                value={float}
                onChange={(event) => setFloat(event.target.value)}
              />
            </div>
          </div>

          <Button
            className="w-full"
            onClick={() => void open()}
            disabled={busy || !facility || !location}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <LockKeyhole className="h-4 w-4" />
            )}
            Open till
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The bar across the top                                                      */
/* -------------------------------------------------------------------------- */

function TillBar({
  session,
  view,
  onView,
}: {
  session: CounterSession;
  view: string;
  onView: (view: "sell" | "sales" | "close") => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-background px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
        </span>
        <span className="font-medium">{session.counter}</span>
        <Badge variant="secondary">{session.reference}</Badge>
      </div>
      <span className="text-sm text-muted-foreground">
        {session.cashier_name} · {session.facility_name} · {session.location_code}
      </span>
      <div className="ml-auto flex gap-1">
        {(
          [
            ["sell", "Sell", ShoppingCart],
            ["sales", "Today", ReceiptIcon],
            ["close", "Cash up", Banknote],
          ] as const
        ).map(([id, label, Icon]) => (
          <Button
            key={id}
            variant={view === id ? "default" : "ghost"}
            size="sm"
            onClick={() => onView(id)}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Button>
        ))}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Selling                                                                     */
/* -------------------------------------------------------------------------- */

function SellView({ session }: { session: CounterSession }) {
  const [term, setTerm] = useState("");
  const [results, setResults] = useState<CounterProduct[]>([]);
  const [searching, setSearching] = useState(false);
  const [basket, setBasket] = useState<BasketItem[]>([]);
  const [quote, setQuote] = useState<SaleQuote | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [paying, setPaying] = useState(false);
  const [receipt, setReceipt] = useState<Sale | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");

  const searchBox = useRef<HTMLInputElement>(null);

  const focusSearch = useCallback(() => {
    // Returning focus after every action is what makes the screen usable at
    // speed. A cashier who has to click back into the box between items is
    // slower than the queue.
    window.setTimeout(() => searchBox.current?.focus(), 0);
  }, []);

  useEffect(focusSearch, [focusSearch]);

  // -- lookup, debounced ---------------------------------------------------
  useEffect(() => {
    if (term.trim().length < 2) {
      setResults([]);
      return;
    }
    const handle = window.setTimeout(async () => {
      setSearching(true);
      try {
        const rows = await api.get<CounterProduct[]>(
          `/pos/search/?q=${encodeURIComponent(term)}&location=${session.location}`,
        );
        setResults(rows);
      } finally {
        setSearching(false);
      }
    }, 180);
    return () => window.clearTimeout(handle);
  }, [term, session.location]);

  // -- re-quote whenever the basket changes --------------------------------
  useEffect(() => {
    if (basket.length === 0) {
      setQuote(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      setQuoting(true);
      try {
        const priced = await api.post<SaleQuote>("/pos/sales/quote/", {
          session: session.uuid,
          items: basket.map((item) => ({
            product: item.product.uuid,
            quantity: String(item.quantity),
            discount_percent: String(item.discountPercent),
          })),
        });
        if (!cancelled) setQuote(priced);
      } catch (err) {
        if (!cancelled) {
          setProblem(
            err instanceof ApiError ? err.message : "Could not price the basket.",
          );
        }
      } finally {
        if (!cancelled) setQuoting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [basket, session.uuid]);

  const add = useCallback(
    (product: CounterProduct) => {
      setBasket((current) => {
        const existing = current.findIndex(
          (item) => item.product.uuid === product.uuid,
        );
        if (existing >= 0) {
          const next = [...current];
          next[existing] = {
            ...next[existing],
            quantity: next[existing].quantity + 1,
          };
          return next;
        }
        return [...current, { product, quantity: 1, discountPercent: 0 }];
      });
      setTerm("");
      setResults([]);
      focusSearch();
    },
    [focusSearch],
  );

  const setQuantity = (index: number, quantity: number) =>
    setBasket((current) =>
      quantity <= 0
        ? current.filter((_, i) => i !== index)
        : current.map((item, i) => (i === index ? { ...item, quantity } : item)),
    );

  const setDiscount = (index: number, percent: number) =>
    setBasket((current) =>
      current.map((item, i) =>
        i === index
          ? { ...item, discountPercent: Math.min(Math.max(percent, 0), 100) }
          : item,
      ),
    );

  const clear = () => {
    setBasket([]);
    setQuote(null);
    setCustomerName("");
    setCustomerPhone("");
    focusSearch();
  };

  // -- keyboard ------------------------------------------------------------
  const onSearchKey = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && results[0]) {
      event.preventDefault();
      add(results[0]);
    }
    if (event.key === "Escape") {
      setTerm("");
      setResults([]);
    }
  };

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "F2" && quote?.can_sell) {
        event.preventDefault();
        setPaying(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [quote]);

  if (receipt) {
    return (
      <ReceiptPanel
        sale={receipt}
        onNext={() => {
          setReceipt(null);
          clear();
        }}
      />
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      {/* ---- left: search and basket ------------------------------------ */}
      <div className="space-y-4">
        <Card>
          <CardContent className="pt-6">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={searchBox}
                className="h-11 pl-9 text-base"
                placeholder="Scan a barcode, or type a brand, generic or code…"
                value={term}
                onChange={(event) => setTerm(event.target.value)}
                onKeyDown={onSearchKey}
                autoComplete="off"
              />
              {searching && (
                <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
              )}
            </div>

            {results.length > 0 && (
              <ul className="mt-2 divide-y rounded-md border">
                {results.map((row, index) => {
                  const days = daysUntil(row.expires_on);
                  const short = Number(row.available) <= 0;
                  return (
                    <li key={row.uuid}>
                      <button
                        type="button"
                        onClick={() => add(row)}
                        disabled={short}
                        className={cn(
                          "flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-muted/60",
                          short && "cursor-not-allowed opacity-50",
                          index === 0 && "bg-muted/40",
                        )}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate font-medium">
                              {row.name}
                            </span>
                            {row.requires_prescription && (
                              <Badge variant="destructive">Rx only</Badge>
                            )}
                            {days !== null && days < 90 && (
                              <Badge variant="secondary">
                                <CalendarClock className="mr-1 h-3 w-3" />
                                {days}d
                              </Badge>
                            )}
                          </div>
                          <p className="truncate text-xs text-muted-foreground">
                            {row.code} · batch {row.batch_number || "—"} ·{" "}
                            {short ? "out of stock" : `${row.available} in stock`}
                          </p>
                        </div>
                        <span className="font-medium tabular-nums">
                          {rupees(row.unit_price)}
                        </span>
                        {index === 0 && (
                          <CornerDownLeft className="h-3.5 w-3.5 text-muted-foreground" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">
              Basket
              {basket.length > 0 && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  {basket.length} item{basket.length === 1 ? "" : "s"}
                </span>
              )}
            </CardTitle>
            {basket.length > 0 && (
              <Button variant="ghost" size="sm" onClick={clear}>
                <Trash2 className="h-4 w-4" />
                Clear
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {basket.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                Scan or search to start a sale.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="w-32">Quantity</TableHead>
                    <TableHead className="w-24">Disc %</TableHead>
                    <TableHead className="w-28 text-right">Line</TableHead>
                    <TableHead className="w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {basket.map((item, index) => {
                    // Quoted lines are per batch, so one basket row can map to
                    // several — sum them rather than showing the first.
                    const lines =
                      quote?.lines.filter(
                        (line) => line.product === item.product.code,
                      ) ?? [];
                    const lineTotal = lines.reduce(
                      (sum, line) => sum + Number(line.total),
                      0,
                    );
                    return (
                      <TableRow key={item.product.uuid}>
                        <TableCell>
                          <div className="font-medium">{item.product.name}</div>
                          <div className="text-xs text-muted-foreground">
                            {lines.length > 1
                              ? `${lines.length} batches`
                              : lines[0]?.batch_number ||
                                item.product.batch_number}
                            {lines.length > 1 && " — FEFO spans batches"}
                            {" · "}
                            {rupees(item.product.unit_price)} each
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() =>
                                setQuantity(index, item.quantity - 1)
                              }
                            >
                              <Minus className="h-3 w-3" />
                            </Button>
                            <Input
                              className="h-7 w-14 text-center tabular-nums"
                              inputMode="numeric"
                              value={item.quantity}
                              onChange={(event) =>
                                setQuantity(index, Number(event.target.value) || 0)
                              }
                            />
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() =>
                                setQuantity(index, item.quantity + 1)
                              }
                            >
                              <Plus className="h-3 w-3" />
                            </Button>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Input
                            className="h-7 w-16 tabular-nums"
                            inputMode="decimal"
                            value={item.discountPercent}
                            onChange={(event) =>
                              setDiscount(index, Number(event.target.value) || 0)
                            }
                          />
                        </TableCell>
                        <TableCell className="text-right font-medium tabular-nums">
                          {lines.length ? rupees(lineTotal) : "—"}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => setQuantity(index, 0)}
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ---- right: totals and tender ----------------------------------- */}
      <div className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Not sold</AlertTitle>
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        {quote?.shortfalls.length ? (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Not enough stock</AlertTitle>
            <AlertDescription>
              <ul className="space-y-1">
                {quote.shortfalls.map((row) => (
                  <li key={row.product}>
                    {row.product}: {row.available} of {row.requested} available.
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}

        {quote?.warnings.length ? (
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Needs a prescription</AlertTitle>
            <AlertDescription>
              <ul className="space-y-1">
                {quote.warnings.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              Attach the prescription from the patient's record to sell this.
            </AlertDescription>
          </Alert>
        ) : null}

        <Card>
          <CardContent className="space-y-3 pt-6">
            <Row label="Subtotal" value={quote?.subtotal ?? "0"} />
            {Number(quote?.discount_total ?? 0) > 0 && (
              <Row
                label="Discount"
                value={`−${quote?.discount_total}`}
                tone="text-emerald-600"
              />
            )}
            {Number(quote?.tax_total ?? 0) > 0 && (
              <Row label="VAT" value={quote?.tax_total ?? "0"} />
            )}
            {Number(quote?.rounding_adjustment ?? 0) !== 0 && (
              <Row
                label="Rounding"
                value={quote?.rounding_adjustment ?? "0"}
                tone="text-muted-foreground"
              />
            )}
            <div className="flex items-baseline justify-between border-t pt-3">
              <span className="font-medium">Total</span>
              <span className="text-2xl font-semibold tabular-nums">
                {quoting ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  rupees(quote?.total ?? "0")
                )}
              </span>
            </div>

            <div className="space-y-2 border-t pt-3">
              <Label htmlFor="cust-name" className="text-xs">
                Customer (optional)
              </Label>
              <Input
                id="cust-name"
                className="h-8"
                placeholder="Name for the receipt"
                value={customerName}
                onChange={(event) => setCustomerName(event.target.value)}
              />
              <Input
                className="h-8"
                placeholder="Phone"
                value={customerPhone}
                onChange={(event) => setCustomerPhone(event.target.value)}
              />
            </div>

            <Button
              className="h-11 w-full text-base"
              disabled={!quote?.can_sell}
              onClick={() => setPaying(true)}
            >
              <Banknote className="h-4 w-4" />
              Take payment
              <kbd className="ml-auto rounded bg-primary-foreground/15 px-1.5 py-0.5 text-xs">
                F2
              </kbd>
            </Button>
          </CardContent>
        </Card>
      </div>

      {paying && quote && (
        <PaymentDialog
          session={session}
          basket={basket}
          quote={quote}
          customerName={customerName}
          customerPhone={customerPhone}
          onCancel={() => {
            setPaying(false);
            focusSearch();
          }}
          onSold={(sale) => {
            setPaying(false);
            setReceipt(sale);
          }}
          onProblem={setProblem}
        />
      )}
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tabular-nums", tone)}>{rupees(value)}</span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Tender                                                                      */
/* -------------------------------------------------------------------------- */

function PaymentDialog({
  session,
  basket,
  quote,
  customerName,
  customerPhone,
  onCancel,
  onSold,
  onProblem,
}: {
  session: CounterSession;
  basket: BasketItem[];
  quote: SaleQuote;
  customerName: string;
  customerPhone: string;
  onCancel: () => void;
  onSold: (sale: Sale) => void;
  onProblem: (message: string) => void;
}) {
  const total = Number(quote.total);
  const [tenders, setTenders] = useState<Tender[]>([
    { method: "cash", amount: quote.total },
  ]);
  const [busy, setBusy] = useState(false);

  const tendered = useMemo(
    () => tenders.reduce((sum, row) => sum + (Number(row.amount) || 0), 0),
    [tenders],
  );
  // Change is only ever given on cash. A wallet overpayment is not change,
  // it is a failed transfer, so the counter must not offer to hand notes back
  // for one.
  const cashTendered = tenders
    .filter((row) => row.method === "cash")
    .reduce((sum, row) => sum + (Number(row.amount) || 0), 0);
  const change = Math.max(tendered - total, 0);
  const shortfall = Math.max(total - tendered, 0);
  const canSettle =
    shortfall === 0 && (change === 0 || cashTendered >= change);

  const settle = async () => {
    setBusy(true);
    try {
      // The last cash tender absorbs any change: what goes to the invoice is
      // what was actually kept, not what was handed over. Anything else would
      // record an overpayment the invoice cannot accept.
      const payload = tenders
        .map((row, index) => {
          const amount =
            index === tenders.length - 1
              ? (Number(row.amount) || 0) - change
              : Number(row.amount) || 0;
          return { method: row.method, amount: amount.toFixed(2) };
        })
        .filter((row) => Number(row.amount) > 0);

      const sale = await api.post<Sale>("/pos/sales/", {
        session: session.uuid,
        sale_type: "walk_in",
        customer_name: customerName,
        customer_phone: customerPhone,
        items: basket.map((item) => ({
          product: item.product.uuid,
          quantity: String(item.quantity),
          discount_percent: String(item.discountPercent),
        })),
        payments: payload,
      });
      onSold(sale);
    } catch (err) {
      onProblem(
        err instanceof ApiError ? err.message : "The sale was not completed.",
      );
      onCancel();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onKeyDown={(event) => event.key === "Escape" && onCancel()}
      role="dialog"
      aria-modal="true"
    >
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Take payment</CardTitle>
          <CardDescription>
            {rupees(quote.total)} due · {basket.length} item
            {basket.length === 1 ? "" : "s"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {tenders.map((tender, index) => (
            <div key={index} className="flex items-center gap-2">
              <Select
                className="h-9 w-32"
                value={tender.method}
                onChange={(event) =>
                  setTenders((current) =>
                    current.map((row, i) =>
                      i === index ? { ...row, method: event.target.value } : row,
                    ),
                  )
                }
              >
                {METHODS.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.label}
                  </option>
                ))}
              </Select>
              <Input
                className="h-9 text-right tabular-nums"
                inputMode="decimal"
                value={tender.amount}
                autoFocus={index === 0}
                onChange={(event) =>
                  setTenders((current) =>
                    current.map((row, i) =>
                      i === index ? { ...row, amount: event.target.value } : row,
                    ),
                  )
                }
              />
              {tenders.length > 1 && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9"
                  onClick={() =>
                    setTenders((current) =>
                      current.filter((_, i) => i !== index),
                    )
                  }
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}

          <div className="flex flex-wrap gap-1.5">
            {NOTES.filter((note) => note >= total / 4).map((note) => (
              <Button
                key={note}
                variant="outline"
                size="sm"
                onClick={() =>
                  setTenders((current) => {
                    const next = [...current];
                    const last = next.length - 1;
                    next[last] = {
                      ...next[last],
                      amount: (
                        (Number(next[last].amount) || 0) + note
                      ).toFixed(2),
                    };
                    return next;
                  })
                }
              >
                +{note}
              </Button>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setTenders((current) => [
                  ...current,
                  { method: "esewa", amount: shortfall.toFixed(2) },
                ])
              }
            >
              <Plus className="h-3 w-3" />
              Split
            </Button>
          </div>

          <div className="space-y-1 rounded-md border p-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Tendered</span>
              <span className="tabular-nums">{rupees(tendered)}</span>
            </div>
            {shortfall > 0 ? (
              <div className="flex justify-between font-medium text-destructive">
                <span>Still due</span>
                <span className="tabular-nums">{rupees(shortfall)}</span>
              </div>
            ) : (
              <div className="flex justify-between text-lg font-semibold text-emerald-600">
                <span>Change</span>
                <span className="tabular-nums">{rupees(change)}</span>
              </div>
            )}
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={!canSettle || busy}
              onClick={() => void settle()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Complete
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Receipt                                                                     */
/* -------------------------------------------------------------------------- */

function ReceiptPanel({ sale, onNext }: { sale: Sale; onNext: () => void }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Enter") onNext();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onNext]);

  return (
    <div className="mx-auto max-w-md space-y-4 py-4">
      <Alert>
        <Check className="h-4 w-4" />
        <AlertTitle>Sale complete</AlertTitle>
        <AlertDescription>
          Invoice {sale.invoice_number} · {rupees(sale.total)}
        </AlertDescription>
      </Alert>

      <Card className="font-mono text-xs">
        <CardContent className="space-y-2 pt-6">
          <div className="text-center">
            <p className="text-sm font-semibold">{sale.invoice_number}</p>
            <p className="text-muted-foreground">
              {new Date(sale.sold_at).toLocaleString()}
            </p>
            <p className="text-muted-foreground">
              {sale.sold_by_name} · {sale.session_reference}
            </p>
          </div>
          <div className="border-t border-dashed pt-2">
            {sale.lines.map((line) => (
              <div key={line.uuid} className="flex justify-between gap-2 py-0.5">
                <span className="min-w-0 flex-1 truncate">
                  {line.product_name}
                  <span className="block text-[10px] text-muted-foreground">
                    {line.quantity} × {line.unit_price} · {line.batch_number}
                  </span>
                </span>
                <span className="tabular-nums">{line.total}</span>
              </div>
            ))}
          </div>
          <div className="space-y-0.5 border-t border-dashed pt-2">
            <div className="flex justify-between">
              <span>Subtotal</span>
              <span className="tabular-nums">{sale.subtotal}</span>
            </div>
            {Number(sale.discount_total) > 0 && (
              <div className="flex justify-between">
                <span>Discount</span>
                <span className="tabular-nums">−{sale.discount_total}</span>
              </div>
            )}
            {Number(sale.tax_total) > 0 && (
              <div className="flex justify-between">
                <span>VAT</span>
                <span className="tabular-nums">{sale.tax_total}</span>
              </div>
            )}
            {Number(sale.rounding_adjustment) !== 0 && (
              <div className="flex justify-between">
                <span>Rounding</span>
                <span className="tabular-nums">{sale.rounding_adjustment}</span>
              </div>
            )}
            <div className="flex justify-between border-t pt-1 text-sm font-semibold">
              <span>Total</span>
              <span className="tabular-nums">{sale.total}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="flex gap-2">
        <Button
          variant="outline"
          className="flex-1"
          onClick={() => window.print()}
        >
          <Printer className="h-4 w-4" />
          Print
        </Button>
        <Button className="flex-1" onClick={onNext}>
          Next customer
          <kbd className="ml-1 rounded bg-primary-foreground/15 px-1.5 py-0.5 text-xs">
            ⏎
          </kbd>
        </Button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Today's sales and returns                                                   */
/* -------------------------------------------------------------------------- */

function SalesView({ session }: { session: CounterSession }) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [summary, setSummary] = useState<SalesSummary | null>(null);
  const [returning, setReturning] = useState<Sale | null>(null);

  const load = useCallback(async () => {
    const list = await api.get<Paginated<Sale>>(
      `/pos/sales/?session=${session.uuid}`,
    );
    setSales(list.results);

    // The day's margin needs `report.read`, which a counter assistant does
    // not hold — they sell, they do not see the branch's profitability. A
    // 403 here is the permission model working, not a failure, so the panel
    // is simply absent rather than the screen breaking.
    try {
      setSummary(
        await api.get<SalesSummary>(`/pos/summary/?facility=${session.facility}`),
      );
    } catch {
      setSummary(null);
    }
  }, [session.uuid, session.facility]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      {summary ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Sales today" value={String(summary.sales_count)} />
          <Stat label="Net revenue" value={rupees(summary.net_revenue)}
                hint={`gross ${rupees(summary.gross_revenue)}`} />
          <Stat
            label="Returns"
            value={rupees(summary.returns_total)}
            hint={`${summary.returns_count} of them`}
          />
          <Stat
            label="Margin"
            value={rupees(summary.gross_margin)}
            hint={`${summary.margin_percent}% — net of returns`}
          />
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Stat label="Sales this session" value={String(sales.length)} />
          <Stat
            label="Rung up"
            value={rupees(
              sales
                .filter((sale) => sale.status !== "voided")
                .reduce((sum, sale) => sum + Number(sale.total), 0),
            )}
          />
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">This session</CardTitle>
          <CardDescription>
            {sales.length} sale{sales.length === 1 ? "" : "s"} rung up at{" "}
            {session.counter}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Sale</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Invoice</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sales.map((sale) => (
                <TableRow key={sale.uuid}>
                  <TableCell className="font-medium">
                    {sale.reference}
                    <span className="block text-xs text-muted-foreground">
                      {new Date(sale.sold_at).toLocaleTimeString()}
                    </span>
                  </TableCell>
                  <TableCell>{sale.customer_label}</TableCell>
                  <TableCell className="text-xs">{sale.invoice_number}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rupees(sale.total)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        sale.status === "completed"
                          ? "secondary"
                          : sale.status === "voided"
                            ? "destructive"
                            : "outline"
                      }
                    >
                      {sale.status.replace("_", " ")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {["completed", "partially_returned"].includes(
                      sale.status,
                    ) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setReturning(sale)}
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        Return
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {sales.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                    Nothing sold on this session yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {returning && (
        <ReturnDialog
          sale={returning}
          onClose={() => setReturning(null)}
          onDone={() => {
            setReturning(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

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
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Returns                                                                     */
/* -------------------------------------------------------------------------- */

function ReturnDialog({
  sale,
  onClose,
  onDone,
}: {
  sale: Sale;
  onClose: () => void;
  onDone: () => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [reason, setReason] = useState("");
  const [restock, setRestock] = useState(true);
  const [restockNote, setRestockNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [raised, setRaised] = useState<string | null>(null);

  const refund = sale.lines.reduce((sum, line) => {
    const quantity = quantities[line.uuid] ?? 0;
    if (!quantity) return sum;
    return sum + (Number(line.total) * quantity) / Number(line.quantity);
  }, 0);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const created = await api.post<{ reference: string }>(
        `/pos/sales/${sale.reference}/return/`,
        {
          entries: Object.entries(quantities)
            .filter(([, quantity]) => quantity > 0)
            .map(([uuid, quantity]) => ({
              sale_line: uuid,
              quantity: String(quantity),
            })),
          reason,
          restock,
          restock_note: restockNote,
        },
      );
      setRaised(created.reference);
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "The return was not raised.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Return against {sale.reference}</CardTitle>
          <CardDescription>
            A manager approves the refund. Whoever sold it cannot approve its
            return.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {raised ? (
            <>
              <Alert>
                <Check className="h-4 w-4" />
                <AlertTitle>Sent for approval</AlertTitle>
                <AlertDescription>
                  {raised} is waiting for a manager. The refund is paid when
                  they approve it.
                </AlertDescription>
              </Alert>
              <Button className="w-full" onClick={onDone}>
                Done
              </Button>
            </>
          ) : (
            <>
              {problem && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>{problem}</AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                {sale.lines.map((line) => {
                  const max = Number(line.returnable_quantity);
                  return (
                    <div
                      key={line.uuid}
                      className={cn(
                        "flex items-center gap-3 rounded-md border p-2",
                        max <= 0 && "opacity-50",
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {line.product_name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {line.quantity} sold · {max} returnable ·{" "}
                          {line.batch_number}
                        </p>
                      </div>
                      <Input
                        className="h-8 w-20 text-center tabular-nums"
                        inputMode="numeric"
                        disabled={max <= 0}
                        value={quantities[line.uuid] ?? ""}
                        placeholder="0"
                        onChange={(event) => {
                          const wanted = Math.min(
                            Number(event.target.value) || 0,
                            max,
                          );
                          setQuantities((current) => ({
                            ...current,
                            [line.uuid]: wanted,
                          }));
                        }}
                      />
                    </div>
                  );
                })}
              </div>

              <div className="space-y-2">
                <Label htmlFor="return-reason">Why is it coming back?</Label>
                <Textarea
                  id="return-reason"
                  rows={2}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Customer bought more than the prescription called for."
                />
              </div>

              <div className="space-y-2 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <input
                    id="return-restock"
                    type="checkbox"
                    className="h-4 w-4"
                    checked={restock}
                    onChange={(event) => setRestock(event.target.checked)}
                  />
                  <Label htmlFor="return-restock" className="cursor-pointer">
                    Put back on the shelf
                  </Label>
                </div>
                <p className="text-xs text-muted-foreground">
                  Uncheck for anything opened, unsealed or out of the customer's
                  hands too long. The refund is paid either way — the stock is a
                  separate decision, and the manager makes it.
                </p>
                {!restock && (
                  <Input
                    className="h-8"
                    placeholder="Condition, e.g. blister opened"
                    value={restockNote}
                    onChange={(event) => setRestockNote(event.target.value)}
                  />
                )}
              </div>

              <div className="flex items-baseline justify-between rounded-md bg-muted/50 p-3">
                <span className="text-sm text-muted-foreground">
                  Refund (proportion of what was charged)
                </span>
                <span className="text-lg font-semibold tabular-nums">
                  {rupees(refund)}
                </span>
              </div>

              <div className="flex gap-2">
                <Button variant="outline" className="flex-1" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  className="flex-1"
                  disabled={busy || refund <= 0 || reason.trim().length < 5}
                  onClick={() => void submit()}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RotateCcw className="h-4 w-4" />
                  )}
                  Send for approval
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Cashing up                                                                  */
/* -------------------------------------------------------------------------- */

function CloseTill({
  session,
  onClosed,
}: {
  session: CounterSession;
  onClosed: () => void;
}) {
  const [takings, setTakings] = useState<SessionTakings | null>(null);
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [closed, setClosed] = useState<CounterSession | null>(null);

  useEffect(() => {
    // Blind: the expected cash is deliberately not requested. Showing the
    // cashier the figure they are counting towards is how a count stops
    // being a count.
    void api
      .get<SessionTakings>(`/pos/sessions/${session.reference}/takings/`)
      .then(setTakings);
  }, [session.reference]);

  const close = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const result = await api.post<CounterSession>(
        `/pos/sessions/${session.reference}/close/`,
        { closing_count: counted, variance_reason: reason },
      );
      setClosed(result);
      onClosed();
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "The till was not closed.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (closed) {
    const variance = Number(closed.variance ?? 0);
    return (
      <Card className="mx-auto max-w-md">
        <CardHeader>
          <CardTitle>Till closed</CardTitle>
          <CardDescription>{closed.reference}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Row label="Expected" value={closed.expected_cash ?? "0"} />
          <Row label="Counted" value={closed.closing_count ?? "0"} />
          <div className="flex justify-between border-t pt-2 font-medium">
            <span>Variance</span>
            <span
              className={cn(
                "tabular-nums",
                variance === 0
                  ? "text-emerald-600"
                  : "text-destructive",
              )}
            >
              {variance > 0 ? "+" : ""}
              {rupees(closed.variance ?? "0")}
            </span>
          </div>
          {closed.variance_reason && (
            <p className="text-xs text-muted-foreground">
              {closed.variance_reason}
            </p>
          )}
          <Alert className="mt-4">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              A manager still has to sign this off. Until they do, the count is
              only attested by the person who made it.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle>Cash up</CardTitle>
        <CardDescription>
          Count the drawer and enter what is actually in it. The expected figure
          is shown after you have counted, not before.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        {takings && (
          <div className="space-y-1 rounded-md border p-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Sales rung up</span>
              <span className="tabular-nums">
                {takings.sales_count} · {rupees(takings.sales_total)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Card</span>
              <span className="tabular-nums">{rupees(takings.card)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Wallets</span>
              <span className="tabular-nums">{rupees(takings.wallet)}</span>
            </div>
            <p className="pt-1 text-xs text-muted-foreground">
              Card and wallet settle separately and are not part of the drawer.
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="counted">Cash counted</Label>
          <Input
            id="counted"
            className="h-11 text-lg tabular-nums"
            inputMode="decimal"
            placeholder="0.00"
            value={counted}
            onChange={(event) => setCounted(event.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="variance-reason">
            If it does not match, why? (optional until it doesn't)
          </Label>
          <Textarea
            id="variance-reason"
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Change given from own pocket for a 500 note."
          />
        </div>

        <Button
          className="w-full"
          disabled={busy || !counted}
          onClick={() => void close()}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Banknote className="h-4 w-4" />
          )}
          Close the till
        </Button>
      </CardContent>
    </Card>
  );
}
