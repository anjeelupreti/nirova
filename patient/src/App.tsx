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
  ChevronRight,
  House,
  FileText,
  FlaskConical,
  Loader2,
  LogOut,
  MessageSquare,
  Phone,
  Pill,
  Printer,
  Receipt,
  Send,
  Eye,
  ShieldCheck,
  Smartphone,
  UserCog,
  Wallet,
  X,
} from "lucide-react";

import api, { ApiError, session, whenSignedOut } from "@/lib/api";
import {
  LanguageSwitch,
  dateLeaf,
  directions,
  formatDate,
  formatDateTime,
  formatTime,
  sexLabel,
  translate as tr,
  useI18n,
  type StringKey,
} from "@/lib/i18n";
import { BookVisit } from "@/Booking";
import { cn } from "@/lib/utils";
import type {
  Appointment,
  DocumentResponse,
  HomeScreen,
  Invoices,
  MessageRow,
  PatientProfile,
  PayOption,
  PaymentStart,
  PaymentState,
  Prescription,
  ReferralRow,
  ResultRow,
  SessionRow,
  VisitRow,
  FollowUps,
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
  | "visits"
  | "followups"
  | "appointments"
  | "invoices"
  | "prescriptions"
  | "referrals"
  | "messages"
  | "sessions"
  | "profile"
  | "access";

interface AccessEntry {
  at: string;
  who: string;
  role: string;
  facility: string;
  reason: string;
  severity: string;
}

interface AccessLog {
  entries: AccessEntry[];
  note: string;
}

// Dates follow the chosen language — and, in Nepali, the Bikram Sambat
// calendar. See `lib/i18n.tsx`.
const dateTime = (value: string | null) => formatDateTime(value);
const date = (value: string | null) => formatDate(value);

const rupees = (value: string) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;

export default function App() {
  // Subscribed here, at the root, so a language change re-renders the whole
  // app — the plain date and text helpers read the active language directly.
  useI18n();
  const [signedIn, setSignedIn] = useState(Boolean(session.token));
  const [screen, setScreen] = useState<Screen>("home");
  const [record, setRecord] = useState<string>("");
  // `?attempt=` is appended by the portal when it sends a payer to a wallet.
  const [returning, setReturning] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("attempt"),
  );

  useEffect(() => {
    whenSignedOut(() => {
      setSignedIn(false);
      setScreen("home");
    });
  }, []);

  if (!signedIn) {
    return <SignedOut onSignedIn={() => setSignedIn(true)} />;
  }

  // Back from eSewa or Khalti. Whatever the wallet says in the address bar,
  // the hospital is asked what really happened before anything is shown.
  if (returning) {
    return (
      <div className="min-h-screen bg-background">
        <div className="mx-auto w-full max-w-md px-4 pb-16 pt-10 sm:max-w-2xl sm:px-6">
          <PaymentReturn
            attempt={returning}
            onDone={() => {
              window.history.replaceState({}, "", window.location.pathname);
              setReturning(null);
              setScreen("invoices");
            }}
          />
        </div>
      </div>
    );
  }

  return (
    // Phone first, and then it stops pretending. Everything here was capped at
    // `max-w-md` at every width, so a patient opening their results on a laptop
    // got a narrow strip down the middle of a wide screen -- which reads as
    // broken rather than as focused. The cap widens at each breakpoint instead.
    <div className="min-h-screen bg-background">
      <div className="mx-auto w-full max-w-md px-4 pb-28 pt-6 sm:max-w-2xl sm:px-6 lg:max-w-5xl lg:px-8 lg:pb-16 lg:pt-10">
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
            onBook={() => setScreen("appointments")}
          />
        )}
      </div>
      <TabBar screen={screen} onOpen={setScreen} />
    </div>
  );
}

/**
 * The four places a patient goes most, under the thumb on a phone. Hidden on
 * a laptop, where the directory beside the home screen does the same job and
 * a bar pinned to the bottom of a wide window reads as a mobile site.
 */
const TABS: { screen: Screen; label: StringKey; icon: typeof House }[] = [
  { screen: "home", label: "nav.home", icon: House },
  { screen: "results", label: "nav.results", icon: FlaskConical },
  { screen: "appointments", label: "nav.visits", icon: CalendarDays },
  { screen: "messages", label: "nav.messages", icon: MessageSquare },
  { screen: "profile", label: "nav.me", icon: UserCog },
];

