/**
 * My health record.
 *
 * A patient's application, not a smaller version of the clinician's. Three
 * things follow from that and shape every screen below.
 *
 * **It is read on a phone, standing up, often on a borrowed one.** One column,
 * large targets, no dense tables, and a session that dies with the tab.
 *
 * **A held result is shown, not omitted.** When a clinician is ringing about a
 * result, the card appears saying exactly that. A list with a silent gap in it
 * is worse than a delay the patient can see and ask about.
 *
 * **Nothing here is urgent care, and it says so.** The message box carries the
 * sentence rather than hiding it in terms of use, because somebody describing
 * chest pain into a contact form and waiting is a foreseeable harm.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  ChevronLeft,
  FileText,
  FlaskConical,
  Loader2,
  LogOut,
  MessageSquare,
  Phone,
  Pill,
  Receipt,
  Send,
  ShieldCheck,
  Smartphone,
} from "lucide-react";

import api, { ApiError, session, whenSignedOut } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Appointment,
  HomeScreen,
  Invoices,
  MessageRow,
  Prescription,
  ReferralRow,
  ResultRow,
  SessionRow,
  SignInResult,
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
  Textarea,
} from "@/components/primitives";

type Screen =
  | "home"
  | "results"
  | "appointments"
  | "invoices"
  | "prescriptions"
  | "referrals"
  | "messages"
  | "sessions";

const dateTime = (value: string | null) =>
  value
    ? new Date(value).toLocaleString([], {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

const date = (value: string | null) =>
  value
    ? new Date(value).toLocaleDateString([], {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "—";

const rupees = (value: string) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;

export default function App() {
  const [signedIn, setSignedIn] = useState(Boolean(session.token));
  const [screen, setScreen] = useState<Screen>("home");
  const [record, setRecord] = useState<string>("");

  useEffect(() => {
    whenSignedOut(() => {
      setSignedIn(false);
      setScreen("home");
    });
  }, []);

  if (!signedIn) {
    return <SignedOut onSignedIn={() => setSignedIn(true)} />;
  }

  return (
    <div className="mx-auto min-h-screen w-full max-w-md bg-background px-4 pb-16 pt-6">
      {screen === "home" ? (
        <Home
          record={record}
          onOpen={setScreen}
          onSwitchRecord={setRecord}
          onSignOut={() => setSignedIn(false)}
        />
      ) : (
        <Section
          screen={screen}
          record={record}
          onBack={() => setScreen("home")}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Signed out                                                                  */
/* -------------------------------------------------------------------------- */

