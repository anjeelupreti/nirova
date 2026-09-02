/**
 * The diagnostics department: worklist, result entry, and critical alerts.
 *
 * Built for a laboratory bench, not a manager's dashboard. The worklist is
 * ordered the way work should actually be picked up — STAT first, then
 * urgent, then oldest — and every action a technician needs sits on the row
 * itself rather than behind a detail page.
 *
 * Critical alerts pin to the top and stay there until somebody records that
 * they made the call. That is not a styling choice: an unacknowledged
 * critical value is the single most dangerous state this screen can be in.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  PhoneCall,
  Siren,
  TestTube,
  XCircle,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  CriticalAlert,
  DiagnosticOrder,
  DiagnosticOrderDetail,
  Facility,
  Paginated,
  TurnaroundReport,
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

const REFRESH_MS = 20000;

const PRIORITY_VARIANT: Record<string, "default" | "warning" | "destructive"> = {
  routine: "default",
  urgent: "warning",
  stat: "destructive",
};

const STATUS_LABEL: Record<string, string> = {
  ordered: "Awaiting collection",
  collected: "Collected",
  received: "In the laboratory",
  in_progress: "In progress",
  resulted: "Awaiting verification",
  released: "Released",
  rejected: "Rejected",
};

/** Colour a result by how far outside normal it is. */
const FLAG_STYLE: Record<string, string> = {
  normal: "",
  low: "text-amber-700 dark:text-amber-400 font-medium",
  high: "text-amber-700 dark:text-amber-400 font-medium",
  abnormal: "text-amber-700 dark:text-amber-400 font-medium",
  critical_low: "text-destructive font-semibold",
  critical_high: "text-destructive font-semibold",
};

/* -------------------------------------------------------------------------- */
/* Critical alerts                                                             */
/* -------------------------------------------------------------------------- */

