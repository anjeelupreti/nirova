/**
 * The emergency board.
 *
 * This is a wall display as much as a screen: it hangs where the whole
 * department can see it, and it is read at a glance by somebody walking past.
 * Everything follows from that.
 *
 * **Sickest first, then longest waiting.** Sorting by arrival alone is the
 * first-come-first-served queue triage exists to override. The board refreshes
 * itself, because a wait time that only updates on reload is a wait time
 * nobody trusts.
 *
 * **A breach is loud and stays loud.** The row goes red and it does not go
 * quiet when the patient is finally seen — a breach that happened is a breach,
 * and a board that forgot it would let the department flatter itself.
 *
 * **Registering somebody with no name is the easy path**, not a special case
 * buried behind a checkbox. The commonest ambulance arrival is a person nobody
 * can name, and a form that makes that harder than the ordinary case gets used
 * wrongly under pressure.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ambulance,
  CheckCircle2,
  Clock,
  HeartPulse,
  Loader2,
  LogOut,
  Siren,
  Stethoscope,
  UserPlus,
  UserSearch,
  Zap,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Arrival,
  BoardRow,
  DepartmentSummary,
  Facility,
  Paginated,
  Patient,
  ResuscitationRecord,
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

/** How often the board re-reads itself, in milliseconds. */
const REFRESH_MS = 30_000;

const CATEGORY_LABEL: Record<number, string> = {
  1: "Resuscitation",
  2: "Emergent",
  3: "Urgent",
  4: "Less urgent",
  5: "Non-urgent",
};

/**
 * Triage colours, in the order a department already reads them.
 *
 * Red for resuscitation and orange for emergent are near-universal, so the
 * screen does not invent a scheme staff would have to learn.
 */
const CATEGORY_TONE: Record<number, string> = {
  1: "bg-red-600 text-white",
  2: "bg-orange-500 text-white",
  3: "bg-amber-400 text-black",
  4: "bg-emerald-500 text-white",
  5: "bg-sky-500 text-white",
};

const PATHWAYS = [
  ["stemi", "STEMI"],
  ["stroke", "Stroke"],
  ["sepsis", "Sepsis"],
  ["trauma", "Major trauma"],
  ["cardiac_arrest", "Cardiac arrest"],
  ["obstetric", "Obstetric"],
  ["paediatric", "Paediatric"],
  ["poisoning", "Poisoning"],
  ["burn", "Major burn"],
] as const;

const humanise = (value: string) => value.replace(/_/g, " ");

