/**
 * Referrals.
 *
 * Almost every system can send a referral. What goes wrong is afterwards: the
 * patient is referred and nobody at the referring end ever learns whether they
 * went, whether they were seen, or what was found. So this screen is built
 * around the loop, not the letter.
 *
 * Three things it refuses to soften.
 *
 * **"Seen but nobody has been told" is its own tab, with a count on it.**
 * Every other status is somebody waiting for something to happen. That one is
 * something having happened that nobody passed on, and it is invisible in any
 * list ordered by status.
 *
 * **The referrer's question is shown wherever the referral is.** It is on the
 * worklist row, on the unanswered list, and above the reply box — because a
 * response that does not answer it is the commonest complaint referring
 * clinicians have.
 *
 * **A breach stays a breach after the patient is finally seen.** A red row
 * that turns green the moment somebody deals with it is a breach nobody
 * counts.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Inbox,
  Loader2,
  MailQuestion,
  Send,
  TrendingUp,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  DeclineReason,
  ExternalProvider,
  Facility,
  Paginated,
  Referral,
  ReferralSummaryReport,
  ReferralTarget,
  ReferralWorklistRow,
  UnansweredReferral,
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

type Tab = "worklist" | "unanswered" | "performance" | "providers";

const TABS: { id: Tab; label: string; icon: typeof Inbox }[] = [
  { id: "worklist", label: "Worklist", icon: Inbox },
  { id: "unanswered", label: "Nobody told the referrer", icon: MailQuestion },
  { id: "performance", label: "How it is working", icon: TrendingUp },
  { id: "providers", label: "Where we refer", icon: ClipboardList },
];

const URGENCY_TONE: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  routine: "outline",
  soon: "secondary",
  urgent: "default",
  emergency: "destructive",
};

const humanise = (value: string) => value.replace(/_/g, " ");

const day = (value: string | null) =>
  value
    ? new Date(value).toLocaleDateString([], {
        day: "2-digit",
        month: "short",
        year: "2-digit",
      })
    : "—";

export default function ReferralsPage() {
  const [tab, setTab] = useState<Tab>("worklist");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<UnansweredReferral[]>([]);
  const [denied, setDenied] = useState(false);

  const loadWaiting = useCallback(() => {
    void api
      .get<UnansweredReferral[]>("/referrals/reports/?report=unanswered&days=7")
      .then(setWaiting)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

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
      .catch(() => undefined);
    loadWaiting();
  }, [loadWaiting]);

  if (denied) {
    return (
      <Alert>
        <Send className="h-4 w-4" />
        <AlertTitle>Referrals are not visible to you</AlertTitle>
        <AlertDescription>
          Seeing them needs clinical permissions.
        </AlertDescription>
      </Alert>
    );
  }

  if (open) {
    return (
      <ReferralDetail
        reference={open}
        onBack={() => {
          setOpen(null);
          loadWaiting();
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Referrals</h1>
          <p className="text-sm text-muted-foreground">
            The handoff, and whether anybody ever closed the loop.
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

      <div className="flex gap-1 overflow-x-auto border-b">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
              tab === id
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
            {id === "unanswered" && waiting.length > 0 && (
              <Badge variant="destructive">{waiting.length}</Badge>
            )}
          </button>
        ))}
      </div>

      {tab === "worklist" && (
        <Worklist facility={facility} onOpen={setOpen} />
      )}
      {tab === "unanswered" && (
        <Unanswered rows={waiting} onOpen={setOpen} />
      )}
      {tab === "performance" && <Performance facility={facility} />}
      {tab === "providers" && <Providers />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Worklist                                                                    */
/* -------------------------------------------------------------------------- */

