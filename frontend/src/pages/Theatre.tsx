/**
 * The operating theatre.
 *
 * Two audiences with opposite needs. A theatre coordinator wants the day's
 * lists side by side with the idle gaps visible — the whole job is finding
 * the hour that nobody can use. A scrub team wants one case, its checklist,
 * and the button for the next timing.
 *
 * Three things the screen refuses to soften.
 *
 * **The idle gap is drawn, not implied.** A list with three twenty-minute
 * holes has an hour of theatre time nobody is looking at, and a calendar that
 * merely stacks cases hides it.
 *
 * **The safety checklist is the loudest thing on a case.** Not a tab, not a
 * form buried under the notes. And where a case reached incision without a
 * time-out, that is stated in red on the case and counted on the audit — the
 * screen does not offer to make it go away.
 *
 * **An implant needs a serial number before the button enables.** A recall
 * asks which patients have one, and a product code cannot answer that.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  CalendarRange,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Loader2,
  Package,
  ScanLine,
  ShieldAlert,
  ShieldCheck,
  Stethoscope,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  CaseCost,
  ChecklistState,
  Facility,
  ImplantRecord,
  OperatingTheatre,
  Paginated,
  SafetyAudit,
  SurgicalCase,
  SurgicalCaseSummary,
  TheatreListRow,
  TheatreUtilisation,
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

type Tab = "lists" | "waiting" | "implants" | "performance";

const TABS: { id: Tab; label: string; icon: typeof Activity }[] = [
  { id: "lists", label: "Today's lists", icon: CalendarRange },
  { id: "waiting", label: "Waiting list", icon: Clock },
  { id: "implants", label: "Implants", icon: ScanLine },
  { id: "performance", label: "Performance", icon: Activity },
];

/** The case's timings, in the order they happen. */
const STEPS: { key: string; label: string; field: keyof SurgicalCase }[] = [
  { key: "sent_for", label: "Sent for", field: "sent_for_at" },
  { key: "wheels_in", label: "Wheels in", field: "wheels_in_at" },
  {
    key: "anaesthesia_start",
    label: "Anaesthesia",
    field: "anaesthesia_start_at",
  },
  { key: "incision", label: "Incision", field: "incision_at" },
  { key: "closure", label: "Closure", field: "closure_at" },
  { key: "wheels_out", label: "Wheels out", field: "wheels_out_at" },
  { key: "recovery_out", label: "Left recovery", field: "recovery_out_at" },
];

const CANCELLATION_REASONS = [
  ["no_bed", "No bed available"],
  ["no_theatre_time", "List overran"],
  ["no_staff", "Staff unavailable"],
  ["no_equipment", "Equipment or implant unavailable"],
  ["emergency_bumped", "Displaced by an emergency"],
  ["patient_unfit", "Patient medically unfit"],
  ["patient_not_fasted", "Patient not fasted"],
  ["patient_dna", "Patient did not attend"],
  ["patient_declined", "Patient declined"],
  ["clinical_decision", "No longer indicated"],
  ["administrative", "Administrative"],
] as const;

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;

const humanise = (value: string) => value.replace(/_/g, " ");

const clock = (value: string | null) =>
  value
    ? new Date(value).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

const URGENCY_TONE: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  elective: "outline",
  scheduled: "secondary",
  urgent: "default",
  emergency: "destructive",
};

