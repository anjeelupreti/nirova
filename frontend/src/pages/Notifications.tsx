/**
 * The notification centre.
 *
 * Every module in this system produces things that need somebody's attention,
 * and until now each kept its own queue. This screen is the one place they
 * arrive, and its whole job is to make "what is waiting for me" answerable in
 * one glance.
 *
 * Four decisions it does not soften.
 *
 * **"Waiting" is the default tab, not "unread".** Unread is a fact about
 * attention; waiting is a fact about work. A nurse who has read an approval
 * four times has still not approved it, and a screen that opens on unread
 * shows an empty list to somebody with twelve outstanding tasks.
 *
 * **Clearing the badge does not clear the work.** "Mark all read" is offered
 * because catching up is a real need — but it says what it does, and nothing
 * on this screen dismisses anything in bulk. A single button that emptied the
 * approvals queue would be a disaster dressed as a convenience.
 *
 * **A critical notification cannot be cleared without typing what was done.**
 * The server refuses it; this screen asks for it up front rather than letting
 * somebody press a button and be told off afterwards.
 *
 * **Critical is shown as unchangeable in preferences, not hidden from them.**
 * Leaving it off the list would look like an oversight. Showing it fixed, with
 * the reason beside it, is the honest version.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  BellRing,
  CheckCheck,
  ClipboardCheck,
  Info,
  Loader2,
  Lock,
  Megaphone,
  Settings2,
  Timer,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  NotificationCategory,
  NotificationPreference,
  NotificationRow,
  NotificationSummary,
} from "@/types";
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
  Input,
  Label,
  Textarea,
} from "@/components/ui/primitives";

type Tab = "waiting" | "all" | "preferences";

const TABS: { id: Tab; label: string; icon: typeof BellRing }[] = [
  { id: "waiting", label: "Waiting for me", icon: ClipboardCheck },
  { id: "all", label: "Everything", icon: BellRing },
  { id: "preferences", label: "What I am told about", icon: Settings2 },
];

/**
 * Category presentation, in one place.
 *
 * Severity is carried by an icon and a word as well as a colour: a red dot on
 * its own is invisible to a colour-blind reader and meaningless on a printout.
 */
const CATEGORY: Record<
  NotificationCategory,
  { label: string; icon: typeof Info; tone: string; rail: string }
> = {
  critical: {
    label: "Critical",
    icon: AlertOctagon,
    tone: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
    rail: "border-l-red-500",
  },
  warning: {
    label: "Warning",
    icon: AlertTriangle,
    tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
    rail: "border-l-amber-500",
  },
  approval: {
    label: "Approval",
    icon: ClipboardCheck,
    tone: "bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-200",
    rail: "border-l-violet-500",
  },
  task: {
    label: "Task",
    icon: CheckCheck,
    tone: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
    rail: "border-l-sky-500",
  },
  reminder: {
    label: "Reminder",
    icon: Timer,
    tone: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-200",
    rail: "border-l-teal-500",
  },
  information: {
    label: "Information",
    icon: Info,
    tone: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200",
    rail: "border-l-slate-400",
  },
};

function when(value: string): string {
  const then = new Date(value);
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 8) return `${days} d ago`;
  return then.toLocaleDateString();
}

