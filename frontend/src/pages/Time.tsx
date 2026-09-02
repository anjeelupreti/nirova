/**
 * Time: my day, the roster, and who is away.
 *
 * The first tab is **mine**, not the team's, and that ordering is the point.
 * This is the only screen in the product that almost every employee opens —
 * a ward attendant marking in, a nurse checking their shift, a doctor
 * applying for leave — and none of them need the facility's attendance
 * report. Managers get the team tabs; everyone gets the first one.
 *
 * Two things the screen refuses to smooth over.
 *
 * **A check-in with no check-out is shown as unfinished, not as a short
 * day.** They are different facts and payroll treats them differently, so the
 * screen must not blur them into one number.
 *
 * **A leave balance links to the entries behind it.** Somebody disputing
 * their balance is asking *why*, and a single figure cannot answer that.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  CalendarRange,
  CheckCircle2,
  Clock,
  Loader2,
  LogIn,
  LogOut,
  Plane,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AttendanceRecord,
  AttendanceSummary,
  Facility,
  LeaveBalances,
  LeaveCalendarRow,
  LeaveLedgerEntry,
  LeaveRequest,
  LeaveType,
  Paginated,
  RosterEntry,
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

type Tab = "mine" | "roster" | "leave" | "attendance";

const TABS: { id: Tab; label: string; icon: typeof Clock }[] = [
  { id: "mine", label: "My time", icon: Clock },
  { id: "roster", label: "Roster", icon: CalendarRange },
  { id: "leave", label: "Away", icon: Plane },
  { id: "attendance", label: "Attendance", icon: Users },
];

const STATUS_TONE: Record<string, string> = {
  present: "text-emerald-600",
  late: "text-amber-600",
  early_exit: "text-amber-600",
  half_day: "text-amber-600",
  absent: "text-destructive",
  on_leave: "text-sky-600",
  holiday: "text-muted-foreground",
  weekly_off: "text-muted-foreground",
};

const humanise = (value: string) => value.replace(/_/g, " ");

const clock = (value: string | null) =>
  value
    ? new Date(value).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

const today = () => new Date().toISOString().slice(0, 10);
const inDays = (days: number) =>
  new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);

export default function TimePage() {
  const [tab, setTab] = useState<Tab>("mine");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        setFacilities(page.results);
        if (page.results[0]) setFacility(page.results[0].uuid);
      })
      .catch(() => setFacilities([]));
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Time</h1>
          <p className="text-sm text-muted-foreground">
            Your day, the roster, and who is away.
          </p>
        </div>
        {tab !== "mine" && facilities.length > 0 && (
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

      {tab === "mine" && <MyTime />}
      {tab === "roster" && <Roster facility={facility} />}
      {tab === "leave" && <Away facility={facility} />}
      {tab === "attendance" && <TeamAttendance facility={facility} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* My time                                                                     */
/* -------------------------------------------------------------------------- */