function TabBar({ screen, onOpen }: { screen: Screen; onOpen: (screen: Screen) => void }) {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      <ul className="mx-auto grid max-w-md grid-cols-5 sm:max-w-2xl">
        {TABS.map(({ screen: target, label, icon: Icon }) => {
          const active = screen === target;
          return (
            <li key={target}>
              <button
                type="button"
                onClick={() => onOpen(target)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex w-full flex-col items-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="h-5 w-5" />
                {tr(label)}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/* -------------------------------------------------------------------------- */
/* Signed out                                                                  */
/* -------------------------------------------------------------------------- */

function SignedOut({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<"in" | "register">("in");

  return (
    // The *form* stays narrow at every width -- a sign-in box stretched across
    // a monitor is harder to use, not easier -- but it is centred in the page
    // rather than pinned to a phone-width column on the left.
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10 sm:py-16">
      <div className="mb-8 text-center">
        <div className="mb-4 flex justify-end">
          <LanguageSwitch />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{tr("app.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{tr("app.subtitle")}</p>
      </div>

      {mode === "in" ? (
        <SignIn onSignedIn={onSignedIn} onRegister={() => setMode("register")} />
      ) : (
        <Register onDone={() => setMode("in")} onBack={() => setMode("in")} />
      )}

      <Alert className="mt-8">
        <Phone className="h-4 w-4" />
        <AlertTitle>{tr("emergency.title")}</AlertTitle>
        <AlertDescription>{tr("emergency.body")}</AlertDescription>
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
        <CardTitle>{tr("signin.title")}</CardTitle>
        <CardDescription>{tr("signin.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-1">
          <Label htmlFor="s-org">{tr("signin.hospital")}</Label>
          <Input
            id="s-org"
            value={organization}
            onChange={(event) => setOrganization(event.target.value)}
            autoComplete="organization"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="s-id">{tr("signin.phone")}</Label>
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
          <Label htmlFor="s-pw">{tr("signin.password")}</Label>
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
          {tr("signin.submit")}
        </Button>

        <Button variant="ghost" className="w-full" onClick={onRegister}>
          {tr("signin.code")}
        </Button>

        <p className="text-center text-xs text-muted-foreground">{tr("signin.lockout")}</p>
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
          <CardTitle>{tr("signup.created")}</CardTitle>
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
        <CardTitle>{tr("signup.setUp")}</CardTitle>
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
          <Label htmlFor="r-org">{tr("signup.hospital")}</Label>
          <Input
            id="r-org"
            value={organization}
            onChange={(event) => setOrganization(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-mrn">{tr("signup.mrn")}</Label>
          <Input
            id="r-mrn"
            value={form.mrn}
            onChange={set("mrn")}
            placeholder="MRN-000123"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-code">{tr("signup.code")}</Label>
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
          <Label htmlFor="r-phone">{tr("signup.phone")}</Label>
          <Input
            id="r-phone"
            inputMode="tel"
            value={form.login_identifier}
            onChange={set("login_identifier")}
            placeholder="+977-98…"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="r-pw">{tr("signup.password")}</Label>
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
  label: StringKey;
  icon: typeof FlaskConical;
  needs?: "results" | "invoices";
}[] = [
  { screen: "results", label: "section.results", icon: FlaskConical, needs: "results" },
  { screen: "appointments", label: "section.appointments", icon: CalendarDays },
  { screen: "visits", label: "section.visits", icon: House },
  { screen: "followups", label: "section.followups", icon: CalendarDays },
  { screen: "prescriptions", label: "section.prescriptions", icon: Pill, needs: "results" },
  { screen: "invoices", label: "section.invoices", icon: Receipt, needs: "invoices" },
  { screen: "referrals", label: "section.referrals", icon: Send },
  { screen: "messages", label: "section.messages", icon: MessageSquare },
  { screen: "access", label: "section.access", icon: Eye },
  { screen: "profile", label: "section.profile", icon: UserCog },
];

/**
 * The first screen after signing in.
 *
 * **It was a menu.** Eight identical tiles on a white page, the same for
 * every patient, with the name and number of the record at the top and
 * nothing else — so a patient who opened the app to see whether their result
 * was back, or when they were next due, had to guess which tile held it. The
 * patient apps people actually keep (MyChart, the NHS App) open on the
 * person's own situation and put the directory underneath; so does this.
 *
 * In the order a patient asks: who am I to this hospital (the card they show
 * at the desk), what is next, what is waiting for me, what am I taking — and,
 * on every screen, who to ring if this is an emergency, as a number that
 * dials rather than a sentence that advises.
 */
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
      <div className="space-y-4 pt-2" aria-busy="true">
        <div className="h-40 animate-pulse rounded-3xl bg-muted" />
        <div className="h-28 animate-pulse rounded-3xl bg-muted" />
        <div className="h-28 animate-pulse rounded-3xl bg-muted" />
      </div>
    );
  }

  const greeting = (() => {
    const hour = new Date().getHours();
    return tr(hour < 12 ? "home.greeting.morning" : hour < 17 ? "home.greeting.afternoon" : "home.greeting.evening");
  })();
  const sex = sexLabel(data.gender);

  // What is waiting for this person, most important first. Only what exists
  // is listed — an attention list of zeros is a list nobody reads twice.
  const waiting: {
    key: string;
    screen: Screen;
    icon: typeof FlaskConical;
    title: string;
    detail: string;
    tone: "calm" | "warm";
  }[] = [];
  if (data.results_being_discussed > 0) {
    waiting.push({
      key: "discussed",
      screen: "results",
      icon: Phone,
      title:
        data.results_being_discussed === 1
          ? tr("home.discussedOne")
          : tr("home.discussedMany", { n: data.results_being_discussed }),
      detail: tr("home.discussedDetail"),
      tone: "warm",
    });
  }
  if (data.results_ready > 0 && data.can_see_results) {
    waiting.push({
      key: "results",
      screen: "results",
      icon: FlaskConical,
      title:
        data.results_ready === 1 ? tr("home.resultsOne") : tr("home.resultsMany", { n: data.results_ready }),
      detail: data.latest_result
        ? tr("home.latest", { test: data.latest_result.test }) +
          (data.latest_result.abnormal ? tr("home.outsideRange") : "")
        : "",
      tone: data.latest_result?.abnormal ? "warm" : "calm",
    });
  }
  if (Number(data.outstanding) > 0 && data.can_see_invoices) {
    waiting.push({
      key: "bills",
      screen: "invoices",
      icon: Receipt,
      title: tr("home.toPay", { amount: rupees(data.outstanding) }),
      detail: tr("home.payHow"),
      tone: "warm",
    });
  }
  if (data.follow_ups_due > 0) {
    waiting.push({
      key: "followups",
      screen: "followups",
      icon: CalendarDays,
      title:
        data.follow_ups_due === 1
          ? tr("home.followUpOne")
          : tr("home.followUpMany", { n: data.follow_ups_due }),
      detail: tr("home.followUpDetail"),
      tone: data.follow_up_overdue ? "warm" : "calm",
    });
  }
  if (data.unread_messages > 0) {
    waiting.push({
      key: "messages",
      screen: "messages",
      icon: MessageSquare,
      title:
        data.unread_messages === 1 ? tr("home.messagesOne") : tr("home.messagesMany", { n: data.unread_messages }),
      detail: tr("home.fromHospital"),
      tone: "calm",
    });
  }

  return (
    <div className="space-y-5">
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">
            {(data.hospital?.name || "H").charAt(0)}
          </span>
          <span className="truncate text-sm font-semibold">
            {data.hospital?.name || "My health record"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <LanguageSwitch />
          <Button variant="ghost" size="sm" onClick={() => void signOut()} aria-label={tr("home.signOut")}>
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">{tr("home.signOut")}</span>
          </Button>
        </div>
      </header>

      {/* Reading somebody else's record should never be ambiguous. */}
      {data.via_proxy && (
        <Alert>
          <ShieldCheck className="h-4 w-4" />
          <AlertTitle>{tr("home.proxyTitle", { name: data.patient })}</AlertTitle>
          <AlertDescription>{tr("home.proxyBody", { relationship: data.relationship })}</AlertDescription>
        </Alert>
      )}

      {data.records.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Whose record">
          {data.records.map((row) => {
            const active = (record || data.records[0].uuid) === row.uuid;
            return (
              <button
                key={row.uuid}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onSwitchRecord(row.uuid)}
                className={cn(
                  "shrink-0 rounded-full border px-4 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "bg-card hover:bg-muted",
                )}
              >
                {row.name}
                {row.via_proxy && <span className="ml-1 opacity-70">· {row.relationship}</span>}
              </button>
            );
          })}
        </div>
      )}

      {/* The health card: what the desk asks for, in the order it asks. */}
      <section className="relative overflow-hidden rounded-3xl bg-primary p-5 text-primary-foreground shadow-sm sm:p-6">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-10 -top-16 h-48 w-48 rounded-full bg-white/10"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-20 right-16 h-40 w-40 rounded-full bg-white/5"
        />
        <p className="text-sm opacity-90">
          {greeting}
          {!data.via_proxy && data.first_name ? `, ${data.first_name}` : ""}
        </p>
        <p className="mt-1 text-2xl font-semibold tracking-tight">{data.patient}</p>
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="text-xs opacity-80">{tr("home.mrn")}</dt>
            <dd className="font-semibold tabular-nums">{data.mrn}</dd>
          </div>
          <div>
            <dt className="text-xs opacity-80">{tr("home.blood")}</dt>
            <dd className="font-semibold">{data.blood_group || tr("home.bloodUnknown")}</dd>
          </div>
          <div>
            <dt className="text-xs opacity-80">{tr("home.age")}</dt>
            <dd className="font-semibold">
              {data.age != null ? `${data.age}${sex ? ` · ${sex}` : ""}` : "—"}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs opacity-80">{tr("home.showAtDesk")}</p>
      </section>

      <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-5">
          {/* What is next. */}
          <section className="rounded-3xl border bg-card p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {tr("home.upNext")}
            </p>
            {data.next_appointment ? (
              <div className="mt-3 flex items-start gap-4">
                <DateBadge value={data.next_appointment.when} />
                <div className="min-w-0">
                  <p className="font-semibold">{data.next_appointment.provider}</p>
                  <p className="text-sm text-muted-foreground">
                    {dateTime(data.next_appointment.when)}
                    {data.next_appointment.facility && ` · ${data.next_appointment.facility}`}
                  </p>
                  {data.next_appointment.reason && (
                    <p className="mt-1 text-sm">{data.next_appointment.reason}</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">{tr("home.noAppointment")}</p>
                {data.can_book_appointments && (
                  <Button size="sm" variant="outline" onClick={() => onOpen("appointments")}>
                    <CalendarDays className="h-4 w-4" />
                    {tr("home.bookVisit")}
                  </Button>
                )}
              </div>
            )}
          </section>

          {/* What is waiting. */}
          <section className="rounded-3xl border bg-card p-2">
            <p className="px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {tr("home.forYou")}
            </p>
            {waiting.length === 0 ? (
              <p className="px-3 pb-4 pt-1 text-sm text-muted-foreground">
                {tr("home.nothingWaiting")}
              </p>
            ) : (
              <ul>
                {waiting.map(({ key, screen, icon: Icon, title, detail, tone }) => (
                  <li key={key}>
                    <button
                      type="button"
                      onClick={() => onOpen(screen)}
                      className="flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition-colors hover:bg-muted/60"
                    >
                      <span
                        className={cn(
                          "grid h-10 w-10 shrink-0 place-items-center rounded-full",
                          tone === "warm"
                            ? "bg-warm text-warm-foreground"
                            : "bg-primary/10 text-primary",
                        )}
                      >
                        <Icon className="h-5 w-5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{title}</span>
                        {detail && (
                          <span className="block truncate text-sm text-muted-foreground">{detail}</span>
                        )}
                      </span>
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* What am I taking. */}
          {data.medicines.length > 0 && (
            <section className="rounded-3xl border bg-card p-5">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {tr("home.medicines")}
                </p>
                <button
                  type="button"
                  onClick={() => onOpen("prescriptions")}
                  className="text-sm font-medium text-primary hover:underline"
                >
                  {tr("home.all")}
                </button>
              </div>
              <ul className="mt-3 divide-y">
                {data.medicines.map((row, index) => (
                  <li key={index} className="flex items-start gap-3 py-2.5">
                    <Pill className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <div className="min-w-0">
                      <p className="font-medium">
                        {row.drug}
                        {row.brand && <span className="font-normal text-muted-foreground"> ({row.brand})</span>}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {directions(row.dose ?? "", row.frequency ?? "", row.how, row.prn_for ?? "")}
                        {row.until && ` · ${tr("home.until", { date: formatDate(row.until) })}`}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="space-y-5">
          <nav aria-label="Everything in your record" className="rounded-3xl border bg-card p-2">
            {TILES.filter((tile) => {
              if (tile.needs === "results") return data.can_see_results;
              if (tile.needs === "invoices") return data.can_see_invoices;
              return true;
            }).map(({ screen, label, icon: Icon }) => (
              <button
                key={screen}
                type="button"
                onClick={() => onOpen(screen)}
                className="flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/60"
              >
                <Icon className="h-4 w-4 text-muted-foreground" />
                <span className="flex-1 font-medium">{tr(label)}</span>
                {screen === "results" && data.results_ready > 0 && (
                  <Badge variant="secondary">{data.results_ready}</Badge>
                )}
                {screen === "appointments" && data.upcoming_appointments > 0 && (
                  <Badge variant="secondary">{data.upcoming_appointments}</Badge>
                )}
                {screen === "messages" && data.unread_messages > 0 && (
                  <Badge variant="destructive">{data.unread_messages}</Badge>
                )}
              </button>
            ))}
            <button
              type="button"
              onClick={() => onOpen("sessions")}
              className="flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted/60"
            >
              <Smartphone className="h-4 w-4" />
              <span className="flex-1">{tr("home.signedIn")}</span>
            </button>
          </nav>

          <EmergencyCard hospital={data.hospital} />
        </aside>
      </div>
    </div>
  );
}

/** A calendar leaf: the day, large, because the day is what people remember. */
function DateBadge({ value }: { value: string }) {
  const leaf = dateLeaf(value);
  return (
    <div className="grid w-14 shrink-0 overflow-hidden rounded-2xl border text-center">
      <span className="truncate bg-primary px-0.5 py-0.5 text-[11px] font-semibold uppercase text-primary-foreground">
        {leaf.month}
      </span>
      <span className="py-1 text-xl font-semibold tabular-nums">{leaf.day}</span>
    </div>
  );
}

/** Every screen's way out, as a number that dials. */
function EmergencyCard({ hospital }: { hospital?: { name: string; phone: string } }) {
  return (
    <div className="rounded-3xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
      <p className="flex items-center gap-2 font-semibold text-destructive">
        <Phone className="h-4 w-4" />
        {tr("emergency.title")}
      </p>
      <p className="mt-1 text-foreground/80">{tr("emergency.body")}</p>
      {hospital?.phone && (
        <a
          href={`tel:${hospital.phone.replace(/\s+/g, "")}`}
          className="mt-3 inline-flex items-center gap-2 rounded-full bg-destructive px-4 py-2 font-semibold text-destructive-foreground"
        >
          <Phone className="h-4 w-4" />
          {tr("emergency.call", { name: hospital.name ? hospital.name.split(",")[0] : tr("emergency.hospital") })}
        </a>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Sections                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * How a flag reads to a patient: which way, in a word. Warm rather than red —
 * a slightly low haemoglobin is something to ask about, not an emergency, and
 * the result screen is read at home, alone.
 */
const FLAG_WORDS: Record<string, string> = {
  low: "Low",
  high: "High",
  critical_low: "Very low",
  critical_high: "Very high",
  abnormal: "Outside range",
};

/* -------------------------------------------------------------------------- */
/* Visits and follow-ups                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Where I have been.
 *
 * **The portal could show a patient every test they had had and never once
 * tell them when they were last in the building.** Results, bills and
 * medicines are all consequences of a visit, and the visit itself -- the date,
 * the department, the person they saw, the thing they came in saying -- was
 * the one thing the application did not hold.
 *
 * It carries no note and no diagnosis, deliberately, and says so at the foot
 * rather than leaving the absence to be read as a gap: findings reach a
 * patient through results and documents, which a clinician releases.
 */
function Visits({ rows }: { rows: VisitRow[] }) {
  if (rows.length === 0) {
    return <p className="py-10 text-center text-muted-foreground">{tr("visits.none")}</p>;
  }

  return (
    <div className="space-y-3">
      {rows.map((visit) => (
        <Card key={visit.reference}>
          <CardHeader className="pb-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <CardTitle className="text-base">{visit.kind}</CardTitle>
                <CardDescription>
                  {date(visit.when)}
                  {visit.department ? ` · ${visit.department}` : ""}
                  {visit.facility ? ` · ${visit.facility}` : ""}
                </CardDescription>
              </div>
              {/* "Happening now" only if it really is today. An encounter a
                  ward forgot to close still reads as open in the record, and
                  a visit from last Tuesday labelled as under way on somebody's
                  phone is the kind of thing they ring the hospital about. */}
              {visit.in_progress && new Date(visit.when).toDateString() === new Date().toDateString() ? (
                <Badge variant="success">{tr("visits.today")}</Badge>
              ) : visit.outcome ? (
                <Badge variant="secondary">{visit.outcome}</Badge>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {visit.reason && <p>{visit.reason}</p>}
            {visit.clinician && (
              <p className="text-muted-foreground">{visit.clinician}</p>
            )}
            {visit.advice && (
              <div className="rounded-lg bg-muted/60 p-3">
                <p className="mb-0.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {tr("visits.advice")}
                </p>
                <p>{visit.advice}</p>
              </div>
            )}
            {visit.follow_up_on && (
              <p className="flex items-center gap-1.5 text-muted-foreground">
                <CalendarDays className="h-3.5 w-3.5" />
                {tr("visits.comeBack", { when: date(visit.follow_up_on) })}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
      <p className="px-1 pt-1 text-xs text-muted-foreground">{tr("visits.note")}</p>
    </div>
  );
}

/**
 * When I am meant to come back.
 *
 * The same derivation the front desk's register runs, narrowed to one person
 * -- so a patient reading their phone and a clerk reading the register cannot
 * be told different things about the same date. Overdue first, because that
 * is the row this screen exists for.
 */
function FollowUps({ data, onBook }: { data: FollowUps; onBook: () => void }) {
  if (data.results.length === 0) {
    return <p className="py-10 text-center text-muted-foreground">{tr("followups.none")}</p>;
  }

  const word = {
    due: tr("followups.due"),
    overdue: tr("followups.overdue"),
    booked: tr("followups.booked"),
  };

  return (
    <div className="space-y-3">
      {data.results.map((row) => (
        <Card
          key={`${row.source}-${row.due_on}`}
          className={cn(row.status === "overdue" && "border-warning")}
        >
          <CardHeader className="pb-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <CardTitle className="text-base">{date(row.due_on)}</CardTitle>
                {row.clinician && (
                  <CardDescription>
                    {tr("followups.by", { who: row.clinician })}
                  </CardDescription>
                )}
              </div>
              <Badge variant={row.status === "overdue" ? "warning" : row.status === "booked" ? "success" : "secondary"}>
                {word[row.status]}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {row.status === "overdue" && row.days_overdue > 0 && (
              <p className="text-muted-foreground">
                {tr("followups.lateBy", { n: row.days_overdue })}
              </p>
            )}
            {row.advice && <p>{row.advice}</p>}
            {row.status !== "booked" && (
              <Button size="sm" onClick={onBook}>
                <CalendarDays className="mr-1.5 h-4 w-4" />
                {tr("followups.book")}
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Section({
  screen,
  record,
  onBack,
  onBook,
}: {
  screen: Screen;
  record: string;
  onBack: () => void;
  /** A follow-up is only useful if the next tap books it. */
  onBook: () => void;
}) {
  const [data, setData] = useState<unknown>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [documentModal, setDocumentModal] = useState<{ html: string; title: string } | null>(null);

  const load = useCallback(async () => {
    setProblem(null);
    try {
      // The screen is named for the tab; the section is named for the API.
      const section = screen === "followups" ? "follow-ups" : screen;
      setData(
        await api.get(
          `/me/?section=${section}${record ? `&record=${record}` : ""}`,
        ),
      );
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not load.");
    }
  }, [screen, record]);

  const handlePrint = async (type: "result" | "prescription" | "invoice", reference: string) => {
    try {
      const res = await api.get<DocumentResponse>(
        `/me/?section=document&type=${type}&reference=${encodeURIComponent(reference)}${record ? `&record=${record}` : ""}`
      );
      const w = window.open("", "_blank");
      if (w) {
        w.document.write(res.html);
        w.document.close();
      } else {
        setDocumentModal({ html: res.html, title: res.title });
      }
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Could not generate printable document.");
    }
  };

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
          {tr(`section.${screen}` as StringKey)}
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
        <Results rows={data as ResultRow[]} onPrint={handlePrint} />
      )}
      {data !== null && screen === "appointments" && (
        <Appointments rows={data as Appointment[]} record={record} onChanged={load} />
      )}
      {data !== null && screen === "visits" && (
        <Visits rows={(data as { visits: VisitRow[] }).visits} />
      )}
      {data !== null && screen === "followups" && (
        <FollowUps data={data as FollowUps} onBook={onBook} />
      )}
      {data !== null && screen === "invoices" && (
        <Bills data={data as Invoices} record={record} onPrint={handlePrint} />
      )}
      {data !== null && screen === "prescriptions" && (
        <Medicines rows={data as Prescription[]} onPrint={handlePrint} />
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
      {data !== null && screen === "access" && (
        <AccessLogView data={data as AccessLog} />
      )}
      {data !== null && screen === "profile" && (
        <ProfileView
          data={data as PatientProfile}
          record={record}
          onReload={load}
        />
      )}

      {documentModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="flex h-[90vh] w-full max-w-2xl flex-col rounded-lg bg-background shadow-xl">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-sm font-semibold">{documentModal.title}</h3>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    const frame = document.getElementById("doc-frame") as HTMLIFrameElement;
                    frame?.contentWindow?.print();
                  }}
                >
                  <Printer className="mr-1.5 h-4 w-4" />
                  Print
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setDocumentModal(null)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
            {/* allow-scripts without allow-same-origin: the document needs
                its own print button to work, but the frame gets an opaque
                origin, so nothing inside it can reach this page's
                sessionStorage -- which is where the portal token lives. The
                server escapes every value it interpolates; this is the second
                lock on the same door. */}
            <iframe
              id="doc-frame"
              srcDoc={documentModal.html}
              sandbox="allow-scripts allow-modals"
              className="h-full w-full rounded-b-lg border-0 bg-white"
              title="Document Preview"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Results({
  rows,
  onPrint,
}: {
  rows: ResultRow[];
  onPrint: (type: "result" | "prescription" | "invoice", reference: string) => void;
}) {
  if (rows.length === 0) {
    return <Empty>{tr("empty.results")}</Empty>;
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
                {row.results.map((value, index) =>
                  /*
                    A written report — an X-ray, a scan — is a paragraph, not a
                    number. It had been squeezed into the value column in bold
                    red, which made a whole report read as an alarm and was
                    hard to read at all. It is set as text, in ordinary ink,
                    with "worth discussing" said in words where it applies.
                  */
                  value.value.length > 40 ? (
                    <div key={index} className="space-y-1.5 text-sm">
                      {value.abnormal && (
                        <p className="inline-flex rounded-full bg-warm px-2.5 py-0.5 text-xs font-medium text-warm-foreground">
                          {tr("results.discuss")}
                        </p>
                      )}
                      <p className="whitespace-pre-line leading-relaxed">{value.value}</p>
                    </div>
                  ) : (
                    <div
                      key={index}
                      className="flex items-baseline justify-between gap-2 text-sm"
                    >
                      <span className="text-muted-foreground">{value.analyte}</span>
                      <span className="text-right tabular-nums">
                        <span className={cn(value.abnormal && "font-semibold text-warm-foreground")}>
                          {value.value} {value.unit}
                        </span>
                        {value.abnormal && (
                          <span className="ml-1.5 rounded-full bg-warm px-1.5 py-0.5 text-[11px] font-medium text-warm-foreground">
                            {tr((`flag.${value.flag}` in FLAG_WORDS ? `flag.${value.flag}` : "flag.abnormal") as StringKey)}
                          </span>
                        )}
                        {value.reference_range && (
                          <span className="block text-xs text-muted-foreground">
                            {tr("results.usual", { range: value.reference_range })}
                          </span>
                        )}
                      </span>
                    </div>
                  ),
                )}
                {row.results.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    {tr("results.withDoctor")}
                  </p>
                )}
                <div className="mt-3 flex justify-end border-t pt-3">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 text-xs"
                    onClick={() => onPrint("result", row.reference)}
                  >
                    <Printer className="h-3.5 w-3.5" />
                    {tr("results.report")}
                  </Button>
                </div>
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

function Appointments({
  rows,
  record,
  onChanged,
}: {
  rows: Appointment[];
  record: string;
  onChanged: () => void;
}) {
  const [booking, setBooking] = useState(false);
  const upcoming = rows.filter((row) => row.upcoming);
  const past = rows.filter((row) => !row.upcoming);

  if (booking) {
    return (
      <BookVisit
        record={record}
        onBack={() => setBooking(false)}
        onDone={() => {
          setBooking(false);
          onChanged();
        }}
      />
    );
  }

  return (
    <div className="space-y-5">
      <Button className="w-full" size="lg" onClick={() => setBooking(true)}>
        <CalendarDays className="h-4 w-4" />
        {tr("appointments.book")}
      </Button>
      {upcoming.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {tr("appointments.upcoming")}
          </p>
          {upcoming.map((row) => (
            <AppointmentCard key={row.reference} row={row} record={record} onChanged={onChanged} />
          ))}
        </div>
      )}
      {past.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {tr("appointments.past")}
          </p>
          {past.slice(0, 10).map((row) => (
            <AppointmentCard key={row.reference} row={row} record={record} onChanged={onChanged} />
          ))}
        </div>
      )}
      {rows.length === 0 && <Empty>{tr("appointments.none")}</Empty>}
    </div>
  );
}

function AppointmentCard({
  row,
  record,
  onChanged,
}: {
  row: Appointment;
  record: string;
  onChanged: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const when = new Date(row.when);

  const cancel = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/me/", {
        action: "cancel_appointment",
        reference: row.reference,
        ...(record ? { record } : {}),
      });
      onChanged();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not cancel.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("rounded-3xl border bg-card p-4", !row.upcoming && "opacity-80")}>
      <div className="flex items-start gap-4">
        <div className="grid w-14 shrink-0 overflow-hidden rounded-2xl border text-center">
          <span className={cn(
            "py-0.5 text-[11px] font-semibold uppercase",
            row.upcoming ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
          )}>
            {dateLeaf(when).month}
          </span>
          <span className="py-1 text-xl font-semibold tabular-nums">{dateLeaf(when).day}</span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{row.provider}</p>
          <p className="text-sm text-muted-foreground">
            {formatTime(when)}
            {row.facility && ` · ${row.facility}`}
          </p>
          {row.reason && <p className="mt-1 text-sm">{row.reason}</p>}
        </div>
        <Badge variant="outline" className="shrink-0 capitalize">
          {row.status.replace(/_/g, " ")}
        </Badge>
      </div>
      {row.upcoming && row.can_cancel && !cancelling && (
        <button
          type="button"
          onClick={() => setCancelling(true)}
          className="mt-3 text-sm font-medium text-muted-foreground underline-offset-4 hover:text-destructive hover:underline"
        >
          {tr("appointments.cancel")}
        </button>
      )}
      {row.upcoming && !row.can_cancel && (
        <p className="mt-3 text-xs text-muted-foreground">
          {tr("appointments.tooLate")}
        </p>
      )}
      {cancelling && (
        <div className="mt-3 space-y-2 rounded-2xl bg-muted p-3 text-sm">
          <p>{tr("appointments.confirmCancel")}</p>
          {problem && <p className="text-destructive">{problem}</p>}
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" disabled={busy} onClick={() => void cancel()}>
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {tr("appointments.yesCancel")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setCancelling(false)}>
              {tr("appointments.keep")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * What happened at the wallet.
 *
 * The address bar carries the wallet's own verdict, and it is ignored: the
 * app asks the hospital, which asks the provider server to server. Until that
 * answer arrives the screen says it is checking — never "paid".
 */
function PaymentReturn({ attempt, onDone }: { attempt: string; onDone: () => void }) {
  const [state, setState] = useState<PaymentState | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.search);
    let record = "";
    try {
      record = sessionStorage.getItem("nirova.portal.payrecord") ?? "";
      sessionStorage.removeItem("nirova.portal.payrecord");
    } catch {
      /* private browsing */
    }
    api
      .post<PaymentState>("/me/", {
        action: "confirm_payment",
        attempt,
        record,
        // eSewa appends its own signed summary; it is recorded, never trusted.
        callback: params.get("data") ? { data: params.get("data") } : undefined,
      })
      .then((answer) => !cancelled && setState(answer))
      .catch((err) =>
        !cancelled && setProblem(err instanceof ApiError ? err.message : "Could not check that payment."),
      );
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const paid = state?.status === "completed" && !state.needs_attention;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{tr("section.invoices")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!state && !problem && (
          <p className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {tr("bills.checking")}
          </p>
        )}
        {problem && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        {state && (
          <div className="space-y-2">
            <p className="text-2xl font-semibold tabular-nums">{rupees(state.amount)}</p>
            <p className="text-sm text-muted-foreground">
              {state.provider_label} · {state.invoice}
            </p>
            <p className={cn("text-sm", paid ? "font-medium text-primary" : "text-muted-foreground")}>
              {paid
                ? tr("bills.paid", { receipt: state.receipt || "—" })
                : state.status === "completed"
                  ? tr("bills.attention")
                  : state.status === "pending" || state.status === "initiated"
                    ? tr("bills.pending")
                    : tr("bills.notPaid")}
            </p>
          </div>
        )}
        <Button className="w-full" onClick={onDone} disabled={!state && !problem}>
          {tr("bills.done")}
        </Button>
      </CardContent>
    </Card>
  );
}

/**
 * Paying a bill, from the phone it is read on.
 *
 * The wallet takes over the whole tab rather than opening a popup: eSewa and
 * Khalti both sign the payer in, and a popup on a phone is a window somebody
 * loses. `sessionStorage` — where the portal keeps its token — survives the
 * round trip in the same tab, so the patient comes back signed in, and the
 * app confirms the payment with the hospital before saying anything about it.
 */
function payAt(start: PaymentStart): void {
  if (start.redirect_url) {
    window.location.href = start.redirect_url;
    return;
  }
  if (!start.form) return;
  const form = document.createElement("form");
  form.method = "POST";
  form.action = start.form.action;
  for (const [name, value] of Object.entries(start.form.fields)) {
    const field = document.createElement("input");
    field.type = "hidden";
    field.name = name;
    field.value = value;
    form.append(field);
  }
  document.body.append(form);
  form.submit();
}

function Bills({
  data,
  record,
  onPrint,
}: {
  data: Invoices;
  record: string;
  onPrint: (type: "result" | "prescription" | "invoice", reference: string) => void;
}) {
  const [paying, setPaying] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const wallets = data.pay_with ?? [];

  async function pay(number: string, option: PayOption) {
    setProblem(null);
    setPaying(`${number}:${option.provider}`);
    try {
      const start = await api.post<PaymentStart>("/me/", {
        action: "pay", invoice: number, provider: option.provider, record,
      });
      // Which record this was for, so the confirmation after the wallet sends
      // the patient back asks about the right one.
      try {
        sessionStorage.setItem("nirova.portal.payrecord", record);
      } catch {
        /* private browsing: the first record is assumed on return */
      }
      payAt(start);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not start the payment.");
      setPaying(null);
    }
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>{tr("bills.outstanding")}</CardDescription>
          <CardTitle className="text-2xl">
            {rupees(data.outstanding)}
          </CardTitle>
        </CardHeader>
      </Card>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {data.invoices.map((row) => (
        <Card key={row.number}>
          <CardContent className="flex items-start justify-between gap-3 py-4">
            <div>
              <p className="font-mono text-xs text-muted-foreground">
                {row.number}
              </p>
              <p className="text-sm">{date(row.issued_on)}</p>
              {row.is_credit_note && (
                <Badge variant="secondary">{tr("bills.refund")}</Badge>
              )}
              <div className="flex flex-wrap gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 text-xs"
                  onClick={() => onPrint("invoice", row.number)}
                >
                  <Printer className="h-3.5 w-3.5" />
                  {tr("bills.receipt")}
                </Button>
                {Number(row.balance) > 0 && !row.is_credit_note &&
                  wallets.map((option) => (
                    <Button
                      key={option.provider}
                      size="sm"
                      className="h-7 gap-1.5 text-xs"
                      disabled={paying !== null}
                      onClick={() => void pay(row.number, option)}
                    >
                      {paying === `${row.number}:${option.provider}` ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Wallet className="h-3.5 w-3.5" />
                      )}
                      {tr("bills.payWith", { wallet: option.label })}
                    </Button>
                  ))}
              </div>
              {wallets.some((option) => option.test_mode) && Number(row.balance) > 0 && (
                <p className="pt-1 text-[11px] text-muted-foreground">{tr("bills.testMode")}</p>
              )}
            </div>
            <div className="text-right">
              <p className="font-medium tabular-nums">{rupees(row.total)}</p>
              {Number(row.balance) > 0 && (
                <p className="text-sm tabular-nums text-destructive">
                  {tr("bills.toPay", { amount: rupees(row.balance) })}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
      {data.invoices.length === 0 && <Empty>{tr("bills.none")}</Empty>}
    </div>
  );
}

function Medicines({
  rows,
  onPrint,
}: {
  rows: Prescription[];
  onPrint: (type: "result" | "prescription" | "invoice", reference: string) => void;
}) {
  if (rows.length === 0) return <Empty>{tr("empty.medicines")}</Empty>;
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
                  {directions(line.dose, line.frequency, line.directions || `${line.dose} · ${line.frequency}`, line.prn_indication ?? "")}
                  {line.duration_days ? ` · ${line.duration_days} days` : ""}
                </p>
                {line.instructions && <p>{line.instructions}</p>}
              </div>
            ))}
            {row.reference && (
              <div className="mt-3 flex justify-end border-t pt-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5 text-xs"
                  onClick={() => onPrint("prescription", row.reference)}
                >
                  <Printer className="h-3.5 w-3.5" />
                  Print Prescription
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Referrals({ rows }: { rows: ReferralRow[] }) {
  if (rows.length === 0) return <Empty>{tr("empty.referrals")}</Empty>;
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
        <AlertTitle>{tr("messages.hours")}</AlertTitle>
        <AlertDescription>
          {tr("messages.notUrgent")}
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
          <CardTitle className="text-base">{tr("messages.ask")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder={tr("messages.about")}
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
      {rows.length === 0 && <Empty>{tr("empty.messages")}</Empty>}
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
      {live.length === 0 && <Empty>{tr("empty.devices")}</Empty>}

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

function ProfileView({
  data,
  record,
  onReload,
}: {
  data: PatientProfile;
  record: string;
  onReload: () => void;
}) {
  const [proposing, setProposing] = useState(false);
  const [field, setField] = useState<string>("phone");
  const [proposedValue, setProposedValue] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const currentVal = String(data[field as keyof PatientProfile] || "");

  const submit = async () => {
    if (!proposedValue.trim() || !reason.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.post("/me/", {
        action: "request_correction",
        field_name: field,
        proposed_value: proposedValue.trim(),
        reason: reason.trim(),
        ...(record ? { record } : {}),
      });
      setProposing(false);
      setProposedValue("");
      setReason("");
      onReload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to submit request.");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (uuid: string) => {
    try {
      await api.post("/me/", {
        action: "cancel_correction",
        correction: uuid,
        ...(record ? { record } : {}),
      });
      onReload();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "Could not cancel request.");
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base">{data.full_name}</CardTitle>
              <CardDescription>MRN: {data.mrn}</CardDescription>
            </div>
            <Badge variant="outline" className="capitalize">
              {data.gender}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5 text-sm">
          <div className="flex justify-between border-b py-1">
            <span className="text-muted-foreground">{tr("profile.phone")}</span>
            <span className="font-medium">{data.phone || "—"}</span>
          </div>
          {data.alternate_phone && (
            <div className="flex justify-between border-b py-1">
              <span className="text-muted-foreground">{tr("profile.altPhone")}</span>
              <span>{data.alternate_phone}</span>
            </div>
          )}
          {data.email && (
            <div className="flex justify-between border-b py-1">
              <span className="text-muted-foreground">{tr("profile.email")}</span>
              <span>{data.email}</span>
            </div>
          )}
          <div className="flex justify-between border-b py-1">
            <span className="text-muted-foreground">{tr("profile.address")}</span>
            <span className="max-w-[200px] text-right font-medium">
              {data.temporary_address || data.tole || data.district || "—"}
            </span>
          </div>
          <div className="flex justify-between border-b py-1">
            <span className="text-muted-foreground">{tr("profile.emergency")}</span>
            <span className="text-right">
              {data.guardian_name ? `${data.guardian_name} (${data.guardian_relationship || "Guardian"})` : "—"}
              {data.guardian_phone && <div className="text-xs text-muted-foreground">{data.guardian_phone}</div>}
            </span>
          </div>
        </CardContent>
      </Card>

      {!proposing ? (
        <Button className="w-full gap-2" variant="outline" onClick={() => setProposing(true)}>
          <UserCog className="h-4 w-4" />
          Request Detail Correction
        </Button>
      ) : (
        <Card className="border-primary/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{tr("correction.propose")}</CardTitle>
            <CardDescription>
              {tr("correction.reviewed")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {err && (
              <Alert variant="destructive">
                <AlertDescription>{err}</AlertDescription>
              </Alert>
            )}
            <div className="space-y-1">
              <Label>{tr("correction.field")}</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={field}
                onChange={(e) => {
                  setField(e.target.value);
                  setProposedValue("");
                }}
              >
                <option value="phone">{tr("field.phone")}</option>
                <option value="alternate_phone">{tr("profile.altPhone")}</option>
                <option value="email">{tr("profile.email")}</option>
                <option value="temporary_address">{tr("field.address")}</option>
                <option value="tole">{tr("field.tole")}</option>
                <option value="municipality">{tr("field.municipality")}</option>
                <option value="guardian_name">{tr("field.guardianName")}</option>
                <option value="guardian_phone">{tr("field.guardianPhone")}</option>
                <option value="guardian_relationship">{tr("field.guardianRelationship")}</option>
              </select>
            </div>

            <div className="rounded border bg-muted/50 p-2.5 text-xs">
              <span className="text-muted-foreground">{tr("correction.current")}</span>
              <strong>{currentVal || tr("correction.none")}</strong>
            </div>

            <div className="space-y-1">
              <Label>{tr("correction.newValue")}</Label>
              <Input
                value={proposedValue}
                onChange={(e) => setProposedValue(e.target.value)}
                placeholder={tr("correction.enterValue")}
              />
            </div>

            <div className="space-y-1">
              <Label>{tr("correction.reason")}</Label>
              <Textarea
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={tr("correction.reasonHint")}
              />
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                className="flex-1"
                disabled={busy || !proposedValue.trim() || !reason.trim()}
                onClick={() => void submit()}
              >
                {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Submit Request
              </Button>
              <Button variant="ghost" onClick={() => setProposing(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {data.pending_corrections && data.pending_corrections.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Pending verification ({data.pending_corrections.length})
          </p>
          {data.pending_corrections.map((p) => (
            <Card key={p.uuid} className="border-amber-500/40 bg-amber-500/5">
              <CardContent className="space-y-1 py-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase text-amber-700">
                    {p.field_label}
                  </span>
                  <Badge variant="secondary" className="bg-amber-100 text-xs text-amber-800">
                    Pending Desk Review
                  </Badge>
                </div>
                <div className="text-sm">
                  <span className="text-xs text-muted-foreground line-through">{p.old_value || "Empty"}</span>{" "}
                  &rarr; <strong>{p.proposed_value}</strong>
                </div>
                <div className="text-xs italic text-muted-foreground">&ldquo;{p.reason}&rdquo;</div>
                <div className="flex justify-end pt-2">
                  <Button variant="ghost" size="sm" className="h-7 text-xs text-destructive" onClick={() => void cancel(p.uuid)}>
                    Cancel Request
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {data.recent_corrections && data.recent_corrections.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Past Requests
          </p>
          {data.recent_corrections.map((p) => (
            <Card key={p.uuid}>
              <CardContent className="space-y-1 py-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{p.field_label}</span>
                  <Badge
                    variant={p.status === "approved" ? "secondary" : "destructive"}
                    className="text-xs capitalize"
                  >
                    {p.status}
                  </Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  Proposed: <strong>{p.proposed_value}</strong> on {date(p.requested_at)}
                </div>
                {p.decision_notes && (
                  <div className="rounded bg-muted/40 p-1.5 text-xs text-muted-foreground">
                    Staff note: {p.decision_notes}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}


/**
 * Who has opened this record.
 *
 * The one report a patient is entitled to without asking anybody, and the
 * screen has to be careful in two directions at once.
 *
 * **Staff are named.** A log saying "a member of staff" answers nothing, and
 * the fact that the people reading records know they are named is most of what
 * makes the logging work at all.
 *
 * **But a long list of names is frightening if it is not explained.** Somebody
 * treating you reads your record constantly — that is what treating you looks
 * like — and a screen that presents forty entries with no context invites a
 * complaint about the forty rather than about the one that matters. So the
 * note sits above the list, not below it, and every row says *why*.
 */
function AccessLogView({ data }: { data: AccessLog }) {
  const entries = data.entries ?? [];
  return (
    <section className="space-y-3">
      <p className="text-sm text-slate-600">{data.note}</p>

      {entries.length === 0 ? (
        <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
          Nobody has opened your record in the last year.
        </p>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry, index) => (
            <li
              key={`${entry.at}-${index}`}
              className="rounded-lg border border-slate-200 bg-white p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium text-slate-900">{entry.who}</p>
                <p className="shrink-0 text-xs text-slate-500">
                  {dateTime(entry.at)}
                </p>
              </div>
              {entry.role && (
                <p className="text-xs text-slate-500">{entry.role}</p>
              )}
              {/* The reason, in the words the system recorded at the time.
                  A row that says who and when but not why is the one that
                  produces a phone call. */}
              {entry.reason && (
                <p className="mt-1 text-sm text-slate-700">{entry.reason}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-slate-500">
        If something here looks wrong, say so — use Messages, or ask at the
        desk. Every entry is kept.
      </p>
    </section>
  );
}
