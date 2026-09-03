/**
 * Intensive care.
 *
 * Two screens with opposite jobs. The board is read from the doorway by a
 * charge nurse deciding where to stand — it must parse by colour and shape
 * before anybody reads a word. The chart is read at the bedside by somebody
 * who has to know what changed in the last hour and why.
 *
 * What the screen refuses to soften.
 *
 * **A partial SOFA is drawn differently from a complete one.** A score of 6
 * computed without a bilirubin is not a score of 6. It carries an asterisk and
 * names the systems it could not see, because the error only ever runs one
 * way: the patient looks less sick than they are.
 *
 * **A device reading is visibly not a validated reading** until somebody says
 * so, and the alerts it raised say where they came from. An arterial line
 * reads 300/150 while it is flushed; nobody should act on that, and nobody
 * should be able to delete it either.
 *
 * **Stale charting is a state, not an absence.** A patient whose last
 * observation was three hours ago is shown as such, in amber. An empty column
 * looks like a well patient.
 *
 * **"Not for resuscitation" is on the page before anything else.** It is the
 * single most important thing to know before responding to an alert, and the
 * thing least likely to be to hand at three in the morning.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  CheckCircle2,
  ClipboardList,
  Droplets,
  Gauge,
  HeartPulse,
  Loader2,
  MonitorCheck,
  ShieldAlert,
  Syringe,
  Wind,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Facility,
  FluidBalance,
  IcuAlert,
  IcuStay,
  IcuSummary,
  Paginated,
  RunningInfusion,
  SofaDay,
  TrendPoint,
  UnitBoardRow,
  Ward,
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

type Tab = "board" | "performance";

/** Parameters worth plotting, in the order a chart is read. */
const TREND_PARAMETERS: { key: string; label: string }[] = [
  { key: "heart_rate", label: "Heart rate" },
  { key: "systolic", label: "Systolic" },
  { key: "mean_arterial_pressure", label: "MAP" },
  { key: "spo2", label: "SpO₂" },
  { key: "respiratory_rate", label: "Resp rate" },
  { key: "temperature", label: "Temperature" },
  { key: "lactate", label: "Lactate" },
];

const FLUID_ROUTES_IN = [
  ["iv", "Intravenous"],
  ["oral", "Oral"],
  ["ng", "Nasogastric"],
  ["blood", "Blood product"],
  ["flush", "Line flush"],
] as const;

const FLUID_ROUTES_OUT = [
  ["urine", "Urine"],
  ["drain", "Drain"],
  ["ng_aspirate", "NG aspirate"],
  ["vomit", "Vomit"],
  ["stool", "Stool"],
  ["blood_loss", "Blood loss"],
  ["insensible", "Insensible"],
] as const;

const OUTCOMES = [
  ["to_ward", "Stepped down to a ward"],
  ["to_hdu", "Stepped down to HDU"],
  ["to_theatre", "To theatre"],
  ["transferred_out", "Transferred to another hospital"],
  ["died", "Died in the unit"],
  ["lama", "Left against medical advice"],
] as const;

const humanise = (value: string) => value.replace(/_/g, " ");

const clock = (value: string | null) =>
  value
    ? new Date(value).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