function SignedOut({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<"in" | "register">("in");

  return (
    <div className="mx-auto min-h-screen w-full max-w-md px-4 py-10">
      <div className="mb-8 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          My health record
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Your appointments, results and bills.
        </p>
      </div>

      {mode === "in" ? (
        <SignIn onSignedIn={onSignedIn} onRegister={() => setMode("register")} />
      ) : (
        <Register onDone={() => setMode("in")} onBack={() => setMode("in")} />
      )}

      <Alert className="mt-8">
        <Phone className="h-4 w-4" />
        <AlertTitle>If this is an emergency</AlertTitle>
        <AlertDescription>
          Do not use this app. Go to the emergency department or call for an
          ambulance.
        </AlertDescription>
      </Alert>
    </div>
  );
}

function SignIn({
  onSignedIn,
  onRegister,
}: {
  onSignedIn: () => void;
  onRegister: () => void;
}) {
  const [organization, setOrganization] = useState(
    session.organization || "manakamana",
  );
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    session.organization = organization.trim();
    try {
      const result = await api.open<SignInResult>("/me/auth/", {
        action: "login",
        identifier: identifier.trim(),
        password,
        device: navigator.userAgent.slice(0, 120),
      });
      session.token = result.token;
      onSignedIn();
    } catch (err) {
      // Whatever went wrong, the server says the same thing. Repeating it
      // verbatim keeps this screen from leaking what the API deliberately
      // will not.
      setProblem(
        err instanceof ApiError
          ? err.message
          : "Could not sign in. Check your connection.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>
          With the phone number you gave at the hospital.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-1">
          <Label htmlFor="s-org">Hospital</Label>
          <Input
            id="s-org"
            value={organization}
            onChange={(event) => setOrganization(event.target.value)}
            autoComplete="organization"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="s-id">Phone number</Label>
          <Input
            id="s-id"
            inputMode="tel"
            autoComplete="username"
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder="+977-98…"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="s-pw">Password</Label>
          <Input
            id="s-pw"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <Button
          className="w-full"
          disabled={busy || !identifier.trim() || !password}
          onClick={() => void submit()}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Sign in
        </Button>

        <Button variant="ghost" className="w-full" onClick={onRegister}>
          I have a code from the hospital
        </Button>

        <p className="text-center text-xs text-muted-foreground">
          After five wrong attempts you will be locked out for a few minutes.
        </p>
      </CardContent>
    </Card>
  );
}

function Register({ onDone, onBack }: { onDone: () => void; onBack: () => void }) {
  const [organization, setOrganization] = useState(
    session.organization || "manakamana",
  );
  const [form, setForm] = useState({
    mrn: "",
    code: "",
    login_identifier: "",
    password: "",
    email: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    session.organization = organization.trim();
    try {
      await api.open("/me/auth/", { action: "register", ...form });
      setDone(true);
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "Could not create the account.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Account created</CardTitle>
          <CardDescription>
            Sign in with the phone number and password you just chose.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button className="w-full" onClick={onDone}>
            Sign in
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Set up your account</CardTitle>
        <CardDescription>
          You need the number on your hospital card and the code the desk gave
          you. Neither works without the other.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-1">
          <Label htmlFor="r-org">Hospital</Label>
          <Input
            id="r-org"
            value={organization}
            onChange={(event) => setOrganization(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-mrn">Number on your card</Label>
          <Input
            id="r-mrn"
            value={form.mrn}
            onChange={set("mrn")}
            placeholder="MRN-000123"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-code">Code from the desk</Label>
          <Input
            id="r-code"
            inputMode="numeric"
            className="text-center font-mono text-lg tracking-widest"
            value={form.code}
            onChange={set("code")}
            placeholder="12345678"
          />
          <p className="text-xs text-muted-foreground">
            The code expires after two weeks and after five wrong tries. If it
            stops working, ask the desk for another.
          </p>
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-phone">Your phone number</Label>
          <Input
            id="r-phone"
            inputMode="tel"
            value={form.login_identifier}
            onChange={set("login_identifier")}
            placeholder="+977-98…"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-pw">Choose a password</Label>
          <Input
            id="r-pw"
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={set("password")}
          />
          <p className="text-xs text-muted-foreground">
            At least eight characters. This account opens your medical record.
          </p>
        </div>

        <Button
          className="w-full"
          disabled={
            busy ||
            !form.mrn.trim() ||
            !form.code.trim() ||
            !form.login_identifier.trim() ||
            form.password.length < 8
          }
          onClick={() => void submit()}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Create my account
        </Button>
        <Button variant="ghost" className="w-full" onClick={onBack}>
          Back
        </Button>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Home                                                                        */
/* -------------------------------------------------------------------------- */

const TILES: {
  screen: Screen;
  label: string;
  icon: typeof FlaskConical;
  needs?: "results" | "invoices";
}[] = [
  { screen: "results", label: "Test results", icon: FlaskConical, needs: "results" },
  { screen: "appointments", label: "Appointments", icon: CalendarDays },
  { screen: "prescriptions", label: "Medicines", icon: Pill, needs: "results" },
  { screen: "invoices", label: "Bills", icon: Receipt, needs: "invoices" },
  { screen: "referrals", label: "Referrals", icon: Send },
  { screen: "messages", label: "Messages", icon: MessageSquare },
];

function Home({
  record,
  onOpen,
  onSwitchRecord,
  onSignOut,
}: {
  record: string;
  onOpen: (screen: Screen) => void;
  onSwitchRecord: (uuid: string) => void;
  onSignOut: () => void;
}) {
  const [data, setData] = useState<HomeScreen | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(
        await api.get<HomeScreen>(
          `/me/?section=home${record ? `&record=${record}` : ""}`,
        ),
      );
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not load.");
    }
  }, [record]);

  useEffect(() => {
    void load();
  }, [load]);

  const signOut = async () => {
    try {
      await api.post("/me/", { action: "sign_out" });
    } finally {
      session.clear();
      onSignOut();
    }
  };

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
      <p className="py-20 text-center text-muted-foreground">
        <Loader2 className="inline h-5 w-5 animate-spin" />
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {data.patient}
          </h1>
          <p className="text-sm text-muted-foreground">{data.mrn}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => void signOut()}>
          <LogOut className="h-4 w-4" />
        </Button>
      </div>

      {/* Reading somebody else's record should never be ambiguous. */}
      {data.via_proxy && (
        <Alert>
          <ShieldCheck className="h-4 w-4" />
          <AlertTitle>You are viewing {data.patient}'s record</AlertTitle>
          <AlertDescription>
            As their {data.relationship}. They or the hospital can end this at
            any time.
          </AlertDescription>
        </Alert>
      )}

      {data.records.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {data.records.map((row) => (
            <Button
              key={row.uuid}
              size="sm"
              variant={
                (record || data.records[0].uuid) === row.uuid
                  ? "default"
                  : "outline"
              }
              onClick={() => onSwitchRecord(row.uuid)}
            >
              {row.name}
            </Button>
          ))}
        </div>
      )}

      {/* Shown, not omitted. A silent gap is worse than a visible delay. */}
      {data.results_being_discussed > 0 && (
        <Alert>
          <Phone className="h-4 w-4" />
          <AlertTitle>
            {data.results_being_discussed === 1
              ? "A result is ready and a doctor will call you"
              : `${data.results_being_discussed} results are ready and a doctor will call you`}
          </AlertTitle>
          <AlertDescription>
            Some results are better explained than read alone. They will appear
            here shortly if nobody has been in touch.
          </AlertDescription>
        </Alert>
      )}

      {data.next_appointment && (
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Your next appointment</CardDescription>
            <CardTitle className="text-base">
              {dateTime(data.next_appointment.when)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {data.next_appointment.provider}
            {data.next_appointment.facility &&
              ` · ${data.next_appointment.facility}`}
          </CardContent>
        </Card>
      )}

      {Number(data.outstanding) > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>To pay</CardDescription>
            <CardTitle className="text-base">
              {rupees(data.outstanding)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              className="w-full"
              onClick={() => onOpen("invoices")}
            >
              See the bills
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3">
        {TILES.filter((tile) => {
          if (tile.needs === "results") return data.can_see_results;
          if (tile.needs === "invoices") return data.can_see_invoices;
          return true;
        }).map(({ screen, label, icon: Icon }) => (
          <button
            key={screen}
            type="button"
            onClick={() => onOpen(screen)}
            className="flex flex-col items-start gap-2 rounded-lg border p-4 text-left transition-colors hover:bg-muted/50"
          >
            <Icon className="h-5 w-5 text-muted-foreground" />
            <span className="font-medium">{label}</span>
            {screen === "results" && data.results_ready > 0 && (
              <Badge variant="secondary">{data.results_ready} ready</Badge>
            )}
            {screen === "appointments" && data.upcoming_appointments > 0 && (
              <Badge variant="secondary">
                {data.upcoming_appointments} upcoming
              </Badge>
            )}
            {screen === "messages" && data.unread_messages > 0 && (
              <Badge variant="destructive">{data.unread_messages} new</Badge>
            )}
          </button>
        ))}
      </div>

      <Button
        variant="ghost"
        className="w-full"
        onClick={() => onOpen("sessions")}
      >
        <Smartphone className="h-4 w-4" />
        Where I am signed in
      </Button>

      <p className="pt-2 text-center text-xs text-muted-foreground">
        This app is not for urgent problems. In an emergency, go to the
        emergency department.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Sections                                                                    */
/* -------------------------------------------------------------------------- */

const TITLES: Record<Screen, string> = {
  home: "Home",
  results: "Test results",
  appointments: "Appointments",
  invoices: "Bills",
  prescriptions: "Medicines",
  referrals: "Referrals",
  messages: "Messages",
  sessions: "Where I am signed in",
};

function Section({
  screen,
  record,
  onBack,
}: {
  screen: Screen;
  record: string;
  onBack: () => void;
}) {
  const [data, setData] = useState<unknown>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    setProblem(null);
    try {
      setData(
        await api.get(
          `/me/?section=${screen}${record ? `&record=${record}` : ""}`,
        ),
      );
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not load.");
    }
  }, [screen, record]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold tracking-tight">
          {TITLES[screen]}
        </h1>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {!data && !problem && (
        <p className="py-16 text-center text-muted-foreground">
          <Loader2 className="inline h-5 w-5 animate-spin" />
        </p>
      )}

      {data !== null && screen === "results" && (
        <Results rows={data as ResultRow[]} />
      )}
      {data !== null && screen === "appointments" && (
        <Appointments rows={data as Appointment[]} />
      )}
      {data !== null && screen === "invoices" && (
        <Bills data={data as Invoices} />
      )}
      {data !== null && screen === "prescriptions" && (
        <Medicines rows={data as Prescription[]} />
      )}
      {data !== null && screen === "referrals" && (
        <Referrals rows={data as ReferralRow[]} />
      )}
      {data !== null && screen === "messages" && (
        <Messages rows={data as MessageRow[]} record={record} onSent={load} />
      )}
      {data !== null && screen === "sessions" && (
        <Sessions rows={data as SessionRow[]} onChanged={load} />
      )}
    </div>
  );
}

function Results({ rows }: { rows: ResultRow[] }) {
  if (rows.length === 0) {
    return <Empty>No results yet.</Empty>;
  }
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <Card
          key={row.reference}
          className={cn(!row.visible && "border-amber-500/50")}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{row.test}</CardTitle>
            <CardDescription>{date(row.ordered_at)}</CardDescription>
          </CardHeader>
          <CardContent>
            {row.visible ? (
              <div className="space-y-1">
                {row.results.map((value, index) => (
                  <div
                    key={index}
                    className="flex items-baseline justify-between gap-2 text-sm"
                  >
                    <span className="text-muted-foreground">
                      {value.analyte}
                    </span>
                    <span
                      className={cn(
                        "tabular-nums",
                        value.abnormal && "font-medium text-destructive",
                      )}
                    >
                      {value.value} {value.unit}
                      {value.reference_range && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          ({value.reference_range})
                        </span>
                      )}
                    </span>
                  </div>
                ))}
                {row.results.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    The report is with your doctor.
                  </p>
                )}
              </div>
            ) : (
              /* The whole point of showing this card at all. */
              <div className="flex gap-3">
                <Phone className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <p className="text-sm">{row.message}</p>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Appointments({ rows }: { rows: Appointment[] }) {
  const upcoming = rows.filter((row) => row.upcoming);
  const past = rows.filter((row) => !row.upcoming);

  return (
    <div className="space-y-4">
      {upcoming.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Coming up
          </p>
          {upcoming.map((row) => (
            <AppointmentCard key={row.reference} row={row} />
          ))}
        </div>
      )}
      {past.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Past
          </p>
          {past.slice(0, 10).map((row) => (
            <AppointmentCard key={row.reference} row={row} />
          ))}
        </div>
      )}
      {rows.length === 0 && <Empty>No appointments.</Empty>}
    </div>
  );
}

function AppointmentCard({ row }: { row: Appointment }) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 py-4">
        <div>
          <p className="font-medium">{dateTime(row.when)}</p>
          <p className="text-sm text-muted-foreground">
            {row.provider}
            {row.facility && ` · ${row.facility}`}
          </p>
          {row.reason && <p className="text-sm">{row.reason}</p>}
        </div>
        <Badge variant="outline">{row.status.replace(/_/g, " ")}</Badge>
      </CardContent>
    </Card>
  );
}

function Bills({ data }: { data: Invoices }) {
  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Outstanding</CardDescription>
          <CardTitle className="text-2xl">
            {rupees(data.outstanding)}
          </CardTitle>
        </CardHeader>
      </Card>

      {data.invoices.map((row) => (
        <Card key={row.number}>
          <CardContent className="flex items-start justify-between gap-3 py-4">
            <div>
              <p className="font-mono text-xs text-muted-foreground">
                {row.number}
              </p>
              <p className="text-sm">{date(row.issued_on)}</p>
              {row.is_credit_note && (
                <Badge variant="secondary">refund</Badge>
              )}
            </div>
            <div className="text-right">
              <p className="font-medium tabular-nums">{rupees(row.total)}</p>
              {Number(row.balance) > 0 && (
                <p className="text-sm tabular-nums text-destructive">
                  {rupees(row.balance)} to pay
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
      {data.invoices.length === 0 && <Empty>No bills.</Empty>}
    </div>
  );
}

function Medicines({ rows }: { rows: Prescription[] }) {
  if (rows.length === 0) return <Empty>No medicines prescribed.</Empty>;
  return (
    <div className="space-y-3">
      {rows.map((row, index) => (
        <Card key={row.reference || index}>
          <CardHeader className="pb-2">
            <CardDescription>
              {date(row.prescribed_on)}
              {row.prescriber && ` · ${row.prescriber}`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {row.lines.map((line, position) => (
              <div key={position} className="text-sm">
                <p className="font-medium">
                  {line.drug}
                  {line.brand && (
                    <span className="text-muted-foreground"> ({line.brand})</span>
                  )}
                </p>
                <p className="text-muted-foreground">
                  {line.dose} · {line.frequency}
                  {line.duration_days ? ` · ${line.duration_days} days` : ""}
                </p>
                {line.instructions && <p>{line.instructions}</p>}
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Referrals({ rows }: { rows: ReferralRow[] }) {
  if (rows.length === 0) return <Empty>No referrals.</Empty>;
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <Card key={row.reference}>
          <CardContent className="py-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{row.specialty}</p>
                <p className="text-sm text-muted-foreground">
                  {date(row.created_on)}
                </p>
              </div>
              <Badge variant="outline">{row.status.replace(/_/g, " ")}</Badge>
            </div>
            {row.seen_at && (
              <p className="mt-1 text-sm">
                Seen on {date(row.seen_at)}.{" "}
                {row.answered
                  ? "The specialist has written back to your doctor."
                  : "Your doctor has not had the letter back yet."}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Messages({
  rows,
  record,
  onSent,
}: {
  rows: MessageRow[];
  record: string;
  onSent: () => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/me/${record ? `?record=${record}` : ""}`, {
        action: "message",
        subject,
        body,
      });
      setSubject("");
      setBody("");
      onSent();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Said here, next to the box, rather than buried in terms of use. */}
      <Alert>
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Answered in working hours</AlertTitle>
        <AlertDescription>
          This is not a way to get urgent help. If you are unwell now, go to the
          emergency department or call for an ambulance.
        </AlertDescription>
      </Alert>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Ask something</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="What it is about"
          />
          <Textarea
            rows={4}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="Your question"
          />
          <Button
            className="w-full"
            disabled={busy || !subject.trim() || body.trim().length < 5}
            onClick={() => void send()}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Send
          </Button>
        </CardContent>
      </Card>

      {rows.map((row) => (
        <Card
          key={row.uuid}
          className={cn(row.direction === "to_patient" && "border-primary/40")}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{row.subject}</CardTitle>
            <CardDescription>
              {row.direction === "to_patient"
                ? `From ${row.sender || "the hospital"}`
                : "You"}{" "}
              · {date(row.sent_at)}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{row.body}</p>
            {row.direction === "from_patient" && !row.answered && (
              <p className="mt-2 text-xs text-muted-foreground">
                Not answered yet.
              </p>
            )}
          </CardContent>
        </Card>
      ))}
      {rows.length === 0 && <Empty>No messages yet.</Empty>}
    </div>
  );
}

function Sessions({
  rows,
  onChanged,
}: {
  rows: SessionRow[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const endAll = async () => {
    setBusy(true);
    try {
      await api.post("/me/", { action: "sign_out_everywhere" });
      session.clear();
      window.location.reload();
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  const live = rows.filter((row) => row.is_live);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Signing out here really does end the session — it is not just forgotten
        on this phone.
      </p>

      {live.map((row) => (
        <Card key={row.uuid}>
          <CardContent className="py-4">
            <p className="font-medium">
              {row.device_label || "Unknown device"}
            </p>
            <p className="text-sm text-muted-foreground">
              Signed in {dateTime(row.issued_at)}
              {row.last_seen_at && ` · last used ${dateTime(row.last_seen_at)}`}
            </p>
          </CardContent>
        </Card>
      ))}
      {live.length === 0 && <Empty>No other devices.</Empty>}

      <Button
        variant="destructive"
        className="w-full"
        disabled={busy || live.length === 0}
        onClick={() => void endAll()}
      >
        <FileText className="h-4 w-4" />
        Sign out everywhere
      </Button>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-16 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
