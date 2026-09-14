/**
 * Today at work: whether you are checked in, the shift you are on, and the
 * button that changes it.
 *
 * **Check-in was three clicks deep.** It lived inside a banner on the
 * self-service screen, which nobody opens at seven in the morning; the screen
 * people open is My day. The same card now sits on both, reading the same
 * summary, so the two cannot disagree about whether you are in.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, CheckCircle2, Loader2, LogIn, LogOut } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { formatTime } from "@/lib/dates";
import type { ESSMeSummary } from "@/types";
import { Badge, Button, Card, CardContent } from "@/components/ui/primitives";

/** Fired after a check-in or check-out, so every open section re-reads. */
export const ATTENDANCE_CHANGED = "nirova:attendance-changed";

/**
 * The employment summary, or `null` when this person has no employee record.
 * `enabled` is false when the plan has no HR module, and then nothing is asked.
 */
export function useStaffSummary(enabled: boolean) {
  const [summary, setSummary] = useState<ESSMeSummary | null>(null);
  const [loading, setLoading] = useState(enabled);

  const reload = useCallback(async () => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    try {
      setSummary((await api.get<ESSMeSummary | null>("/hr/me/summary/")) ?? null);
    } catch {
      // No employee record, or HR unreachable: the hub shows the sign-in half.
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
    const refresh = () => void reload();
    window.addEventListener(ATTENDANCE_CHANGED, refresh);
    return () => window.removeEventListener(ATTENDANCE_CHANGED, refresh);
  }, [reload]);

  return { summary, loading, reload };
}

function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** The check-in button alone, for a page header. */
export function CheckInButton({ summary }: { summary: ESSMeSummary }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const today = summary.attendance_today;

  if (today?.checked_out_at) {
    return (
      <Badge variant="outline" className="gap-1">
        <CheckCircle2 className="h-3.5 w-3.5 text-good" />
        Day complete · {today.worked_hours}h
      </Badge>
    );
  }

  const action: "in" | "out" = today?.checked_in_at ? "out" : "in";

  async function punch() {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/hr/attendance/check-${action}/`, { source: "web" });
      window.dispatchEvent(new Event(ATTENDANCE_CHANGED));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : `Could not check ${action}.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button
        size="sm"
        variant={action === "in" ? "default" : "outline"}
        disabled={busy}
        onClick={() => void punch()}
      >
        {busy ? (
          <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
        ) : action === "in" ? (
          <LogIn className="mr-1.5 h-4 w-4" />
        ) : (
          <LogOut className="mr-1.5 h-4 w-4" />
        )}
        {action === "in" ? "Check in" : "Check out"}
      </Button>
      {problem ? <span className="text-xs text-destructive">{problem}</span> : null}
    </span>
  );
}

/** One line for the top of My day: status, today's shift, the button. */
export function TodayAtWork({ summary }: { summary: ESSMeSummary }) {
  const today = summary.attendance_today;
  const shift = summary.upcoming_shifts?.find((entry) => entry.date === todayIso());

  const status = today?.checked_out_at
    ? `Checked out at ${formatTime(today.checked_out_at)}`
    : today?.checked_in_at
      ? `In since ${formatTime(today.checked_in_at)}`
      : "Not checked in yet";

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-foreground">
            <CalendarClock className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-medium">{status}</p>
            <p className="truncate text-xs text-muted-foreground">
              {shift
                ? `${shift.shift_name}, ${shift.starts_at}–${shift.ends_at}${shift.is_on_call ? " · on call" : ""}`
                : "No shift on the rota today"}
              {" · "}
              <Link to="/me?tab=time" className="hover:underline">
                Attendance and shifts
              </Link>
            </p>
          </div>
        </div>
        <CheckInButton summary={summary} />
      </CardContent>
    </Card>
  );
}
