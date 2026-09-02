/**
 * The pharmacy: dispensing, stock, and what is about to go out of date.
 *
 * Built for a dispensary counter. The FEFO allocation is shown *before* the
 * pharmacist commits, so they can see which batches are about to leave the
 * shelf and in what order — and so a FEFO override is a visible decision
 * rather than a rejected form submission.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  CalendarClock,
  CheckCircle2,
  Package,
  PackageSearch,
  Search,
  TrendingDown,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  ExpiringStockResponse,
  Facility,
  FefoAllocation,
  Paginated,
  Patient,
  PharmacyProduct,
  ReorderResponse,
  StockLevel,
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

type Tab = "dispense" | "stock" | "expiry" | "reorder";

const TABS: { id: Tab; label: string; icon: typeof Package }[] = [
  { id: "dispense", label: "Dispense", icon: Package },
  { id: "stock", label: "Stock", icon: Boxes },
  { id: "expiry", label: "Expiry", icon: CalendarClock },
  { id: "reorder", label: "Reorder", icon: TrendingDown },
];

/** Colour an expiry bucket by how much time is left to act. */
const BUCKET_TONE: Record<string, string> = {
  expired: "text-destructive font-semibold",
  "7_days": "text-destructive font-semibold",
  "15_days": "text-destructive",
  "30_days": "text-amber-700 dark:text-amber-400 font-medium",
  "60_days": "text-amber-700 dark:text-amber-400",
  "90_days": "text-amber-700 dark:text-amber-400",
};

const BUCKET_LABEL: Record<string, string> = {
  expired: "Already expired",
  "7_days": "Within 7 days",
  "15_days": "Within 15 days",
  "30_days": "Within 30 days",
  "60_days": "Within 60 days",
  "90_days": "Within 90 days",
  "120_days": "Within 120 days",
  "180_days": "Within 180 days",
  "365_days": "Within a year",
};

/* -------------------------------------------------------------------------- */
/* Dispensing                                                                  */
/* -------------------------------------------------------------------------- */

