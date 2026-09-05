/**
 * Emergency access, and the queue that reviews it.
 *
 * This screen exists because an override nobody reviews is theatre. The
 * mechanism — opening a record you have no care relationship with — is
 * deliberately easy; what makes it a control is that somebody reads this
 * afterwards.
 *
 * Four things it does not soften.
 *
 * **The unreviewed count is the headline, and it sits beside the total.**
 * "Eleven waiting" means one thing against twelve and another against four
 * hundred, and a screen that shows only the first number invites the wrong
 * conclusion in both directions.
 *
 * **There is no bulk sign-off.** Every grant is reviewed one at a time with a
 * conclusion attached. A "mark all appropriate" button would empty this queue
 * in a fortnight and the control with it.
 *
 * **A live override is shown as live, at the top, in red.** Everything else
 * here is history; that row is a record somebody has open right now, and it is
 * the only thing on this screen anybody can still do something about.
 *
 * **Grants nobody used are called out rather than hidden.** A grant taken and
 * never read usually means somebody clicked through a warning, which is worth
 * knowing about the warning rather than about the person.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  Loader2,
  MessageCircleQuestion,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { BreakGlassGrant, BreakGlassQueue } from "@/types";
import {
  Alert,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Label,
  Textarea,
} from "@/components/ui/primitives";

type Outcome = "appropriate" | "queried" | "escalated";

const OUTCOMES: { id: Outcome; label: string; icon: typeof CheckCircle2 }[] = [
  { id: "appropriate", label: "Appropriate", icon: CheckCircle2 },
  { id: "queried", label: "Query with them", icon: MessageCircleQuestion },
  { id: "escalated", label: "Escalate", icon: TriangleAlert },
];

function when(value: string): string {
  const then = new Date(value);
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 60) return `${Math.max(minutes, 0)} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return then.toLocaleDateString();
}

function remaining(value: string): string {
  const minutes = Math.round((new Date(value).getTime() - Date.now()) / 60000);
  if (minutes <= 0) return "expired";
  if (minutes < 60) return `${minutes} min left`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min left`;
}

export default function Privacy() {
  const [queue, setQueue] = useState<BreakGlassQueue | null>(null);
  const [pending, setPending] = useState<BreakGlassGrant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // One open form at a time. A page of expanded note boxes is how somebody
  // pastes the wrong conclusion onto the wrong person's override.
  const [open, setOpen] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("appropriate");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summary, list] = await Promise.all([
        api.get<BreakGlassQueue>("/privacy/grants/summary/"),
        api.get<{ results?: BreakGlassGrant[] } | BreakGlassGrant[]>(
          "/privacy/grants/?pending=true",
        ),
      ]);
      setQueue(summary);
      setPending(Array.isArray(list) ? list : (list.results ?? []));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load the queue.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setOpen(null);
      setNotes("");
      setOutcome("appropriate");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    }
  };

  const submit = (grant: BreakGlassGrant) => {
    if (outcome !== "appropriate" && !notes.trim()) {
      setError(
        "Say why this one is being queried or escalated — the clinician will " +
          "be asked about it.",
      );
      return;
    }
    void act(() =>
      api.post(`/privacy/grants/${grant.uuid}/review/`, {
        outcome,
        notes: notes.trim(),
      }),
    );
  };

  const endNow = (grant: BreakGlassGrant) => {
    const reason = notes.trim();
    if (!reason) {
      setError("Say why the access is being ended. The clinician is told.");
      return;
    }
    void act(() =>
      api.post(`/privacy/grants/${grant.uuid}/revoke/`, { reason }),
    );
  };

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Emergency access
        </h1>
        <p className="text-muted-foreground text-sm">
          Records opened by somebody who was not treating that patient. Every
          one is reviewed by hand.
        </p>
      </header>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}

      {loading ? (
        <div className="text-muted-foreground flex items-center gap-2 py-12">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading
        </div>
      ) : (
        <>
          {queue && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {/* Waiting first and biggest. The total sits under it rather
                  than beside it, because the ratio is the thing to read. */}
              <Card className={cn(queue.pending > 0 && "border-amber-400")}>
                <CardContent className="py-4">
                  <p className="text-3xl font-semibold tabular-nums">
                    {queue.pending}
                  </p>
                  <p className="text-muted-foreground text-sm">
                    waiting to be reviewed
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    of {queue.total} in the last {queue.window_days} days
                  </p>
                </CardContent>
              </Card>

              <Card className={cn(queue.live > 0 && "border-red-500")}>
                <CardContent className="py-4">
                  <p className="text-3xl font-semibold tabular-nums">
                    {queue.live}
                  </p>
                  <p className="text-muted-foreground text-sm">open right now</p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    the only rows anybody can still act on
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="py-4">
                  <p className="text-3xl font-semibold tabular-nums">
                    {queue.never_used}
                  </p>
                  <p className="text-muted-foreground text-sm">taken, never read</p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    usually somebody clicking through a warning
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="py-4 text-sm">
                  <p className="text-muted-foreground mb-2 text-xs uppercase tracking-wide">
                    Outcomes
                  </p>
                  {Object.entries(queue.by_outcome)
                    .filter(([key]) => key !== "pending")
                    .map(([key, count]) => (
                      <div key={key} className="flex justify-between">
                        <span className="capitalize">{key}</span>
                        <span className="tabular-nums">{count}</span>
                      </div>
                    ))}
                </CardContent>
              </Card>
            </div>
          )}

          {/* Said plainly, because the temptation this screen creates is to
              find a faster way through it. */}
          <p className="text-muted-foreground text-xs">
            There is no bulk sign-off. A queue that can be emptied in one click
            is not a control.
          </p>

          {pending.length === 0 ? (
            <Card>
              <CardContent className="text-muted-foreground py-12 text-center text-sm">
                Nothing waiting. Every override has been looked at.
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {pending.map((grant) => {
                const isOpen = open === grant.uuid;
                return (
                  <Card
                    key={grant.uuid}
                    className={cn(
                      "border-l-4",
                      grant.is_live ? "border-l-red-500" : "border-l-amber-400",
                    )}
                  >
                    <CardHeader className="pb-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <CardTitle className="text-base">
                            {grant.user_label} opened {grant.patient_label}
                          </CardTitle>
                          <CardDescription className="mt-1">
                            {when(grant.granted_at)} · read{" "}
                            {grant.use_count === 0
                              ? "not once"
                              : `${grant.use_count} time${grant.use_count === 1 ? "" : "s"}`}
                          </CardDescription>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          {grant.is_live ? (
                            <Badge className="bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200">
                              <Clock className="mr-1 h-3 w-3" />
                              {remaining(grant.expires_at)}
                            </Badge>
                          ) : (
                            <Badge variant="outline">expired</Badge>
                          )}
                          {grant.use_count === 0 && (
                            <Badge variant="outline">
                              <Eye className="mr-1 h-3 w-3" />
                              never read
                            </Badge>
                          )}
                        </div>
                      </div>
                    </CardHeader>

                    <CardContent className="space-y-3">
                      {/* The reason is the whole point of the row. It sits in
                          its own block, in the clinician's words. */}
                      <blockquote className="border-muted-foreground/30 text-sm italic border-l-2 pl-3">
                        {grant.reason}
                      </blockquote>

                      {!isOpen ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setOpen(grant.uuid);
                            setNotes("");
                            setOutcome("appropriate");
                          }}
                        >
                          <ShieldAlert className="mr-2 h-4 w-4" />
                          Review this
                        </Button>
                      ) : (
                        <div className="space-y-3 border-t pt-3">
                          <div className="flex flex-wrap gap-2">
                            {OUTCOMES.map((option) => {
                              const Icon = option.icon;
                              return (
                                <Button
                                  key={option.id}
                                  size="sm"
                                  variant={
                                    outcome === option.id ? "default" : "outline"
                                  }
                                  onClick={() => setOutcome(option.id)}
                                >
                                  <Icon className="mr-2 h-4 w-4" />
                                  {option.label}
                                </Button>
                              );
                            })}
                          </div>

                          <div className="space-y-1">
                            <Label htmlFor={`notes-${grant.uuid}`}>
                              {outcome === "appropriate"
                                ? "Note (optional)"
                                : "Why? (required — the clinician will be asked about it)"}
                            </Label>
                            <Textarea
                              id={`notes-${grant.uuid}`}
                              rows={2}
                              value={notes}
                              onChange={(event) => setNotes(event.target.value)}
                            />
                          </div>

                          <div className="flex flex-wrap gap-2">
                            <Button size="sm" onClick={() => submit(grant)}>
                              Record this
                            </Button>
                            {grant.is_live && (
                              /* Only offered while it is live. Ending an
                                 override that has already expired is a button
                                 that does nothing and teaches people the
                                 screen is unreliable. */
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => endNow(grant)}
                              >
                                End the access now
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setOpen(null);
                                setNotes("");
                              }}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