function MyTime() {
  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [balances, setBalances] = useState<LeaveBalances | null>(null);
  const [myLeave, setMyLeave] = useState<LeaveRequest[]>([]);
  const [shifts, setShifts] = useState<RosterEntry[]>([]);
  const [noRecord, setNoRecord] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [ledgerFor, setLedgerFor] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [attendance, balance, leave, roster] = await Promise.all([
        api.get<AttendanceRecord[] | null>("/hr/attendance/me/?days=30"),
        api.get<LeaveBalances>("/hr/leave-balance/"),
        api.get<Paginated<LeaveRequest>>("/hr/leave/?mine=true"),
        api.get<Paginated<RosterEntry>>(
          `/hr/roster/?mine=true&from=${today()}&to=${inDays(14)}`,
        ),
      ]);
      // A 204 means the caller has no employee record — a platform admin,
      // legitimately. Not an error, but there is nothing to show.
      if (attendance === null) {
        setNoRecord(true);
        return;
      }
      setRecords(attendance);
      setBalances(balance);
      setMyLeave(leave.results);
      setShifts(roster.results);
      setProblem(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setNoRecord(true);
        return;
      }
      setProblem(err instanceof ApiError ? err.message : "Could not load.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (noRecord) {
    return (
      <Alert>
        <Users className="h-4 w-4" />
        <AlertTitle>You have no employee record</AlertTitle>
        <AlertDescription>
          Attendance and leave hang off the employee record, and not every
          login has one — a platform administrator legitimately does not.
        </AlertDescription>
      </Alert>
    );
  }

  const todaysRecord = records.find((row) => row.date === today());
  const nextShift = shifts.find((row) => row.date >= today());

  const mark = async (direction: "check-in" | "check-out") => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/hr/attendance/${direction}/`, {});
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Today</CardTitle>
            <CardDescription>
              {nextShift
                ? `${nextShift.shift_name}, ${nextShift.starts_at.slice(0, 5)}–${nextShift.ends_at.slice(0, 5)}${
                    nextShift.date === today() ? "" : ` on ${nextShift.date}`
                  }`
                : "No shift rostered."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-6">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  In
                </p>
                <p className="text-2xl font-semibold tabular-nums">
                  {clock(todaysRecord?.checked_in_at ?? null)}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Out
                </p>
                <p className="text-2xl font-semibold tabular-nums">
                  {clock(todaysRecord?.checked_out_at ?? null)}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Worked
                </p>
                <p className="text-2xl font-semibold tabular-nums">
                  {todaysRecord?.worked_hours ?? "0.00"}h
                </p>
              </div>
              {todaysRecord && (
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Status
                  </p>
                  <p
                    className={cn(
                      "text-lg font-medium capitalize",
                      STATUS_TONE[todaysRecord.status],
                    )}
                  >
                    {humanise(todaysRecord.status)}
                    {todaysRecord.late_minutes > 0 &&
                      ` · ${todaysRecord.late_minutes}m late`}
                  </p>
                </div>
              )}

              <div className="ml-auto flex gap-2">
                <Button
                  disabled={busy || Boolean(todaysRecord?.checked_in_at)}
                  onClick={() => void mark("check-in")}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <LogIn className="h-4 w-4" />
                  )}
                  Check in
                </Button>
                <Button
                  variant="outline"
                  disabled={busy || !todaysRecord?.checked_in_at}
                  onClick={() => void mark("check-out")}
                >
                  <LogOut className="h-4 w-4" />
                  Check out
                </Button>
              </div>
            </div>

            {todaysRecord &&
              todaysRecord.checked_in_at &&
              !todaysRecord.checked_out_at && (
                <p className="mt-3 text-sm text-amber-600">
                  Still checked in. An unfinished day is not the same as a short
                  one, and payroll reads them differently.
                </p>
              )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Leave</CardTitle>
            <Button size="sm" onClick={() => setApplying(true)}>
              <Plane className="h-4 w-4" />
              Apply
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {balances?.balances
              .filter((row) => Number(row.entitlement) > 0)
              .map((row) => (
                <button
                  key={row.leave_type}
                  type="button"
                  onClick={() => setLedgerFor(row.leave_type)}
                  className="flex w-full items-baseline justify-between rounded px-1 py-0.5 text-sm hover:bg-muted/60"
                >
                  <span className="text-muted-foreground">
                    {row.leave_type_name}
                  </span>
                  <span className="tabular-nums">
                    <span className="font-medium">{row.available}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      / {row.entitlement}
                    </span>
                    {Number(row.pending) > 0 && (
                      <span className="ml-1 text-amber-600">
                        ({row.pending} pending)
                      </span>
                    )}
                  </span>
                </button>
              ))}
            <p className="pt-1 text-xs text-muted-foreground">
              Tap a balance to see the entries behind it.
            </p>
          </CardContent>
        </Card>
      </div>

      {myLeave.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">My requests</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Dates</TableHead>
                  <TableHead className="text-right">Days</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {myLeave.map((row) => (
                  <TableRow key={row.uuid}>
                    <TableCell className="font-medium">
                      {row.reference}
                    </TableCell>
                    <TableCell>
                      {row.leave_type_name}
                      {row.is_unpaid && (
                        <Badge variant="outline" className="ml-2">
                          unpaid
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.starts_on} → {row.ends_on}
                      <span className="block text-muted-foreground">
                        {row.calendar_days} calendar days
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.working_days}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          row.status === "approved"
                            ? "secondary"
                            : row.status === "rejected" ||
                                row.status === "cancelled"
                              ? "destructive"
                              : "default"
                        }
                      >
                        {humanise(row.status)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Last 30 days</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>In</TableHead>
                <TableHead>Out</TableHead>
                <TableHead className="text-right">Worked</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((row) => (
                <TableRow key={row.uuid}>
                  <TableCell className="tabular-nums">{row.date}</TableCell>
                  <TableCell className="tabular-nums">
                    {clock(row.checked_in_at)}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {clock(row.checked_out_at)}
                    {row.checked_in_at && !row.checked_out_at && (
                      <span className="ml-1 text-xs text-amber-600">
                        unfinished
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.worked_hours}
                    {Number(row.overtime_hours) > 0 && (
                      <span className="text-xs text-emerald-600">
                        {" "}
                        +{row.overtime_hours}
                      </span>
                    )}
                  </TableCell>
                  <TableCell
                    className={cn("capitalize", STATUS_TONE[row.status])}
                  >
                    {humanise(row.status)}
                    {row.is_regularised && (
                      <Badge variant="outline" className="ml-2">
                        corrected
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {records.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    Nothing recorded yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {applying && (
        <ApplyLeave
          onClose={() => setApplying(false)}
          onApplied={() => {
            setApplying(false);
            void load();
          }}
        />
      )}
      {ledgerFor && (
        <LedgerDialog
          leaveType={ledgerFor}
          onClose={() => setLedgerFor(null)}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Applying                                                                    */
/* -------------------------------------------------------------------------- */

function ApplyLeave({
  onClose,
  onApplied,
}: {
  onClose: () => void;
  onApplied: () => void;
}) {
  const [types, setTypes] = useState<LeaveType[]>([]);
  const [balances, setBalances] = useState<LeaveBalances | null>(null);
  const [form, setForm] = useState({
    leave_type: "",
    starts_on: inDays(7),
    ends_on: inDays(8),
    reason: "",
    allow_unpaid: false,
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<LeaveType>>("/hr/leave-types/")
      .then((page) => {
        setTypes(page.results);
        if (page.results[0]) {
          setForm((f) => ({ ...f, leave_type: page.results[0].uuid }));
        }
      })
      .catch(() => undefined);
    void api
      .get<LeaveBalances>("/hr/leave-balance/")
      .then(setBalances)
      .catch(() => undefined);
  }, []);

  const chosen = types.find((t) => t.uuid === form.leave_type);
  const balance = balances?.balances.find(
    (b) => b.leave_type === chosen?.code,
  );

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/hr/leave/", form);
      onApplied();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not submitted.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Apply for leave</CardTitle>
          <CardDescription>
            Weekly offs and public holidays are not deducted — only working
            days are.
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
            <Label htmlFor="l-type">Type</Label>
            <Select
              id="l-type"
              value={form.leave_type}
              onChange={(event) =>
                setForm((f) => ({ ...f, leave_type: event.target.value }))
              }
            >
              {types.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name}
                </option>
              ))}
            </Select>
            {balance && (
              <p className="text-xs text-muted-foreground">
                {balance.available} of {balance.entitlement} days available
                {Number(balance.pending) > 0 &&
                  `, ${balance.pending} already requested`}
                .
              </p>
            )}
            {chosen && chosen.minimum_notice_days > 0 && (
              <p className="text-xs text-muted-foreground">
                Needs {chosen.minimum_notice_days} days' notice.
              </p>
            )}
            {chosen?.requires_document && (
              <p className="text-xs text-amber-600">
                A supporting document is needed beyond{" "}
                {chosen.document_required_after_days} days.
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="l-from">From</Label>
              <Input
                id="l-from"
                type="date"
                value={form.starts_on}
                onChange={(event) =>
                  setForm((f) => ({ ...f, starts_on: event.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="l-to">To</Label>
              <Input
                id="l-to"
                type="date"
                value={form.ends_on}
                onChange={(event) =>
                  setForm((f) => ({ ...f, ends_on: event.target.value }))
                }
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="l-reason">Reason</Label>
            <Textarea
              id="l-reason"
              rows={2}
              value={form.reason}
              onChange={(event) =>
                setForm((f) => ({ ...f, reason: event.target.value }))
              }
            />
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              checked={form.allow_unpaid}
              onChange={(event) =>
                setForm((f) => ({ ...f, allow_unpaid: event.target.checked }))
              }
            />
            <span>
              Take it unpaid if my balance is short
              <span className="block text-xs text-muted-foreground">
                Explicit, because taking leave you have not accrued has a pay
                consequence and should be a decision rather than a surprise.
              </span>
            </span>
          </label>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || form.reason.trim().length < 3}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plane className="h-4 w-4" />
              )}
              Apply
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function LedgerDialog({
  leaveType,
  onClose,
}: {
  leaveType: string;
  onClose: () => void;
}) {
  const [entries, setEntries] = useState<LeaveLedgerEntry[]>([]);

  useEffect(() => {
    void api
      .get<LeaveLedgerEntry[]>("/hr/leave-ledger/")
      .then((rows) => setEntries(rows.filter((r) => r.leave_type_name)))
      .catch(() => setEntries([]));
  }, [leaveType]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Where the balance came from</CardTitle>
          <CardDescription>
            Every movement, in order. The balance is their sum — never a stored
            counter.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Why</TableHead>
                <TableHead className="text-right">Days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((row) => (
                <TableRow key={row.uuid}>
                  <TableCell className="tabular-nums">
                    {row.effective_on}
                  </TableCell>
                  <TableCell className="text-xs">
                    {row.leave_type_name}
                  </TableCell>
                  <TableCell className="text-xs capitalize">
                    {humanise(row.reason)}
                    {row.reference_id && (
                      <span className="block text-muted-foreground">
                        {row.reference_id}
                      </span>
                    )}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-medium tabular-nums",
                      Number(row.days) < 0
                        ? "text-destructive"
                        : "text-emerald-600",
                    )}
                  >
                    {Number(row.days) > 0 ? "+" : ""}
                    {row.days}
                  </TableCell>
                </TableRow>
              ))}
              {entries.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    No entries yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <Button variant="outline" className="w-full" onClick={onClose}>
            Close
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Roster                                                                      */
/* -------------------------------------------------------------------------- */

function Roster({ facility }: { facility: string }) {
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [start, setStart] = useState(today());

  useEffect(() => {
    if (!facility) return;
    const end = new Date(new Date(start).getTime() + 6 * 86_400_000)
      .toISOString()
      .slice(0, 10);
    void api
      .get<Paginated<RosterEntry>>(
        `/hr/roster/?facility=${facility}&from=${start}&to=${end}`,
      )
      .then((page) => setEntries(page.results))
      .catch(() => setEntries([]));
  }, [facility, start]);

  const days = Array.from({ length: 7 }, (_, index) =>
    new Date(new Date(start).getTime() + index * 86_400_000)
      .toISOString()
      .slice(0, 10),
  );
  const people = Array.from(
    new Map(
      entries.map((row) => [row.employee, {
        uuid: row.employee,
        name: row.employee_name,
        code: row.employee_code,
      }]),
    ).values(),
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Label htmlFor="r-start" className="text-sm">
          Week from
        </Label>
        <Input
          id="r-start"
          type="date"
          className="h-9 w-auto"
          value={start}
          onChange={(event) => setStart(event.target.value)}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Roster</CardTitle>
          <CardDescription>
            Saturday is the weekly off. A published roster is one people can
            rely on — a draft is not.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[48rem] border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 bg-background p-2 text-left font-medium">
                  Who
                </th>
                {days.map((day) => {
                  const saturday = new Date(day).getDay() === 6;
                  return (
                    <th
                      key={day}
                      className={cn(
                        "p-2 text-center text-xs font-medium",
                        saturday && "bg-muted/50 text-muted-foreground",
                      )}
                    >
                      {new Date(day).toLocaleDateString([], {
                        weekday: "short",
                      })}
                      <span className="block font-normal">
                        {day.slice(5)}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {people.map((person) => (
                <tr key={person.uuid} className="border-t">
                  <td className="sticky left-0 bg-background p-2">
                    <span className="font-medium">{person.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {person.code}
                    </span>
                  </td>
                  {days.map((day) => {
                    const entry = entries.find(
                      (row) =>
                        row.employee === person.uuid && row.date === day,
                    );
                    const saturday = new Date(day).getDay() === 6;
                    return (
                      <td
                        key={day}
                        className={cn(
                          "p-1 text-center",
                          saturday && "bg-muted/50",
                        )}
                      >
                        {entry ? (
                          <span
                            className={cn(
                              "inline-block rounded px-2 py-1 text-xs",
                              entry.status === "published"
                                ? "bg-primary/10 text-foreground"
                                : "border border-dashed text-muted-foreground",
                            )}
                            title={`${entry.shift_name} ${entry.starts_at.slice(0, 5)}–${entry.ends_at.slice(0, 5)}${
                              entry.status === "draft" ? " (draft)" : ""
                            }`}
                          >
                            {entry.shift_code}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            ·
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {people.length === 0 && (
                <tr>
                  <td
                    colSpan={days.length + 1}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    Nothing rostered this week.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Away                                                                        */
/* -------------------------------------------------------------------------- */

function Away({ facility }: { facility: string }) {
  const [pending, setPending] = useState<LeaveRequest[]>([]);
  const [calendar, setCalendar] = useState<LeaveCalendarRow[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [queue, away] = await Promise.all([
      api.get<Paginated<LeaveRequest>>("/hr/leave/?pending=true"),
      facility
        ? api.get<LeaveCalendarRow[]>(`/hr/leave-calendar/?facility=${facility}`)
        : Promise.resolve([]),
    ]);
    setPending(queue.results);
    setCalendar(away);
  }, [facility]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (request: LeaveRequest, approve: boolean) => {
    setBusy(request.uuid);
    setProblem(null);
    try {
      await api.post(`/hr/leave/${request.reference}/decide/`, {
        approve,
        notes: approve ? "Approved." : "Not approved at this time.",
      });
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Waiting for a decision</CardTitle>
          <CardDescription>
            Nobody approves their own — the check is on the person, at the
            moment of the act.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pending.length === 0 ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              Nothing is waiting.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Who</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Dates</TableHead>
                  <TableHead className="text-right">Days</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pending.map((row) => (
                  <TableRow key={row.uuid}>
                    <TableCell>
                      <span className="font-medium">{row.employee_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {row.reference}
                      </span>
                    </TableCell>
                    <TableCell>
                      {row.leave_type_name}
                      {row.is_unpaid && (
                        <Badge variant="outline" className="ml-1">
                          unpaid
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">
                      {row.starts_on} → {row.ends_on}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.working_days}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs">
                      {row.reason}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy === row.uuid}
                          onClick={() => void decide(row, false)}
                        >
                          Refuse
                        </Button>
                        <Button
                          size="sm"
                          disabled={busy === row.uuid}
                          onClick={() => void decide(row, true)}
                        >
                          {busy === row.uuid ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            "Approve"
                          )}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Who is away</CardTitle>
          <CardDescription>
            The next two months, so a department head can plan against it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {calendar.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Nobody is booked away.
            </p>
          ) : (
            <ul className="divide-y">
              {calendar.map((row) => (
                <li key={row.reference} className="flex items-center gap-3 py-2">
                  <CalendarDays className="h-4 w-4 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {row.employee_name}
                      {row.department && (
                        <span className="font-normal text-muted-foreground">
                          {" "}
                          · {row.department}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {row.leave_type} · {row.starts_on} → {row.ends_on} (
                      {row.working_days} days)
                      {row.delegate && ` · covered by ${row.delegate}`}
                    </p>
                  </div>
                  <Badge
                    variant={
                      row.status === "approved" ? "secondary" : "default"
                    }
                  >
                    {humanise(row.status)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Team attendance                                                             */
/* -------------------------------------------------------------------------- */

function TeamAttendance({ facility }: { facility: string }) {
  const [summary, setSummary] = useState<AttendanceSummary | null>(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    if (!facility) return;
    setDenied(false);
    void api
      .get<AttendanceSummary>(`/hr/attendance-summary/?facility=${facility}`)
      .then(setSummary)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, [facility]);

  if (denied) {
    return (
      <Alert>
        <Users className="h-4 w-4" />
        <AlertTitle>Not visible to you</AlertTitle>
        <AlertDescription>
          Seeing the facility's attendance needs a separate permission from
          marking your own.
        </AlertDescription>
      </Alert>
    );
  }
  if (!summary) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Records
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {summary.records}
            </p>
            <p className="text-xs text-muted-foreground">
              {summary.from} → {summary.to}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Hours worked
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {summary.total_hours}
            </p>
            <p className="text-xs text-muted-foreground">
              {summary.overtime_hours} overtime
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Lateness
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {summary.total_late_minutes}m
            </p>
            <p className="text-xs text-muted-foreground">
              summed, not averaged
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Unfinished days
            </p>
            <p
              className={cn(
                "mt-1 text-2xl font-semibold tabular-nums",
                summary.unclosed_days > 0 && "text-amber-600",
              )}
            >
              {summary.unclosed_days}
            </p>
            <p className="text-xs text-muted-foreground">
              checked in, never out
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">By status</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {Object.entries(summary.by_status).map(([status, count]) => (
            <Badge key={status} variant="outline" className="capitalize">
              {humanise(status)}: {count}
            </Badge>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">By person</CardTitle>
          <CardDescription>
            Sorted by lateness — an average would hide the one person who is
            forty minutes late every day behind twenty who are punctual.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Who</TableHead>
                <TableHead className="text-right">Days</TableHead>
                <TableHead className="text-right">Absent</TableHead>
                <TableHead className="text-right">Late</TableHead>
                <TableHead className="text-right">Overtime</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.by_employee.map((row) => (
                <TableRow key={row.employee__employee_code}>
                  <TableCell>
                    {row.employee__first_name} {row.employee__last_name}
                    <span className="block text-xs text-muted-foreground">
                      {row.employee__employee_code}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.days}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.absent > 0 && "text-destructive",
                    )}
                  >
                    {row.absent}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.late_minutes > 60 && "text-amber-600",
                    )}
                  >
                    {row.late_minutes}m
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.overtime}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