function CriticalAlerts({
  alerts,
  onChanged,
}: {
  alerts: CriticalAlert[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [person, setPerson] = useState<Record<string, string>>({});
  const [action, setAction] = useState<Record<string, string>>({});

  if (alerts.length === 0) return null;

  async function notify(alert: CriticalAlert) {
    setBusy(true);
    try {
      await api.post(`/diagnostics/critical-alerts/${alert.uuid}/notify/`, {
        person: person[alert.uuid] ?? "",
        via: "telephone",
      });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge(alert: CriticalAlert) {
    setBusy(true);
    try {
      await api.post(`/diagnostics/critical-alerts/${alert.uuid}/acknowledge/`, {
        action_taken: action[alert.uuid] ?? "",
      });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Alert variant="destructive">
      <Siren className="h-4 w-4" />
      <AlertTitle>
        {alerts.length} critical {alerts.length === 1 ? "value" : "values"} outstanding
      </AlertTitle>
      <AlertDescription className="space-y-4 pt-2">
        {alerts.map((alert) => (
          <div key={alert.uuid} className="space-y-2 rounded-md border border-destructive/30 bg-background/60 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span>
                <span className="font-semibold">{alert.analyte} {alert.value}</span>
                <span className="ml-2 text-xs opacity-80">
                  threshold {alert.threshold}
                </span>
              </span>
              <span className="text-xs">
                {alert.patient_name} · {alert.patient_mrn} ·{" "}
                <span className="font-medium">
                  {alert.minutes_outstanding} min outstanding
                </span>
              </span>
            </div>

            {!alert.notified_at ? (
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex-1 space-y-1" style={{ minWidth: "14rem" }}>
                  <Label className="text-xs">Who did you speak to?</Label>
                  <Input
                    value={person[alert.uuid] ?? ""}
                    placeholder="Dr Prakash Rana, on call"
                    onChange={(e) =>
                      setPerson({ ...person, [alert.uuid]: e.target.value })
                    }
                  />
                </div>
                <Button
                  size="sm"
                  disabled={busy || !(person[alert.uuid] ?? "").trim()}
                  onClick={() => void notify(alert)}
                >
                  <PhoneCall className="h-4 w-4" />
                  Record the call
                </Button>
              </div>
            ) : (
              <>
                <p className="text-xs">
                  Told <span className="font-medium">{alert.notified_person}</span> by{" "}
                  {alert.notified_via}
                </p>
                <div className="flex flex-wrap items-end gap-2">
                  <div className="flex-1 space-y-1" style={{ minWidth: "16rem" }}>
                    <Label className="text-xs">What was done?</Label>
                    <Textarea
                      rows={2}
                      value={action[alert.uuid] ?? ""}
                      placeholder="Patient reviewed; treatment given."
                      onChange={(e) =>
                        setAction({ ...action, [alert.uuid]: e.target.value })
                      }
                    />
                  </div>
                  <Button
                    size="sm"
                    disabled={busy || (action[alert.uuid] ?? "").trim().length < 5}
                    onClick={() => void acknowledge(alert)}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Close
                  </Button>
                </div>
              </>
            )}
          </div>
        ))}
      </AlertDescription>
    </Alert>
  );
}

/* -------------------------------------------------------------------------- */
/* Result entry                                                                */
/* -------------------------------------------------------------------------- */

function ResultEntry({
  order,
  onDone,
  onCancel,
}: {
  order: DiagnosticOrderDetail;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [narrative, setNarrative] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Panel analytes come from the catalogue; a single test has none, and a
  // radiology study reports one narrative instead.
  const [analytes, setAnalytes] = useState<
    { code: string; name: string; unit: string }[]
  >([]);

  useEffect(() => {
    api
      .get<Paginated<{
        code: string;
        name: string;
        unit: string;
        is_panel: boolean;
        component_codes: string[];
      }>>(`/diagnostics/tests/?search=${order.test_code}`)
      .then((page) => {
        const definition = page.results.find((t) => t.code === order.test_code);
        if (!definition) return;
        if (!definition.is_panel) {
          setAnalytes([
            {
              code: definition.code,
              name: definition.name,
              unit: definition.unit,
            },
          ]);
          return;
        }
        // Fetch the components so each analyte gets its own labelled box.
        void api
          .get<Paginated<{ code: string; name: string; unit: string }>>(
            "/diagnostics/tests/?page_size=200",
          )
          .then((all) =>
            setAnalytes(
              definition.component_codes
                .map((code) => all.results.find((t) => t.code === code))
                .filter(Boolean) as { code: string; name: string; unit: string }[],
            ),
          );
      })
      .catch(() => undefined);
  }, [order.test_code]);

  const isNarrative = order.modality !== "laboratory";

  async function submit() {
    setError(null);
    setBusy(true);
    try {
      const results = isNarrative
        ? [{ value: narrative }]
        : analytes
            .filter((a) => (values[a.code] ?? "").trim())
            .map((a) => ({ analyte_code: a.code, value: values[a.code] }));

      if (results.length === 0) {
        setError("Enter at least one value.");
        return;
      }
      await api.post(`/diagnostics/orders/${order.uuid}/results/`, { results });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save results.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <TestTube className="h-4 w-4 text-muted-foreground" />
          {order.test_name}
        </CardTitle>
        <CardDescription>
          {order.patient_name} · {order.patient_mrn} · {order.reference}
          {order.accession_number && ` · ${order.accession_number}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {order.clinical_indication && (
          <p className="rounded-md bg-muted/40 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Indication: </span>
            {order.clinical_indication}
          </p>
        )}

        {isNarrative ? (
          <div className="space-y-1">
            <Label htmlFor="narrative">Report</Label>
            <Textarea
              id="narrative"
              rows={8}
              value={narrative}
              placeholder="Findings, then a conclusion."
              onChange={(e) => setNarrative(e.target.value)}
            />
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {analytes.map((analyte) => (
              <div key={analyte.code} className="space-y-1">
                <Label className="text-xs">
                  {analyte.name}{" "}
                  <span className="text-muted-foreground">{analyte.unit}</span>
                </Label>
                <Input
                  inputMode="decimal"
                  value={values[analyte.code] ?? ""}
                  onChange={(e) =>
                    setValues({ ...values, [analyte.code]: e.target.value })
                  }
                />
              </div>
            ))}
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void submit()}>
            Save results
          </Button>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Results are checked against this patient's reference range as they
          are saved. A critical value raises an alert immediately, before
          verification.
        </p>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Order detail                                                                */
/* -------------------------------------------------------------------------- */

function OrderDetail({
  order,
  onChanged,
  onEnterResults,
}: {
  order: DiagnosticOrderDetail;
  onChanged: () => void;
  onEnterResults: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [busy, setBusy] = useState(false);

  async function act(path: string, body?: unknown) {
    setError(null);
    setBusy(true);
    try {
      await api.post(`/diagnostics/orders/${order.uuid}/${path}/`, body);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>{order.test_name}</CardTitle>
            <CardDescription className="mt-1">
              {order.patient_name} · {order.patient_mrn} · {order.reference}
            </CardDescription>
          </div>
          <div className="flex gap-1.5">
            <Badge variant={PRIORITY_VARIANT[order.priority] ?? "default"}>
              {order.priority}
            </Badge>
            <Badge variant={order.is_overdue ? "destructive" : "secondary"}>
              {STATUS_LABEL[order.status] ?? order.status}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {order.clinical_indication && (
          <p className="text-sm">
            <span className="text-muted-foreground">Indication: </span>
            {order.clinical_indication}
          </p>
        )}

        {order.results.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Analyte</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead>Reference</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {order.results.map((result) => (
                <TableRow key={result.uuid}>
                  <TableCell>
                    {result.analyte_name}
                    {result.was_amended && (
                      <Badge variant="warning" className="ml-2">
                        amended
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      FLAG_STYLE[result.flag],
                    )}
                  >
                    {result.display_value}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {result.unit}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {result.reference_text || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {showReject ? (
          <div className="space-y-2">
            <Label className="text-xs">Why is the specimen being rejected?</Label>
            <Textarea
              rows={2}
              value={rejectReason}
              placeholder="Haemolysed; clotted; insufficient volume; mislabelled."
              onChange={(e) => setRejectReason(e.target.value)}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="destructive"
                disabled={busy || rejectReason.trim().length < 3}
                onClick={() => void act("reject", { reason: rejectReason })}
              >
                Reject specimen
              </Button>
              <Button size="sm" variant="outline" onClick={() => setShowReject(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {order.status === "ordered" && order.modality === "laboratory" && (
              <Button size="sm" disabled={busy} onClick={() => void act("collect")}>
                Collect specimen
              </Button>
            )}
            {order.status === "collected" && (
              <>
                <Button size="sm" disabled={busy} onClick={() => void act("receive")}>
                  Receive in laboratory
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowReject(true)}
                >
                  <XCircle className="h-4 w-4" />
                  Reject
                </Button>
              </>
            )}
            {(order.status === "received" ||
              order.status === "in_progress" ||
              (order.status === "ordered" && order.modality !== "laboratory")) && (
              <Button size="sm" disabled={busy} onClick={onEnterResults}>
                Enter results
              </Button>
            )}
            {order.status === "resulted" && (
              <Button size="sm" disabled={busy} onClick={() => void act("verify")}>
                <CheckCircle2 className="h-4 w-4" />
                Verify and release
              </Button>
            )}
          </div>
        )}

        {order.status === "resulted" && (
          <p className="text-xs text-muted-foreground">
            Verification must be done by someone other than{" "}
            {order.results[0]?.entered_by_name || "whoever entered the results"}.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function DiagnosticsPage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facilityUuid, setFacilityUuid] = useState("");
  const [modality, setModality] = useState("");
  const [orders, setOrders] = useState<DiagnosticOrder[]>([]);
  const [alerts, setAlerts] = useState<CriticalAlert[]>([]);
  const [stats, setStats] = useState<TurnaroundReport | null>(null);
  const [selected, setSelected] = useState<DiagnosticOrderDetail | null>(null);
  const [entering, setEntering] = useState(false);

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        const usable = page.results.filter((f) => f.status === "active");
        setFacilities(usable);
        const clinic =
          usable.find((f) => f.facility_type === "clinic") ?? usable[0];
        if (clinic) setFacilityUuid(clinic.uuid);
      })
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    if (!facilityUuid) return;
    const query = modality ? `&modality=${modality}` : "";
    const [work, alertPage, report] = await Promise.all([
      api.get<{ orders: DiagnosticOrder[] }>(
        `/diagnostics/worklist/?facility=${facilityUuid}${query}`,
      ),
      api.get<Paginated<CriticalAlert>>("/diagnostics/critical-alerts/?open=true"),
      api.get<TurnaroundReport>(`/diagnostics/turnaround/?facility=${facilityUuid}`),
    ]);
    setOrders(work.orders);
    setAlerts(alertPage.results);
    setStats(report);
  }, [facilityUuid, modality]);

  useEffect(() => {
    void load();
    const handle = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(handle);
  }, [load]);

  async function openOrder(order: DiagnosticOrder) {
    const detail = await api.get<DiagnosticOrderDetail>(
      `/diagnostics/orders/${order.uuid}/`,
    );
    setSelected(detail);
    setEntering(false);
  }

  async function refreshSelected() {
    if (selected) {
      const detail = await api.get<DiagnosticOrderDetail>(
        `/diagnostics/orders/${selected.uuid}/`,
      );
      setSelected(detail);
    }
    setEntering(false);
    await load();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <FlaskConical className="h-5 w-5 text-muted-foreground" />
            Diagnostics
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Worklist in the order work should be picked up — STAT first, then
            urgent, then oldest.
          </p>
        </div>
        <div className="flex gap-2">
          <Select
            className="h-9 w-auto"
            value={modality}
            onChange={(e) => setModality(e.target.value)}
          >
            <option value="">All modalities</option>
            <option value="laboratory">Laboratory</option>
            <option value="xray">X-ray</option>
            <option value="ultrasound">Ultrasound</option>
            <option value="ct">CT</option>
          </Select>
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
        </div>
      </div>

      <CriticalAlerts alerts={alerts} onChanged={() => void load()} />

      {stats && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[
            { label: "Outstanding", value: stats.open },
            { label: "Overdue", value: stats.overdue, danger: stats.overdue > 0 },
            { label: "Released (7 days)", value: stats.released },
            {
              label: "Average TAT (min)",
              value: stats.average_total_minutes,
            },
            {
              label: "Breach rate",
              value: `${stats.breach_rate_percent}%`,
              danger: stats.breach_rate_percent > 10,
            },
          ].map((tile) => (
            <Card key={tile.label}>
              <CardContent className="py-4">
                <p
                  className={cn(
                    "text-2xl font-semibold leading-none",
                    tile.danger && "text-destructive",
                  )}
                >
                  {tile.value}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">{tile.label}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle>Worklist</CardTitle>
            <CardDescription>
              {orders.length} outstanding
              {stats?.overdue ? ` · ${stats.overdue} past their turnaround` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {orders.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing outstanding.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Reference</TableHead>
                    <TableHead>Patient</TableHead>
                    <TableHead>Test</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orders.map((order) => (
                    <TableRow
                      key={order.uuid}
                      className={cn(
                        "cursor-pointer",
                        order.priority === "stat" && "bg-destructive/5",
                        selected?.uuid === order.uuid && "bg-accent",
                      )}
                      onClick={() => void openOrder(order)}
                    >
                      <TableCell className="font-mono text-xs">
                        {order.reference}
                        {order.priority !== "routine" && (
                          <Badge
                            variant={PRIORITY_VARIANT[order.priority]}
                            className="ml-2"
                          >
                            {order.priority}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{order.patient_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {order.patient_mrn}
                        </div>
                      </TableCell>
                      <TableCell>{order.test_name}</TableCell>
                      <TableCell>
                        <span
                          className={
                            order.is_overdue ? "text-destructive" : undefined
                          }
                        >
                          {STATUS_LABEL[order.status] ?? order.status}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="lg:col-span-2">
          {!selected ? (
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">
                  Select an order to work on it.
                </p>
              </CardContent>
            </Card>
          ) : entering ? (
            <ResultEntry
              order={selected}
              onDone={() => void refreshSelected()}
              onCancel={() => setEntering(false)}
            />
          ) : (
            <OrderDetail
              order={selected}
              onChanged={() => void refreshSelected()}
              onEnterResults={() => setEntering(true)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
