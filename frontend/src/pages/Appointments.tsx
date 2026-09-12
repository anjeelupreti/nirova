/**
 * The appointment diary: who is booked, when, and where there is still room.
 *
 * **This is the screen that was missing.** Provider schedules, slot generation,
 * capacity, overbooking, walk-in reserve, schedule exceptions, booking with
 * double-book prevention, cancellation with a reason, no-show as distinct from
 * cancellation, follow-up linkage, waiting-time measurement — all of §20 was
 * built and none of it was reachable. A receptionist could not book an
 * appointment, and the only visible symptom was that nobody ever did.
 *
 * **A day, not a month.** A month grid is what people picture when they hear
 * "calendar" and it is the wrong tool at a clinic counter: the question at the
 * desk is always "when can this patient be seen", which is answered by looking
 * at one day's sessions and their remaining room. The date strip moves between
 * days in one click and the month picker is there for the rare booking six
 * weeks out.
 *
 * **Sessions are columns, and a session that is full says so.** Remaining
 * *capacity* is the number shown, not free slot times: with a slot capacity of
 * two, a session of nine slots holding four bookings still has nine slots with
 * room in them, which reads to a receptionist as an empty diary. What they need
 * is how many more patients fit.
 *
 * **Cancelled and no-show appointments stay on the day.** They are struck
 * through rather than removed, because "did that patient come?" is asked the
 * next morning and a diary that silently drops them cannot answer it.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock,
  Plus,
  UserX,
  X,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Appointment,
  Facility,
  Paginated,
  Patient,
  Paginated as Page,
  ScheduleSlots,
  SessionAvailability,
} from "@/types";
import { Page as Shell, PageHeader, Section, ScrollX, StatGrid } from "@/components/ui/layout";
import { EmptyState, TableSkeleton } from "@/components/ui/feedback";
import { StatTile } from "@/components/ui/data";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
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

/* -------------------------------------------------------------------------- */
/* Dates                                                                       */
/* -------------------------------------------------------------------------- */

const iso = (date: Date) => date.toISOString().slice(0, 10);
const today = () => iso(new Date());

function shift(day: string, days: number): string {
  const date = new Date(`${day}T12:00:00`);
  date.setDate(date.getDate() + days);
  return iso(date);
}

