/**
 * People: who works here, in what job, with what licence, since when.
 *
 * Three things this screen is built around.
 *
 * **A lapsed registration is the headline, not a footnote.** Someone whose
 * council registration has expired may not treat patients, and the person
 * looking at this screen is usually the only one who will notice before an
 * audit does. So it is a banner on the profile, a badge in the directory, and
 * the first card on the overview — not a date in a table somebody has to
 * read.
 *
 * **History is shown as a timeline, because that is what it is.** A transfer
 * writes an event rather than overwriting a field, and the screen shows the
 * chain: joined here, moved there, promoted then. A profile that only showed
 * the current posting would throw away the reason the data is modelled this
 * way.
 *
 * **Pay is behind its own permission and its own tab.** Most people who need
 * the directory need none of the payroll, so a 403 on the contracts tab is an
 * expected answer that hides the tab rather than an error that breaks the
 * page.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  BadgeCheck,
  Ban,
  Briefcase,
  Building2,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  GraduationCap,
  History,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  UserMinus,
  UserPlus,
  Users,
  Wallet,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Credential,
  Employee,
  EmployeeSummary,
  EmploymentContract,
  EmploymentEvent,
  Facility,
  HrDashboard,
  Paginated,
  Position,
  PracticeStatus,
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

type Tab = "overview" | "directory" | "positions";

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: "overview", label: "Overview", icon: ClipboardCheck },
  { id: "directory", label: "Directory", icon: Users },
  { id: "positions", label: "Positions", icon: Briefcase },
];

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const humanise = (value: string) => value.replace(/_/g, " ");

export default function PeoplePage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .catch(() => setFacilities([]));
  }, []);

  if (selected) {
    return (
      <EmployeeProfile
        employeeCode={selected}
        onBack={() => setSelected(null)}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">People</h1>
          <p className="text-sm text-muted-foreground">
            The workforce, the jobs, and who may practise.
          </p>
        </div>
        <Select
          className="h-9 w-auto"
          aria-label="Facility"
          value={facility}
          onChange={(event) => setFacility(event.target.value)}
        >
          <option value="">All facilities</option>
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

      {tab === "overview" && (
        <Overview facility={facility} onOpen={setSelected} />
      )}
      {tab === "directory" && (
        <Directory facility={facility} onOpen={setSelected} />
      )}
      {tab === "positions" && <Positions facility={facility} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Overview                                                                    */
/* -------------------------------------------------------------------------- */