const dayAndClock = (value: string | null) =>
  value
    ? new Date(value).toLocaleString([], {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

/** Minutes since a timestamp, or null. Used to age the charting. */
function minutesSince(value: string | null): number | null {
  if (!value) return null;
  return Math.floor((Date.now() - new Date(value).getTime()) / 60000);
}

function staleness(value: string | null) {
  const minutes = minutesSince(value);
  if (minutes === null) return { text: "never charted", tone: "text-destructive" };
  if (minutes < 90) return { text: `${minutes}m ago`, tone: "text-muted-foreground" };
  const hours = Math.floor(minutes / 60);
  return {
    text: `${hours}h ago`,
    tone: hours >= 4 ? "text-destructive" : "text-amber-600",
  };
}

const balanceTone = (ml: number) =>
  ml > 2000 ? "text-destructive" : ml < -1500 ? "text-amber-600" : "";

export default function IcuPage() {
  const [tab, setTab] = useState<Tab>("board");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [wards, setWards] = useState<Ward[]>([]);
  const [ward, setWard] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        const preferred =
          page.results.find((row) => row.facility_type === "hospital") ??
          page.results[0];
        setFacilities(page.results);
        if (preferred) setFacility(preferred.uuid);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<Paginated<Ward>>(`/ipd/wards/?facility=${facility}`)
      .then((page) => {
        // Critical care only. A general ward on this screen would be a board
        // whose columns — ventilation, vasopressors, SOFA — are all empty.
        const critical = page.results.filter((row) => row.is_critical_care);
        setWards(critical);
        setWard(critical[0]?.uuid ?? "");
      })
      .catch(() => setWards([]));
  }, [facility]);

  if (denied) {
    return (
      <Alert>
        <HeartPulse className="h-4 w-4" />
        <AlertTitle>The unit is not visible to you</AlertTitle>
        <AlertDescription>
          Seeing the intensive care board needs clinical permissions.
        </AlertDescription>
      </Alert>
    );
  }

  if (open) {
    return <Chart stayUuid={open} onBack={() => setOpen(null)} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Intensive care
          </h1>
          <p className="text-sm text-muted-foreground">
            The board, the chart, and what the score could not see.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
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
          {wards.length > 1 && (
            <Select
              className="h-9 w-auto"
              aria-label="Unit"
              value={ward}
              onChange={(event) => setWard(event.target.value)}
            >
              {wards.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name}
                </option>
              ))}
            </Select>
          )}
        </div>
      </div>

      <div className="flex gap-1 border-b">
        {(
          [
            { id: "board", label: "Unit board", icon: HeartPulse },
            { id: "performance", label: "Performance", icon: Activity },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
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

      {tab === "board" && <Board ward={ward} onOpen={setOpen} />}
      {tab === "performance" && <Performance facility={facility} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The board                                                                   */
/* -------------------------------------------------------------------------- */

function Board({
  ward,
  onOpen,
}: {
  ward: string;
  onOpen: (uuid: string) => void;
}) {
  const [rows, setRows] = useState<UnitBoardRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!ward) {
      setRows([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setRows(await api.get<UnitBoardRow[]>(`/icu/board/?ward=${ward}`));
    } finally {
      setLoading(false);
    }
  }, [ward]);

  useEffect(() => {
    void load();
    // A board that only updates on reload is a board nobody trusts. Thirty
    // seconds is the rate a nurse walking past would notice a change at.
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (loading && rows.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-sm text-muted-foreground">
          Nobody in the unit.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((row) => {
          const last = staleness(row.last_observation_at);
          return (
            <button
              key={row.stay}
              type="button"
              onClick={() => onOpen(row.stay)}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors hover:bg-muted/40",
                row.critical_alerts > 0 &&
                  "border-destructive/60 bg-destructive/5",
                row.critical_alerts === 0 &&
                  row.unacknowledged_alerts > 0 &&
                  "border-amber-500/50",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-medium">
                    <span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                      {row.bed || "—"}
                    </span>
                    {row.patient}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {row.mrn} · day {row.icu_day} · {row.diagnosis}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    SOFA
                  </p>
                  <p className="text-lg font-semibold tabular-nums leading-none">
                    {row.sofa ?? "—"}
                    {row.sofa !== null && row.sofa_complete === false && (
                      <span
                        className="text-amber-600"
                        title="Partial score — some systems had no data"
                      >
                        *
                      </span>
                    )}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {row.critical_alerts > 0 && (
                  <Badge variant="destructive">
                    {row.critical_alerts} critical
                  </Badge>
                )}
                {row.unacknowledged_alerts > row.critical_alerts && (
                  <Badge variant="secondary">
                    {row.unacknowledged_alerts - row.critical_alerts} unseen
                  </Badge>
                )}
                {row.ventilated && (
                  <Badge variant="outline">
                    <Wind className="mr-1 h-3 w-3" />
                    {row.mode?.toUpperCase()}
                    {row.fio2 ? ` ${row.fio2}%` : ""}
                  </Badge>
                )}
                {row.vasopressors.map((drug) => (
                  <Badge key={drug} variant="outline">
                    <Syringe className="mr-1 h-3 w-3" />
                    {drug}
                  </Badge>
                ))}
                {!row.for_resuscitation && (
                  <Badge variant="secondary" title={row.ceiling_of_care}>
                    not for CPR
                  </Badge>
                )}
              </div>

              <div className="flex items-baseline justify-between gap-2 border-t pt-2 text-xs">
                <span className={last.tone}>charted {last.text}</span>
                <span
                  className={cn(
                    "tabular-nums",
                    balanceTone(row.balance_24h_ml),
                  )}
                >
                  {row.balance_24h_ml > 0 ? "+" : ""}
                  {row.balance_24h_ml.toLocaleString()} ml / 24h
                </span>
              </div>
            </button>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Ordered by unacknowledged critical alerts, then by SOFA — not by bed
        number. A board sorted by bed tells a charge nurse nothing they did not
        already know from walking past. An asterisk means the score was
        computed with systems missing.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One patient's chart                                                         */
/* -------------------------------------------------------------------------- */

function Chart({
  stayUuid,
  onBack,
}: {
  stayUuid: string;
  onBack: () => void;
}) {
  const [stay, setStay] = useState<IcuStay | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [dialog, setDialog] = useState<
    null | "observation" | "fluid" | "infusion" | "sofa" | "discharge"
  >(null);

  const load = useCallback(async () => {
    setStay(await api.get<IcuStay>(`/icu/stays/${stayUuid}/`));
  }, [stayUuid]);

  useEffect(() => {
    void load();
  }, [load]);

  const post = async (path: string, body: unknown) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/icu/stays/${stayUuid}/${path}`, body);
      await load();
      return true;
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "That did not go through.",
      );
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!stay) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const unacknowledged = stay.alerts.filter((row) => !row.is_acknowledged);
  const clinical = stay.blockers.filter((row) => row.kind === "clinical");
  const record = stay.blockers.filter((row) => row.kind === "record");

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back to the board
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {stay.patient_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {stay.patient_mrn} · {stay.bed_code || "no bed"} · ICU day{" "}
            {stay.icu_day} ({stay.hours}h) · {stay.ward_name}
            {stay.weight_kg && ` · ${stay.weight_kg}kg`}
          </p>
          <p className="text-sm">{stay.primary_diagnosis || stay.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setDialog("observation")}>
            <HeartPulse className="h-4 w-4" />
            Chart obs
          </Button>
          <Button size="sm" variant="outline" onClick={() => setDialog("fluid")}>
            <Droplets className="h-4 w-4" />
            Fluid
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setDialog("infusion")}
          >
            <Syringe className="h-4 w-4" />
            Infusion
          </Button>
          <Button size="sm" variant="outline" onClick={() => setDialog("sofa")}>
            <Gauge className="h-4 w-4" />
            Score
          </Button>
          {stay.outcome === "ongoing" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDialog("discharge")}
            >
              Step down
            </Button>
          )}
        </div>
      </div>

      {/* Before anything else. */}
      {!stay.is_for_resuscitation && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>Not for resuscitation</AlertTitle>
          <AlertDescription>
            {stay.ceiling_of_care}
            {stay.ceiling_set_by && (
              <span className="block text-xs">
                Set by {stay.ceiling_set_by}
                {stay.ceiling_set_at &&
                  ` on ${dayAndClock(stay.ceiling_set_at)}`}
              </span>
            )}
          </AlertDescription>
        </Alert>
      )}

      {stay.outcome !== "ongoing" && (
        <Alert>
          <Ban className="h-4 w-4" />
          <AlertTitle>
            Left the unit — {humanise(stay.outcome)} on{" "}
            {dayAndClock(stay.discharged_at)}
          </AlertTitle>
          <AlertDescription>{stay.outcome_notes}</AlertDescription>
        </Alert>
      )}

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <Alerts
            alerts={stay.alerts}
            unacknowledged={unacknowledged}
            busy={busy}
            onAcknowledge={(uuid, action) =>
              post(`alerts/${uuid}/acknowledge/`, { action })
            }
          />
          <Observations
            stay={stay}
            stayUuid={stayUuid}
            onValidate={(uuid) => post(`observations/${uuid}/validate/`, {})}
          />
          <Ventilation stay={stay} />
          <Fluids balance={stay.balance} stayUuid={stayUuid} />
        </div>

        <div className="space-y-4">
          <Infusions
            infusions={stay.infusions}
            busy={busy}
            onRate={(uuid, body) => post(`infusions/${uuid}/rate/`, body)}
          />
          <Severity sofa={stay.sofa} />
          <Devices stay={stay} />
          <Rounds stay={stay} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Ready to leave?</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {stay.blockers.length === 0 ? (
                <p className="flex items-center gap-2 text-emerald-600">
                  <CheckCircle2 className="h-4 w-4" />
                  Nothing holding this patient in the unit.
                </p>
              ) : (
                <>
                  {clinical.map((row) => (
                    <p key={row.detail} className="flex gap-2">
                      <Badge variant="destructive" className="shrink-0">
                        clinical
                      </Badge>
                      <span>{row.detail}</span>
                    </p>
                  ))}
                  {record.map((row) => (
                    <p key={row.detail} className="flex gap-2">
                      <Badge variant="secondary" className="shrink-0">
                        record
                      </Badge>
                      <span>{row.detail}</span>
                    </p>
                  ))}
                  <p className="pt-1 text-xs text-muted-foreground">
                    Labelled because they are different arguments. A
                    vasopressor makes the patient unfit for a ward; an
                    unacknowledged alert is unfinished reviewing.
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {dialog === "observation" && (
        <ObservationDialog
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await post("observations/", body)) setDialog(null);
          }}
        />
      )}
      {dialog === "fluid" && (
        <FluidDialog
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await post("fluids/", body)) setDialog(null);
          }}
        />
      )}
      {dialog === "infusion" && (
        <InfusionDialog
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await post("infusions/", body)) setDialog(null);
          }}
        />
      )}
      {dialog === "sofa" && (
        <SofaDialog
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await post("sofa/", body)) setDialog(null);
          }}
        />
      )}
      {dialog === "discharge" && (
        <DischargeDialog
          blockers={stay.blockers}
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await post("discharge/", body)) {
              setDialog(null);
              onBack();
            }
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Panels                                                                      */
/* -------------------------------------------------------------------------- */

function Alerts({
  alerts,
  unacknowledged,
  busy,
  onAcknowledge,
}: {
  alerts: IcuAlert[];
  unacknowledged: IcuAlert[];
  busy: boolean;
  onAcknowledge: (uuid: string, action: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? alerts : unacknowledged;

  return (
    <Card
      className={cn(
        unacknowledged.some((row) => row.severity === "critical") &&
          "border-destructive/50",
      )}
    >
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-4 w-4" />
            Alerts
          </CardTitle>
          <CardDescription>
            {unacknowledged.length} unacknowledged of {alerts.length}. Nothing
            here clears itself when the number comes back — a night of
            self-clearing desaturations is what a morning review needs to see.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowAll((value) => !value)}
        >
          {showAll ? "Unseen only" : "Show all"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {shown.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            {showAll ? "No alerts on this stay." : "Everything has been seen."}
          </p>
        )}
        {shown.slice(0, 20).map((row) => (
          <div
            key={row.uuid}
            className={cn(
              "flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm",
              row.severity === "critical" &&
                !row.is_acknowledged &&
                "border-destructive/50 bg-destructive/5",
              row.is_acknowledged && "opacity-70",
            )}
          >
            <Badge
              variant={row.severity === "critical" ? "destructive" : "secondary"}
            >
              {row.severity}
            </Badge>
            <span className="min-w-0 flex-1">
              {row.message}
              {row.from_unvalidated_device && (
                <span className="ml-1 text-xs text-amber-600">
                  · from an unvalidated monitor reading
                </span>
              )}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {clock(row.raised_at)}
            </span>
            {row.is_acknowledged ? (
              <span className="shrink-0 text-xs text-muted-foreground">
                seen by {row.acknowledged_by_name} in{" "}
                {row.minutes_to_acknowledge}m
              </span>
            ) : (
              <AcknowledgeButton
                busy={busy}
                onAcknowledge={(action) => onAcknowledge(row.uuid, action)}
              />
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function AcknowledgeButton({
  busy,
  onAcknowledge,
}: {
  busy: boolean;
  onAcknowledge: (action: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState("");

  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Acknowledge
      </Button>
    );
  }
  return (
    <span className="flex w-full gap-2 sm:w-auto">
      <Input
        autoFocus
        className="h-8"
        placeholder="What you did (optional)"
        value={action}
        onChange={(event) => setAction(event.target.value)}
      />
      <Button size="sm" disabled={busy} onClick={() => onAcknowledge(action)}>
        Seen
      </Button>
    </span>
  );
}

function Observations({
  stay,
  stayUuid,
  onValidate,
}: {
  stay: IcuStay;
  stayUuid: string;
  onValidate: (uuid: string) => void;
}) {
  const [parameter, setParameter] = useState("mean_arterial_pressure");
  const [points, setPoints] = useState<TrendPoint[]>([]);

  useEffect(() => {
    void api
      .get<{ points: TrendPoint[] }>(
        `/icu/stays/${stayUuid}/trend/?parameter=${parameter}&hours=48`,
      )
      .then((data) => setPoints(data.points))
      .catch(() => setPoints([]));
  }, [stayUuid, parameter]);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="text-base">Observations</CardTitle>
          <CardDescription>
            Appended, never edited. The trend is the clinical content: a
            pressure that has been 70 all night and one that fell to 70 in the
            last hour are the same number and different emergencies.
          </CardDescription>
        </div>
        <Select
          className="h-8 w-auto"
          aria-label="Trend parameter"
          value={parameter}
          onChange={(event) => setParameter(event.target.value)}
        >
          {TREND_PARAMETERS.map((row) => (
            <option key={row.key} value={row.key}>
              {row.label}
            </option>
          ))}
        </Select>
      </CardHeader>
      <CardContent className="space-y-3">
        <Sparkline points={points} />

        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead className="text-right">HR</TableHead>
                <TableHead className="text-right">BP</TableHead>
                <TableHead className="text-right">MAP</TableHead>
                <TableHead className="text-right">RR</TableHead>
                <TableHead className="text-right">SpO₂</TableHead>
                <TableHead className="text-right">Temp</TableHead>
                <TableHead className="text-right">GCS</TableHead>
                <TableHead className="text-right">Lactate</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stay.observations.map((row) => (
                <TableRow
                  key={row.uuid}
                  className={cn(!row.is_validated && "bg-amber-50/60 dark:bg-amber-950/10")}
                >
                  <TableCell className="whitespace-nowrap tabular-nums">
                    {clock(row.recorded_at)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.heart_rate ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.systolic && row.diastolic
                      ? `${row.systolic}/${row.diastolic}`
                      : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.map_value ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.respiratory_rate ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.spo2 ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.temperature ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.gcs_total ?? "—"}
                    {row.gcs_verbal_not_testable && (
                      <span
                        className="text-muted-foreground"
                        title="Intubated — verbal score not testable"
                      >
                        t
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.lactate ?? "—"}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right">
                    {row.source === "device" && !row.is_validated ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onValidate(row.uuid)}
                      >
                        <MonitorCheck className="h-3 w-3" />
                        Validate
                      </Button>
                    ) : row.source === "device" ? (
                      <span className="text-xs text-muted-foreground">
                        validated
                      </span>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
              {stay.observations.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={10}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    Nothing charted yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        <p className="text-xs text-muted-foreground">
          An amber row came from a monitor and nobody has confirmed it. It is
          kept rather than filtered, because a run of impossible values is how
          a failing transducer gets noticed.
        </p>
      </CardContent>
    </Card>
  );
}

/** A trend, drawn small. Enough to see a shape; not a substitute for the chart. */
function Sparkline({ points }: { points: TrendPoint[] }) {
  const numbers = useMemo(
    () => points.map((row) => Number(row.value)).filter((n) => !Number.isNaN(n)),
    [points],
  );

  if (numbers.length < 2) {
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        Not enough charted to draw a trend.
      </p>
    );
  }

  const low = Math.min(...numbers);
  const high = Math.max(...numbers);
  const span = high - low || 1;
  const width = 600;
  const height = 72;
  const step = width / (numbers.length - 1);

  const path = numbers
    .map((value, index) => {
      const x = index * step;
      const y = height - ((value - low) / span) * (height - 8) - 4;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="rounded-md border p-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-20 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="Trend over the last 48 hours"
      >
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-primary"
          vectorEffect="non-scaling-stroke"
        />
        {points.map((row, index) =>
          row.validated ? null : (
            <circle
              key={index}
              cx={index * step}
              cy={
                height -
                ((Number(row.value) - low) / span) * (height - 8) -
                4
              }
              r="4"
              className="fill-amber-500"
              vectorEffect="non-scaling-stroke"
            />
          ),
        )}
      </svg>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{dayAndClock(points[0]?.at ?? null)}</span>
        <span className="tabular-nums">
          {low} – {high}
        </span>
        <span>{dayAndClock(points[points.length - 1]?.at ?? null)}</span>
      </div>
    </div>
  );
}

function Ventilation({ stay }: { stay: IcuStay }) {
  const latest = stay.ventilation[0];
  if (!latest) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Wind className="h-4 w-4" />
          Ventilation
        </CardTitle>
        <CardDescription>
          {latest.mode.toUpperCase()} ·{" "}
          {latest.is_invasive ? "invasive" : "non-invasive"} ·{" "}
          {stay.ventilator.invasive_hours}h invasive over the stay
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-md border p-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Set
            </p>
            <Pair label="Rate" value={latest.set_rate} />
            <Pair label="Tidal volume" value={latest.set_tidal_volume} unit="ml" />
            <Pair label="PEEP" value={latest.peep} />
            <Pair label="Pressure support" value={latest.pressure_support} />
            <Pair label="FiO₂" value={latest.fio2} unit="%" />
          </div>
          <div className="rounded-md border p-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Measured
            </p>
            <Pair label="Rate" value={latest.measured_rate} />
            <Pair
              label="Expired tidal volume"
              value={latest.expired_tidal_volume}
              unit="ml"
              tone={
                latest.set_tidal_volume &&
                latest.expired_tidal_volume &&
                latest.set_tidal_volume - latest.expired_tidal_volume > 50
                  ? "text-destructive"
                  : undefined
              }
            />
            <Pair label="Peak pressure" value={latest.peak_pressure} />
            <Pair label="Plateau" value={latest.plateau_pressure} />
            <Pair label="EtCO₂" value={latest.etco2} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 border-t pt-3 sm:grid-cols-4">
          <Fact label="PF ratio" value={latest.pf_ratio ?? "—"} />
          <Fact
            label="Driving pressure"
            value={latest.driving_pressure ?? "—"}
            hint="plateau − PEEP"
          />
          <Fact label="pH" value={latest.ph ?? "—"} />
          <Fact
            label="PaCO₂"
            value={latest.paco2 ?? "—"}
          />
        </div>

        {latest.set_tidal_volume &&
          latest.expired_tidal_volume &&
          latest.set_tidal_volume - latest.expired_tidal_volume > 50 && (
            <p className="text-sm text-destructive">
              {latest.set_tidal_volume - latest.expired_tidal_volume}ml of the
              set tidal volume is not coming back — a leak, visible only
              because set and measured are separate fields.
            </p>
          )}
      </CardContent>
    </Card>
  );
}

function Fluids({
  balance,
  stayUuid,
}: {
  balance: FluidBalance;
  stayUuid: string;
}) {
  const [cumulative, setCumulative] = useState<
    { icu_day: number; balance_ml: number; cumulative_ml: number }[]
  >([]);

  useEffect(() => {
    void api
      .get<{ cumulative: { days: typeof cumulative } }>(
        `/icu/stays/${stayUuid}/fluids/`,
      )
      .then((data) => setCumulative(data.cumulative.days))
      .catch(() => setCumulative([]));
  }, [stayUuid]);

  const peak = Math.max(
    1,
    ...cumulative.map((row) => Math.abs(row.cumulative_ml)),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Droplets className="h-4 w-4" />
          Fluid balance
        </CardTitle>
        <CardDescription>
          Computed from the entries, never stored. A correction reverses an
          entry rather than editing it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Fact label="In (24h)" value={`${balance.intake_ml.toLocaleString()} ml`} />
          <Fact label="Out (24h)" value={`${balance.output_ml.toLocaleString()} ml`} />
          <Fact
            label="Balance"
            value={`${balance.balance_ml > 0 ? "+" : ""}${balance.balance_ml.toLocaleString()} ml`}
            tone={balanceTone(balance.balance_ml)}
          />
          <Fact
            label="Urine"
            value={
              balance.urine_ml_per_kg_per_hour
                ? `${balance.urine_ml_per_kg_per_hour} ml/kg/h`
                : `${balance.urine_ml} ml`
            }
            hint={
              balance.urine_ml_per_kg_per_hour
                ? `${balance.urine_ml} ml`
                : "no weight recorded"
            }
            tone={
              balance.urine_ml_per_kg_per_hour &&
              Number(balance.urine_ml_per_kg_per_hour) < 0.5
                ? "text-destructive"
                : undefined
            }
          />
        </div>

        {cumulative.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Cumulative
            </p>
            {cumulative.map((row) => (
              <div
                key={row.icu_day}
                className="flex items-center gap-2 text-xs"
              >
                <span className="w-12 shrink-0 text-muted-foreground">
                  day {row.icu_day}
                </span>
                <span className="flex h-3 flex-1 items-center">
                  <span
                    className={cn(
                      "h-3 rounded-sm",
                      row.cumulative_ml >= 0 ? "bg-sky-500/70" : "bg-amber-500/70",
                    )}
                    style={{
                      width: `${(Math.abs(row.cumulative_ml) / peak) * 100}%`,
                    }}
                  />
                </span>
                <span
                  className={cn(
                    "w-24 shrink-0 text-right tabular-nums",
                    balanceTone(row.cumulative_ml),
                  )}
                >
                  {row.cumulative_ml > 0 ? "+" : ""}
                  {row.cumulative_ml.toLocaleString()} ml
                </span>
              </div>
            ))}
            <p className="pt-1 text-xs text-muted-foreground">
              The cumulative figure is the one nobody has and the one that
              matters — a patient six litres up over four days is in trouble no
              single day's chart shows.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Infusions({
  infusions,
  busy,
  onRate,
}: {
  infusions: RunningInfusion[];
  busy: boolean;
  onRate: (uuid: string, body: Record<string, unknown>) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Syringe className="h-4 w-4" />
          Running
        </CardTitle>
        <CardDescription>
          Vasopressors first. The current rate is the last rate charted — there
          is one place the rate lives, and it is the history.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {infusions.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            Nothing running.
          </p>
        )}
        {infusions.map((row) => (
          <div
            key={row.uuid}
            className={cn(
              "rounded-md border p-2 text-sm",
              row.is_vasopressor && "border-destructive/40 bg-destructive/5",
            )}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium">{row.drug_name}</span>
              <span className="tabular-nums">
                {row.rate ?? "—"}{" "}
                <span className="text-xs text-muted-foreground">
                  {row.rate_unit}
                </span>
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {row.concentration && `${row.concentration} · `}
              {row.target && `target ${row.target} · `}
              {row.changes} change{row.changes === 1 ? "" : "s"}
              {row.last_changed_at && ` · last ${clock(row.last_changed_at)}`}
              {row.volume_ml && ` · ${row.volume_ml} ml given`}
            </p>
            {row.is_titratable && (
              <TitrateRow
                busy={busy}
                unit={row.rate_unit}
                maximum={row.maximum_rate}
                onSubmit={(rate, reason) =>
                  onRate(row.uuid, { rate, reason })
                }
                onStop={(reason) =>
                  onRate(row.uuid, { rate: "0", stop: true, reason })
                }
              />
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function TitrateRow({
  busy,
  unit,
  maximum,
  onSubmit,
  onStop,
}: {
  busy: boolean;
  unit: string;
  maximum: string | null;
  onSubmit: (rate: string, reason: string) => void;
  onStop: (reason: string) => void;
}) {
  const [rate, setRate] = useState("");
  const [reason, setReason] = useState("");

  return (
    <div className="mt-2 space-y-1 border-t pt-2">
      <div className="flex gap-1">
        <Input
          className="h-8"
          inputMode="decimal"
          placeholder={`New rate${maximum ? ` (max ${maximum})` : ""}`}
          value={rate}
          onChange={(event) => setRate(event.target.value)}
        />
        <Input
          className="h-8"
          placeholder="Why"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <div className="flex gap-1">
        <Button
          size="sm"
          className="flex-1"
          disabled={busy || !rate.trim()}
          onClick={() => {
            onSubmit(rate, reason);
            setRate("");
            setReason("");
          }}
        >
          Titrate {unit && <span className="text-xs">{unit}</span>}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onStop(reason || "Stopped")}
        >
          Stop
        </Button>
      </div>
    </div>
  );
}

function Severity({ sofa }: { sofa: SofaDay[] }) {
  const peak = Math.max(4, ...sofa.map((row) => row.total));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Gauge className="h-4 w-4" />
          SOFA
        </CardTitle>
        <CardDescription>
          A rising score over three days is the most useful trajectory in
          intensive care. A partial day is drawn differently because it is not
          the same kind of point.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-1">
        {sofa.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            Not scored yet.
          </p>
        )}
        {sofa.map((row) => (
          <div key={row.icu_day} className="text-sm">
            <div className="flex items-center gap-2">
              <span className="w-12 shrink-0 text-xs text-muted-foreground">
                day {row.icu_day}
              </span>
              <span className="flex h-4 flex-1 items-center">
                <span
                  className={cn(
                    "h-4 rounded-sm",
                    row.complete
                      ? "bg-primary"
                      : "border border-dashed border-amber-500 bg-amber-500/30",
                  )}
                  style={{ width: `${(row.total / peak) * 100}%` }}
                />
              </span>
              <span className="w-8 shrink-0 text-right font-medium tabular-nums">
                {row.total}
                {!row.complete && <span className="text-amber-600">*</span>}
              </span>
            </div>
            {!row.complete && (
              <p className="pl-14 text-xs text-amber-600">
                no data for {row.missing.map(humanise).join(", ")} — scored as
                zero, so the real score is higher
              </p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Devices({ stay }: { stay: IcuStay }) {
  const inSitu = stay.devices.filter((row) => !row.removed_at);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Lines and tubes</CardTitle>
        <CardDescription>
          Intervals, not flags — infection rates need line-days as a
          denominator.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-1 text-sm">
        {inSitu.length === 0 && (
          <p className="py-2 text-muted-foreground">Nothing in situ.</p>
        )}
        {inSitu.map((row) => {
          const overdue =
            (row.next_change_due &&
              new Date(row.next_change_due) <= new Date()) ||
            (row.inserted_in_emergency && Number(row.days_in_situ) > 1);
          return (
            <div
              key={row.uuid}
              className={cn(
                "flex items-baseline justify-between gap-2",
                overdue && "text-destructive",
              )}
            >
              <span className="min-w-0 truncate">
                {humanise(row.device_type)}
                {row.site && ` · ${row.site}`}
                {row.inserted_in_emergency && (
                  <span className="ml-1 text-xs">(emergency)</span>
                )}
              </span>
              <span className="shrink-0 tabular-nums">
                {row.days_in_situ}d
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function Rounds({ stay }: { stay: IcuStay }) {
  const latest = stay.rounds[0];
  if (!latest) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ClipboardList className="h-4 w-4" />
          Day {latest.icu_day} round
        </CardTitle>
        <CardDescription>
          {latest.consultant_name} · {dayAndClock(latest.round_at)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {latest.plan && <p>{latest.plan}</p>}

        <div className="flex flex-wrap gap-1">
          {Object.entries(latest.fasthug).map(([key, value]) => (
            <Badge
              key={key}
              variant={value ? "outline" : "destructive"}
              title={latest.fasthug_reasons[key] ?? ""}
            >
              {humanise(key)}
            </Badge>
          ))}
          {latest.missed_items.map((key) => (
            <Badge key={key} variant="secondary" className="opacity-60">
              {humanise(key)}: not asked
            </Badge>
          ))}
        </div>
        {latest.missed_items.length > 0 && (
          <p className="text-xs text-muted-foreground">
            An item nobody answered is shown as unasked, not as declined. They
            are different facts.
          </p>
        )}
      </CardContent>
    </Card>
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
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent className="space-y-4">{children}</CardContent>
      </Card>
    </div>
  );
}

function ObservationDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [notTestable, setNotTestable] = useState(false);

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = () => {
    const body: Record<string, unknown> = {
      gcs_verbal_not_testable: notTestable,
    };
    for (const [key, value] of Object.entries(form)) {
      if (value.trim() !== "") body[key] = value;
    }
    onSubmit(body);
  };

  const fields: [string, string, string?][] = [
    ["heart_rate", "Heart rate"],
    ["systolic", "Systolic"],
    ["diastolic", "Diastolic"],
    ["mean_arterial_pressure", "MAP (arterial)"],
    ["respiratory_rate", "Respiratory rate"],
    ["spo2", "SpO₂ %"],
    ["temperature", "Temperature °C"],
    ["blood_glucose", "Glucose mmol/L"],
    ["lactate", "Lactate mmol/L"],
    ["rass", "RASS (−5 to +4)"],
  ];

  return (
    <Shell
      title="Chart observations"
      description="Leave anything not measured blank. A blank is recorded as not measured, which is not the same as normal."
    >
      <div className="grid grid-cols-2 gap-3">
        {fields.map(([key, label]) => (
          <div key={key} className="space-y-1">
            <Label htmlFor={`o-${key}`} className="text-xs">
              {label}
            </Label>
            <Input
              id={`o-${key}`}
              inputMode="decimal"
              value={form[key] ?? ""}
              onChange={set(key)}
            />
          </div>
        ))}
      </div>

      <div className="space-y-2 rounded-md border p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Glasgow coma scale
        </p>
        <div className="grid grid-cols-3 gap-2">
          {[
            ["gcs_eye", "Eye (1–4)"],
            ["gcs_verbal", "Verbal (1–5)"],
            ["gcs_motor", "Motor (1–6)"],
          ].map(([key, label]) => (
            <div key={key} className="space-y-1">
              <Label htmlFor={`o-${key}`} className="text-xs">
                {label}
              </Label>
              <Input
                id={`o-${key}`}
                inputMode="numeric"
                disabled={key === "gcs_verbal" && notTestable}
                value={form[key] ?? ""}
                onChange={set(key)}
              />
            </div>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={notTestable}
            onChange={(event) => setNotTestable(event.target.checked)}
          />
          Intubated — verbal score not testable
        </label>
        <p className="text-xs text-muted-foreground">
          Recording 1 for an intubated patient without saying so makes a
          sedated patient look moribund, and the severity score then counts
          four points of brain failure caused by the propofol.
        </p>
      </div>

      <div className="space-y-1">
        <Label htmlFor="o-notes">Notes</Label>
        <Input id="o-notes" value={form.notes ?? ""} onChange={set("notes")} />
      </div>

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button className="flex-1" disabled={busy} onClick={submit}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Chart
        </Button>
      </div>
    </Shell>
  );
}

function FluidDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [route, setRoute] = useState("iv");
  const [volume, setVolume] = useState("");
  const [description, setDescription] = useState("");

  const routes = direction === "in" ? FLUID_ROUTES_IN : FLUID_ROUTES_OUT;

  return (
    <Shell
      title="Record a fluid"
      description="One volume, one time. To correct an earlier entry, reverse it — the chart then shows that somebody corrected it, which is itself worth seeing."
    >
      <div className="flex gap-2">
        {(["in", "out"] as const).map((value) => (
          <Button
            key={value}
            variant={direction === value ? "default" : "outline"}
            className="flex-1"
            onClick={() => {
              setDirection(value);
              setRoute(value === "in" ? "iv" : "urine");
            }}
          >
            {value === "in" ? "In" : "Out"}
          </Button>
        ))}
      </div>

      <div className="space-y-1">
        <Label htmlFor="f-route">Route</Label>
        <Select
          id="f-route"
          value={route}
          onChange={(event) => setRoute(event.target.value)}
        >
          {routes.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <p className="text-xs text-muted-foreground">
          The balance is read by route as well as in total: two litres positive
          from maintenance fluid and two litres positive because the patient
          has stopped passing urine are the same figure and opposite problems.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="f-volume">Volume (ml)</Label>
          <Input
            id="f-volume"
            inputMode="numeric"
            value={volume}
            onChange={(event) => setVolume(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="f-what">What</Label>
          <Input
            id="f-what"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Hartmann's"
          />
        </div>
      </div>

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy || !volume.trim() || Number(volume) <= 0}
          onClick={() =>
            onSubmit({
              direction,
              route,
              volume_ml: Number(volume),
              description,
            })
          }
        >
          Record
        </Button>
      </div>
    </Shell>
  );
}

function InfusionDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState({
    drug_name: "",
    rate: "",
    rate_unit: "ml/hr",
    concentration: "",
    target: "",
    maximum_rate: "",
  });
  const [titratable, setTitratable] = useState(false);

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <Shell
      title="Start an infusion"
      description="The starting rate is charted as a rate change like any other, so the first rate and every later one are the same kind of thing."
    >
      <div className="space-y-1">
        <Label htmlFor="i-drug">Drug</Label>
        <Input id="i-drug" value={form.drug_name} onChange={set("drug_name")} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label htmlFor="i-rate">Rate</Label>
          <Input
            id="i-rate"
            inputMode="decimal"
            value={form.rate}
            onChange={set("rate")}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="i-unit">Unit</Label>
          <Select id="i-unit" value={form.rate_unit} onChange={set("rate_unit")}>
            <option value="ml/hr">ml/hr</option>
            <option value="mcg/kg/min">mcg/kg/min</option>
            <option value="mg/hr">mg/hr</option>
            <option value="units/hr">units/hr</option>
          </Select>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        The unit is stored with the rate. Vasopressors are ordered in
        mcg/kg/min and sedatives in mg/hr, and a bare number with an assumed
        unit is how a hundred-fold overdose happens.
      </p>

      <div className="space-y-1">
        <Label htmlFor="i-conc">Concentration</Label>
        <Input
          id="i-conc"
          value={form.concentration}
          onChange={set("concentration")}
          placeholder="4mg in 50ml"
        />
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="h-4 w-4"
          checked={titratable}
          onChange={(event) => setTitratable(event.target.checked)}
        />
        Titratable at the bedside
      </label>

      {titratable && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="i-target">Titrate to</Label>
            <Input
              id="i-target"
              value={form.target}
              onChange={set("target")}
              placeholder="MAP > 65"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="i-max">Maximum rate</Label>
            <Input
              id="i-max"
              inputMode="decimal"
              value={form.maximum_rate}
              onChange={set("maximum_rate")}
            />
          </div>
          <p className="col-span-2 text-xs text-muted-foreground">
            A titratable infusion must say what it is titrated to — a nurse
            cannot titrate to nothing.
          </p>
        </div>
      )}

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={
            busy ||
            form.drug_name.trim().length < 2 ||
            !form.rate.trim() ||
            (titratable && !form.target.trim())
          }
          onClick={() =>
            onSubmit({
              ...form,
              is_titratable: titratable,
              maximum_rate: form.maximum_rate || null,
            })
          }
        >
          Start
        </Button>
      </div>
    </Shell>
  );
}

function SofaDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState({
    platelets: "",
    bilirubin: "",
    creatinine: "",
    urine_ml_24h: "",
  });

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const blank = Object.entries(form)
    .filter(([, value]) => !value.trim())
    .map(([key]) => key);

  return (
    <Shell
      title="Score SOFA"
      description="Respiratory, cardiovascular and neurological come from what is already charted. These three come from the lab."
    >
      <div className="grid grid-cols-2 gap-3">
        {[
          ["platelets", "Platelets (×10⁹/L)"],
          ["bilirubin", "Bilirubin (mg/dL)"],
          ["creatinine", "Creatinine (mg/dL)"],
          ["urine_ml_24h", "Urine over 24h (ml)"],
        ].map(([key, label]) => (
          <div key={key} className="space-y-1">
            <Label htmlFor={`s-${key}`} className="text-xs">
              {label}
            </Label>
            <Input
              id={`s-${key}`}
              inputMode="decimal"
              value={form[key as keyof typeof form]}
              onChange={set(key)}
            />
          </div>
        ))}
      </div>

      {blank.length > 0 && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {blank.length} value{blank.length === 1 ? "" : "s"} left blank
          </AlertTitle>
          <AlertDescription>
            The score will be stored and marked as partial, naming what was
            missing. It is not recorded as normal: SOFA gives zero to a healthy
            value, so a missing result and a healthy one would otherwise score
            the same — always making the patient look less sick than they are.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy}
          onClick={() =>
            onSubmit(
              Object.fromEntries(
                Object.entries(form)
                  .filter(([, value]) => value.trim() !== "")
                  .map(([key, value]) => [key, value]),
              ),
            )
          }
        >
          Score
        </Button>
      </div>
    </Shell>
  );
}

function DischargeDialog({
  blockers,
  busy,
  onClose,
  onSubmit,
}: {
  blockers: { kind: string; detail: string }[];
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [outcome, setOutcome] = useState("to_ward");
  const [notes, setNotes] = useState("");
  const [override, setOverride] = useState(false);

  const stepDown = outcome === "to_ward" || outcome === "to_hdu";

  return (
    <Shell
      title="Leaving the unit"
      description="The outcome is recorded as one of a fixed set, because transferred-out and left-against-advice both remove a patient whose outcome nobody knows — and a mortality rate quoted without them can be improved by transferring the sickest patients out."
    >
      <div className="space-y-1">
        <Label htmlFor="d-outcome">Outcome</Label>
        <Select
          id="d-outcome"
          value={outcome}
          onChange={(event) => setOutcome(event.target.value)}
        >
          {OUTCOMES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      {stepDown && blockers.length > 0 && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>
            {blockers.length} thing{blockers.length === 1 ? "" : "s"} still
            holding this patient
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-1 space-y-0.5">
              {blockers.map((row) => (
                <li key={row.detail}>
                  [{row.kind}] {row.detail}
                </li>
              ))}
            </ul>
            <label className="mt-2 flex items-center gap-2">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={override}
                onChange={(event) => setOverride(event.target.checked)}
              />
              Step down anyway — recorded, with the reasons, in the audit trail
            </label>
          </AlertDescription>
        </Alert>
      )}

      <div className="space-y-1">
        <Label htmlFor="d-notes">Notes</Label>
        <Textarea
          id="d-notes"
          rows={3}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </div>

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy || (stepDown && blockers.length > 0 && !override)}
          onClick={() =>
            onSubmit({ outcome, notes, override_blockers: override })
          }
        >
          Record
        </Button>
      </div>
    </Shell>
  );
}

/* -------------------------------------------------------------------------- */
/* Performance                                                                 */
/* -------------------------------------------------------------------------- */

function Performance({ facility }: { facility: string }) {
  const [data, setData] = useState<IcuSummary | null>(null);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<IcuSummary>(`/icu/summary/?facility=${facility}`)
      .then(setData)
      .catch(() => setData(null));
  }, [facility]);

  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        Nothing to report yet.
      </p>
    );
  }

  const { unit, devices, fasthug } = data;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">The unit</CardTitle>
          <CardDescription>Since {unit.since}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Fact label="Admissions" value={String(unit.admissions)} />
            <Fact label="In the unit" value={String(unit.current)} />
            <Fact
              label="Mortality"
              value={
                unit.mortality_percent === null
                  ? "—"
                  : `${unit.mortality_percent}%`
              }
              hint={`${unit.died} of ${unit.completed}`}
            />
            <Fact
              label="Outcome unknown"
              value={String(unit.outcome_unknown)}
              hint={`${unit.transferred_out} out, ${unit.left_against_advice} LAMA`}
              tone={unit.outcome_unknown > 0 ? "text-amber-600" : undefined}
            />
            <Fact
              label="Median stay"
              value={
                unit.median_hours === null ? "—" : `${unit.median_hours}h`
              }
            />
            <Fact
              label="Readmitted < 48h"
              value={
                unit.readmission_percent === null
                  ? "—"
                  : `${unit.readmission_percent}%`
              }
              hint={`${unit.readmissions_within_48h} patients`}
              tone={
                unit.readmissions_within_48h > 0 ? "text-destructive" : undefined
              }
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Mortality sits beside the outcome-unknown count on purpose. Both
            transferred-out and left-against-advice remove a patient nobody
            followed up, and a mortality rate quoted without them can be
            improved by moving the sickest patients somewhere else.
          </p>
          <div className="flex flex-wrap gap-2 border-t pt-3">
            {Object.entries(unit.by_route).map(([route, count]) => (
              <Badge key={route} variant="outline">
                {humanise(route)}: {count}
              </Badge>
            ))}
            <Badge variant="outline">
              {unit.ventilated} ventilated · {unit.invasive_ventilator_days}{" "}
              ventilator-days
            </Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Line and tube surveillance</CardTitle>
          <CardDescription>
            "Six infections" means nothing. Six per thousand line-days is a
            number a unit can act on — which is why the interval is stored
            rather than a flag.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead className="text-right">In use</TableHead>
                <TableHead className="text-right">Device-days</TableHead>
                <TableHead className="text-right">Infections</TableHead>
                <TableHead className="text-right">Per 1,000 days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(devices.by_type).map(([type, row]) => (
                <TableRow key={type}>
                  <TableCell>{humanise(type)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.devices}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.device_days}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.infections}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      Number(row.per_thousand_device_days ?? 0) > 0 &&
                        "text-destructive",
                    )}
                  >
                    {row.per_thousand_device_days ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
              {Object.keys(devices.by_type).length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    No lines recorded in the window.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Daily goals</CardTitle>
          <CardDescription>
            Reported per item because they fail differently: sedation is nearly
            always addressed, and thromboprophylaxis is the one that quietly is
            not. Across {fasthug.rounds} rounds.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {fasthug.items.map((row) => (
            <div key={row.item} className="flex items-center gap-2 text-sm">
              <span className="w-40 shrink-0 truncate">
                {humanise(row.item)}
              </span>
              <span className="flex h-3 flex-1 items-center">
                <span
                  className={cn(
                    "h-3 rounded-sm",
                    (row.answered_percent ?? 0) >= 90
                      ? "bg-emerald-500/70"
                      : "bg-amber-500/70",
                  )}
                  style={{ width: `${row.answered_percent ?? 0}%` }}
                />
              </span>
              <span className="w-16 shrink-0 text-right tabular-nums">
                {row.answered_percent === null ? "—" : `${row.answered_percent}%`}
              </span>
              <span className="w-24 shrink-0 text-right text-xs text-muted-foreground">
                {row.declined} declined
              </span>
            </div>
          ))}
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
    <div>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("font-semibold tabular-nums", tone)}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Pair({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: string | number | null;
  unit?: string;
  tone?: string;
}) {
  return (
    <div className="flex justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tabular-nums", tone)}>
        {value ?? "—"}
        {value !== null && unit ? ` ${unit}` : ""}
      </span>
    </div>
  );
}