function DispensePanel({
  facilityUuid,
  locationUuid,
}: {
  facilityUuid: string;
  locationUuid: string;
}) {
  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);

  const [products, setProducts] = useState<PharmacyProduct[]>([]);
  const [productUuid, setProductUuid] = useState("");
  const [quantity, setQuantity] = useState("10");
  const [allocation, setAllocation] = useState<FefoAllocation | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [counselling, setCounselling] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<Paginated<PharmacyProduct>>("/pharmacy/products/?page_size=200")
      .then((page) => {
        const active = page.results.filter((p) => p.is_active);
        setProducts(active);
        if (active.length) setProductUuid(active[0].uuid);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (term.trim().length < 2) {
      setMatches([]);
      return;
    }
    const handle = setTimeout(() => {
      api
        .get<{ results: Patient[] }>(
          `/clinical/patients/search/?q=${encodeURIComponent(term.trim())}`,
        )
        .then((data) => setMatches(data.results))
        .catch(() => setMatches([]));
    }, 300);
    return () => clearTimeout(handle);
  }, [term]);

  // Preview the allocation as the pharmacist changes product or quantity, so
  // the batches about to leave the shelf are visible before they commit.
  useEffect(() => {
    if (!productUuid || !locationUuid || !quantity) {
      setAllocation(null);
      return;
    }
    const handle = setTimeout(() => {
      api
        .get<FefoAllocation>(
          `/pharmacy/dispenses/allocate/?product=${productUuid}` +
            `&location=${locationUuid}&quantity=${quantity}`,
        )
        .then(setAllocation)
        .catch(() => setAllocation(null));
    }, 350);
    return () => clearTimeout(handle);
  }, [productUuid, locationUuid, quantity]);

  const shortfall = Number(allocation?.shortfall ?? 0) > 0;

  async function submit() {
    if (!patient) return;
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await api.post<{ reference: string; total_value: string }>(
        "/pharmacy/dispenses/",
        {
          patient_uuid: patient.uuid,
          facility_uuid: facilityUuid,
          location_uuid: locationUuid,
          counselling_notes: counselling,
          items: [
            {
              product_uuid: productUuid,
              quantity: Number(quantity),
              override_reason: overrideReason,
            },
          ],
        },
      );
      setNotice(`${result.reference} dispensed`);
      setQuantity("10");
      setOverrideReason("");
      setCounselling("");
      setAllocation(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not dispense.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Patient</CardTitle>
          <CardDescription>Name, MRN or phone number.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {patient ? (
            <div className="flex items-center justify-between gap-3 rounded-md border p-3">
              <div>
                <p className="font-medium">{patient.full_name}</p>
                <p className="text-sm text-muted-foreground">
                  {patient.mrn} · {patient.category}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setPatient(null)}>
                Change
              </Button>
            </div>
          ) : (
            <>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  value={term}
                  placeholder="Search…"
                  onChange={(e) => setTerm(e.target.value)}
                />
              </div>
              {matches.length > 0 && (
                <div className="divide-y rounded-md border">
                  {matches.map((match) => (
                    <button
                      key={match.uuid}
                      type="button"
                      className="w-full px-3 py-2 text-left text-sm hover:bg-accent"
                      onClick={() => {
                        setPatient(match);
                        setMatches([]);
                        setTerm("");
                      }}
                    >
                      <span className="font-medium">{match.full_name}</span>
                      <span className="ml-2 font-mono text-xs text-muted-foreground">
                        {match.mrn}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1 sm:col-span-2">
              <Label className="text-xs">Medicine</Label>
              <Select
                value={productUuid}
                onChange={(e) => setProductUuid(e.target.value)}
              >
                {products.map((product) => (
                  <option key={product.uuid} value={product.uuid}>
                    {product.display_name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Quantity</Label>
              <Input
                inputMode="numeric"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Counselling given</Label>
            <Textarea
              rows={2}
              value={counselling}
              placeholder="Take with food. Finish the course."
              onChange={(e) => setCounselling(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <PackageSearch className="h-4 w-4 text-muted-foreground" />
            Which batches
          </CardTitle>
          <CardDescription>
            Earliest expiry first, spanning batches where needed.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!allocation ? (
            <p className="text-sm text-muted-foreground">
              Choose a medicine and quantity.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Batch</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {allocation.allocation.map((row) => (
                    <TableRow key={row.batch_uuid}>
                      <TableCell className="font-mono text-xs">
                        {row.batch_number}
                      </TableCell>
                      <TableCell className="text-sm">{row.expires_on}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {Number(row.quantity)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {shortfall && (
                <Alert variant="warning">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Not enough stock</AlertTitle>
                  <AlertDescription>
                    {Number(allocation.allocated)} available of{" "}
                    {allocation.requested}. Dispense what there is and order
                    the rest, or choose another presentation.
                  </AlertDescription>
                </Alert>
              )}

              {allocation.breaks_fefo && (
                <>
                  <Alert variant="destructive">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertTitle>This is not the earliest batch</AlertTitle>
                    <AlertDescription>
                      {allocation.earliest_batch} expires sooner and is in
                      stock. Give a reason to dispense a later batch — it is
                      kept on the record permanently.
                    </AlertDescription>
                  </Alert>
                  <div className="space-y-1">
                    <Label className="text-xs">Reason for the override</Label>
                    <Textarea
                      rows={2}
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                    />
                  </div>
                </>
              )}
            </>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {notice && (
            <Alert variant="info">
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>{notice}</AlertDescription>
            </Alert>
          )}

          <Button
            className="w-full"
            disabled={
              busy ||
              !patient ||
              !allocation ||
              shortfall ||
              (allocation.breaks_fefo && !overrideReason.trim())
            }
            onClick={() => void submit()}
          >
            {!patient
              ? "Select a patient first"
              : allocation?.breaks_fefo && !overrideReason.trim()
                ? "Give a reason to continue"
                : "Dispense"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Stock                                                                       */
/* -------------------------------------------------------------------------- */

function StockPanel({ locationUuid }: { locationUuid: string }) {
  const [levels, setLevels] = useState<StockLevel[]>([]);

  useEffect(() => {
    if (!locationUuid) return;
    api
      .get<{ levels: StockLevel[] }>(
        `/pharmacy/stock/levels/?location=${locationUuid}`,
      )
      .then((data) => setLevels(data.levels))
      .catch(() => setLevels([]));
  }, [locationUuid]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>Stock on hand</CardTitle>
        <CardDescription>
          By batch, earliest expiry first — the order it will be dispensed in.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {levels.length === 0 ? (
          <p className="text-sm text-muted-foreground">No stock here.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead>Batch</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead className="text-right">Days</TableHead>
                <TableHead className="text-right">Quantity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {levels.map((level) => (
                <TableRow key={level.uuid}>
                  <TableCell>{level.product_name}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {level.batch_number}
                  </TableCell>
                  <TableCell className="text-sm">{level.expires_on}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      level.days_to_expiry < 30 && "text-destructive font-medium",
                      level.days_to_expiry >= 30 &&
                        level.days_to_expiry < 90 &&
                        "text-amber-700 dark:text-amber-400",
                    )}
                  >
                    {level.days_to_expiry}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Number(level.quantity)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Expiry                                                                      */
/* -------------------------------------------------------------------------- */

function ExpiryPanel({ locationUuid }: { locationUuid: string }) {
  const [data, setData] = useState<ExpiringStockResponse | null>(null);

  useEffect(() => {
    if (!locationUuid) return;
    api
      .get<ExpiringStockResponse>(
        `/pharmacy/stock/expiring/?location=${locationUuid}&days=365`,
      )
      .then(setData)
      .catch(() => setData(null));
  }, [locationUuid]);

  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  // Most urgent bucket first, so what needs acting on today is at the top.
  const order = [
    "expired", "7_days", "15_days", "30_days", "60_days",
    "90_days", "120_days", "180_days", "365_days",
  ];
  const buckets = Object.entries(data.by_bucket).sort(
    (a, b) => order.indexOf(a[0]) - order.indexOf(b[0]),
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="py-4">
          <p className="text-2xl font-semibold leading-none">
            {data.count} batch{data.count === 1 ? "" : "es"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            expiring within a year, worth{" "}
            {Number(data.total_value_at_cost).toLocaleString()} at cost
          </p>
        </CardContent>
      </Card>

      {buckets.map(([bucket, group]) => (
        <Card key={bucket}>
          <CardHeader className="pb-3">
            <CardTitle className={BUCKET_TONE[bucket]}>
              {BUCKET_LABEL[bucket] ?? bucket}
            </CardTitle>
            <CardDescription>
              {group.count} batch{group.count === 1 ? "" : "es"}, worth{" "}
              {Number(group.value).toLocaleString()} at cost
              {bucket === "180_days" && " — still time to transfer"}
              {bucket === "30_days" && " — discount or return"}
              {(bucket === "7_days" || bucket === "expired") &&
                " — likely a write-off"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead>Batch</TableHead>
                  <TableHead className="text-right">Days</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {group.items.map((item) => (
                  <TableRow key={`${item.batch_number}-${item.product_code}`}>
                    <TableCell>{item.product_name}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {item.batch_number}
                    </TableCell>
                    <TableCell
                      className={cn("text-right tabular-nums", BUCKET_TONE[bucket])}
                    >
                      {item.days_to_expiry}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {Number(item.quantity)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {Number(item.value_at_cost).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Reorder                                                                     */
/* -------------------------------------------------------------------------- */

function ReorderPanel({ locationUuid }: { locationUuid: string }) {
  const [data, setData] = useState<ReorderResponse | null>(null);

  useEffect(() => {
    if (!locationUuid) return;
    api
      .get<ReorderResponse>(`/pharmacy/stock/reorder/?location=${locationUuid}`)
      .then(setData)
      .catch(() => setData(null));
  }, [locationUuid]);

  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>Reorder</CardTitle>
        <CardDescription>
          {data.count} product{data.count === 1 ? "" : "s"} at or below reorder
          level
          {data.urgent > 0 && (
            <span className="ml-1 font-medium text-destructive">
              · {data.urgent} will run out before a delivery could arrive
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.suggestions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing needs ordering.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead className="text-right">On hand</TableHead>
                <TableHead className="text-right">Per day</TableHead>
                <TableHead className="text-right">Cover</TableHead>
                <TableHead className="text-right">Suggest</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.suggestions.map((row) => (
                <TableRow
                  key={row.product_code}
                  className={
                    row.stockout_before_delivery ? "bg-destructive/5" : undefined
                  }
                >
                  <TableCell>
                    {row.product_name}
                    {row.stockout_before_delivery && (
                      <Badge variant="destructive" className="ml-2">
                        urgent
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Number(row.on_hand)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {Number(row.daily_consumption)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.days_of_cover === null
                      ? "—"
                      : `${row.days_of_cover}d`}
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-medium">
                    {Number(row.suggested_quantity)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function PharmacyPage() {
  const [tab, setTab] = useState<Tab>("dispense");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facilityUuid, setFacilityUuid] = useState("");
  const [locations, setLocations] = useState<StockLocation[]>([]);
  const [locationUuid, setLocationUuid] = useState("");

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        const usable = page.results.filter((f) => f.status === "active");
        setFacilities(usable);
        const first =
          usable.find((f) => f.facility_type === "pharmacy") ??
          usable.find((f) => f.facility_type === "clinic") ??
          usable[0];
        if (first) setFacilityUuid(first.uuid);
      })
      .catch(() => undefined);
  }, []);

  const loadLocations = useCallback(async () => {
    if (!facilityUuid) return;
    const page = await api.get<Paginated<StockLocation>>(
      `/pharmacy/locations/?facility=${facilityUuid}`,
    );
    setLocations(page.results);
    // Default to somewhere stock can actually be dispensed from — a store is
    // not a counter, and defaulting there would show an empty dispensing list.
    const dispensary =
      page.results.find((l) => l.is_dispensable) ?? page.results[0];
    if (dispensary) setLocationUuid(dispensary.uuid);
  }, [facilityUuid]);

  useEffect(() => {
    void loadLocations();
  }, [loadLocations]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Package className="h-5 w-5 text-muted-foreground" />
            Pharmacy
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Dispensing takes the earliest-expiring batch first.
          </p>
        </div>
        <div className="flex gap-2">
          <Select
            className="h-9 w-auto"
            value={facilityUuid}
            onChange={(e) => setFacilityUuid(e.target.value)}
          >
            {facilities.map((facility) => (
              <option key={facility.uuid} value={facility.uuid}>
                {facility.name}
              </option>
            ))}
          </Select>
          <Select
            className="h-9 w-auto"
            value={locationUuid}
            onChange={(e) => setLocationUuid(e.target.value)}
          >
            {locations.map((location) => (
              <option key={location.uuid} value={location.uuid}>
                {location.code} — {location.name}
              </option>
            ))}
          </Select>
        </div>
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

      {tab === "dispense" && (
        <DispensePanel facilityUuid={facilityUuid} locationUuid={locationUuid} />
      )}
      {tab === "stock" && <StockPanel locationUuid={locationUuid} />}
      {tab === "expiry" && <ExpiryPanel locationUuid={locationUuid} />}
      {tab === "reorder" && <ReorderPanel locationUuid={locationUuid} />}
    </div>
  );
}