export default function TheatrePage() {
  const [tab, setTab] = useState<Tab>("lists");
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
        <AlertTitle>The theatre is not visible to you</AlertTitle>
        <AlertDescription>
          Seeing the operating lists needs clinical permissions.
        </AlertDescription>
      </Alert>
    );
  }

  if (open) {
    return <CaseDetail reference={open} onBack={() => setOpen(null)} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Theatre</h1>
          <p className="text-sm text-muted-foreground">
            The lists, the checklist, and the time nobody can use.
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

      {tab === "lists" && <Lists facility={facility} onOpen={setOpen} />}
      {tab === "waiting" && <Waiting facility={facility} onOpen={setOpen} />}
      {tab === "implants" && <Implants />}
      {tab === "performance" && <Performance facility={facility} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The day's lists                                                             */
/* -------------------------------------------------------------------------- */

function Lists({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [theatres, setTheatres] = useState<OperatingTheatre[]>([]);
  const [lists, setLists] = useState<Record<string, TheatreListRow[]>>({});
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!facility) return;
    setLoading(true);
    try {
      const page = await api.get<Paginated<OperatingTheatre>>(
        `/ot/theatres/?facility=${facility}&is_active=true`,
      );
      setTheatres(page.results);
      const rows = await Promise.all(
        page.results.map((room) =>
          api
            .get<TheatreListRow[]>(`/ot/theatres/${room.uuid}/list/?date=${date}`)
            .then((list) => [room.uuid, list] as const),
        ),
      );
      setLists(Object.fromEntries(rows));
    } finally {
      setLoading(false);
    }
  }, [facility, date]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && theatres.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Label htmlFor="ot-date" className="text-sm">
          Date
        </Label>
        <Input
          id="ot-date"
          type="date"
          className="h-9 w-auto"
          value={date}
          onChange={(event) => setDate(event.target.value)}
        />
      </div>

      {theatres.length === 0 && (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            No theatres at this facility.
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {theatres.map((room) => {
          const rows = lists[room.uuid] ?? [];
          const idle = rows.reduce(
            (sum, row) => sum + (row.unused_gap_minutes ?? 0),
            0,
          );
          const booked = rows.reduce(
            (sum, row) => sum + row.planned_minutes,
            0,
          );
          return (
            <Card key={room.uuid}>
              <CardHeader className="flex-row items-start justify-between space-y-0">
                <div>
                  <CardTitle className="text-base">{room.name}</CardTitle>
                  <CardDescription>
                    {rows.length} case{rows.length === 1 ? "" : "s"} ·{" "}
                    {booked} minutes booked · {room.turnaround_minutes}m
                    turnaround
                  </CardDescription>
                </div>
                {idle > 0 && (
                  <Badge variant="destructive">{idle}m idle</Badge>
                )}
              </CardHeader>
              <CardContent>
                {rows.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    Nothing booked.
                  </p>
                ) : (
                  <ol className="space-y-1">
                    {rows.map((row) => (
                      <li key={row.reference}>
                        {/* The idle gap is drawn, not implied. A calendar
                            that merely stacks cases hides the hour nobody
                            can use. */}
                        {row.unused_gap_minutes ? (
                          <div className="my-1 flex items-center gap-2 text-xs text-destructive">
                            <span className="h-px flex-1 bg-destructive/30" />
                            {row.unused_gap_minutes} minutes idle
                            <span className="h-px flex-1 bg-destructive/30" />
                          </div>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => onOpen(row.reference)}
                          className="flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm hover:bg-muted/50"
                        >
                          <span className="w-12 shrink-0 font-medium tabular-nums">
                            {clock(row.scheduled_start)}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">
                              {row.procedure}
                              {row.laterality !== "na" && (
                                <span className="ml-1 uppercase text-destructive">
                                  {row.laterality}
                                </span>
                              )}
                            </span>
                            <span className="block truncate text-xs text-muted-foreground">
                              {row.patient} · {row.mrn}
                              {row.asa_grade && ` · ASA ${row.asa_grade}`}
                            </span>
                          </span>
                          <span className="shrink-0 text-right">
                            <Badge
                              variant={URGENCY_TONE[row.urgency] ?? "outline"}
                            >
                              {humanise(row.status)}
                            </Badge>
                            <span className="block text-xs tabular-nums text-muted-foreground">
                              {row.planned_minutes}m
                              {row.overran_minutes !== null &&
                                row.overran_minutes > 0 && (
                                  <span className="text-destructive">
                                    {" "}
                                    +{row.overran_minutes}
                                  </span>
                                )}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Idle time is measured beyond the room's own turnaround — a gap the
        length of the cleaning time is not waste, and a gap twice that is.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Waiting list                                                                */
/* -------------------------------------------------------------------------- */

function Waiting({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [rows, setRows] = useState<SurgicalCaseSummary[]>([]);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<Paginated<SurgicalCaseSummary>>(
        `/ot/cases/?facility=${facility}&waiting=true`,
      )
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, [facility]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Approved, awaiting a slot</CardTitle>
        <CardDescription>
          The clinical decision that somebody needs surgery and the operational
          decision about when are made by different people, weeks apart. This
          is the gap between them.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Patient</TableHead>
              <TableHead>Procedure</TableHead>
              <TableHead>Urgency</TableHead>
              <TableHead className="text-right">ASA</TableHead>
              <TableHead className="text-right">Booked for</TableHead>
              <TableHead>Waiting since</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.uuid}
                className="cursor-pointer"
                onClick={() => onOpen(row.reference)}
              >
                <TableCell>
                  <span className="font-medium">{row.patient_name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {row.patient_mrn} · {row.reference}
                  </span>
                </TableCell>
                <TableCell>
                  {row.planned_procedure}
                  {row.laterality !== "na" && (
                    <span className="ml-1 text-xs uppercase text-destructive">
                      {row.laterality}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={URGENCY_TONE[row.urgency] ?? "outline"}>
                    {humanise(row.urgency)}
                  </Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.asa_grade ?? "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.planned_minutes}m
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {row.is_day_case ? "day case" : "inpatient"}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-sm text-muted-foreground"
                >
                  Nothing waiting for a slot.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* One case                                                                    */
/* -------------------------------------------------------------------------- */

function CaseDetail({
  reference,
  onBack,
}: {
  reference: string;
  onBack: () => void;
}) {
  const [surgicalCase, setCase] = useState<SurgicalCase | null>(null);
  const [checklist, setChecklist] = useState<ChecklistState | null>(null);
  const [cost, setCost] = useState<CaseCost | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [phase, setPhase] = useState<string | null>(null);
  const [consuming, setConsuming] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    const [detail, checks, money] = await Promise.all([
      api.get<SurgicalCase>(`/ot/cases/${reference}/`),
      api.get<ChecklistState>(`/ot/cases/${reference}/checklist/`),
      api.get<CaseCost>(`/ot/cases/${reference}/consumption/`),
    ]);
    setCase(detail);
    setChecklist(checks);
    setCost(money);
  }, [reference]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ot/cases/${reference}/${path}/`, body);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  if (!surgicalCase || !checklist) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const nextStep = STEPS.find((step) => !surgicalCase[step.field]);

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back to the lists
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {surgicalCase.planned_procedure}
            {surgicalCase.laterality !== "na" && (
              <span className="ml-2 text-base uppercase text-destructive">
                {surgicalCase.laterality}
              </span>
            )}
          </h1>
          <p className="text-sm text-muted-foreground">
            {surgicalCase.reference} · {surgicalCase.patient_name} ·{" "}
            {surgicalCase.patient_mrn}
            {surgicalCase.theatre_code && ` · ${surgicalCase.theatre_code}`}
            {surgicalCase.asa_grade && ` · ASA ${surgicalCase.asa_grade}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {nextStep && surgicalCase.status !== "cancelled" && (
            <Button
              disabled={busy}
              onClick={() => void act("mark", { step: nextStep.key })}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Clock className="h-4 w-4" />
              )}
              {nextStep.label}
            </Button>
          )}
          {surgicalCase.is_live && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConsuming(true)}
              >
                <Package className="h-4 w-4" />
                Record use
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCancelling(true)}
              >
                <Ban className="h-4 w-4" />
                Cancel
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

      {/* The loudest thing on the page when it is true. */}
      {checklist.state.incision_without_timeout && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>Incision without a time-out</AlertTitle>
          <AlertDescription>
            The WHO time-out was not completed before the incision. The system
            did not stop the case; it recorded that this happened, and this
            case appears on the safety audit.
          </AlertDescription>
        </Alert>
      )}

      {surgicalCase.status === "cancelled" && (
        <Alert>
          <Ban className="h-4 w-4" />
          <AlertTitle>
            Cancelled — {humanise(surgicalCase.cancellation_reason)}
          </AlertTitle>
          <AlertDescription>
            {surgicalCase.cancellation_notes}
            {surgicalCase.was_avoidable_cancellation &&
              " Counted as avoidable by the hospital."}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          {/* The safety checklist, first. */}
          <Card
            className={cn(
              checklist.state.incision_without_timeout &&
                "border-destructive/50",
            )}
          >
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-4 w-4" />
                Surgical safety checklist
              </CardTitle>
              <CardDescription>
                Said aloud by a named person at a named moment. Recorded, never
                enforced — a system that blocks the incision gets bypassed
                within a week.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {checklist.state.phases.map((row) => (
                <div
                  key={row.phase}
                  className={cn(
                    "rounded-md border p-3",
                    row.skipped && "border-destructive/50 bg-destructive/5",
                    row.complete && "border-emerald-500/40",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    {row.complete ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    ) : row.skipped ? (
                      <ShieldAlert className="h-4 w-4 text-destructive" />
                    ) : (
                      <ClipboardCheck className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className="font-medium">{row.label}</span>
                    {row.completed_by && (
                      <span className="text-xs text-muted-foreground">
                        {row.completed_by} · {clock(row.completed_at)}
                      </span>
                    )}
                    {row.skipped && (
                      <Badge variant="destructive">skipped</Badge>
                    )}
                    {!row.complete && !row.skipped && surgicalCase.is_live && (
                      <Button
                        size="sm"
                        className="ml-auto"
                        onClick={() => setPhase(row.phase)}
                      >
                        Perform
                      </Button>
                    )}
                  </div>
                  {row.skip_reason && (
                    <p className="mt-1 text-sm text-destructive">
                      {row.skip_reason}
                    </p>
                  )}
                  {row.concerns && (
                    <p className="mt-1 text-sm text-amber-600">
                      {row.concerns}
                    </p>
                  )}
                  {row.negative_answers.length > 0 && (
                    <ul className="mt-1 space-y-0.5 text-xs text-amber-600">
                      {row.negative_answers.map((item) => (
                        <li key={item}>· {item}</li>
                      ))}
                    </ul>
                  )}
                  {row.complete && row.unanswered.length > 0 && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {row.unanswered.length} item
                      {row.unanswered.length === 1 ? "" : "s"} not recorded
                    </p>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Timings</CardTitle>
              <CardDescription>
                The gaps between these are the whole of theatre productivity.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="relative space-y-3 border-l pl-6">
                {STEPS.map((step) => {
                  const at = surgicalCase[step.field] as string | null;
                  return (
                    <li key={step.key} className="relative">
                      <span
                        className={cn(
                          "absolute -left-[1.65rem] top-1 h-3 w-3 rounded-full border-2 border-background",
                          at ? "bg-primary" : "bg-muted",
                        )}
                      />
                      <div className="flex items-baseline justify-between gap-3">
                        <span
                          className={cn(
                            !at && "text-muted-foreground",
                          )}
                        >
                          {step.label}
                        </span>
                        <span className="tabular-nums">{clock(at)}</span>
                      </div>
                    </li>
                  );
                })}
              </ol>

              <div className="mt-4 grid grid-cols-2 gap-3 border-t pt-3 text-sm sm:grid-cols-4">
                <Fact
                  label="Started"
                  value={
                    surgicalCase.start_delay_minutes === null
                      ? "—"
                      : `${surgicalCase.start_delay_minutes > 0 ? "+" : ""}${surgicalCase.start_delay_minutes}m`
                  }
                  tone={
                    (surgicalCase.start_delay_minutes ?? 0) > 15
                      ? "text-destructive"
                      : undefined
                  }
                />
                <Fact
                  label="Operating"
                  value={
                    surgicalCase.operating_minutes === null
                      ? "—"
                      : `${surgicalCase.operating_minutes}m`
                  }
                />
                <Fact
                  label="Theatre"
                  value={
                    surgicalCase.theatre_minutes === null
                      ? "—"
                      : `${surgicalCase.theatre_minutes}m`
                  }
                  hint={`booked ${surgicalCase.planned_minutes}m`}
                />
                <Fact
                  label="Overran"
                  value={
                    surgicalCase.overran_minutes === null
                      ? "—"
                      : `${surgicalCase.overran_minutes > 0 ? "+" : ""}${surgicalCase.overran_minutes}m`
                  }
                  tone={
                    (surgicalCase.overran_minutes ?? 0) > 0
                      ? "text-destructive"
                      : undefined
                  }
                />
              </div>
              {surgicalCase.theatre_minutes !== null &&
                surgicalCase.operating_minutes !== null && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    The room was occupied{" "}
                    {surgicalCase.theatre_minutes -
                      surgicalCase.operating_minutes}
                    m longer than the operation took — the gap that booking a
                    list on surgeons' estimates always misses.
                  </p>
                )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="h-4 w-4" />
                The team
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {surgicalCase.team.map((member) => (
                <div key={member.uuid} className="flex justify-between gap-2">
                  <span className="text-muted-foreground">
                    {humanise(member.role)}
                  </span>
                  <span className="text-right">
                    {member.name}
                    {member.registration_number && (
                      <span className="block text-xs text-muted-foreground">
                        {member.registration_number}
                      </span>
                    )}
                  </span>
                </div>
              ))}
              {surgicalCase.team.length === 0 && (
                <p className="text-muted-foreground">Nobody assigned.</p>
              )}
              <p className="pt-2 text-xs text-muted-foreground">
                A licensed role goes through the same practice check that
                refuses a prescription — nobody operates on a lapsed
                registration.
              </p>
            </CardContent>
          </Card>

          {cost && cost.items > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Used</CardTitle>
                <CardDescription>
                  {cost.items} items · {rupees(cost.total)}
                  {cost.unbilled > 0 && ` · ${cost.unbilled} unbilled`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {cost.implants.length > 0 && (
                  <div className="rounded-md border border-amber-500/40 bg-amber-50 p-2 text-sm dark:bg-amber-950/20">
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
                      Implants
                    </p>
                    {cost.implants.map((row) => (
                      <div key={row.serial_number}>
                        <span className="font-medium">{row.description}</span>
                        <span className="block font-mono text-xs">
                          {row.serial_number}
                          {row.site && ` · ${row.site}`}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {surgicalCase.consumption
                  .filter((row) => row.kind !== "implant")
                  .map((row) => (
                    <div
                      key={row.uuid}
                      className="flex justify-between gap-2 text-sm"
                    >
                      <span className="min-w-0 truncate text-muted-foreground">
                        {row.description}
                        {row.batch_number && (
                          <span className="block text-xs">
                            batch {row.batch_number}
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 tabular-nums">
                        × {Number(row.quantity)}
                      </span>
                    </div>
                  ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Field label="Urgency" value={humanise(surgicalCase.urgency)} />
              <Field
                label="Requested"
                value={`${surgicalCase.requested_by_name} · ${new Date(surgicalCase.requested_at).toLocaleDateString()}`}
              />
              {surgicalCase.approved_by_name && (
                <Field
                  label="Approved"
                  value={surgicalCase.approved_by_name}
                />
              )}
              {surgicalCase.indication && (
                <Field label="Indication" value={surgicalCase.indication} />
              )}
              {surgicalCase.performed_procedure && (
                <Field
                  label="Performed"
                  value={surgicalCase.performed_procedure}
                />
              )}
              {surgicalCase.blood_loss_ml !== null && (
                <Field
                  label="Blood loss"
                  value={`${surgicalCase.blood_loss_ml} ml`}
                />
              )}
              {surgicalCase.findings && (
                <div className="border-t pt-2">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Findings
                  </p>
                  <p>{surgicalCase.findings}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {phase && (
        <ChecklistDialog
          reference={reference}
          phase={phase}
          items={checklist.items[phase] ?? []}
          label={
            checklist.state.phases.find((row) => row.phase === phase)?.label ??
            phase
          }
          onClose={() => setPhase(null)}
          onDone={() => {
            setPhase(null);
            void load();
          }}
        />
      )}
      {consuming && (
        <ConsumeDialog
          reference={reference}
          onClose={() => setConsuming(false)}
          onDone={() => {
            setConsuming(false);
            void load();
          }}
        />
      )}
      {cancelling && (
        <CancelDialog
          reference={reference}
          onClose={() => setCancelling(false)}
          onDone={() => {
            setCancelling(false);
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

function ChecklistDialog({
  reference,
  phase,
  label,
  items,
  onClose,
  onDone,
}: {
  reference: string;
  phase: string;
  label: string;
  items: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [responses, setResponses] = useState<Record<string, boolean>>({});
  const [concerns, setConcerns] = useState("");
  const [skipping, setSkipping] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ot/cases/${reference}/checklist/`, {
        phase,
        responses,
        concerns,
        skip: skipping,
        reason: skipReason,
      });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>{label}</CardTitle>
          <CardDescription>
            Say each aloud. The point is the conversation, not the ticks.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          {skipping ? (
            <div className="space-y-2">
              <Alert variant="destructive">
                <ShieldAlert className="h-4 w-4" />
                <AlertTitle>Recording this phase as skipped</AlertTitle>
                <AlertDescription>
                  A blank phase is indistinguishable from nobody filling the
                  form in. A skip with a reason is a decision somebody made and
                  can be asked about.
                </AlertDescription>
              </Alert>
              <Label htmlFor="skip-reason">Why</Label>
              <Textarea
                id="skip-reason"
                rows={3}
                value={skipReason}
                onChange={(event) => setSkipReason(event.target.value)}
                placeholder="Exsanguinating haemorrhage; time-out performed verbally without recording."
              />
            </div>
          ) : (
            <ul className="space-y-2">
              {items.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <div className="flex gap-1 pt-0.5">
                    <button
                      type="button"
                      onClick={() =>
                        setResponses((current) => ({
                          ...current,
                          [item]: true,
                        }))
                      }
                      className={cn(
                        "rounded px-2 py-0.5 text-xs",
                        responses[item] === true
                          ? "bg-emerald-600 text-white"
                          : "border text-muted-foreground",
                      )}
                    >
                      Yes
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setResponses((current) => ({
                          ...current,
                          [item]: false,
                        }))
                      }
                      className={cn(
                        "rounded px-2 py-0.5 text-xs",
                        responses[item] === false
                          ? "bg-destructive text-white"
                          : "border text-muted-foreground",
                      )}
                    >
                      No
                    </button>
                  </div>
                  <span className="flex-1 text-sm">{item}</span>
                </li>
              ))}
            </ul>
          )}

          {!skipping && (
            <div className="space-y-2">
              <Label htmlFor="concerns">Concerns raised</Label>
              <Textarea
                id="concerns"
                rows={2}
                value={concerns}
                onChange={(event) => setConcerns(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Items left unanswered are recorded as unanswered rather than
                blocking — a phase done in a hurry with two gaps is better
                evidence than none, and refusing it produces the pre-ticking
                the checklist exists to prevent.
              </p>
            </div>
          )}

          <div className="flex gap-2">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => (skipping ? setSkipping(false) : onClose())}
            >
              {skipping ? "Back" : "Cancel"}
            </Button>
            {!skipping && (
              <Button
                variant="outline"
                onClick={() => setSkipping(true)}
              >
                Skip
              </Button>
            )}
            <Button
              className="flex-1"
              disabled={
                busy || (skipping && skipReason.trim().length < 10)
              }
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {skipping ? "Record as skipped" : "Record"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ConsumeDialog({
  reference,
  onClose,
  onDone,
}: {
  reference: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    kind: "consumable",
    description: "",
    quantity: "1",
    serial_number: "",
    unit_cost: "",
    implanted_site: "",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const isImplant = form.kind === "implant";

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ot/cases/${reference}/consumption/`, {
        ...form,
        unit_cost: form.unit_cost || null,
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
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Record something used</CardTitle>
          <CardDescription>
            Comes out of theatre stock, and onto the bill.
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
            <Label htmlFor="c-kind">What</Label>
            <Select id="c-kind" value={form.kind} onChange={set("kind")}>
              <option value="consumable">Consumable</option>
              <option value="implant">Implant</option>
              <option value="drug">Drug</option>
              <option value="blood">Blood product</option>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="c-description">Description</Label>
            <Input
              id="c-description"
              value={form.description}
              onChange={set("description")}
            />
          </div>

          {isImplant && (
            <>
              <div className="space-y-2">
                <Label htmlFor="c-serial">Serial number</Label>
                <Input
                  id="c-serial"
                  className="font-mono"
                  value={form.serial_number}
                  onChange={set("serial_number")}
                />
                <p className="text-xs text-amber-600">
                  Required. A recall asks which patients have one, and a
                  product code cannot answer that. A serial already recorded
                  against another patient is refused — two people cannot hold
                  the same device.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="c-site">Site</Label>
                <Input
                  id="c-site"
                  value={form.implanted_site}
                  onChange={set("implanted_site")}
                  placeholder="Right knee"
                />
              </div>
            </>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="c-quantity">Quantity</Label>
              <Input
                id="c-quantity"
                inputMode="decimal"
                value={form.quantity}
                onChange={set("quantity")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="c-cost">Unit cost</Label>
              <Input
                id="c-cost"
                inputMode="decimal"
                value={form.unit_cost}
                onChange={set("unit_cost")}
              />
            </div>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={
                busy ||
                form.description.trim().length < 2 ||
                (isImplant && form.serial_number.trim().length < 3)
              }
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Package className="h-4 w-4" />
              )}
              Record
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function CancelDialog({
  reference,
  onClose,
  onDone,
}: {
  reference: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("no_bed");
  const [notes, setNotes] = useState("");
  const [postpone, setPostpone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const avoidable = [
    "no_bed",
    "no_theatre_time",
    "no_staff",
    "no_equipment",
    "administrative",
  ].includes(reason);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ot/cases/${reference}/cancel/`, {
        reason,
        notes,
        postpone,
      });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Cancel this case</CardTitle>
          <CardDescription>
            A cancelled list is a hospital's largest single waste, so the
            reason is a countable one rather than free text.
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
            <Label htmlFor="x-reason">Reason</Label>
            <Select
              id="x-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            >
              {CANCELLATION_REASONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
            {avoidable && (
              <p className="text-xs text-amber-600">
                Counted as avoidable by the hospital — this is the number a
                theatre committee acts on.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="x-notes">Notes</Label>
            <Textarea
              id="x-notes"
              rows={2}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={postpone}
              onChange={(event) => setPostpone(event.target.checked)}
            />
            Postponed rather than cancelled — it will be rebooked
          </label>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Keep it
            </Button>
            <Button
              className="flex-1"
              disabled={busy}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Ban className="h-4 w-4" />
              )}
              {postpone ? "Postpone" : "Cancel"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Implants                                                                    */
/* -------------------------------------------------------------------------- */

function Implants() {
  const [rows, setRows] = useState<ImplantRecord[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    void api
      .get<ImplantRecord[]>("/ot/implants/")
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  const filtered = search.trim()
    ? rows.filter((row) =>
        [row.serial_number, row.batch_number, row.implant, row.patient]
          .join(" ")
          .toLowerCase()
          .includes(search.toLowerCase()),
      )
    : rows;

  return (
    <div className="space-y-4">
      <Alert>
        <ScanLine className="h-4 w-4" />
        <AlertTitle>The recall register</AlertTitle>
        <AlertDescription>
          When a manufacturer issues a recall the question is "which patients
          have one", and the only acceptable answer is a list of names and
          phone numbers. That is the whole reason a serial number is stored.
        </AlertDescription>
      </Alert>

      <Input
        className="max-w-md"
        placeholder="Search by serial, batch, device or patient…"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Patient</TableHead>
                <TableHead>Contact</TableHead>
                <TableHead>Device</TableHead>
                <TableHead>Serial</TableHead>
                <TableHead>Site</TableHead>
                <TableHead>Operated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((row) => (
                <TableRow key={row.serial_number}>
                  <TableCell>
                    <span className="font-medium">{row.patient}</span>
                    <span className="block text-xs text-muted-foreground">
                      {row.mrn} · {row.case}
                    </span>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {row.phone || "—"}
                  </TableCell>
                  <TableCell className="max-w-xs truncate">
                    {row.implant}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {row.serial_number}
                    {row.batch_number && (
                      <span className="block text-muted-foreground">
                        {row.batch_number}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>{row.site || "—"}</TableCell>
                  <TableCell className="text-xs">
                    {row.operated_on
                      ? new Date(row.operated_on).toLocaleDateString()
                      : "—"}
                  </TableCell>
                </TableRow>
              ))}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No implants recorded.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Performance                                                                 */
/* -------------------------------------------------------------------------- */

function Performance({ facility }: { facility: string }) {
  const [theatres, setTheatres] = useState<OperatingTheatre[]>([]);
  const [stats, setStats] = useState<Record<string, TheatreUtilisation>>({});
  const [audit, setAudit] = useState<SafetyAudit | null>(null);

  useEffect(() => {
    if (!facility) return;
    void (async () => {
      const page = await api.get<Paginated<OperatingTheatre>>(
        `/ot/theatres/?facility=${facility}&is_active=true`,
      );
      setTheatres(page.results);
      const rows = await Promise.all(
        page.results.map((room) =>
          api
            .get<TheatreUtilisation>(`/ot/theatres/${room.uuid}/utilisation/`)
            .then((value) => [room.uuid, value] as const),
        ),
      );
      setStats(Object.fromEntries(rows));
      setAudit(
        await api
          .get<SafetyAudit>(`/ot/safety/?facility=${facility}`)
          .catch(() => null),
      );
    })();
  }, [facility]);

  return (
    <div className="space-y-4">
      {audit && (
        <Card
          className={cn(
            audit.incisions_without_a_time_out > 0 && "border-destructive/50",
          )}
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldAlert className="h-4 w-4" />
              Safety
            </CardTitle>
            <CardDescription>
              The number that matters is not how many checklists exist, but how
              many incisions happened without a time-out.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-4">
              <Fact label="Operations" value={String(audit.operations)} />
              <Fact
                label="Without a time-out"
                value={String(audit.incisions_without_a_time_out)}
                tone={
                  audit.incisions_without_a_time_out > 0
                    ? "text-destructive"
                    : undefined
                }
              />
              <Fact
                label="Breach rate"
                value={`${audit.breach_percent}%`}
                tone={audit.breach_percent > 0 ? "text-destructive" : undefined}
              />
              <Fact
                label="Phases skipped"
                value={String(audit.phases_skipped)}
              />
            </div>
            {audit.breaching_cases.length > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">
                To review: {audit.breaching_cases.join(", ")}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {theatres.map((room) => {
        const row = stats[room.uuid];
        if (!row) return null;
        return (
          <Card key={room.uuid}>
            <CardHeader>
              <CardTitle className="text-base">{room.name}</CardTitle>
              <CardDescription>
                {row.from} to {row.to} · {row.cases} cases, {row.completed}{" "}
                completed
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Fact
                  label="Booked"
                  value={
                    row.booked_percent === null
                      ? "—"
                      : `${row.booked_percent}%`
                  }
                  hint={`${row.booked_minutes}m`}
                />
                <Fact
                  label="Used"
                  value={
                    row.used_percent === null ? "—" : `${row.used_percent}%`
                  }
                  hint={`${row.used_minutes}m`}
                />
                <Fact
                  label="Started late"
                  value={String(row.cases_starting_late)}
                  hint={
                    row.average_start_delay_minutes === null
                      ? undefined
                      : `avg ${row.average_start_delay_minutes}m`
                  }
                />
                <Fact
                  label="Cancelled"
                  value={String(row.cancelled)}
                  hint={`${row.avoidable_cancellations} avoidable`}
                  tone={
                    row.avoidable_cancellations > 0
                      ? "text-destructive"
                      : undefined
                  }
                />
              </div>

              {row.booked_percent !== null && row.used_percent !== null && (
                <p className="text-xs text-muted-foreground">
                  Booked and used are reported separately: a room booked to 90%
                  that operates for 60% has an hour a day of late starts and
                  slow turnarounds, and a single utilisation figure would show
                  the same 90% as a room running perfectly.
                </p>
              )}

              {Object.keys(row.cancellation_reasons).length > 0 && (
                <div className="border-t pt-2">
                  <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                    Cancelled because
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(row.cancellation_reasons).map(
                      ([reason, count]) => (
                        <Badge key={reason} variant="outline">
                          {humanise(reason)}: {count}
                        </Badge>
                      ),
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
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

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
