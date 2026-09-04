/**
 * The patient portal, from the staff side.
 *
 * The patient-facing half is a separate application by nature: a different
 * audience, a different authentication, a different tenant binding. What
 * belongs in this console is what staff administer — who has been invited,
 * who can see whose record, and what patients have asked that nobody has
 * answered.
 *
 * Three things this screen refuses to soften.
 *
 * **An invitation code is shown once and never again.** The dialog says so
 * before it is generated, because the database keeps only a hash and a
 * clinician who closes the box without writing it down needs to issue a new
 * one rather than go looking.
 *
 * **Proxy grants that give sight of results are marked in red.** Somebody
 * else reading a patient's results is the highest-consequence permission this
 * system hands out, and it is invisible in a list of names and relationships.
 *
 * **"Nobody answered" is the message count that matters.** Read and answered
 * are different, and a queue sorted by unread hides the message somebody
 * opened, meant to come back to, and did not.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Copy,
  Eye,
  KeyRound,
  Loader2,
  MailQuestion,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Paginated,
  Patient,
  PortalAccount,
  PortalAdoption,
  PortalInvitationIssued,
  PortalMessage,
  ProxyAccess,
  ProxyReviewRow,
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

type Tab = "accounts" | "proxies" | "messages" | "adoption";

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: "accounts", label: "Accounts", icon: Users },
  { id: "proxies", label: "Who can see whose", icon: Eye },
  { id: "messages", label: "Messages", icon: MailQuestion },
  { id: "adoption", label: "Take-up", icon: CheckCircle2 },
];

const humanise = (value: string) => value.replace(/_/g, " ");

const day = (value: string | null) =>
  value
    ? new Date(value).toLocaleDateString([], {
        day: "2-digit",
        month: "short",
        year: "2-digit",
      })
    : "—";

export default function PortalPage() {
  const [tab, setTab] = useState<Tab>("accounts");
  const [denied, setDenied] = useState(false);
  const [unanswered, setUnanswered] = useState<PortalMessage[]>([]);

  const loadUnanswered = useCallback(() => {
    void api
      .get<PortalMessage[]>("/portal/messages/unanswered/")
      .then(setUnanswered)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  useEffect(loadUnanswered, [loadUnanswered]);

  if (denied) {
    return (
      <Alert>
        <Users className="h-4 w-4" />
        <AlertTitle>The portal is not visible to you</AlertTitle>
        <AlertDescription>
          Administering patient accounts needs patient-record permissions.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Patient portal</h1>
        <p className="text-sm text-muted-foreground">
          Who has an account, who can see whose record, and what nobody has
          answered.
        </p>
      </div>

      <Alert>
        <KeyRound className="h-4 w-4" />
        <AlertTitle>The patient-facing app is separate</AlertTitle>
        <AlertDescription>
          Patients sign in to their own application with their own credential
          and their own session. This console administers it: it never shows a
          patient's password, and it cannot sign in as one.
        </AlertDescription>
      </Alert>

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
            {id === "messages" && unanswered.length > 0 && (
              <Badge variant="destructive">{unanswered.length}</Badge>
            )}
          </button>
        ))}
      </div>

      {tab === "accounts" && <Accounts />}
      {tab === "proxies" && <Proxies />}
      {tab === "messages" && (
        <Messages unanswered={unanswered} onChanged={loadUnanswered} />
      )}
      {tab === "adoption" && <Adoption />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Accounts                                                                    */
/* -------------------------------------------------------------------------- */

