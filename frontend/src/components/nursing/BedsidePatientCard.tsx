/**
 * One patient, as the nurse at the bedside needs them.
 *
 * The card this replaced was built from parts that each looked like a
 * dashboard: a monospace bed code, a "NEWS2: 5 [MEDIUM]" pill in brackets and
 * capitals, a gradient wash for risk, three boxed counters, and a pulsing
 * badge. It read as generated, and worse, it read the same whether the
 * patient was fine or not — everything shouted.
 *
 * Every line here answers something a nurse asks at the bedside:
 *
 *  - **Who and where** — bed, name, age and sex, which night. The MRN is
 *    there for the wristband check, not as a headline.
 *  - **How sick, and what that obliges me to do** — NEWS2 with its response
 *    ("Clinician within the hour"), and only when it asks for one; the
 *    parameters that scored, so the escalation call has its numbers ready.
 *  - **Which observation is off** — the value that scored is coloured in the
 *    vitals grid itself, rather than listed again somewhere else.
 *  - **When the next observations are due** — from the RCP minimum frequency
 *    for the score, counting down, and saying so plainly once overdue. This
 *    is the question a nurse carrying six patients asks most often, and it
 *    was not on the screen at all.
 *  - **What else is waiting** — fluid balance, medicines given, open tasks —
 *    as one quiet line, because they are context, not alarms.
 */

import { AlertTriangle, Clock, Droplets, ListTodo, Pill, Send, Stethoscope } from "lucide-react";

import { cn } from "@/lib/utils";
import type { NursePatientCard } from "@/types";
import { Button } from "@/components/ui/primitives";
import { News2Badge, news2Band } from "@/components/clinical/News2";

/** The NEWS2 trigger that scores each vitals cell, by the service's parameter names. */
const PARAMETER = {
  bp: "Systolic BP",
  pulse: "Pulse",
  spo2: "SpO2",
  rr: "Respiration rate",
  temp: "Temperature",
} as const;

/**
 * Minimum observation frequency for a NEWS2 score (RCP 2017, chart 2), in
 * minutes. Seven or more asks for continuous monitoring; an hour is the
 * figure a ward can be held to.
 */
function interval(score: number, extreme: boolean): number {
  if (score >= 5 || extreme) return 60;
  if (score >= 1) return 4 * 60;
  return 12 * 60;
}

function obsDue(recordedAt: string | undefined, score: number, extreme: boolean) {
  if (!recordedAt) return { label: "No observations yet", overdue: true };
  const due = new Date(recordedAt).getTime() + interval(score, extreme) * 60_000;
  const minutes = Math.round((due - Date.now()) / 60_000);
  const at = new Date(due).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (minutes < 0) {
    const late = -minutes;
    return {
      label: `Obs overdue by ${late >= 90 ? `${Math.round(late / 60)} h` : `${late} min`}`,
      overdue: true,
    };
  }
  return { label: `Next obs by ${at}`, overdue: false };
}

const RESPONSE = {
  urgent: "Clinician review within the hour · observe at least hourly",
  emergency: "Emergency response · continuous monitoring",
} as const;