/** "Mon 3 Mar", the way a diary is read aloud. */
function readable(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

const clock = (value: string) =>
  new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/**
 * Status → how the row reads.
 *
 * `cancelled` and `no_show` are struck through rather than tinted red: they are
 * not errors, they are what happened, and a diary full of red reads as a diary
 * full of problems.
 */
const STATUS: Record<string, { label: string; className: string }> = {
  // The server's vocabulary, checked against `AppointmentStatus` rather than
  // guessed: a new booking is `scheduled`, not "booked", and a map missing the
  // one status every new appointment has would have shown the raw string on
  // every row of a fresh diary.
  requested: { label: "Requested", className: "text-warning" },
  scheduled: { label: "Scheduled", className: "" },
  confirmed: { label: "Confirmed", className: "" },
  arrived: { label: "Arrived", className: "text-good" },
  in_consultation: { label: "In consultation", className: "text-good" },
  completed: { label: "Completed", className: "text-muted-foreground" },
  cancelled: { label: "Cancelled", className: "text-muted-foreground line-through" },
  no_show: { label: "Did not attend", className: "text-muted-foreground line-through" },
  rescheduled: { label: "Rescheduled", className: "text-muted-foreground line-through" },
};

/** Statuses that no longer hold a slot, and offer no further action. */
const CLOSED = new Set(["cancelled", "no_show", "completed", "rescheduled"]);

/* -------------------------------------------------------------------------- */
/* Screen                                                                      */
/* -------------------------------------------------------------------------- */

export default function AppointmentsPage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [day, setDay] = useState(today());
  const [sessions, setSessions] = useState<SessionAvailability[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const [booking, setBooking] = useState<SessionAvailability | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        setFacilities(page.results);
        if (page.results[0]) setFacility(page.results[0].uuid);
      })
      .catch(() => setFacilities([]));
  }, []);

  const load = useCallback(async () => {
    if (!facility) return;
    setLoading(true);
    // Settled independently: the diary is worth showing without the
    // availability panel, and the availability panel without the diary.
    const [avail, booked] = await Promise.allSettled([
      api.get<{ sessions: SessionAvailability[] }>(
        `/clinical/availability/?facility=${facility}&date=${day}`,
      ),
      api.get<Page<Appointment>>(
        `/clinical/appointments/?facility=${facility}&date=${day}&page_size=200`,
      ),
    ]);
    setSessions(avail.status === "fulfilled" ? avail.value.sessions : []);
    setAppointments(booked.status === "fulfilled" ? booked.value.results : []);
    if (avail.status === "rejected" && booked.status === "rejected") {
      const reason = avail.reason;
      setProblem(reason instanceof ApiError ? reason.message : "Could not load.");
    } else {
      setProblem(null);
    }
    setLoading(false);
  }, [facility, day]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (work: () => Promise<unknown>) => {
    try {
      await work();
      setProblem(null);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    }
  };

  const cancel = (appointment: Appointment) => {
    // A reason is required by the API and rightly so: "why was this cancelled"
    // is the question asked when a patient rings back.
    const reason = window.prompt(
      `Cancel ${appointment.patient_name}'s appointment. Why?`,
    );
    if (!reason || reason.trim().length < 3) return;
    void act(() =>
      api.post(`/clinical/appointments/${appointment.uuid}/cancel/`, {
        reason: reason.trim(),
      }),
    );
  };

  const noShow = (appointment: Appointment) => {
    void act(() =>
      api.post(`/clinical/appointments/${appointment.uuid}/no-show/`, {}),
    );
  };

  /** Appointments grouped by the session they belong to, plus the unassigned. */
  const byProvider = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const appointment of appointments) {
      const key = appointment.provider_uuid || "";
      map.set(key, [...(map.get(key) ?? []), appointment]);
    }
    return map;
  }, [appointments]);

  const counts = useMemo(() => {
    const live = appointments.filter((a) => !CLOSED.has(a.status));
    return {
      booked: live.length,
      arrived: live.filter((a) => a.arrived_at).length,
      missed: appointments.filter((a) => a.status === "no_show").length,
      room: sessions.reduce((total, s) => total + s.remaining_capacity, 0),
    };
  }, [appointments, sessions]);

  return (
    <Shell>
      <PageHeader
        title="Appointments"
        description="Today's bookings and open slots."
        actions={
          <>
            {facilities.length > 1 && (
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
            )}
          </>
        }
      />

      <DateStrip day={day} onChange={setDay} />

      {problem && (
        <Alert variant="destructive">
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <StatGrid>
        <StatTile label="Booked" value={counts.booked} hint={readable(day)} />
        <StatTile label="Arrived" value={counts.arrived} intent="good" />
        <StatTile
          label="Did not attend"
          value={counts.missed}
          intent={counts.missed ? "bad" : "neutral"}
        />
        <StatTile
          label="Room left"
          value={counts.room}
          hint="across every session"
        />
      </StatGrid>

      {loading ? (
        <TableSkeleton rows={5} />
      ) : sessions.length === 0 ? (
        <EmptyState
          illustration="calendar"
          title={`Nobody is holding a session on ${readable(day)}`}
          description={
            "A session comes from a provider schedule — a weekday pattern with " +
            "a start, an end and a slot length. Set one up under Configuration, " +
            "or check whether this day is a holiday or a schedule exception."
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {sessions.map((session) => (
            <SessionColumn
              key={session.schedule_uuid}
              session={session}
              appointments={byProvider.get(session.provider_uuid) ?? []}
              onBook={() => setBooking(session)}
              onCancel={cancel}
              onNoShow={noShow}
            />
          ))}
        </div>
      )}

      <Unassigned
        appointments={byProvider.get("") ?? []}
        onCancel={cancel}
        onNoShow={noShow}
      />

      {booking && (
        <BookDialog
          session={booking}
          day={day}
          facility={facility}
          onClose={() => setBooking(null)}
          onBooked={() => {
            setBooking(null);
            void load();
          }}
        />
      )}
    </Shell>
  );
}

/* -------------------------------------------------------------------------- */
/* The date strip                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Seven days at a time, centred on the chosen one.
 *
 * A week rather than a month because a clinic books days, not months: the
 * common moves are "tomorrow", "next Tuesday" and "same day next week", and all
 * three are one click here. The date field beside it handles the appointment
 * six weeks out without making everybody else scroll a grid.
 */
function DateStrip({
  day,
  onChange,
}: {
  day: string;
  onChange: (day: string) => void;
}) {
  const days = [-3, -2, -1, 0, 1, 2, 3].map((offset) => shift(day, offset));
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        aria-label="Previous day"
        onClick={() => onChange(shift(day, -1))}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>

      <div className="flex flex-wrap gap-1">
        {days.map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => onChange(candidate)}
            className={cn(
              "rounded-md border px-3 py-1.5 text-sm",
              candidate === day
                ? "border-primary bg-primary/10 font-medium"
                : "border-transparent text-muted-foreground hover:border-border",
              candidate === today() && candidate !== day && "text-foreground",
            )}
            aria-current={candidate === day ? "date" : undefined}
          >
            {candidate === today() ? "Today" : readable(candidate)}
          </button>
        ))}
      </div>

      <Button
        variant="outline"
        size="sm"
        aria-label="Next day"
        onClick={() => onChange(shift(day, 1))}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>

      <Input
        type="date"
        aria-label="Date"
        className="h-9 w-auto"
        value={day}
        onChange={(event) => event.target.value && onChange(event.target.value)}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One provider's session                                                      */