function Accounts() {
  const [rows, setRows] = useState<PortalAccount[]>([]);
  const [inviting, setInviting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    const page = await api.get<Paginated<PortalAccount>>("/portal/accounts/");
    setRows(page.results);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const unlock = async (account: PortalAccount) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/portal/accounts/${account.uuid}/unlock/`, {});
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setInviting(true)}>
          <KeyRound className="h-4 w-4" />
          Invite a patient
        </Button>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Patient</TableHead>
                <TableHead>Signs in with</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Registered</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((account) => (
                <TableRow key={account.uuid}>
                  <TableCell>
                    {account.patient_name}
                    <span className="block text-xs text-muted-foreground">
                      {account.patient_mrn}
                    </span>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {account.login_identifier}
                    {account.email && (
                      <span className="block text-xs text-muted-foreground">
                        {account.email}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        account.is_locked
                          ? "destructive"
                          : account.status === "active"
                            ? "secondary"
                            : "outline"
                      }
                    >
                      {account.is_locked
                        ? "locked"
                        : humanise(account.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>{day(account.registered_at)}</TableCell>
                  <TableCell>{day(account.last_login_at)}</TableCell>
                  <TableCell className="text-right">
                    {account.is_locked && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void unlock(account)}
                      >
                        Unlock
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    Nobody has an account yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        A lockout expires on its own after a few minutes. Unlocking early is a
        convenience, not a repair — a lockout that never expired would be a
        support call rather than a security control.
      </p>

      {inviting && (
        <InviteDialog
          onClose={() => setInviting(false)}
          onDone={() => {
            setInviting(false);
            void load();
          }}
        />
      )}
    </div>
  );
}

function InviteDialog({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [search, setSearch] = useState("");
  const [patient, setPatient] = useState("");
  const [deliveredBy, setDeliveredBy] = useState("read aloud at the desk");
  const [deliveredTo, setDeliveredTo] = useState("");
  const [issued, setIssued] = useState<PortalInvitationIssued | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const query = search.trim() ? `?search=${encodeURIComponent(search)}` : "";
    void api
      .get<Paginated<Patient>>(`/patients/${query}`)
      .then((page) => setPatients(page.results.slice(0, 25)))
      .catch(() => setPatients([]));
  }, [search]);

  const issue = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setIssued(
        await api.post<PortalInvitationIssued>("/portal/accounts/invite/", {
          patient,
          delivered_by: deliveredBy,
          delivered_to: deliveredTo,
        }),
      );
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not issued.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>Invite a patient</CardTitle>
          <CardDescription>
            An account can only be created against a code issued by somebody
            who saw the patient. Without that, the portal would be "type an MRN
            and a date of birth" — both printed on every document they carry.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          {issued ? (
            <>
              {/* Shown once, and the box says so before it is closed. */}
              <Alert>
                <Copy className="h-4 w-4" />
                <AlertTitle>Write this down now</AlertTitle>
                <AlertDescription>
                  The code is not stored — only a hash of it. Once this box is
                  closed nobody can read it again, and a new invitation has to
                  be issued.
                </AlertDescription>
              </Alert>
              <p className="rounded-md border-2 border-dashed p-4 text-center font-mono text-3xl tracking-widest">
                {issued.code}
              </p>
              <p className="text-center text-sm text-muted-foreground">
                Valid until {day(issued.expires_at)}
              </p>
              <Button className="w-full" onClick={onDone}>
                I have written it down
              </Button>
            </>
          ) : (
            <>
              <div className="space-y-1">
                <Label htmlFor="i-search">Find the patient</Label>
                <Input
                  id="i-search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Name or MRN"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="i-patient">Patient</Label>
                <Select
                  id="i-patient"
                  value={patient}
                  onChange={(event) => setPatient(event.target.value)}
                >
                  <option value="">Choose…</option>
                  {patients.map((row) => (
                    <option key={row.uuid} value={row.uuid}>
                      {row.full_name} · {row.mrn}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="i-by">Given how</Label>
                  <Select
                    id="i-by"
                    value={deliveredBy}
                    onChange={(event) => setDeliveredBy(event.target.value)}
                  >
                    <option value="read aloud at the desk">
                      Read aloud at the desk
                    </option>
                    <option value="printed">Printed and handed over</option>
                    <option value="sms">Sent by SMS</option>
                    <option value="email">Sent by email</option>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="i-to">To whom or what</Label>
                  <Input
                    id="i-to"
                    value={deliveredTo}
                    onChange={(event) => setDeliveredTo(event.target.value)}
                    placeholder="The patient in person"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Recorded because "we sent it to the number on file" is the
                answer to a later question about who could have received it.
              </p>
              <div className="flex gap-2">
                <Button variant="outline" className="flex-1" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  className="flex-1"
                  disabled={busy || !patient}
                  onClick={() => void issue()}
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Issue the code
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Proxy access                                                                */
/* -------------------------------------------------------------------------- */

function Proxies() {
  const [rows, setRows] = useState<ProxyAccess[]>([]);
  const [review, setReview] = useState<ProxyReviewRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [page, stale] = await Promise.all([
      api.get<Paginated<ProxyAccess>>("/portal/proxies/"),
      api.get<ProxyReviewRow[]>("/portal/proxies/review/?days=180"),
    ]);
    setRows(page.results);
    setReview(stale);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const revoke = async (grant: ProxyAccess) => {
    const reason = window.prompt(
      "Withdrawing access takes effect immediately. Why?",
    );
    if (!reason) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/portal/proxies/${grant.uuid}/revoke/`, { reason });
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  const live = rows.filter((row) => row.is_live);

  return (
    <div className="space-y-4">
      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {review.length > 0 && (
        <Alert variant="destructive">
          <Eye className="h-4 w-4" />
          <AlertTitle>
            {review.length} grant{review.length === 1 ? "" : "s"} nobody has
            revisited
          </AlertTitle>
          <AlertDescription>
            Consent given once and never revisited is the mechanism by which an
            estranged relative keeps reading somebody's results for years. Ask.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {live.length} live grant{live.length === 1 ? "" : "s"}
          </CardTitle>
          <CardDescription>
            One account seeing another patient's record. Withdrawal takes
            effect immediately, because access is checked when a record is
            opened rather than resolved at sign-in.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Who</TableHead>
                  <TableHead>May see</TableHead>
                  <TableHead>As</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>Consent</TableHead>
                  <TableHead>Until</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((grant) => (
                  <TableRow
                    key={grant.uuid}
                    className={cn(
                      !grant.is_live && "opacity-50",
                      grant.is_live &&
                        grant.can_see_results &&
                        "bg-destructive/5",
                    )}
                  >
                    <TableCell>{grant.account_holder}</TableCell>
                    <TableCell>{grant.patient_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline">
                        {humanise(grant.relationship)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">
                      {/* The highest-consequence permission, marked. */}
                      {grant.can_see_results && (
                        <Badge variant="destructive">results</Badge>
                      )}{" "}
                      {grant.can_see_invoices && (
                        <Badge variant="secondary">invoices</Badge>
                      )}{" "}
                      {grant.can_book_appointments && (
                        <Badge variant="outline">booking</Badge>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[14rem] truncate text-xs">
                      {grant.consent_evidence}
                    </TableCell>
                    <TableCell className="text-xs">
                      {grant.revoked_at ? (
                        <span className="text-muted-foreground">
                          withdrawn {day(grant.revoked_at)}
                        </span>
                      ) : (
                        day(grant.expires_at)
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {grant.is_live && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => void revoke(grant)}
                        >
                          <Ban className="h-3 w-3" />
                        </Button>
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
                      Nobody has access to anybody else's record.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {review.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Due a conversation</CardTitle>
            <CardDescription>
              Granted more than six months ago, oldest first, with when the
              proxy last actually looked.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {review.map((row) => (
              <div
                key={row.grant}
                className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border px-3 py-2"
              >
                <span>
                  {row.proxy} → {row.patient}{" "}
                  <span className="text-muted-foreground">
                    ({humanise(row.relationship)})
                  </span>
                  {row.can_see_results && (
                    <Badge variant="destructive" className="ml-2">
                      sees results
                    </Badge>
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  granted {row.days_old} days ago · last looked{" "}
                  {row.last_looked ? day(row.last_looked) : "never"}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Messages                                                                    */
/* -------------------------------------------------------------------------- */

function Messages({
  unanswered,
  onChanged,
}: {
  unanswered: PortalMessage[];
  onChanged: () => void;
}) {
  const [replying, setReplying] = useState<PortalMessage | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const send = async () => {
    if (!replying) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/portal/messages/${replying.uuid}/reply/`, { body });
      setReplying(null);
      setBody("");
      onChanged();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not sent.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Alert variant={unanswered.length > 0 ? "destructive" : "default"}>
        {unanswered.length > 0 ? (
          <MailQuestion className="h-4 w-4" />
        ) : (
          <CheckCircle2 className="h-4 w-4" />
        )}
        <AlertTitle>
          {unanswered.length === 0
            ? "Every message has been answered"
            : `${unanswered.length} message${unanswered.length === 1 ? "" : "s"} nobody has answered`}
        </AlertTitle>
        <AlertDescription>
          Read and answered are different. A queue sorted by unread hides the
          message somebody opened, meant to come back to, and did not.
        </AlertDescription>
      </Alert>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {unanswered.map((message) => (
        <Card key={message.uuid}>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-base">{message.subject}</CardTitle>
              <CardDescription>
                {message.patient_name} · {day(message.sent_at)}
              </CardDescription>
            </div>
            <Button
              size="sm"
              onClick={() => {
                setReplying(message);
                setBody("");
              }}
            >
              Reply
            </Button>
          </CardHeader>
          <CardContent>
            <p className="text-sm">{message.body}</p>
          </CardContent>
        </Card>
      ))}

      {unanswered.length === 0 && (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            Nothing waiting.
          </CardContent>
        </Card>
      )}

      {replying && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
          <Card className="my-8 w-full max-w-lg">
            <CardHeader>
              <CardTitle>Reply to {replying.patient_name}</CardTitle>
              <CardDescription>
                The portal tells patients this is not a clinical channel and
                is answered in working hours. A reply that reads as urgent
                advice contradicts what they were told when they wrote.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="rounded-md border-l-4 border-primary bg-muted/40 p-3 text-sm">
                <span className="block font-medium">{replying.subject}</span>
                {replying.body}
              </p>
              <Textarea
                rows={5}
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder="Yes — please book a review appointment and we will issue it then."
              />
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  className="flex-1"
                  onClick={() => setReplying(null)}
                >
                  Cancel
                </Button>
                <Button
                  className="flex-1"
                  disabled={busy || body.trim().length < 5}
                  onClick={() => void send()}
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Send
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Adoption                                                                    */
/* -------------------------------------------------------------------------- */

function Adoption() {
  const [data, setData] = useState<PortalAdoption | null>(null);

  useEffect(() => {
    void api
      .get<PortalAdoption>("/portal/adoption/")
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) {
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
          <CardTitle className="text-base">Take-up</CardTitle>
          <CardDescription>
            Invitations issued against accounts registered is the number that
            says whether the desk is offering it or quietly skipping it — and
            it is invisible if only active accounts are counted.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Fact label="Patients" value={String(data.patients)} />
          <Fact label="Invited" value={String(data.invited)} />
          <Fact
            label="Registered"
            value={
              data.invitation_to_account_percent === null
                ? "—"
                : `${data.invitation_to_account_percent}%`
            }
            hint={`${data.accounts} of ${data.invited} invited`}
          />
          <Fact
            label="Coverage"
            value={
              data.coverage_percent === null ? "—" : `${data.coverage_percent}%`
            }
            hint={`${data.active} active accounts`}
          />
          <Fact
            label="Used in 90 days"
            value={String(data.used_in_90_days)}
            tone={
              data.used_in_90_days < data.active ? "text-amber-600" : undefined
            }
          />
          <Fact
            label="Live proxy grants"
            value={String(data.live_proxy_grants)}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Things to look at</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <Fact
            label="Invitations that expired unused"
            value={String(data.expired_unused_invitations)}
            hint="offered and never taken up"
            tone={
              data.expired_unused_invitations > 0
                ? "text-amber-600"
                : undefined
            }
          />
          <Fact
            label="Accounts locked right now"
            value={String(data.locked_accounts)}
            hint="clears itself in minutes"
          />
        </CardContent>
      </Card>
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
    <div className="rounded-md border p-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("text-lg font-semibold tabular-nums", tone)}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