export function BedsidePatientCard({
  patient,
  onObserve,
  onMeds,
  onHandover,
  onTasks,
}: {
  patient: NursePatientCard;
  onObserve: () => void;
  onMeds: () => void;
  onHandover: () => void;
  onTasks: () => void;
}) {
  const { news2, vitals } = patient;
  const hasObs = Boolean(vitals?.recorded_at);
  const band = hasObs ? news2Band(news2.score) : "routine";
  const scored = new Map(news2.triggers.map((row) => [row.parameter, row.score]));
  const due = obsDue(vitals?.recorded_at, news2.score, news2.single_param_extreme);
  const sex = patient.patient_gender === "female" ? "F" : patient.patient_gender === "male" ? "M" : "";
  const facts = [
    patient.patient_age ? `${patient.patient_age}${sex}` : sex,
    `night ${Math.max(1, patient.length_of_stay_days)}`,
    patient.consultant_name,
  ].filter(Boolean);
  const net = patient.fluid_balance_24h.net_ml;
  // The summary sends "MW/MW-01" — ward code, then the bed. The ward is
  // already named on the card; the bed is what is on the door.
  const bed = patient.bed_code.split("/").pop() ?? patient.bed_code;

  return (
    <article
      className={cn(
        "relative flex flex-col overflow-hidden rounded-xl border bg-card shadow-flat",
        band === "emergency" && "border-critical/50",
        band === "urgent" && "border-warning/50",
      )}
      aria-label={`${patient.patient_name}, bed ${bed}`}
    >
      {band !== "routine" && (
        <span
          className={cn("absolute inset-y-0 left-0 w-1", band === "emergency" ? "bg-critical" : "bg-warning")}
          aria-hidden
        />
      )}

      {/* -- who and where ----------------------------------------------- */}
      <header className="flex items-start gap-3 px-4 pb-3 pt-4">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-muted text-center">
          <span className="text-[13px] font-semibold leading-none tabular-nums">
            {bed.split("-").pop()}
          </span>
          <span className="sr-only">bed {bed}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-semibold leading-tight">{patient.patient_name}</h3>
            {patient.is_mine && (
              <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                Yours
              </span>
            )}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {facts.join(" · ")}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {patient.ward_name} · {bed} · {patient.patient_mrn}
          </p>
        </div>
        {hasObs && <News2Badge score={news2.score} recordedAt={vitals?.recorded_at} size="md" />}
      </header>

      <div className="space-y-3 px-4 pb-3">
        <p className="line-clamp-1 text-sm">{patient.admitting_diagnosis || "Diagnosis not yet recorded"}</p>

        {/* -- what the score obliges ------------------------------------- */}
        {band !== "routine" && (
          <div
            className={cn(
              "rounded-lg px-3 py-2 text-xs",
              band === "emergency"
                ? "bg-critical-subtle text-critical-subtle-foreground"
                : "bg-warning-subtle text-warning-subtle-foreground",
            )}
            role="alert"
          >
            <p className="flex items-center gap-1.5 font-semibold">
              <AlertTriangle className="h-3.5 w-3.5" />
              {RESPONSE[band]}
            </p>
            {news2.triggers.length > 0 && (
              <p className="mt-1 opacity-90">
                {news2.triggers
                  .filter((row) => row.score > 0)
                  .map((row) => `${row.parameter} ${row.value} (+${row.score})`)
                  .join(" · ")}
              </p>
            )}
          </div>
        )}

        {/* -- the observations ------------------------------------------ */}
        {vitals ? (
          <dl className="grid grid-cols-3 overflow-hidden rounded-lg border text-center sm:grid-cols-6">
            <Vital label="BP" value={vitals.bp} unit="" points={scored.get(PARAMETER.bp)} />
            <Vital label="Pulse" value={vitals.pulse} unit="/min" points={scored.get(PARAMETER.pulse)} />
            <Vital label="SpO₂" value={vitals.spo2} unit="%" points={scored.get(PARAMETER.spo2)} />
            <Vital label="Resp" value={vitals.rr} unit="/min" points={scored.get(PARAMETER.rr)} />
            <Vital label="Temp" value={vitals.temp} unit="°" points={scored.get(PARAMETER.temp)} />
            <Vital label="Pain" value={vitals.pain} unit="/10" points={vitals.pain !== null && vitals.pain >= 7 ? 2 : 0} />
          </dl>
        ) : (
          <p className="rounded-lg border border-dashed px-3 py-3 text-center text-xs text-muted-foreground">
            No observations recorded for this stay.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className={cn("flex items-center gap-1", due.overdue && "font-medium text-critical")}>
            <Clock className="h-3.5 w-3.5" />
            {due.label}
          </span>
          <span className="flex items-center gap-1" title="Intake minus output, last 24 hours">
            <Droplets className="h-3.5 w-3.5" />
            {net >= 0 ? "+" : ""}
            {net} mL
          </span>
          <span className="flex items-center gap-1" title="Doses given today of the active medicines">
            <Pill className="h-3.5 w-3.5" />
            {patient.emar.active_medicines > 0
              ? `${patient.emar.administrations_today} doses given · ${patient.emar.active_medicines} charted`
              : "No medicines charted"}
          </span>
          {patient.tasks.pending_count > 0 && (
            <span className="flex items-center gap-1 text-foreground">
              <ListTodo className="h-3.5 w-3.5" />
              {patient.tasks.pending_count} task{patient.tasks.pending_count === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>

      {/* -- what to do ------------------------------------------------ */}
      <footer className="mt-auto flex items-center gap-1.5 border-t bg-muted/30 px-3 py-2">
        <Button size="sm" className="h-8" onClick={onObserve}>
          <Stethoscope className="h-3.5 w-3.5" />
          Record obs
        </Button>
        <Button size="sm" variant="ghost" className="h-8" onClick={onMeds}>
          <Pill className="h-3.5 w-3.5" />
          Medicines
        </Button>
        <Button size="sm" variant="ghost" className="h-8" onClick={onTasks}>
          <ListTodo className="h-3.5 w-3.5" />
          Tasks
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-8"
          onClick={onHandover}
          title="SBAR handover"
        >
          <Send className="h-3.5 w-3.5" />
          Handover
        </Button>
      </footer>
    </article>
  );
}

function Vital({
  label,
  value,
  unit,
  points = 0,
}: {
  label: string;
  value: string | number | null;
  unit: string;
  points?: number;
}) {
  return (
    <div
      className={cn(
        "border-b border-r px-1 py-1.5 last:border-r-0 sm:border-b-0 [&:nth-child(3)]:border-r-0 sm:[&:nth-child(3)]:border-r",
        points >= 3 && "bg-critical-subtle",
        points > 0 && points < 3 && "bg-warning-subtle",
      )}
    >
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "text-sm font-semibold tabular-nums",
          points >= 3 && "text-critical",
          points > 0 && points < 3 && "text-warning",
        )}
      >
        {points > 0 && (
          <span className={cn("mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle", points >= 3 ? "bg-critical" : "bg-warning")} aria-label={`scores ${points}`} />
        )}
        {value === null || value === "" ? "—" : value}
        {value !== null && value !== "" && unit && (
          <span className="text-[11px] font-normal text-muted-foreground">{unit}</span>
        )}
      </dd>
    </div>
  );
}