/* -------------------------------------------------------------------------- */

function SessionColumn({
  session,
  appointments,
  onBook,
  onCancel,
  onNoShow,
}: {
  session: SessionAvailability;
  appointments: Appointment[];
  onBook: () => void;
  onCancel: (appointment: Appointment) => void;
  onNoShow: (appointment: Appointment) => void;
}) {
  const full = session.remaining_capacity <= 0;
  const ordered = [...appointments].sort((a, b) =>
    a.scheduled_for.localeCompare(b.scheduled_for),
  );

  return (
    <Section
      title={session.provider_name}
      description={[
        session.department,
        session.room && `Room ${session.room}`,
        `${session.start_time.slice(0, 5)}–${session.end_time.slice(0, 5)}`,
      ]
        .filter(Boolean)
        .join(" · ")}
      actions={
        <div className="flex items-center gap-2">
          <Badge variant={full ? "secondary" : "outline"}>
            {session.is_blocked
              ? "Blocked"
              : full
                ? "Full"
                : `${session.remaining_capacity} left`}
          </Badge>
          <Button size="sm" onClick={onBook} disabled={full || session.is_blocked}>
            <Plus className="mr-1 h-4 w-4" />
            Book
          </Button>
        </div>
      }
    >
      <div className="rounded-xl border">
        {ordered.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            Nobody booked yet.{" "}
            {session.next_free
              ? `First free slot is ${clock(session.next_free)}.`
              : ""}
          </p>
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20">Time</TableHead>
                  <TableHead>Patient</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {ordered.map((appointment) => (
                  <AppointmentRow
                    key={appointment.uuid}
                    appointment={appointment}
                    onCancel={onCancel}
                    onNoShow={onNoShow}
                  />
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}
      </div>
    </Section>
  );
}

function AppointmentRow({
  appointment,
  onCancel,
  onNoShow,
}: {
  appointment: Appointment;
  onCancel: (appointment: Appointment) => void;
  onNoShow: (appointment: Appointment) => void;
}) {
  const status = STATUS[appointment.status] ?? {
    label: appointment.status,
    className: "",
  };
  // Nothing more to do with an appointment that is finished or already
  // written off. Offering "cancel" on a completed consultation is offering an
  // action that will be refused.
  const closed = CLOSED.has(appointment.status);

  return (
    <TableRow className={status.className}>
      <TableCell className="tabular-nums">
        {clock(appointment.scheduled_for)}
      </TableCell>
      <TableCell>
        <div className="font-medium">{appointment.patient_name}</div>
        <div className="text-xs text-muted-foreground">
          {appointment.patient_mrn}
          {appointment.reason ? ` · ${appointment.reason}` : ""}
          {appointment.is_follow_up ? " · follow-up" : ""}
        </div>
      </TableCell>
      <TableCell>
        <span className="text-sm">{status.label}</span>
        {appointment.is_overdue && !closed && (
          <span className="ml-2 text-xs text-warning">overdue</span>
        )}
      </TableCell>
      <TableCell className="text-right">
        {!closed && (
          <div className="flex justify-end gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNoShow(appointment)}
              title="Did not attend"
            >
              <UserX className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onCancel(appointment)}
              title="Cancel"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

/**
 * Appointments booked against no provider.
 *
 * Bookable by design — a patient can be given a time at a department without a
 * named doctor — so they need somewhere to appear. Without this they were
 * loaded, counted, and never shown, which is the quietest way for a booking to
 * be lost.
 */
function Unassigned({
  appointments,
  onCancel,
  onNoShow,
}: {
  appointments: Appointment[];
  onCancel: (appointment: Appointment) => void;
  onNoShow: (appointment: Appointment) => void;
}) {
  if (appointments.length === 0) return null;
  return (
    <Section
      title="Without a named provider"
      description="Booked to a department or a time rather than to a person."
    >
      <div className="rounded-xl border">
        <ScrollX>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-20">Time</TableHead>
                <TableHead>Patient</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {appointments.map((appointment) => (
                <AppointmentRow
                  key={appointment.uuid}
                  appointment={appointment}
                  onCancel={onCancel}
                  onNoShow={onNoShow}
                />
              ))}
            </TableBody>
          </Table>
        </ScrollX>
      </div>
    </Section>
  );
}

/* -------------------------------------------------------------------------- */
/* Booking                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Book one patient into one free slot.
 *
 * **The slot times come from the server, not from arithmetic here.** Free slots
 * account for slot capacity, existing bookings, the walk-in reserve held back
 * from online booking, and schedule exceptions. Recomputing any of that in the
 * browser would produce a diary that disagrees with the one the booking service
 * enforces, and the disagreement would only show up as a rejected booking.
 */
function BookDialog({
  session,
  day,
  facility,
  onClose,
  onBooked,
}: {
  session: SessionAvailability;
  day: string;
  facility: string;
  onClose: () => void;
  onBooked: () => void;
}) {
  const [slots, setSlots] = useState<string[]>([]);
  const [slot, setSlot] = useState("");
  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [reason, setReason] = useState("");
  const [followUp, setFollowUp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<ScheduleSlots>(
        `/clinical/schedules/${session.schedule_uuid}/slots/?date=${day}`,
      )
      .then((res) => {
        setSlots(res.free_slots);
        setSlot(res.free_slots[0] ?? "");
      })
      .catch(() => setSlots([]));
  }, [session.schedule_uuid, day]);

  const search = async () => {
    if (term.trim().length < 2) return;
    try {
      const found = await api.get<{ results: Patient[] } | Patient[]>(
        `/clinical/patients/search/?q=${encodeURIComponent(term.trim())}`,
      );
      setMatches(Array.isArray(found) ? found : found.results);
    } catch {
      setMatches([]);
    }
  };

  const book = async () => {
    if (!patient || !slot) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/clinical/appointments/", {
        patient_uuid: patient.uuid,
        facility_uuid: facility,
        scheduled_for: slot,
        schedule_uuid: session.schedule_uuid,
        provider_uuid: session.provider_uuid,
        provider_name: session.provider_name,
        reason: reason.trim(),
        source: "counter",
        is_follow_up: followUp,
      });
      onBooked();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not book.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Book with ${session.provider_name}`}
    >
      <div className="mt-12 w-full max-w-lg space-y-4 rounded-xl border bg-card p-5 shadow-lg">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">
              Book with {session.provider_name}
            </h2>
            <p className="text-sm text-muted-foreground">
              {readable(day)} · {session.remaining_capacity} place
              {session.remaining_capacity === 1 ? "" : "s"} left
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        {problem && (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="appointment-patient">Patient</Label>
          {patient ? (
            <div className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span>
                {patient.full_name}{" "}
                <span className="text-muted-foreground">({patient.mrn})</span>
              </span>
              <Button variant="ghost" size="sm" onClick={() => setPatient(null)}>
                Change
              </Button>
            </div>
          ) : (
            <>
              <div className="flex gap-2">
                <Input
                  id="appointment-patient"
                  value={term}
                  placeholder="Name, MRN, telephone or document number"
                  onChange={(event) => setTerm(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void search();
                    }
                  }}
                />
                <Button variant="outline" onClick={() => void search()}>
                  Find
                </Button>
              </div>
              {matches.length > 0 && (
                <ul className="max-h-40 divide-y overflow-y-auto rounded-md border">
                  {matches.map((match) => (
                    <li key={match.uuid}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm hover:bg-accent"
                        onClick={() => {
                          setPatient(match);
                          setMatches([]);
                        }}
                      >
                        {match.full_name}{" "}
                        <span className="text-muted-foreground">
                          {match.mrn} · {match.phone || "no telephone"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="appointment-slot">Time</Label>
          <Select
            id="appointment-slot"
            value={slot}
            onChange={(event) => setSlot(event.target.value)}
          >
            {slots.length === 0 && <option value="">No free slots</option>}
            {slots.map((value) => (
              <option key={value} value={value}>
                {clock(value)}
              </option>
            ))}
          </Select>
          <p className="text-xs text-muted-foreground">
            <Clock className="mr-1 inline h-3 w-3" />
            Free slots come from the schedule itself — capacity, existing
            bookings and the walk-in reserve are already taken off.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="appointment-reason">Reason</Label>
          <Textarea
            id="appointment-reason"
            rows={2}
            value={reason}
            placeholder="What the visit is for."
            onChange={(event) => setReason(event.target.value)}
          />
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={followUp}
            onChange={(event) => setFollowUp(event.target.checked)}
          />
          This is a follow-up
        </label>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void book()} disabled={!patient || !slot || busy}>
            <CalendarDays className="mr-2 h-4 w-4" />
            Book
          </Button>
        </div>
      </div>
    </div>
  );
}