export default function EmergencyPage() {
  const [tab, setTab] = useState<Tab>("board");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
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

  if (denied) {
    return (
      <Alert>
        <Stethoscope className="h-4 w-4" />
        <AlertTitle>The department is not visible to you</AlertTitle>
        <AlertDescription>
          Seeing who is waiting needs clinical permissions.
        </AlertDescription>
      </Alert>
    );
  }

  if (open) {
    return <ArrivalDetail reference={open} onBack={() => setOpen(null)} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Emergency</h1>
          <p className="text-sm text-muted-foreground">
            Sickest first, then longest waiting.
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

      <div className="flex gap-1 border-b">
        {(
          [
            ["board", "Board", Activity],
            ["performance", "Performance", Clock],
          ] as const
        ).map(([id, label, Icon]) => (
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

      {tab === "board" && <Board facility={facility} onOpen={setOpen} />}
      {tab === "performance" && <Performance facility={facility} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The board                                                                   */
/* -------------------------------------------------------------------------- */

function Board({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [rows, setRows] = useState<BoardRow[]>([]);
  const [registering, setRegistering] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!facility) return;
    try {
      setRows(await api.get<BoardRow[]>(`/ed/board/?facility=${facility}`));
    } finally {
      setLoading(false);
    }
  }, [facility]);

  useEffect(() => {
    void load();
    // Refreshed on a timer. A wait time that only updates when somebody
    // reloads is a wait time nobody believes, and this screen is read from
    // across the room.
    const handle = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(handle);
  }, [load]);

  const breaching = rows.filter((row) => row.is_breaching).length;
  const unnamed = rows.filter((row) => row.is_unidentified).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant="secondary">{rows.length} in the department</Badge>
        {breaching > 0 && (
          <Badge variant="destructive">{breaching} breaching</Badge>
        )}
        {unnamed > 0 && (
          <Badge variant="outline">
            <UserSearch className="mr-1 h-3 w-3" />
            {unnamed} unidentified
          </Badge>
        )}
        <span className="text-xs text-muted-foreground">
          refreshes every {REFRESH_MS / 1000}s
        </span>
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => setRegistering(true)}
        >
          <UserPlus className="h-4 w-4" />
          Register an arrival
        </Button>
      </div>

      {loading && rows.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          <Loader2 className="inline h-4 w-4 animate-spin" />
        </p>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-600" />
            The department is empty.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <button
              key={row.reference}
              type="button"
              onClick={() => onOpen(row.reference)}
              className={cn(
                "flex w-full items-stretch gap-3 rounded-md border text-left transition-colors hover:brightness-95",
                row.is_breaching
                  ? "border-destructive/60 bg-destructive/5"
                  : "border-muted",
              )}
            >
              {/* The category block, full height, so the board reads by colour
                  from across the room before anybody reads a word. */}
              <div
                className={cn(
                  "flex w-16 shrink-0 flex-col items-center justify-center rounded-l-md py-3",
                  row.triage_category
                    ? CATEGORY_TONE[row.triage_category]
                    : "bg-muted text-muted-foreground",
                )}
              >
                <span className="text-2xl font-bold leading-none">
                  {row.triage_category ?? "?"}
                </span>
                <span className="mt-0.5 text-[10px] uppercase tracking-wide">
                  {row.triage_category ? "triage" : "not yet"}
                </span>
              </div>

              <div className="min-w-0 flex-1 py-2 pr-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {row.is_unidentified ? (
                      <span className="text-amber-700 dark:text-amber-400">
                        {row.description || row.patient}
                      </span>
                    ) : (
                      row.patient
                    )}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {row.mrn} · {row.reference}
                  </span>
                  {row.is_unidentified && (
                    <Badge variant="outline">
                      <UserSearch className="mr-1 h-3 w-3" />
                      no name
                      {row.minutes_unidentified !== null &&
                        ` · ${row.minutes_unidentified}m`}
                    </Badge>
                  )}
                  {row.is_mlc && (
                    <Badge variant="destructive">
                      <Siren className="mr-1 h-3 w-3" />
                      MLC
                    </Badge>
                  )}
                  {row.arrival_mode === "ambulance" && (
                    <Ambulance className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                  {row.alerts
                    .filter((alert) => !alert.stood_down)
                    .map((alert) => (
                      <Badge
                        key={alert.pathway}
                        variant={
                          alert.met_target === false
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        <Zap className="mr-1 h-3 w-3" />
                        {humanise(alert.pathway)}
                        {alert.elapsed !== null &&
                          ` ${alert.elapsed}/${alert.target_minutes}m`}
                      </Badge>
                    ))}
                </div>
                <p className="truncate text-sm text-muted-foreground">
                  {row.complaint}
                </p>
              </div>

              <div className="flex shrink-0 flex-col items-end justify-center py-2 pr-3 text-right">
                <span
                  className={cn(
                    "text-lg font-semibold tabular-nums",
                    row.is_breaching && "text-destructive",
                  )}
                >
                  {row.waiting_minutes}m
                </span>
                {row.target_minutes !== null && (
                  <span className="text-xs text-muted-foreground">
                    {row.is_breaching
                      ? `${Math.abs(row.minutes_to_breach ?? 0)}m over`
                      : `${row.minutes_to_breach}m left`}
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  {row.seen ? `seen · ${row.seen_by}` : "waiting"}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        A breach stays marked after the patient is seen. A board that forgot it
        would let the department flatter its own numbers.
      </p>

      {registering && (
        <RegisterDialog
          facility={facility}
          onClose={() => setRegistering(false)}
          onRegistered={(reference) => {
            setRegistering(false);
            onOpen(reference);
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Registering                                                                 */
/* -------------------------------------------------------------------------- */

function RegisterDialog({
  facility,
  onClose,
  onRegistered,
}: {
  facility: string;
  onClose: () => void;
  onRegistered: (reference: string) => void;
}) {
  //: Unidentified is the default. The commonest ambulance arrival is somebody
  //: nobody can name, and the form should not make that the awkward path.
  const [known, setKnown] = useState(false);
  const [search, setSearch] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [form, setForm] = useState({
    patient: "",
    presenting_complaint: "",
    arrival_mode: "ambulance",
    unidentified_description: "",
    apparent_gender: "unknown",
    is_mlc: false,
    ambulance_reference: "",
    brought_by: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!known || search.trim().length < 2) return;
    const handle = window.setTimeout(() => {
      void api
        .get<Paginated<Patient>>(
          `/clinical/patients/?search=${encodeURIComponent(search)}`,
        )
        .then((page) => setPatients(page.results.slice(0, 8)))
        .catch(() => setPatients([]));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [known, search]);

  const chosen = patients.find((row) => row.uuid === form.patient);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const arrival = await api.post<Arrival>("/ed/arrivals/", {
        ...form,
        facility,
        patient: known ? form.patient || null : null,
      });
      onRegistered(arrival.reference);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not registered.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>Register an arrival</CardTitle>
          <CardDescription>
            Nothing here requires knowing who they are.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="flex gap-2">
            <Button
              type="button"
              variant={known ? "outline" : "default"}
              className="flex-1"
              onClick={() => setKnown(false)}
            >
              <UserSearch className="h-4 w-4" />
              Nobody can name them
            </Button>
            <Button
              type="button"
              variant={known ? "default" : "outline"}
              className="flex-1"
              onClick={() => setKnown(true)}
            >
              We know who they are
            </Button>
          </div>

          {known ? (
            <div className="space-y-2">
              <Label htmlFor="e-patient">Patient</Label>
              <Input
                id="e-patient"
                placeholder="Name or MRN…"
                value={chosen ? `${chosen.full_name} (${chosen.mrn})` : search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setForm((f) => ({ ...f, patient: "" }));
                }}
              />
              {!chosen && patients.length > 0 && (
                <ul className="divide-y rounded-md border">
                  {patients.map((row) => (
                    <li key={row.uuid}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm hover:bg-muted/60"
                        onClick={() => {
                          setForm((f) => ({ ...f, patient: row.uuid }));
                          setPatients([]);
                        }}
                      >
                        {row.full_name}
                        <span className="text-muted-foreground">
                          {" "}
                          · {row.mrn}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="e-description">
                What staff will call them
              </Label>
              <Input
                id="e-description"
                placeholder="Male, approximately 40, blue shirt, tattoo left forearm"
                value={form.unidentified_description}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    unidentified_description: event.target.value,
                  }))
                }
              />
              <p className="text-xs text-muted-foreground">
                A description beats "Unknown 3" when two of them are in the
                department at once — and it is what a relative arriving at the
                desk will recognise. A real patient record is created either
                way, and merges cleanly when somebody names them.
              </p>
              <Select
                aria-label="Apparent gender"
                value={form.apparent_gender}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    apparent_gender: event.target.value,
                  }))
                }
              >
                <option value="unknown">Gender not stated</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="e-complaint">Presenting complaint</Label>
            <Textarea
              id="e-complaint"
              rows={2}
              value={form.presenting_complaint}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  presenting_complaint: event.target.value,
                }))
              }
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="e-mode">How they arrived</Label>
              <Select
                id="e-mode"
                value={form.arrival_mode}
                onChange={(event) =>
                  setForm((f) => ({ ...f, arrival_mode: event.target.value }))
                }
              >
                {[
                  ["ambulance", "Ambulance"],
                  ["walk_in", "Walked in"],
                  ["private_vehicle", "Private vehicle"],
                  ["police", "Police"],
                  ["referred", "Referred"],
                  ["helicopter", "Air ambulance"],
                  ["other", "Other"],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="e-ambulance">Ambulance reference</Label>
              <Input
                id="e-ambulance"
                value={form.ambulance_reference}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    ambulance_reference: event.target.value,
                  }))
                }
              />
            </div>
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              checked={form.is_mlc}
              onChange={(event) =>
                setForm((f) => ({ ...f, is_mlc: event.target.checked }))
              }
            />
            <span>
              Medico-legal case
              <span className="block text-xs text-muted-foreground">
                Assault, accident, poisoning or burns. The police must be
                informed.
              </span>
            </span>
          </label>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={
                busy ||
                form.presenting_complaint.trim().length < 3 ||
                (known && !form.patient)
              }
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              Register
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One arrival                                                                 */
/* -------------------------------------------------------------------------- */

function ArrivalDetail({
  reference,
  onBack,
}: {
  reference: string;
  onBack: () => void;
}) {
  const [arrival, setArrival] = useState<Arrival | null>(null);
  const [resus, setResus] = useState<ResuscitationRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [triaging, setTriaging] = useState(false);
  const [naming, setNaming] = useState(false);
  const [disposing, setDisposing] = useState(false);

  const load = useCallback(async () => {
    const [detail, record] = await Promise.all([
      api.get<Arrival>(`/ed/arrivals/${reference}/`),
      api.get<ResuscitationRecord>(`/ed/arrivals/${reference}/resuscitation/`),
    ]);
    setArrival(detail);
    setResus(record);
  }, [reference]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ed/arrivals/${reference}/${path}/`, body);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  if (!arrival) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const activeAlerts = arrival.alerts.filter((row) => !row.stood_down_at);

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back to the board
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {arrival.is_unidentified
              ? arrival.provisional_description || arrival.patient_name
              : arrival.patient_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {arrival.reference} · {arrival.patient_mrn} ·{" "}
            {humanise(arrival.arrival_mode)}
            {arrival.ambulance_reference && ` ${arrival.ambulance_reference}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {arrival.is_unidentified && (
            <Button variant="outline" size="sm" onClick={() => setNaming(true)}>
              <UserSearch className="h-4 w-4" />
              Identify
            </Button>
          )}
          {arrival.is_open && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTriaging(true)}
              >
                <HeartPulse className="h-4 w-4" />
                {arrival.triage_category ? "Re-triage" : "Triage"}
              </Button>
              {!arrival.first_seen_at && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => void act("seen")}
                >
                  <Stethoscope className="h-4 w-4" />
                  Mark seen
                </Button>
              )}
              <Button size="sm" onClick={() => setDisposing(true)}>
                <LogOut className="h-4 w-4" />
                Disposition
              </Button>
            </>
          )}
        </div>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {arrival.is_unidentified && (
        <Alert>
          <UserSearch className="h-4 w-4" />
          <AlertTitle>
            Unidentified for {arrival.minutes_unidentified} minutes
          </AlertTitle>
          <AlertDescription>
            {arrival.provisional_description || "No description recorded."} An
            hour unidentified is an hour nobody can ring a relative or check an
            allergy.
          </AlertDescription>
        </Alert>
      )}

      {arrival.is_mlc && (
        <Alert variant="destructive">
          <Siren className="h-4 w-4" />
          <AlertTitle>Medico-legal case</AlertTitle>
          <AlertDescription>
            {arrival.police_informed_at
              ? `Police informed ${new Date(arrival.police_informed_at).toLocaleString()}.`
              : "The police have not been recorded as informed."}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Triage"
          value={
            arrival.triage_category
              ? `${arrival.triage_category} — ${CATEGORY_LABEL[arrival.triage_category]}`
              : "not triaged"
          }
        />
        <Stat
          label="Waited"
          value={`${arrival.waiting_minutes}m`}
          hint={
            arrival.target_minutes !== null
              ? `target ${arrival.target_minutes}m`
              : undefined
          }
          tone={arrival.is_breaching ? "text-destructive" : undefined}
        />
        <Stat
          label="In department"
          value={`${arrival.total_minutes}m`}
        />
        <Stat
          label="Status"
          value={humanise(arrival.disposition)}
          hint={arrival.seen_by_name ? `seen by ${arrival.seen_by_name}` : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Triage history</CardTitle>
              <CardDescription>
                Appended, never overwritten. A deterioration is the one fact a
                mortality review asks about.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="relative space-y-4 border-l pl-6">
                {arrival.assessments.map((row) => (
                  <li key={row.uuid} className="relative">
                    <span
                      className={cn(
                        "absolute -left-[1.65rem] top-1 h-3 w-3 rounded-full border-2 border-background",
                        row.is_deterioration
                          ? "bg-destructive"
                          : "bg-muted-foreground",
                      )}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-xs font-semibold",
                          CATEGORY_TONE[row.category],
                        )}
                      >
                        {row.category}
                      </span>
                      {row.is_deterioration && (
                        <Badge variant="destructive">
                          deteriorated from {row.previous_category}
                        </Badge>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {new Date(row.assessed_at).toLocaleTimeString()} ·{" "}
                        {row.assessed_by_name}
                      </span>
                    </div>
                    {row.reason && <p className="text-sm">{row.reason}</p>}
                    <p className="text-xs text-muted-foreground">
                      {[
                        row.pulse && `HR ${row.pulse}`,
                        row.systolic && `BP ${row.systolic}/${row.diastolic}`,
                        row.respiratory_rate && `RR ${row.respiratory_rate}`,
                        row.spo2 && `SpO₂ ${row.spo2}%`,
                        row.gcs && `GCS ${row.gcs}`,
                        row.temperature_c && `${row.temperature_c}°C`,
                        row.pain_score !== null && `pain ${row.pain_score}/10`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </li>
                ))}
                {arrival.assessments.length === 0 && (
                  <li className="text-sm text-muted-foreground">
                    Not yet triaged.
                  </li>
                )}
              </ol>
            </CardContent>
          </Card>

          {resus && resus.events.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Resuscitation record
                </CardTitle>
                <CardDescription>
                  {resus.duration_minutes} minutes · {resus.shocks} shocks ·{" "}
                  {resus.drugs} drugs
                  {resus.rosc && " · return of circulation"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ol className="space-y-1 font-mono text-xs">
                  {resus.events.map((row, index) => (
                    <li key={index} className="flex gap-3">
                      <span className="w-10 shrink-0 text-right text-muted-foreground">
                        +{row.elapsed_minutes}m
                      </span>
                      <span className="w-24 shrink-0">{row.event_type}</span>
                      <span className="min-w-0 flex-1">
                        {row.drug && `${row.drug} ${row.dose} ${row.route}`}
                        {row.joules && `${row.joules}J`}
                        {row.rhythm && ` ${row.rhythm}`}
                        {row.detail}
                      </span>
                    </li>
                  ))}
                </ol>
                <p className="mt-3 text-xs text-muted-foreground">
                  Each entry timestamped as it happened. A resus written
                  afterwards from memory is not the thing a coroner reads.
                </p>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Critical pathways</CardTitle>
              <CardDescription>
                The clock runs from arrival, not from recognition.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {activeAlerts.map((alert) => (
                <div key={alert.uuid} className="rounded-md border p-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium capitalize">
                      {humanise(alert.pathway)}
                    </span>
                    {alert.met_target === null ? (
                      <Badge variant="default">running</Badge>
                    ) : alert.met_target ? (
                      <Badge variant="secondary">met</Badge>
                    ) : (
                      <Badge variant="destructive">missed</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    recognised at {alert.recognition_minutes}m · target{" "}
                    {alert.target_minutes}m
                    {alert.door_to_intervention_minutes !== null &&
                      ` · done at ${alert.door_to_intervention_minutes}m`}
                  </p>
                  {alert.intervention && (
                    <p className="text-xs">{alert.intervention}</p>
                  )}
                </div>
              ))}
              {activeAlerts.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  None activated.
                </p>
              )}

              {arrival.is_open && (
                <Select
                  aria-label="Activate a pathway"
                  className="h-9"
                  value=""
                  onChange={(event) => {
                    if (event.target.value) {
                      void act("alerts", { pathway: event.target.value });
                    }
                  }}
                >
                  <option value="">Activate a pathway…</option>
                  {PATHWAYS.filter(
                    ([code]) =>
                      !arrival.alerts.some((row) => row.pathway === code),
                  ).map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </Select>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Field
                label="Arrived"
                value={new Date(arrival.arrived_at).toLocaleString()}
              />
              <Field label="Complaint" value={arrival.presenting_complaint} />
              {arrival.brought_by && (
                <Field label="Brought by" value={arrival.brought_by} />
              )}
              {arrival.arrived_unidentified && (
                <Field
                  label="Arrived unnamed"
                  value={
                    arrival.identified_at
                      ? `yes, named after ${arrival.minutes_unidentified}m`
                      : "yes, still unnamed"
                  }
                />
              )}
              {arrival.disposition_at && (
                <Field
                  label="Left"
                  value={`${humanise(arrival.disposition)} at ${new Date(arrival.disposition_at).toLocaleTimeString()}`}
                />
              )}
              {arrival.referred_to && (
                <Field label="Referred to" value={arrival.referred_to} />
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {triaging && (
        <TriageDialog
          arrival={arrival}
          onClose={() => setTriaging(false)}
          onDone={() => {
            setTriaging(false);
            void load();
          }}
        />
      )}
      {naming && (
        <IdentifyDialog
          arrival={arrival}
          onClose={() => setNaming(false)}
          onDone={() => {
            setNaming(false);
            void load();
          }}
        />
      )}
      {disposing && (
        <DisposeDialog
          arrival={arrival}
          onClose={() => setDisposing(false)}
          onDone={() => {
            setDisposing(false);
            void load();
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Dialogs                                                                     */
/* -------------------------------------------------------------------------- */

function TriageDialog({
  arrival,
  onClose,
  onDone,
}: {
  arrival: Arrival;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    category: arrival.triage_category ?? 3,
    reason: "",
    pulse: "",
    systolic: "",
    diastolic: "",
    respiratory_rate: "",
    spo2: "",
    gcs: "",
    temperature_c: "",
    pain_score: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const worsening =
    arrival.triage_category !== null && form.category < arrival.triage_category;

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const numeric = (value: string) =>
        value.trim() === "" ? null : Number(value);
      await api.post(`/ed/arrivals/${arrival.reference}/triage/`, {
        category: form.category,
        reason: form.reason,
        pulse: numeric(form.pulse),
        systolic: numeric(form.systolic),
        diastolic: numeric(form.diastolic),
        respiratory_rate: numeric(form.respiratory_rate),
        spo2: numeric(form.spo2),
        gcs: numeric(form.gcs),
        pain_score: numeric(form.pain_score),
        temperature_c: form.temperature_c || null,
      });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(false);
    }
  };

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-md">
        <CardHeader>
          <CardTitle>
            {arrival.triage_category ? "Re-triage" : "Triage"}
          </CardTitle>
          <CardDescription>
            This appends. The previous assessment stays on the record.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-5 gap-1">
            {[1, 2, 3, 4, 5].map((category) => (
              <button
                key={category}
                type="button"
                onClick={() => setForm((f) => ({ ...f, category }))}
                className={cn(
                  "rounded-md py-3 text-center transition-all",
                  form.category === category
                    ? cn(CATEGORY_TONE[category], "ring-2 ring-offset-2 ring-primary")
                    : cn(CATEGORY_TONE[category], "opacity-40"),
                )}
              >
                <span className="block text-xl font-bold">{category}</span>
                <span className="block text-[10px] leading-tight">
                  {CATEGORY_LABEL[category]}
                </span>
              </button>
            ))}
          </div>

          {worsening && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                This records a deterioration from category{" "}
                {arrival.triage_category} to {form.category}. Say what changed.
              </AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="t-reason">What you found</Label>
            <Textarea
              id="t-reason"
              rows={2}
              value={form.reason}
              onChange={set("reason")}
              placeholder="GCS fallen to 8, now snoring. Airway at risk."
            />
          </div>

          <div className="grid grid-cols-3 gap-2">
            {(
              [
                ["pulse", "Pulse"],
                ["systolic", "Systolic"],
                ["diastolic", "Diastolic"],
                ["respiratory_rate", "Resp rate"],
                ["spo2", "SpO₂ %"],
                ["gcs", "GCS"],
                ["temperature_c", "Temp °C"],
                ["pain_score", "Pain /10"],
              ] as const
            ).map(([key, label]) => (
              <div key={key} className="space-y-1">
                <Label htmlFor={`t-${key}`} className="text-xs">
                  {label}
                </Label>
                <Input
                  id={`t-${key}`}
                  className="h-8"
                  inputMode="decimal"
                  value={form[key]}
                  onChange={set(key)}
                />
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || (worsening && form.reason.trim().length < 5)}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <HeartPulse className="h-4 w-4" />
              )}
              Record
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function IdentifyDialog({
  arrival,
  onClose,
  onDone,
}: {
  arrival: Arrival;
  onClose: () => void;
  onDone: () => void;
}) {
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [search, setSearch] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [chosen, setChosen] = useState<Patient | null>(null);
  const [name, setName] = useState({ first_name: "", last_name: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== "existing" || search.trim().length < 2) return;
    const handle = window.setTimeout(() => {
      void api
        .get<Paginated<Patient>>(
          `/clinical/patients/?search=${encodeURIComponent(search)}`,
        )
        .then((page) => setPatients(page.results.slice(0, 8)))
        .catch(() => setPatients([]));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [mode, search]);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ed/arrivals/${arrival.reference}/identify/`, {
        existing_patient: mode === "existing" ? chosen?.uuid : null,
        ...(mode === "new" ? name : {}),
      });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not identified.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Put a name to them</CardTitle>
          <CardDescription>
            Everything written so far follows them across.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="flex gap-2">
            <Button
              variant={mode === "existing" ? "default" : "outline"}
              className="flex-1"
              onClick={() => setMode("existing")}
            >
              They have a record here
            </Button>
            <Button
              variant={mode === "new" ? "default" : "outline"}
              className="flex-1"
              onClick={() => setMode("new")}
            >
              They are new
            </Button>
          </div>

          {mode === "existing" ? (
            <div className="space-y-2">
              <Input
                placeholder="Search by name, MRN or phone…"
                value={chosen ? `${chosen.full_name} (${chosen.mrn})` : search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setChosen(null);
                }}
              />
              {!chosen && patients.length > 0 && (
                <ul className="divide-y rounded-md border">
                  {patients.map((row) => (
                    <li key={row.uuid}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm hover:bg-muted/60"
                        onClick={() => {
                          setChosen(row);
                          setPatients([]);
                        }}
                      >
                        {row.full_name}
                        <span className="text-muted-foreground">
                          {" "}
                          · {row.mrn}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {chosen && (
                <Alert>
                  <CheckCircle2 className="h-4 w-4" />
                  <AlertDescription>
                    The provisional record {arrival.patient_mrn} merges into{" "}
                    {chosen.mrn}. Everything written during this attendance
                    lands on the chart their doctor will read next month.
                  </AlertDescription>
                </Alert>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Input
                  placeholder="First name"
                  value={name.first_name}
                  onChange={(event) =>
                    setName((n) => ({ ...n, first_name: event.target.value }))
                  }
                />
                <Input
                  placeholder="Last name"
                  value={name.last_name}
                  onChange={(event) =>
                    setName((n) => ({ ...n, last_name: event.target.value }))
                  }
                />
              </div>
              <Input
                placeholder="Phone"
                value={name.phone}
                onChange={(event) =>
                  setName((n) => ({ ...n, phone: event.target.value }))
                }
              />
              <p className="text-xs text-muted-foreground">
                The record they already have keeps its MRN and everything
                attached to it.
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
                (mode === "existing"
                  ? !chosen
                  : !(name.first_name.trim() && name.last_name.trim()))
              }
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserSearch className="h-4 w-4" />
              )}
              Identify
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DisposeDialog({
  arrival,
  onClose,
  onDone,
}: {
  arrival: Arrival;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    disposition: "discharged",
    notes: "",
    admission_reference: "",
    referred_to: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ed/arrivals/${arrival.reference}/dispose/`, form);
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>How did it end?</CardTitle>
          <CardDescription>
            {arrival.total_minutes} minutes in the department.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="d-disposition">Disposition</Label>
            <Select
              id="d-disposition"
              value={form.disposition}
              onChange={(event) =>
                setForm((f) => ({ ...f, disposition: event.target.value }))
              }
            >
              <option value="discharged">Discharged home</option>
              <option value="admitted">Admitted</option>
              <option value="referred">Referred to another facility</option>
              <option value="lwbs">Left without being seen</option>
              <option value="lama">Left against medical advice</option>
              <option value="absconded">Absconded</option>
              <option value="died">Died in the department</option>
              <option value="brought_dead">Brought in dead</option>
            </Select>
          </div>

          {form.disposition === "lwbs" && (
            <Alert>
              <Clock className="h-4 w-4" />
              <AlertDescription>
                Recorded as a departmental outcome, not an absence. It only
                exists because somebody records it — an attendance that simply
                goes quiet flatters the numbers.
              </AlertDescription>
            </Alert>
          )}

          {form.disposition === "admitted" && (
            <div className="space-y-2">
              <Label htmlFor="d-admission">Admission reference</Label>
              <Input
                id="d-admission"
                value={form.admission_reference}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    admission_reference: event.target.value,
                  }))
                }
                placeholder="IPD26090001"
              />
              <p className="text-xs text-muted-foreground">
                Admit them on the ward screen first. An attendance marked
                admitted with no admission is a patient nobody is looking
                after.
              </p>
            </div>
          )}

          {form.disposition === "referred" && (
            <div className="space-y-2">
              <Label htmlFor="d-referred">Referred to</Label>
              <Input
                id="d-referred"
                value={form.referred_to}
                onChange={(event) =>
                  setForm((f) => ({ ...f, referred_to: event.target.value }))
                }
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="d-notes">Notes</Label>
            <Textarea
              id="d-notes"
              rows={2}
              value={form.notes}
              onChange={(event) =>
                setForm((f) => ({ ...f, notes: event.target.value }))
              }
            />
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LogOut className="h-4 w-4" />
              )}
              Record
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Performance                                                                 */
/* -------------------------------------------------------------------------- */

function Performance({ facility }: { facility: string }) {
  const [data, setData] = useState<DepartmentSummary | null>(null);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<DepartmentSummary>(`/ed/summary/?facility=${facility}`)
      .then(setData)
      .catch(() => setData(null));
  }, [facility]);

  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const { summary, pathways } = data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Attendances" value={String(summary.arrivals)} hint={`since ${summary.since}`} />
        <Stat
          label="Median wait"
          value={`${summary.median_wait_minutes}m`}
          hint={`longest ${summary.longest_wait_minutes}m`}
        />
        <Stat
          label="Breaches"
          value={`${summary.breach_percent}%`}
          hint={`${summary.breaches} of those seen`}
          tone={summary.breach_percent > 10 ? "text-destructive" : undefined}
        />
        <Stat
          label="Left without being seen"
          value={`${summary.lwbs_percent}%`}
          hint={`${summary.left_without_being_seen} people`}
          tone={summary.lwbs_percent > 5 ? "text-destructive" : undefined}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Breaches by category</CardTitle>
          <CardDescription>
            Per category, because an aggregate can look healthy while every
            single category-2 target is missed.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Seen</TableHead>
                <TableHead className="text-right">Breached</TableHead>
                <TableHead className="text-right">Rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(summary.breach_by_category).map(
                ([category, bucket]) => (
                  <TableRow key={category}>
                    <TableCell>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-xs font-semibold",
                          CATEGORY_TONE[Number(category)],
                        )}
                      >
                        {category}
                      </span>
                      <span className="ml-2">
                        {CATEGORY_LABEL[Number(category)]}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {bucket.seen}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {bucket.breached}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-medium tabular-nums",
                        bucket.breach_percent > 10 && "text-destructive",
                      )}
                    >
                      {bucket.breach_percent}%
                    </TableCell>
                  </TableRow>
                ),
              )}
              {Object.keys(summary.breach_by_category).length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-6 text-center text-sm text-muted-foreground"
                  >
                    Nobody has been seen yet in this period.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {pathways.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Critical pathways</CardTitle>
            <CardDescription>
              Recognition and intervention reported separately: a slow
              recognition is a triage problem, a slow intervention is a
              resource problem, and one figure cannot tell them apart.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Pathway</TableHead>
                  <TableHead className="text-right">Activated</TableHead>
                  <TableHead className="text-right">Recognition</TableHead>
                  <TableHead className="text-right">Door to needle</TableHead>
                  <TableHead className="text-right">Target</TableHead>
                  <TableHead className="text-right">Met</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pathways.map((row) => (
                  <TableRow key={row.pathway}>
                    <TableCell className="capitalize">
                      {humanise(row.pathway)}
                      {row.stood_down > 0 && (
                        <span className="block text-xs text-muted-foreground">
                          {row.stood_down} stood down
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.activations}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.average_recognition_minutes ?? "—"}m
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        (row.average_door_to_intervention_minutes ?? 0) >
                          row.target_minutes && "text-destructive",
                      )}
                    >
                      {row.average_door_to_intervention_minutes ?? "—"}m
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {row.target_minutes}m
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.met_target_percent === null
                        ? "—"
                        : `${row.met_target_percent}%`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Dispositions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {Object.entries(summary.by_disposition).map(([key, count]) => (
              <div key={key} className="flex justify-between">
                <span className="capitalize text-muted-foreground">
                  {humanise(key)}
                </span>
                <span className="tabular-nums">{count}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">How they arrived</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {Object.entries(summary.by_arrival_mode).map(([key, count]) => (
              <div key={key} className="flex justify-between">
                <span className="capitalize text-muted-foreground">
                  {humanise(key)}
                </span>
                <span className="tabular-nums">{count}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Identity and legal</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">
                Arrived unidentified
              </span>
              <span className="tabular-nums">
                {summary.arrived_unidentified}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Still unnamed</span>
              <span
                className={cn(
                  "tabular-nums",
                  summary.still_unidentified > 0 && "text-amber-600",
                )}
              >
                {summary.still_unidentified}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Medico-legal</span>
              <span className="tabular-nums">{summary.medico_legal}</span>
            </div>
            <p className="pt-1 text-xs text-muted-foreground">
              Counted on how they arrived, not on how they are now —
              identification must not erase the fact that nobody could name
              them.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bits                                                                        */
/* -------------------------------------------------------------------------- */

function Stat({
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
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className={cn("mt-1 text-xl font-semibold tabular-nums", tone)}>
          {value}
        </p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