function Worklist({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [rows, setRows] = useState<ReferralWorklistRow[]>([]);
  const [targets, setTargets] = useState<ReferralTarget[]>([]);
  const [direction, setDirection] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const query = new URLSearchParams({ report: "worklist" });
    if (facility) query.set("facility", facility);
    if (direction) query.set("direction", direction);
    void Promise.all([
      api.get<ReferralWorklistRow[]>(`/referrals/reports/?${query}`),
      api.get<ReferralTarget[]>("/referrals/targets/"),
    ])
      .then(([a, b]) => {
        setRows(a);
        setTargets(b);
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [facility, direction]);

  const breaching = rows.filter((row) => row.breaching).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Label htmlFor="r-direction" className="text-sm">
          Direction
        </Label>
        <Select
          id="r-direction"
          className="h-9 w-auto"
          value={direction}
          onChange={(event) => setDirection(event.target.value)}
        >
          <option value="">All</option>
          <option value="internal">Internal</option>
          <option value="outbound">Out to another provider</option>
          <option value="inbound">In from another provider</option>
        </Select>
        <span className="text-xs text-muted-foreground">
          Targets:{" "}
          {targets.map((row) => `${row.urgency} ${row.days}d`).join(" · ")}
        </span>
      </div>

      {breaching > 0 && (
        <Alert variant="destructive">
          <CalendarClock className="h-4 w-4" />
          <AlertTitle>
            {breaching} referral{breaching === 1 ? "" : "s"} past target
          </AlertTitle>
          <AlertDescription>
            A breach stays a breach after the patient is finally seen. One that
            turns green the moment somebody deals with it is a breach nobody
            counts.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="pt-6">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Referral</TableHead>
                  <TableHead>Specialty</TableHead>
                  <TableHead>Urgency</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>The question</TableHead>
                  <TableHead className="text-right">Waiting</TableHead>
                  <TableHead className="text-right">Target</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.reference}
                    className={cn(
                      "cursor-pointer",
                      row.breaching && "bg-destructive/5",
                    )}
                    onClick={() => onOpen(row.reference)}
                  >
                    <TableCell>
                      <span className="font-mono text-xs">{row.reference}</span>
                      <span className="block truncate">{row.patient}</span>
                      <span className="block text-xs text-muted-foreground">
                        {row.mrn} · from {row.referrer}
                      </span>
                    </TableCell>
                    <TableCell>
                      {row.specialty}
                      <span className="block text-xs text-muted-foreground">
                        {humanise(row.direction)}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={URGENCY_TONE[row.urgency] ?? "outline"}>
                        {row.urgency}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{humanise(row.status)}</Badge>
                      {row.awaiting_answer && (
                        <span className="block text-xs text-amber-600">
                          awaiting answer
                        </span>
                      )}
                    </TableCell>
                    {/* Wherever a referral appears, so does what was asked. */}
                    <TableCell className="max-w-[18rem] truncate text-xs">
                      {row.question || (
                        <span className="text-destructive">none asked</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.days_waiting === null ? "—" : `${row.days_waiting}d`}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right text-xs tabular-nums",
                        row.breaching && "font-medium text-destructive",
                      )}
                    >
                      {day(row.target_date)}
                      {row.breaching && (
                        <span className="block">past target</span>
                      )}
                      {!row.breaching && row.days_to_target !== null && (
                        <span className="block text-muted-foreground">
                          {row.days_to_target}d left
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="py-10 text-center text-sm text-muted-foreground"
                    >
                      {loading ? (
                        <Loader2 className="inline h-4 w-4 animate-spin" />
                      ) : (
                        "Nothing open."
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Ordered by breach then by target, not by arrival. A routine referral
        from two months ago and an urgent one from yesterday need opposite
        treatment, and a date-ordered list gives them the same.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The pile nobody looks at                                                    */
/* -------------------------------------------------------------------------- */

function Unanswered({
  rows,
  onOpen,
}: {
  rows: UnansweredReferral[];
  onOpen: (reference: string) => void;
}) {
  return (
    <div className="space-y-3">
      <Alert variant={rows.length > 0 ? "destructive" : "default"}>
        {rows.length > 0 ? (
          <MailQuestion className="h-4 w-4" />
        ) : (
          <CheckCircle2 className="h-4 w-4" />
        )}
        <AlertTitle>
          {rows.length === 0
            ? "Every patient who has been seen has been reported back on"
            : `${rows.length} patient${rows.length === 1 ? " was" : "s were"} seen and the referrer has been told nothing`}
        </AlertTitle>
        <AlertDescription>
          Every other status is somebody waiting for something to happen. This
          one is something having happened that nobody passed on — and it is
          invisible in any list ordered by status.
        </AlertDescription>
      </Alert>

      {rows.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Referral</TableHead>
                  <TableHead>Specialty</TableHead>
                  <TableHead>They asked</TableHead>
                  <TableHead>Referrer</TableHead>
                  <TableHead className="text-right">Seen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.reference}
                    className="cursor-pointer"
                    onClick={() => onOpen(row.reference)}
                  >
                    <TableCell>
                      <span className="font-mono text-xs">{row.reference}</span>
                      <span className="block">{row.patient}</span>
                      <span className="block text-xs text-muted-foreground">
                        {row.mrn}
                      </span>
                    </TableCell>
                    <TableCell>{row.specialty}</TableCell>
                    <TableCell className="max-w-[20rem] text-sm">
                      {row.question || (
                        <span className="text-muted-foreground">
                          nothing specific was asked
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{row.referrer}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        row.days_since_seen > 21 && "text-destructive",
                      )}
                    >
                      {row.days_since_seen}d ago
                      <span className="block text-xs text-muted-foreground">
                        {day(row.seen_at)}
                      </span>
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
/* One referral                                                                */
/* -------------------------------------------------------------------------- */

function ReferralDetail({
  reference,
  onBack,
}: {
  reference: string;
  onBack: () => void;
}) {
  const [referral, setReferral] = useState<Referral | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [dialog, setDialog] = useState<null | "respond" | "decline">(null);

  const load = useCallback(async () => {
    setReferral(await api.get<Referral>(`/referrals/${reference}/`));
  }, [reference]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/referrals/${reference}/${path}/`, body);
      await load();
      return true;
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!referral) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  const destination =
    referral.to_provider_name ||
    referral.to_department_name ||
    referral.to_clinician_name ||
    referral.specialty;

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back to referrals
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {referral.reference}
            <Badge variant="outline" className="ml-2 align-middle">
              {humanise(referral.status)}
            </Badge>
            <Badge
              variant={URGENCY_TONE[referral.urgency] ?? "outline"}
              className="ml-1 align-middle"
            >
              {referral.urgency}
            </Badge>
          </h1>
          <p className="text-sm text-muted-foreground">
            {referral.patient_name} · {referral.patient_mrn} ·{" "}
            {referral.referrer_name} → {destination}
          </p>
          <p className="text-sm">{referral.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {referral.status === "draft" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void act("send", { method: "email" })}
            >
              <Send className="h-4 w-4" />
              Send
            </Button>
          )}
          {referral.status === "sent" && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void act("acknowledge")}
            >
              Acknowledge receipt
            </Button>
          )}
          {["sent", "acknowledged"].includes(referral.status) && (
            <>
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void act("accept")}
              >
                Accept
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setDialog("decline")}
              >
                <Ban className="h-4 w-4" />
                Decline
              </Button>
            </>
          )}
          {["accepted", "booked"].includes(referral.status) && (
            <>
              <Button size="sm" disabled={busy} onClick={() => void act("seen")}>
                Mark seen
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => void act("did-not-attend")}
              >
                Did not attend
              </Button>
            </>
          )}
          {referral.seen_at && (
            <Button size="sm" onClick={() => setDialog("respond")}>
              <MailQuestion className="h-4 w-4" />
              {referral.responded_at ? "Answer again" : "Answer the referrer"}
            </Button>
          )}
        </div>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {/* The two states this module exists to make visible. */}
      {referral.awaiting_answer && (
        <Alert variant="destructive">
          <MailQuestion className="h-4 w-4" />
          <AlertTitle>Seen, and the referrer has been told nothing</AlertTitle>
          <AlertDescription>
            {referral.referrer_name} asked: {referral.question || "nothing specific"}
            {referral.seen_at &&
              ` — the patient was seen on ${day(referral.seen_at)}.`}
          </AlertDescription>
        </Alert>
      )}
      {referral.is_breaching && (
        <Alert variant="destructive">
          <CalendarClock className="h-4 w-4" />
          <AlertTitle>Past target</AlertTitle>
          <AlertDescription>
            {referral.urgency} referrals should be seen by{" "}
            {day(referral.target_date)}.
            {referral.seen_at
              ? ` This one was seen on ${day(referral.seen_at)}, and stays counted as a breach.`
              : " It has not been seen."}
          </AlertDescription>
        </Alert>
      )}
      {referral.status === "declined" && (
        <Alert>
          <Ban className="h-4 w-4" />
          <AlertTitle>Declined — {humanise(referral.decline_reason)}</AlertTitle>
          <AlertDescription>{referral.decline_notes}</AlertDescription>
        </Alert>
      )}
      {referral.status === "lapsed" && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Lapsed without an outcome</AlertTitle>
          <AlertDescription>
            Nobody touched this past its target. Recorded as a state rather
            than left looking open, so that referrals which quietly stopped
            mattering are a number somebody can be shown.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">The question</CardTitle>
              <CardDescription>
                A referral asks something specific. A reply of "seen and
                treated" answers nothing, which is the commonest complaint
                referring clinicians have.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p className="rounded-md border-l-4 border-primary bg-muted/40 p-3">
                {referral.question || (
                  <span className="text-destructive">
                    Nothing specific was asked.
                  </span>
                )}
              </p>
              {referral.clinical_summary && (
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Clinical summary
                  </p>
                  <p>{referral.clinical_summary}</p>
                </div>
              )}
              {referral.provisional_diagnosis && (
                <Field
                  label="Provisional diagnosis"
                  value={referral.provisional_diagnosis}
                />
              )}
            </CardContent>
          </Card>

          {referral.responses.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Answers</CardTitle>
                <CardDescription>
                  A referral can be answered more than once — an interim
                  opinion, then a definitive one. Each is kept, because the
                  referrer may have acted on the first.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {referral.responses.map((response) => (
                  <div
                    key={response.uuid}
                    className={cn(
                      "rounded-md border p-3 text-sm",
                      response.is_interim && "border-amber-500/50",
                    )}
                  >
                    <div className="mb-1 flex flex-wrap items-baseline gap-2">
                      <span className="font-medium">
                        {response.responder_name}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {day(response.responded_at)}
                      </span>
                      {response.is_interim && (
                        <Badge variant="secondary">interim</Badge>
                      )}
                      <Badge variant="outline">
                        {response.care_handed_back
                          ? "care handed back"
                          : "keeping the patient"}
                      </Badge>
                    </div>
                    <p className="rounded-md border-l-4 border-emerald-500/60 bg-muted/40 p-2">
                      {response.answer}
                    </p>
                    {response.findings && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {response.findings}
                      </p>
                    )}
                    {response.advice_to_referrer && (
                      <p className="mt-1">
                        <span className="text-xs uppercase tracking-wide text-muted-foreground">
                          For you to do
                        </span>
                        <br />
                        {response.advice_to_referrer}
                      </p>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">What has happened</CardTitle>
            <CardDescription>
              Sent, acknowledged, seen and answered are four different things.
              Collapsing them is how a referral sits for four months with
              everybody assuming somebody else is chasing it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="relative space-y-3 border-l pl-5">
              {referral.events.map((event, index) => (
                <li key={index} className="relative text-sm">
                  <span className="absolute -left-[1.45rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" />
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{humanise(event.event)}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {day(event.happened_at)}
                    </span>
                  </div>
                  {event.detail && (
                    <p className="text-xs text-muted-foreground">
                      {event.detail}
                    </p>
                  )}
                  {event.actor_name && (
                    <p className="text-xs text-muted-foreground">
                      {event.actor_name}
                    </p>
                  )}
                </li>
              ))}
            </ol>

            {referral.letter_generated_at && (
              <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">
                The letter was assembled and frozen on{" "}
                {day(referral.letter_generated_at)}. It says what was known
                then, not what is true now.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {dialog === "respond" && (
        <RespondDialog
          referral={referral}
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await act("respond", body)) setDialog(null);
          }}
        />
      )}
      {dialog === "decline" && (
        <DeclineDialog
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={async (body) => {
            if (await act("decline", body)) setDialog(null);
          }}
        />
      )}
    </div>
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
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-xl">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">{children}</CardContent>
      </Card>
    </div>
  );
}

function RespondDialog({
  referral,
  busy,
  onClose,
  onSubmit,
}: {
  referral: Referral;
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState({
    answer: "",
    findings: "",
    diagnosis: "",
    treatment: "",
    advice: "",
  });
  const [handedBack, setHandedBack] = useState(true);
  const [interim, setInterim] = useState(false);

  const set = (key: string) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <Shell
      title="Answer the referrer"
      description="The question is above the box on purpose: a response that recites the history without answering it is the commonest complaint referring clinicians have."
    >
      {/* The question, wherever the referral is. */}
      <div className="rounded-md border-l-4 border-primary bg-muted/40 p-3 text-sm">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {referral.referrer_name} asked
        </p>
        <p>
          {referral.question || (
            <span className="text-destructive">
              Nothing specific — say what you found and what you advise.
            </span>
          )}
        </p>
      </div>

      <div className="space-y-1">
        <Label htmlFor="a-answer">Your answer</Label>
        <Textarea
          id="a-answer"
          rows={3}
          value={form.answer}
          onChange={set("answer")}
          placeholder="Yes — start basal insulin. Metformin and gliclazide at maximum dose are not controlling her."
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="a-diagnosis">Diagnosis</Label>
          <Input
            id="a-diagnosis"
            value={form.diagnosis}
            onChange={set("diagnosis")}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="a-treatment">Treatment</Label>
          <Input
            id="a-treatment"
            value={form.treatment}
            onChange={set("treatment")}
          />
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="a-findings">Findings</Label>
        <Textarea
          id="a-findings"
          rows={2}
          value={form.findings}
          onChange={set("findings")}
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="a-advice">What you would like them to do</Label>
        <Textarea
          id="a-advice"
          rows={2}
          value={form.advice}
          onChange={set("advice")}
          placeholder="Review fasting glucose weekly and titrate. Refer back if HbA1c is above 8% at three months."
        />
        <p className="text-xs text-muted-foreground">
          The half of a reply that makes it actionable rather than
          informational.
        </p>
      </div>

      <div className="space-y-2 rounded-md border p-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={handedBack}
            onChange={(event) => setHandedBack(event.target.checked)}
          />
          Handing care back to the referrer
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={interim}
            onChange={(event) => setInterim(event.target.checked)}
          />
          This is an interim opinion — investigations are still outstanding
        </label>
        <p className="text-xs text-muted-foreground">
          A letter that does not say which leaves both ends assuming the other
          is following up. An interim answer keeps the referral open.
        </p>
      </div>

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy || form.answer.trim().length < 10}
          onClick={() =>
            onSubmit({
              ...form,
              care_handed_back: handedBack,
              is_interim: interim,
            })
          }
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Send the answer
        </Button>
      </div>
    </Shell>
  );
}

function DeclineDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [reasons, setReasons] = useState<DeclineReason[]>([]);
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    void api
      .get<DeclineReason[]>("/referrals/decline-reasons/")
      .then((rows) => {
        setReasons(rows);
        setReason(rows[0]?.key ?? "");
      })
      .catch(() => setReasons([]));
  }, []);

  return (
    <Shell
      title="Decline this referral"
      description="A declined referral is more useful to the referring clinic than a silent one — but only if the reason can be counted. Forty declines for 'insufficient information' is a template problem, not forty individual mistakes."
    >
      <div className="space-y-1">
        <Label htmlFor="d-reason">Reason</Label>
        <Select
          id="d-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        >
          {reasons.map((row) => (
            <option key={row.key} value={row.key}>
              {row.label}
            </option>
          ))}
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="d-notes">What the referrer should do</Label>
        <Textarea
          id="d-notes"
          rows={3}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="No neurological examination recorded, no imaging. Please repeat with both."
        />
      </div>
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onClose}>
          Cancel
        </Button>
        <Button
          className="flex-1"
          disabled={busy || !reason}
          onClick={() => onSubmit({ reason, notes })}
        >
          Decline
        </Button>
      </div>
    </Shell>
  );
}

/* -------------------------------------------------------------------------- */
/* Performance                                                                 */
/* -------------------------------------------------------------------------- */

function Performance({ facility }: { facility: string }) {
  const [report, setReport] = useState<ReferralSummaryReport | null>(null);

  useEffect(() => {
    const query = new URLSearchParams({ report: "summary" });
    if (facility) query.set("facility", facility);
    void api
      .get<ReferralSummaryReport>(`/referrals/reports/?${query}`)
      .then(setReport)
      .catch(() => setReport(null));
  }, [facility]);

  if (!report) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Since {day(report.since)}</CardTitle>
          <CardDescription>
            Four numbers a clinical director asks for and most systems cannot
            produce: how many breached, why referrals are declined, how long
            the answer takes, and how many were never answered at all.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Fact label="Sent" value={String(report.sent)} />
          <Fact label="Seen" value={String(report.seen)} />
          <Fact
            label="Breached"
            value={
              report.breach_percent === null ? "—" : `${report.breach_percent}%`
            }
            hint={`${report.breached} referrals`}
            tone={report.breached > 0 ? "text-destructive" : undefined}
          />
          <Fact
            label="Answered"
            value={
              report.answered_percent === null
                ? "—"
                : `${report.answered_percent}%`
            }
            hint={`${report.answered} of ${report.seen} seen`}
          />
          <Fact
            label="Seen, not answered"
            value={String(report.seen_but_unanswered)}
            tone={
              report.seen_but_unanswered > 0 ? "text-destructive" : undefined
            }
          />
          <Fact
            label="Lapsed"
            value={String(report.lapsed)}
            hint={`${report.did_not_attend} did not attend`}
            tone={report.lapsed > 0 ? "text-amber-600" : undefined}
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">How long it takes</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <Fact
              label="Median days to be seen"
              value={
                report.median_days_to_be_seen === null
                  ? "—"
                  : String(report.median_days_to_be_seen)
              }
            />
            <Fact
              label="Median days to answer"
              value={
                report.median_days_to_answer === null
                  ? "—"
                  : String(report.median_days_to_answer)
              }
              hint="from being seen"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Why referrals are declined</CardTitle>
            <CardDescription>
              {report.declined} declined. The aggregate is what tells a
              referring clinic what to fix.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1">
            {Object.entries(report.decline_reasons).map(([reason, count]) => (
              <div
                key={reason}
                className="flex items-center justify-between gap-2 text-sm"
              >
                <span>{humanise(reason)}</span>
                <span className="tabular-nums">{count}</span>
              </div>
            ))}
            {Object.keys(report.decline_reasons).length === 0 && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                None declined.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">By specialty</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Specialty</TableHead>
                <TableHead className="text-right">Sent</TableHead>
                <TableHead className="text-right">Seen</TableHead>
                <TableHead className="text-right">Breached</TableHead>
                <TableHead className="text-right">Answered</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(report.by_specialty).map(([specialty, row]) => (
                <TableRow key={specialty}>
                  <TableCell>{specialty}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.sent}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.seen}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.breached > 0 && "text-destructive",
                    )}
                  >
                    {row.breached}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.answered < row.seen && "text-amber-600",
                    )}
                  >
                    {row.answered}
                  </TableCell>
                </TableRow>
              ))}
              {Object.keys(report.by_specialty).length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    Nothing sent in the window.
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
/* Providers                                                                   */
/* -------------------------------------------------------------------------- */

function Providers() {
  const [rows, setRows] = useState<ExternalProvider[]>([]);

  useEffect(() => {
    void api
      .get<Paginated<ExternalProvider>>("/referrals/providers/")
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Where we refer</CardTitle>
        <CardDescription>
          A directory rather than free text on each referral, so that "how many
          patients did we send there last year, and how many came back with an
          answer" is a question with an answer.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Provider</TableHead>
              <TableHead>Accepts</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Reachable by</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.uuid}>
                <TableCell>
                  {row.name}
                  <span className="block text-xs text-muted-foreground">
                    {row.code} · {row.district}
                  </span>
                </TableCell>
                <TableCell className="max-w-[16rem] text-xs">
                  {row.specialties.join(", ") || "—"}
                </TableCell>
                <TableCell className="text-xs">
                  {row.phone}
                  {row.email && <span className="block">{row.email}</span>}
                </TableCell>
                <TableCell className="text-xs">
                  {row.accepts_email ? (
                    <Badge variant="outline">email</Badge>
                  ) : (
                    <span className="text-muted-foreground">
                      post only — a referral marked emailed here never left the
                      building
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="py-10 text-center text-sm text-muted-foreground"
                >
                  No providers in the directory.
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
    <div className="rounded-md border p-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("text-lg font-semibold tabular-nums", tone)}>{value}</p>
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