export default function Notifications() {
  const [tab, setTab] = useState<Tab>("waiting");
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const [summary, setSummary] = useState<NotificationSummary | null>(null);
  const [preferences, setPreferences] = useState<NotificationPreference[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Which row is being cleared, and the note being typed for it. Held here
  // rather than in the row so that only one is ever open — a page of expanded
  // note boxes is how somebody pastes the wrong note onto the wrong alert.
  const [clearing, setClearing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [announcement, setAnnouncement] = useState({ title: "", body: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, counts] = await Promise.all([
        api.get<{ count: number; results: NotificationRow[] }>(
          tab === "waiting"
            ? "/notifications/?outstanding=true"
            : "/notifications/?limit=100",
        ),
        api.get<NotificationSummary>("/notifications/summary/"),
      ]);
      setRows(list.results);
      setSummary(counts);
      if (tab === "preferences") {
        const prefs = await api.get<{ preferences: NotificationPreference[] }>(
          "/notifications/preferences/",
        );
        setPreferences(prefs.preferences);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load notifications.");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    }
  };

  const clear = async (row: NotificationRow) => {
    if (row.category === "critical" && !note.trim()) {
      setError("Say what was done about this before clearing it.");
      return;
    }
    await act(() =>
      api.post(`/notifications/${row.uuid}/dismiss/`, { note: note.trim() }),
    );
    setClearing(null);
    setNote("");
  };

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Notifications</h1>
          <p className="text-muted-foreground text-sm">
            Everything from every module that wants something from you.
          </p>
        </div>
        {summary && (
          <div className="flex items-center gap-2">
            {summary.critical > 0 && (
              <Badge className={CATEGORY.critical.tone}>
                {summary.critical} critical
              </Badge>
            )}
            <Badge variant="outline">{summary.outstanding} waiting</Badge>
            <Badge variant="outline">{summary.unread} unread</Badge>
            <Button
              variant="outline"
              size="sm"
              disabled={summary.unread === 0}
              onClick={() => void act(() => api.post("/notifications/read-all/"))}
            >
              <CheckCheck className="mr-2 h-4 w-4" />
              Mark all read
            </Button>
          </div>
        )}
      </header>

      {/* Said out loud, because the button above is the one people misread. */}
      <p className="text-muted-foreground -mt-4 text-xs">
        Marking everything read clears the badge. It does not approve, dismiss
        or complete anything.
      </p>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        {TABS.map((entry) => {
          const Icon = entry.icon;
          return (
            <Button
              key={entry.id}
              variant={tab === entry.id ? "default" : "outline"}
              size="sm"
              onClick={() => setTab(entry.id)}
            >
              <Icon className="mr-2 h-4 w-4" />
              {entry.label}
              {entry.id === "waiting" && summary && summary.outstanding > 0 && (
                <span className="bg-background/20 ml-2 rounded px-1.5 text-xs">
                  {summary.outstanding}
                </span>
              )}
            </Button>
          );
        })}
      </div>

      {loading ? (
        <div className="text-muted-foreground flex items-center gap-2 py-12">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading
        </div>
      ) : tab === "preferences" ? (
        <PreferencePanel
          preferences={preferences}
          onChange={(category, enabled) =>
            void act(() =>
              api.post("/notifications/preferences/", { category, enabled }),
            )
          }
          announcement={announcement}
          setAnnouncement={setAnnouncement}
          onAnnounce={() =>
            void act(async () => {
              await api.post("/notifications/announce/", announcement);
              setAnnouncement({ title: "", body: "" });
            })
          }
        />
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground py-12 text-center text-sm">
            {tab === "waiting"
              ? "Nothing is waiting for you."
              : "No notifications yet."}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const meta = CATEGORY[row.category] ?? CATEGORY.information;
            const Icon = meta.icon;
            const isClearing = clearing === row.uuid;
            return (
              <Card
                key={row.uuid}
                className={cn(
                  "border-l-4",
                  meta.rail,
                  !row.read_at && "bg-muted/40",
                )}
              >
                <CardContent className="space-y-3 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className={meta.tone}>
                          <Icon className="mr-1 h-3 w-3" />
                          {meta.label}
                        </Badge>
                        <span className="text-muted-foreground text-xs">
                          {row.source} · {when(row.raised_at)}
                        </span>
                        {!row.is_open && (
                          <Badge variant="outline">Situation resolved</Badge>
                        )}
                        {row.dismissed_at && <Badge variant="outline">Cleared</Badge>}
                      </div>
                      <p className="font-medium">{row.title}</p>
                      {row.body && (
                        <p className="text-muted-foreground text-sm">{row.body}</p>
                      )}
                      {/* Why this reached this person. Frozen when it was
                          raised, so it still answers the question a week
                          later after the roster has changed. */}
                      {row.reason && (
                        <p className="text-muted-foreground text-xs italic">
                          You were told because: {row.reason}
                        </p>
                      )}
                      {row.dismissed_note && (
                        <p className="text-xs">
                          <span className="text-muted-foreground">
                            What was done:{" "}
                          </span>
                          {row.dismissed_note}
                        </p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      {!row.read_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            void act(() =>
                              api.post(`/notifications/${row.uuid}/read/`),
                            )
                          }
                        >
                          Mark read
                        </Button>
                      )}
                      {!row.dismissed_at && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setClearing(isClearing ? null : row.uuid);
                            setNote("");
                          }}
                        >
                          {row.category === "critical"
                            ? "Clear with a note"
                            : "Clear"}
                        </Button>
                      )}
                    </div>
                  </div>

                  {isClearing && (
                    <div className="space-y-2 border-t pt-3">
                      <Label htmlFor={`note-${row.uuid}`}>
                        {row.category === "critical"
                          ? "What was done about this? (required)"
                          : "Note (optional)"}
                      </Label>
                      <Textarea
                        id={`note-${row.uuid}`}
                        rows={2}
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder={
                          row.category === "critical"
                            ? "Rang Dr Sharma at 14:20, treatment started."
                            : ""
                        }
                      />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => void clear(row)}>
                          Clear it
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            setClearing(null);
                            setNote("");
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
    </div>
  );
}

function PreferencePanel({
  preferences,
  onChange,
  announcement,
  setAnnouncement,
  onAnnounce,
}: {
  preferences: NotificationPreference[];
  onChange: (category: NotificationCategory, enabled: boolean) => void;
  announcement: { title: string; body: string };
  setAnnouncement: (next: { title: string; body: string }) => void;
  onAnnounce: () => void;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>What I am told about</CardTitle>
          <CardDescription>
            Turning a category off stops it reaching your inbox. Critical
            notifications cannot be turned off — they are how somebody finds
            out a result needs acting on today.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {preferences.map((pref) => {
            const meta = CATEGORY[pref.category] ?? CATEGORY.information;
            const Icon = meta.icon;
            return (
              <div
                key={pref.category}
                className="flex items-center justify-between gap-4 rounded border p-3"
              >
                <div className="flex items-center gap-2">
                  <Badge className={meta.tone}>
                    <Icon className="mr-1 h-3 w-3" />
                    {meta.label}
                  </Badge>
                </div>
                {pref.can_change ? (
                  <Button
                    variant={pref.enabled ? "default" : "outline"}
                    size="sm"
                    onClick={() => onChange(pref.category, !pref.enabled)}
                  >
                    {pref.enabled ? "On" : "Off"}
                  </Button>
                ) : (
                  /* Shown fixed rather than hidden. A category missing from
                     this list would look like an oversight; one shown locked,
                     with the reason above, is the honest version. */
                  <span className="text-muted-foreground flex items-center gap-1 text-xs">
                    <Lock className="h-3 w-3" />
                    Always on
                  </span>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tell everybody something</CardTitle>
          <CardDescription>
            Reaches every active member of the organization, with your name on
            it. Announcements cannot be marked critical — a critical
            notification means a clinical fact needs acting on today, and that
            is raised by the module that knows it, never typed here.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="announce-title">Title</Label>
            <Input
              id="announce-title"
              value={announcement.title}
              onChange={(event) =>
                setAnnouncement({ ...announcement, title: event.target.value })
              }
              placeholder="Fire drill at 3pm"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="announce-body">Detail</Label>
            <Textarea
              id="announce-body"
              rows={3}
              value={announcement.body}
              onChange={(event) =>
                setAnnouncement({ ...announcement, body: event.target.value })
              }
              placeholder="Ward 3 assembles at the rear gate."
            />
          </div>
          <Button
            onClick={onAnnounce}
            disabled={!announcement.title.trim()}
          >
            <Megaphone className="mr-2 h-4 w-4" />
            Send to everybody
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
