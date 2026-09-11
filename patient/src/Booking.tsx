/**
 * Booking a visit, from the patient's own phone.
 *
 * The portal had a "Book a visit" button and no way to book: the scheduling
 * service has supported online bookings — with a walk-in reserve the portal
 * can never eat into — since the diary was built, and nothing on this side
 * called it.
 *
 * The flow follows how people actually choose: **a day first** (when can I get
 * away), then **who and when** on that day, then one confirmation screen that
 * says exactly what they are agreeing to, the fee included, because an
 * unexpected charge at the counter is the commonest complaint about booked
 * visits. A slot somebody else takes between choosing and confirming comes
 * back as "no longer available" with the day reloaded, not as an error.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarCheck, ChevronLeft, Clock, Loader2, MapPin, Stethoscope } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { dateLeaf, formatLongDate, formatTime, translate as tr, useI18n } from "@/lib/i18n";
import { Alert, AlertDescription, Button, Label, Textarea } from "@/components/primitives";

interface Clinician {
  schedule: string;
  provider: string;
  speciality: string;
  department: string;
  facility: string;
  room: string;
  fee: string;
  minutes: number;
  slots: string[];
}

interface Options {
  date: string;
  days: { date: string; open: number }[];
  clinicians: Clinician[];
  held: number;
  limit: number;
}

interface Booked {
  reference: string;
  when: string;
  provider: string;
  facility: string;
}

const time = (iso: string) => formatTime(iso);
const longDate = (iso: string) => formatLongDate(iso);

const rupees = (value: string) =>
  `NPR ${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

const initials = (name: string) =>
  name
    .replace(/^Dr\.?\s+/i, "")
    .split(/\s+/)
    .map((part) => part.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();

export function BookVisit({
  record,
  onDone,
  onBack,
}: {
  record: string;
  onDone: () => void;
  onBack: () => void;
}) {
  const [day, setDay] = useState<string | null>(null);
  const [options, setOptions] = useState<Options | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [choice, setChoice] = useState<{ clinician: Clinician; slot: string } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [booked, setBooked] = useState<Booked | null>(null);
  useI18n();

  const load = useCallback(
    async (on: string | null) => {
      setProblem(null);
      try {
        const query = new URLSearchParams({ section: "booking" });
        if (on) query.set("date", on);
        if (record) query.set("record", record);
        const result = await api.get<Options>(`/me/?${query.toString()}`);
        setOptions(result);
        setDay(result.date);
      } catch (err) {
        setProblem(err instanceof ApiError ? err.message : "Could not load the diary.");
      }
    },
    [record],
  );

  useEffect(() => {
    void load(null);
  }, [load]);

  const confirm = async () => {
    if (!choice) return;
    setBusy(true);
    setProblem(null);
    try {
      const result = await api.post<Booked>("/me/", {
        action: "book",
        schedule: choice.clinician.schedule,
        when: choice.slot,
        reason,
        record: record || undefined,
      });
      setBooked(result);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setProblem(err instanceof ApiError ? err.message : "Could not book. Please try again.");
      if (code === "slot_unavailable") {
        // Somebody took it in the meantime: show the day as it is now.
        setChoice(null);
        void load(day);
      }
    } finally {
      setBusy(false);
    }
  };

  if (booked) {
    return (
      <div className="space-y-5 text-center">
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-primary/10 text-primary">
          <CalendarCheck className="h-8 w-8" />
        </div>
        <div>
          <p className="text-xl font-semibold">{tr("booking.done")}</p>
          <p className="mt-1 text-muted-foreground">
            {tr("booking.at", { date: longDate(booked.when), time: time(booked.when) })}
          </p>
          <p className="text-muted-foreground">
            {booked.provider} · {booked.facility}
          </p>
        </div>
        <div className="mx-auto max-w-sm rounded-2xl border bg-card p-4 text-left text-sm">
          <p className="font-medium">{tr("booking.before")}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
            <li>{tr("booking.early")}</li>
            <li>{tr("booking.bring")}</li>
            <li>{tr("booking.reference", { ref: booked.reference })}</li>
          </ul>
        </div>
        <Button className="w-full max-w-sm" onClick={onDone}>
          {tr("booking.ok")}
        </Button>
      </div>
    );
  }

  if (choice) {
    return (
      <div className="space-y-5">
        <button
          type="button"
          onClick={() => setChoice(null)}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
          {tr("booking.anotherTime")}
        </button>
        <div className="rounded-3xl border bg-card p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {tr("booking.yourVisit")}
          </p>
          <p className="mt-2 text-lg font-semibold">
            {tr("booking.at", { date: longDate(choice.slot), time: time(choice.slot) })}
          </p>
          <dl className="mt-3 space-y-1.5 text-sm">
            <Fact icon={Stethoscope} label={`${choice.clinician.provider} · ${choice.clinician.speciality}`} />
            <Fact
              icon={MapPin}
              label={`${choice.clinician.facility}${choice.clinician.room ? ` · ${choice.clinician.room}` : ""}`}
            />
            <Fact icon={Clock} label={tr("booking.minutes", { n: choice.clinician.minutes })} />
          </dl>
          <div className="mt-4 flex items-baseline justify-between rounded-2xl bg-muted px-4 py-3">
            <span className="text-sm">{tr("booking.fee")}</span>
            <span className="shrink-0 whitespace-nowrap font-semibold tabular-nums">{rupees(choice.clinician.fee)}</span>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="visit-reason">{tr("booking.reason")}</Label>
          <Textarea
            id="visit-reason"
            rows={3}
            value={reason}
            maxLength={255}
            placeholder={tr("booking.reasonHint")}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
        {problem && (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        <Button className="w-full" size="lg" disabled={busy} onClick={() => void confirm()}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {tr("booking.confirm")}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        {tr("booking.back")}
      </button>
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{tr("booking.title")}</h2>
        {options && (
          <p className="text-sm text-muted-foreground">
            {options.held > 0
              ? tr("booking.held", { n: options.held, limit: options.limit })
              : tr("booking.limit", { limit: options.limit })}
          </p>
        )}
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {!options ? (
        <div className="space-y-3" aria-busy="true">
          <div className="h-20 animate-pulse rounded-2xl bg-muted" />
          <div className="h-40 animate-pulse rounded-3xl bg-muted" />
        </div>
      ) : (
        <>
          <DayStrip days={options.days} value={day} onChange={(value) => void load(value)} />
          {options.clinicians.length === 0 ? (
            <p className="rounded-3xl border bg-card p-6 text-center text-sm text-muted-foreground">
              {tr("booking.noneThisDay")}
            </p>
          ) : (
            <div className="space-y-3">
              {options.clinicians.map((clinician) => (
                <ClinicianSlots
                  key={clinician.schedule}
                  clinician={clinician}
                  onPick={(slot) => setChoice({ clinician, slot })}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DayStrip({
  days,
  value,
  onChange,
}: {
  days: { date: string; open: number }[];
  value: string | null;
  onChange: (date: string) => void;
}) {
  return (
    <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" role="listbox" aria-label="Day">
      {days.map((row) => {
        const leaf = dateLeaf(`${row.date}T12:00:00`);
        const active = row.date === value;
        const closed = row.open === 0;
        return (
          <button
            key={row.date}
            type="button"
            role="option"
            aria-selected={active}
            disabled={closed}
            onClick={() => onChange(row.date)}
            className={cn(
              "flex w-16 shrink-0 flex-col items-center rounded-2xl border px-2 py-2.5 transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : closed
                  ? "cursor-not-allowed bg-muted/40 text-muted-foreground/70"
                  : "bg-card hover:border-primary/50",
            )}
          >
            <span className="text-[11px] font-medium uppercase">
              {leaf.weekday}
            </span>
            <span className="text-lg font-semibold tabular-nums">{leaf.day}</span>
            <span className={cn("text-[10px]", active ? "opacity-90" : "text-muted-foreground")}>
              {closed ? tr("booking.closed") : tr("booking.free", { n: row.open })}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function ClinicianSlots({ clinician, onPick }: { clinician: Clinician; onPick: (slot: string) => void }) {
  const groups = useMemo(() => {
    const morning = clinician.slots.filter((slot) => new Date(slot).getHours() < 12);
    const afternoon = clinician.slots.filter((slot) => new Date(slot).getHours() >= 12);
    return [
      { label: tr("booking.morning"), slots: morning },
      { label: tr("booking.afternoon"), slots: afternoon },
    ].filter((group) => group.slots.length > 0);
  }, [clinician.slots]);

  return (
    <div className="rounded-3xl border bg-card p-4">
      <div className="flex items-start gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
          {initials(clinician.provider)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{clinician.provider}</p>
          <p className="text-sm text-muted-foreground">
            {clinician.speciality}
            {clinician.department && ` · ${clinician.department}`}
          </p>
          <p className="text-xs text-muted-foreground">{clinician.facility}</p>
        </div>
        <span className="shrink-0 whitespace-nowrap text-sm font-semibold tabular-nums">{rupees(clinician.fee)}</span>
      </div>
      {groups.map((group) => (
        <div key={group.label} className="mt-3">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">{group.label}</p>
          <div className="flex flex-wrap gap-2">
            {group.slots.map((slot) => (
              <button
                key={slot}
                type="button"
                onClick={() => onPick(slot)}
                className="rounded-full border px-3 py-1.5 text-sm font-medium tabular-nums transition-colors hover:border-primary hover:bg-primary/5"
              >
                {formatTime(slot, true)}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Fact({ icon: Icon, label }: { icon: typeof Clock; label: string }) {
  return (
    <div className="flex items-center gap-2 text-muted-foreground">
      <Icon className="h-4 w-4 shrink-0" />
      <span className="text-foreground">{label}</span>
    </div>
  );
}