function Overview({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (code: string) => void;
}) {
  const [data, setData] = useState<HrDashboard | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const query = facility ? `?facility=${facility}` : "";
        setData(await api.get<HrDashboard>(`/hr/dashboard/${query}`));
        setProblem(null);
      } catch (err) {
        setProblem(
          err instanceof ApiError ? err.message : "Could not load the overview.",
        );
      }
    })();
  }, [facility]);

  if (problem) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    );
  }
  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const { headcount, expiring_credentials: expiring } = data;
  const blocking = expiring.filter((row) => row.blocks_practice);

  return (
    <div className="space-y-4">
      {/*
        Blocked practice first. This is the one thing on the screen that stops
        somebody being allowed to work, and burying it under headcount would
        mean nobody sees it until an audit does.
      */}
      {blocking.length > 0 && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>
            {blocking.length} {blocking.length === 1 ? "person" : "people"} may
            not treat patients
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-1 space-y-1">
              {blocking.map((row) => (
                <li key={row.credential}>
                  <button
                    type="button"
                    className="underline underline-offset-2"
                    onClick={() => onOpen(row.employee_code)}
                  >
                    {row.employee_name}
                  </button>
                  {" — "}
                  {row.name}{" "}
                  {row.is_expired
                    ? `expired ${Math.abs(row.days_to_expiry)} days ago`
                    : "has never been verified"}
                  .
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="On the books" value={String(headcount.total)} />
        <Stat
          label="Posts filled"
          value={`${headcount.filled} of ${headcount.budgeted}`}
          hint={`${headcount.vacancies} vacant`}
        />
        <Stat
          label="On probation"
          value={String(headcount.on_probation)}
          hint={
            headcount.probation_overdue > 0
              ? `${headcount.probation_overdue} past their date`
              : undefined
          }
          tone={headcount.probation_overdue > 0 ? "text-amber-600" : undefined}
        />
        <Stat
          label="Turnover"
          value={`${data.separations.turnover_percent_of_current_headcount}%`}
          hint={`${data.separations.total} left in 12 months`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Expiring credentials</CardTitle>
            <CardDescription>
              Ninety days ahead — long enough to renew a council registration,
              which is the binding constraint.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {expiring.length === 0 ? (
              <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                Nothing lapses in the next three months.
              </div>
            ) : (
              <ul className="divide-y">
                {expiring.map((row) => (
                  <li
                    key={row.credential}
                    className="flex items-center gap-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        className="truncate text-sm font-medium hover:underline"
                        onClick={() => onOpen(row.employee_code)}
                      >
                        {row.employee_name}
                      </button>
                      <p className="truncate text-xs text-muted-foreground">
                        {row.name}
                        {row.position && ` · ${row.position}`}
                      </p>
                    </div>
                    <Badge
                      variant={
                        row.is_expired
                          ? "destructive"
                          : row.days_to_expiry < 30
                            ? "default"
                            : "secondary"
                      }
                    >
                      {row.is_expired
                        ? "expired"
                        : `${row.days_to_expiry}d`}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Vacancies</CardTitle>
            <CardDescription>
              Budgeted headcount minus the people in post. Counting employees
              can never tell you how many you are short.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {headcount.vacant_positions.length === 0 ? (
              <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                Every budgeted post is filled.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Position</TableHead>
                    <TableHead className="text-right">Filled</TableHead>
                    <TableHead className="text-right">Short</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {headcount.vacant_positions.map((row) => (
                    <TableRow key={row.code}>
                      <TableCell>{row.title}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.filled} / {row.budgeted}
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums text-amber-600">
                        {row.vacancies}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {data.expiring_contracts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Contracts running out</CardTitle>
            <CardDescription>
              A contract that lapses unnoticed means somebody is working with
              no terms.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Employee</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Ends</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.expiring_contracts.map((row) => (
                  <TableRow key={row.contract}>
                    <TableCell>
                      <button
                        type="button"
                        className="font-medium hover:underline"
                        onClick={() => onOpen(row.employee_code)}
                      >
                        {row.employee_name}
                      </button>
                    </TableCell>
                    <TableCell>{row.employment_type}</TableCell>
                    <TableCell
                      className={cn(row.is_expired && "text-destructive")}
                    >
                      {row.ends_on}
                      <span className="block text-xs">
                        {row.is_expired
                          ? "already lapsed"
                          : `${row.days_to_expiry} days`}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.gross_monthly)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

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
        <p className={cn("mt-1 text-2xl font-semibold tabular-nums", tone)}>
          {value}
        </p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Directory                                                                   */
/* -------------------------------------------------------------------------- */

function Directory({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (code: string) => void;
}) {
  const [rows, setRows] = useState<EmployeeSummary[]>([]);
  const [search, setSearch] = useState("");
  const [includeSeparated, setIncludeSeparated] = useState(false);
  const [hiring, setHiring] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (facility) params.set("facility", facility);
      if (search) params.set("search", search);
      if (includeSeparated) params.set("include_separated", "true");
      const page = await api.get<Paginated<EmployeeSummary>>(
        `/hr/employees/?${params}`,
      );
      setRows(page.results);
    } finally {
      setLoading(false);
    }
  }, [facility, search, includeSeparated]);

  useEffect(() => {
    const handle = window.setTimeout(() => void load(), 200);
    return () => window.clearTimeout(handle);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          className="h-9 max-w-xs"
          placeholder="Name, code, phone or email…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={includeSeparated}
            onChange={(event) => setIncludeSeparated(event.target.checked)}
          />
          Include people who have left
        </label>
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => setHiring(true)}
        >
          <UserPlus className="h-4 w-4" />
          Hire
        </Button>
      </div>

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Position</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Since</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={row.uuid}
                  className="cursor-pointer"
                  onClick={() => onOpen(row.employee_code)}
                >
                  <TableCell>
                    <span className="font-medium">{row.full_name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {row.employee_code}
                      {row.phone && ` · ${row.phone}`}
                    </span>
                  </TableCell>
                  <TableCell>
                    {row.position_title || "—"}
                    {row.is_provider && (
                      <Badge variant="secondary" className="ml-2">
                        Provider
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{row.department_name || "—"}</TableCell>
                  <TableCell className="capitalize">
                    {humanise(row.employment_type)}
                  </TableCell>
                  <TableCell className="tabular-nums">{row.joined_on}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        row.status === "active"
                          ? "secondary"
                          : row.status === "separated" ||
                              row.status === "suspended"
                            ? "destructive"
                            : "outline"
                      }
                    >
                      {humanise(row.status)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && !loading && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    Nobody matches.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {loading && (
            <p className="py-4 text-center text-sm text-muted-foreground">
              <Loader2 className="inline h-4 w-4 animate-spin" />
            </p>
          )}
        </CardContent>
      </Card>

      {hiring && (
        <HireDialog
          facility={facility}
          onClose={() => setHiring(false)}
          onHired={(code) => {
            setHiring(false);
            onOpen(code);
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Hiring                                                                      */
/* -------------------------------------------------------------------------- */

function HireDialog({
  facility,
  onClose,
  onHired,
}: {
  facility: string;
  onClose: () => void;
  onHired: (employeeCode: string) => void;
}) {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [form, setForm] = useState({
    facility,
    first_name: "",
    last_name: "",
    position: "",
    employment_type: "permanent",
    probation_days: "0",
    phone: "",
    personal_email: "",
    joined_on: new Date().toISOString().slice(0, 10),
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        setFacilities(page.results);
        if (!form.facility && page.results[0]) {
          setForm((f) => ({ ...f, facility: page.results[0].uuid }));
        }
      })
      .catch(() => undefined);
    void api
      .get<Paginated<Position>>("/hr/positions/?is_active=true")
      .then((page) => setPositions(page.results))
      .catch(() => undefined);
    // Loaded once: the lists are small and do not change while a form is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chosen = positions.find((p) => p.uuid === form.position);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const created = await api.post<Employee>("/hr/employees/", {
        ...form,
        position: form.position || null,
        probation_days: Number(form.probation_days) || 0,
      });
      onHired(created.employee_code);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not hired.");
    } finally {
      setBusy(false);
    }
  };

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Hire</CardTitle>
          <CardDescription>
            Creates the employee record and opens their history. A login is a
            separate, later step — most people never need one.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="h-first">First name</Label>
              <Input
                id="h-first"
                value={form.first_name}
                onChange={set("first_name")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="h-last">Last name</Label>
              <Input
                id="h-last"
                value={form.last_name}
                onChange={set("last_name")}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="h-facility">Facility</Label>
            <Select
              id="h-facility"
              value={form.facility}
              onChange={set("facility")}
            >
              {facilities.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="h-position">Position</Label>
            <Select
              id="h-position"
              value={form.position}
              onChange={set("position")}
            >
              <option value="">Not assigned yet</option>
              {positions.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.title}
                  {row.vacancies > 0
                    ? ` — ${row.vacancies} vacant`
                    : " — fully staffed"}
                </option>
              ))}
            </Select>
            {chosen?.requires_licence && (
              <p className="text-xs text-amber-600">
                This position needs a professional registration. Until one is
                recorded and verified, they cannot treat patients.
              </p>
            )}
            {chosen && chosen.vacancies === 0 && (
              <p className="text-xs text-muted-foreground">
                {chosen.title} is budgeted for {chosen.budgeted_headcount} and
                all are filled. Hiring here puts you over headcount, which is
                allowed and worth knowing.
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="h-type">Employment type</Label>
              <Select
                id="h-type"
                value={form.employment_type}
                onChange={set("employment_type")}
              >
                {[
                  "permanent",
                  "probation",
                  "contract",
                  "locum",
                  "visiting",
                  "intern",
                  "trainee",
                  "part_time",
                  "daily_wage",
                ].map((value) => (
                  <option key={value} value={value}>
                    {humanise(value)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="h-probation">Probation (days)</Label>
              <Input
                id="h-probation"
                inputMode="numeric"
                value={form.probation_days}
                onChange={set("probation_days")}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="h-joined">Joining date</Label>
              <Input
                id="h-joined"
                type="date"
                value={form.joined_on}
                onChange={set("joined_on")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="h-phone">Phone</Label>
              <Input id="h-phone" value={form.phone} onChange={set("phone")} />
            </div>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || !form.first_name || !form.last_name}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              Hire
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Profile                                                                     */
/* -------------------------------------------------------------------------- */

type ProfileTab = "record" | "credentials" | "history" | "pay";

function EmployeeProfile({
  employeeCode,
  onBack,
}: {
  employeeCode: string;
  onBack: () => void;
}) {
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [practice, setPractice] = useState<PracticeStatus | null>(null);
  const [tab, setTab] = useState<ProfileTab>("record");
  const [problem, setProblem] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [record, status] = await Promise.all([
        api.get<Employee>(`/hr/employees/${employeeCode}/`),
        api.get<PracticeStatus>(
          `/hr/employees/${employeeCode}/practice-status/`,
        ),
      ]);
      setEmployee(record);
      setPractice(status);
      setProblem(null);
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "Could not load the record.",
      );
    }
  }, [employeeCode]);

  useEffect(() => {
    void load();
  }, [load]);

  if (problem) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          ← Back
        </Button>
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      </div>
    );
  }
  if (!employee) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const tabs: { id: ProfileTab; label: string; icon: typeof Users }[] = [
    { id: "record", label: "Record", icon: Users },
    { id: "credentials", label: "Credentials", icon: ShieldCheck },
    { id: "history", label: "History", icon: History },
    { id: "pay", label: "Pay", icon: Wallet },
  ];

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Everyone
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {employee.full_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {employee.employee_code} · {employee.position_title || "no position"}
            {employee.department_name && ` · ${employee.department_name}`} ·{" "}
            {employee.facility_name}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setMoving(true)}>
            <ArrowRightLeft className="h-4 w-4" />
            Transfer
          </Button>
          {employee.status !== "separated" && (
            <Button variant="outline" size="sm" onClick={() => setLeaving(true)}>
              <UserMinus className="h-4 w-4" />
              End employment
            </Button>
          )}
        </div>
      </div>

      {/* Practice status is the loudest thing on the page when it is bad. */}
      {practice?.is_provider && !practice.may_practise && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>May not treat patients</AlertTitle>
          <AlertDescription>
            <ul className="space-y-1">
              {practice.blockers.map((blocker) => (
                <li key={blocker.code}>{blocker.message}</li>
              ))}
            </ul>
            Prescribing and scheduling are refused until this is resolved.
          </AlertDescription>
        </Alert>
      )}

      {employee.probation_overdue && (
        <Alert>
          <CalendarClock className="h-4 w-4" />
          <AlertTitle>Probation ended without a decision</AlertTitle>
          <AlertDescription>
            Probation ran to {employee.probation_ends_on} and nobody has
            confirmed or terminated. That leaves the employment status legally
            ambiguous.
          </AlertDescription>
        </Alert>
      )}

      {employee.status === "separated" && (
        <Alert>
          <Ban className="h-4 w-4" />
          <AlertTitle>Left on {employee.separated_on}</AlertTitle>
          <AlertDescription>
            {employee.separation_reason} The record is kept because everything
            they did still points at it.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex gap-1 border-b">
        {tabs.map(({ id, label, icon: Icon }) => (
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

      {tab === "record" && <RecordTab employee={employee} />}
      {tab === "credentials" && (
        <CredentialsTab employee={employee} onChanged={load} />
      )}
      {tab === "history" && <HistoryTab employeeCode={employeeCode} />}
      {tab === "pay" && <PayTab employeeCode={employeeCode} />}

      {moving && (
        <TransferDialog
          employee={employee}
          onClose={() => setMoving(false)}
          onMoved={() => {
            setMoving(false);
            void load();
          }}
        />
      )}
      {leaving && (
        <SeparateDialog
          employee={employee}
          onClose={() => setLeaving(false)}
          onDone={() => {
            setLeaving(false);
            void load();
          }}
        />
      )}
    </div>
  );
}

function RecordTab({ employee }: { employee: Employee }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Employment</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Field label="Type" value={humanise(employee.employment_type)} />
          <Field label="Status" value={humanise(employee.status)} />
          <Field label="Joined" value={employee.joined_on} />
          <Field label="Service" value={`${employee.years_of_service} years`} />
          {employee.probation_ends_on && (
            <Field
              label="Probation to"
              value={employee.probation_ends_on}
              tone={employee.probation_overdue ? "text-amber-600" : undefined}
            />
          )}
          {employee.confirmed_on && (
            <Field label="Confirmed" value={employee.confirmed_on} />
          )}
          <Field label="Reports to" value={employee.manager_name || "—"} />
          <Field
            label="Login"
            value={employee.work_email || "no account"}
            tone={employee.work_email ? undefined : "text-muted-foreground"}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Contact</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Field label="Phone" value={employee.phone || "—"} />
          <Field label="Email" value={employee.personal_email || "—"} />
          <Field
            label="Address"
            value={
              [employee.municipality, employee.district, employee.province]
                .filter(Boolean)
                .join(", ") || "—"
            }
          />
          <Field label="Blood group" value={employee.blood_group || "—"} />
          <div className="border-t pt-2">
            <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
              In an emergency
            </p>
            <Field
              label={employee.emergency_contact_relation || "Contact"}
              value={
                employee.emergency_contact_name
                  ? `${employee.emergency_contact_name} · ${employee.emergency_contact_phone}`
                  : "not recorded"
              }
              tone={
                employee.emergency_contact_name
                  ? undefined
                  : "text-amber-600"
              }
            />
          </div>
        </CardContent>
      </Card>

      {employee.experience.length > 0 && (
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Before here</CardTitle>
            <CardDescription>
              Seniority and locum rates are argued from this, so an unverified
              claim is worth showing as one.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Role</TableHead>
                  <TableHead>Organization</TableHead>
                  <TableHead>Period</TableHead>
                  <TableHead className="text-right">Years</TableHead>
                  <TableHead>Checked</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {employee.experience.map((row) => (
                  <TableRow key={row.uuid}>
                    <TableCell className="font-medium">
                      {row.job_title}
                    </TableCell>
                    <TableCell>{row.organization_name}</TableCell>
                    <TableCell className="text-xs">
                      {row.started_on} → {row.ended_on ?? "present"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.years}
                    </TableCell>
                    <TableCell>
                      {row.is_verified ? (
                        <Badge variant="secondary">verified</Badge>
                      ) : (
                        <Badge variant="outline">claimed</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {employee.skills.length > 0 && (
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Skills</CardTitle>
            <CardDescription>
              What this organization has assessed — distinct from paper
              somebody else issued. Rostering needs this one.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {employee.skills.map((skill) => (
              <Badge key={skill.uuid} variant="secondary">
                {skill.name} · {skill.level}
              </Badge>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("text-right", tone)}>{value}</span>
    </div>
  );
}

function CredentialsTab({
  employee,
  onChanged,
}: {
  employee: Employee;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const verify = async (credential: Credential, passed: boolean) => {
    setBusy(credential.uuid);
    setProblem(null);
    try {
      await api.post(`/hr/credentials/${credential.uuid}/verify/`, {
        passed,
        notes: passed
          ? "Checked against the issuing register."
          : "Not found on the issuing register.",
      });
      await onChanged();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not recorded.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {employee.credentials.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            <GraduationCap className="mx-auto mb-2 h-8 w-8 opacity-40" />
            No credentials recorded.
          </CardContent>
        </Card>
      ) : (
        employee.credentials.map((credential) => (
          <Card
            key={credential.uuid}
            className={cn(
              credential.blocks_practice &&
                "border-destructive/50 bg-destructive/5",
            )}
          >
            <CardContent className="flex flex-wrap items-start gap-4 pt-6">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{credential.name}</span>
                  <Badge variant="outline">
                    {humanise(credential.credential_type)}
                  </Badge>
                  {credential.verification_status === "verified" && (
                    <Badge variant="secondary">
                      <BadgeCheck className="mr-1 h-3 w-3" />
                      verified
                    </Badge>
                  )}
                  {credential.verification_status === "failed" && (
                    <Badge variant="destructive">verification failed</Badge>
                  )}
                  {credential.verification_status === "unverified" && (
                    <Badge variant="outline">never checked</Badge>
                  )}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {credential.issuing_body}
                  {credential.reference_number &&
                    ` · ${credential.reference_number}`}
                </p>
                {credential.expires_on && (
                  <p
                    className={cn(
                      "text-sm",
                      credential.is_expired
                        ? "font-medium text-destructive"
                        : "text-muted-foreground",
                    )}
                  >
                    {credential.is_expired
                      ? `Expired ${credential.expires_on}`
                      : `Expires ${credential.expires_on} — ${credential.days_to_expiry} days`}
                  </p>
                )}
                {credential.verified_by_name && (
                  <p className="text-xs text-muted-foreground">
                    Checked by {credential.verified_by_name}
                    {credential.verification_notes &&
                      ` — ${credential.verification_notes}`}
                  </p>
                )}
              </div>

              {credential.verification_status === "unverified" && (
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy === credential.uuid}
                    onClick={() => void verify(credential, false)}
                  >
                    Not found
                  </Button>
                  <Button
                    size="sm"
                    disabled={busy === credential.uuid}
                    onClick={() => void verify(credential, true)}
                  >
                    {busy === credential.uuid ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <BadgeCheck className="h-4 w-4" />
                    )}
                    Verify
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        ))
      )}

      <p className="text-xs text-muted-foreground">
        Verification is a separate act from recording the claim, and nobody may
        verify their own — self-verification is how a forged registration
        survives in a hospital.
      </p>
    </div>
  );
}

function HistoryTab({ employeeCode }: { employeeCode: string }) {
  const [events, setEvents] = useState<EmploymentEvent[]>([]);

  useEffect(() => {
    void api
      .get<EmploymentEvent[]>(`/hr/employees/${employeeCode}/history/`)
      .then(setEvents)
      .catch(() => setEvents([]));
  }, [employeeCode]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Employment history</CardTitle>
        <CardDescription>
          Append-only. A transfer writes an event rather than overwriting the
          posting, so "where did they work last March?" stays answerable.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="relative space-y-6 border-l pl-6">
          {events.map((event) => (
            <li key={event.uuid} className="relative">
              <span className="absolute -left-[1.65rem] top-1 flex h-3 w-3 items-center justify-center rounded-full border-2 border-background bg-primary" />
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium capitalize">
                  {humanise(event.event_type)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {event.effective_on}
                </span>
              </div>
              <p className="text-sm">{event.summary}</p>
              {event.reason && (
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {event.reason}
                </p>
              )}
              {event.approved_by_name && (
                <p className="text-xs text-muted-foreground">
                  Approved by {event.approved_by_name}
                </p>
              )}
            </li>
          ))}
          {events.length === 0 && (
            <li className="text-sm text-muted-foreground">No events yet.</li>
          )}
        </ol>
      </CardContent>
    </Card>
  );
}

function PayTab({ employeeCode }: { employeeCode: string }) {
  const [data, setData] = useState<{
    current: EmploymentContract | null;
    history: EmploymentContract[];
  } | null>(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    void api
      .get<{ current: EmploymentContract | null; history: EmploymentContract[] }>(
        `/hr/employees/${employeeCode}/contracts/`,
      )
      .then(setData)
      .catch((err) => {
        // 403 is an expected answer here, not a failure: pay sits behind its
        // own permission and most people who need the directory need none of
        // the payroll.
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, [employeeCode]);

  if (denied) {
    return (
      <Alert>
        <Ban className="h-4 w-4" />
        <AlertTitle>Pay is not visible to you</AlertTitle>
        <AlertDescription>
          Viewing salaries needs a separate permission from viewing the
          directory.
        </AlertDescription>
      </Alert>
    );
  }
  if (!data) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="space-y-4">
      {data.current ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Current terms</CardTitle>
            <CardDescription>
              From {data.current.starts_on}
              {data.current.ends_on && ` to ${data.current.ends_on}`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Field label="Basic" value={rupees(data.current.basic_salary)} />
            {Object.entries(data.current.allowances ?? {}).map(
              ([name, value]) => (
                <Field
                  key={name}
                  label={humanise(name)}
                  value={rupees(value)}
                />
              ),
            )}
            <div className="flex justify-between border-t pt-2 font-medium">
              <span>Gross monthly</span>
              <span className="tabular-nums">
                {rupees(data.current.gross_monthly)}
              </span>
            </div>
            <Field
              label="Notice"
              value={`${data.current.notice_period_days} days`}
            />
            <Field
              label="Hours"
              value={`${data.current.working_hours_per_week} a week`}
            />
          </CardContent>
        </Card>
      ) : (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>No contract in force</AlertTitle>
          <AlertDescription>
            Somebody is working with no recorded terms. That is both a legal
            exposure and, in practice, how people end up unpaid.
          </AlertDescription>
        </Alert>
      )}

      {data.history.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Previous terms</CardTitle>
            <CardDescription>
              Superseded, never edited — last year's payslips have to stay
              explicable.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>From</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Gross</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.history.map((row) => (
                  <TableRow key={row.uuid}>
                    <TableCell className="tabular-nums">
                      {row.starts_on}
                    </TableCell>
                    <TableCell>{humanise(row.employment_type)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.gross_monthly)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          row.status === "active" ? "secondary" : "outline"
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
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Movement                                                                    */
/* -------------------------------------------------------------------------- */

function TransferDialog({
  employee,
  onClose,
  onMoved,
}: {
  employee: Employee;
  onClose: () => void;
  onMoved: () => void;
}) {
  const [positions, setPositions] = useState<Position[]>([]);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [position, setPosition] = useState("");
  const [facility, setFacility] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<Position>>("/hr/positions/?is_active=true")
      .then((page) => setPositions(page.results))
      .catch(() => undefined);
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .catch(() => undefined);
  }, []);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/hr/employees/${employee.employee_code}/transfer/`, {
        reason,
        position: position || null,
        facility: facility || null,
      });
      onMoved();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not moved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Move {employee.full_name}</CardTitle>
          <CardDescription>
            The old posting is kept in the history rather than overwritten.
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
            <Label htmlFor="t-position">New position</Label>
            <Select
              id="t-position"
              value={position}
              onChange={(event) => setPosition(event.target.value)}
            >
              <option value="">Unchanged ({employee.position_title})</option>
              {positions
                .filter((row) => row.uuid !== employee.position)
                .map((row) => (
                  <option key={row.uuid} value={row.uuid}>
                    {row.title}
                  </option>
                ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="t-facility">New facility</Label>
            <Select
              id="t-facility"
              value={facility}
              onChange={(event) => setFacility(event.target.value)}
            >
              <option value="">Unchanged ({employee.facility_name})</option>
              {facilities
                .filter((row) => row.uuid !== employee.facility)
                .map((row) => (
                  <option key={row.uuid} value={row.uuid}>
                    {row.name}
                  </option>
                ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="t-reason">Why</Label>
            <Textarea
              id="t-reason"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Completion of specialist training and two years' service."
            />
            <p className="text-xs text-muted-foreground">
              A position change is filed as a promotion, a facility change as a
              transfer. The system decides from what actually changed, so a
              promotion cannot be mislabelled.
            </p>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={
                busy || reason.trim().length < 5 || (!position && !facility)
              }
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowRightLeft className="h-4 w-4" />
              )}
              Move
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SeparateDialog({
  employee,
  onClose,
  onDone,
}: {
  employee: Employee;
  onClose: () => void;
  onDone: () => void;
}) {
  const [eventType, setEventType] = useState("resignation");
  const [reason, setReason] = useState("");
  const [lastDay, setLastDay] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/hr/employees/${employee.employee_code}/separate/`, {
        reason,
        event_type: eventType,
        last_working_day: lastDay,
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
          <CardTitle>End {employee.full_name}'s employment</CardTitle>
          <CardDescription>
            The record is kept. Everything they did — prescriptions written,
            stock adjusted, refunds approved — still points at it.
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
            <Label htmlFor="s-type">How</Label>
            <Select
              id="s-type"
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
            >
              <option value="resignation">Resigned</option>
              <option value="termination">Terminated</option>
              <option value="retirement">Retired</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              Recorded distinctly because a board asks how many resigned versus
              how many were let go, and free text cannot be counted.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="s-day">Last working day</Label>
            <Input
              id="s-day"
              type="date"
              value={lastDay}
              onChange={(event) => setLastDay(event.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="s-reason">Reason</Label>
            <Textarea
              id="s-reason"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>

          <Alert>
            <Building2 className="h-4 w-4" />
            <AlertDescription>
              Their login is not revoked here. That is a separate, deliberate
              act — and doing it silently would lock somebody out mid-handover.
            </AlertDescription>
          </Alert>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || reason.trim().length < 5}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserMinus className="h-4 w-4" />
              )}
              Confirm
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Positions                                                                   */
/* -------------------------------------------------------------------------- */

function Positions({ facility }: { facility: string }) {
  const [rows, setRows] = useState<Position[]>([]);

  useEffect(() => {
    const query = facility ? `?facility=${facility}` : "";
    void api
      .get<Paginated<Position>>(`/hr/positions/${query}`)
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, [facility]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Positions</CardTitle>
        <CardDescription>
          The jobs that exist, whether or not anyone holds them. Headcount is
          planned against the job — which is the only reason a vacancy is a
          number at all.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Position</TableHead>
              <TableHead>Grade</TableHead>
              <TableHead className="text-right">Filled</TableHead>
              <TableHead className="text-right">Vacant</TableHead>
              <TableHead>Nature</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.uuid}>
                <TableCell>
                  <span className="font-medium">{row.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {row.code}
                    {row.department_name && ` · ${row.department_name}`}
                  </span>
                </TableCell>
                <TableCell>{row.grade || "—"}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.filled} / {row.budgeted_headcount}
                </TableCell>
                <TableCell
                  className={cn(
                    "text-right tabular-nums",
                    row.vacancies > 0 && "font-medium text-amber-600",
                  )}
                >
                  {row.vacancies}
                </TableCell>
                <TableCell className="space-x-1">
                  {row.is_clinical && <Badge variant="outline">clinical</Badge>}
                  {row.is_provider && (
                    <Badge variant="secondary">provider</Badge>
                  )}
                  {row.requires_licence && (
                    <Badge variant="outline">needs a licence</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="py-10 text-center text-sm text-muted-foreground"
                >
                  No positions defined.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
