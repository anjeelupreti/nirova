/**
 * What needs me today.
 *
 * Every module has a screen showing what is pending in it, and somebody who
 * approves purchase orders, signs off tills and reviews leave has to remember
 * to visit three of them. This is the one place that answers the question.
 *
 * **The incomplete banner is the point of this screen, not decoration.** An
 * empty approval queue is a positive claim that there is nothing to approve.
 * If a source failed, saying "nothing waiting" is a lie that costs somebody
 * their afternoon, so a failure is stated at the top, in the way that is hard
 * to scroll past, and the total is marked as at-least rather than exact.
 *
 * **Ordered by what it costs to leave it sitting**, not alphabetically and not
 * by count. An unreviewed emergency access and a shift swap are not the same
 * kind of waiting.
 *
 * **Every group links to the screen that can act on it.** This one lists; it
 * deliberately has no approve buttons. Approving a payroll run out of a
 * summary, without the run in front of you, is exactly the habit the
 * maker-checker rules exist to prevent.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  CheckCircle2,
  Loader2,
  RefreshCw,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MyWorkspace } from "@/types";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/layout";

function waitingFor(since: string | null): string {
  if (!since) return "";
  const days = Math.floor(
    (Date.now() - new Date(since).getTime()) / 86_400_000,
  );
  if (days < 1) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export default function WorkspacePage() {
  const [data, setData] = useState<MyWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<MyWorkspace>("/me/workspace/"));
      setError(null);
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "Your workspace could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && data === null) {
    return (
      <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Gathering what needs you…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="What needs you"
        description={
          <>
            {data?.today.has_employee_record
            ? [data.today.employee, data.today.department, data.today.facility]
                .filter(Boolean)
                .join(" · ")
            : "Signed in without an employee record."}
          </>
        }
        actions={
          <>
            <div className="flex items-center gap-2">
              {data?.notifications.unread ? (
                <Link to="/notifications">
                  <Badge variant="outline" className="gap-1">
                    <Bell className="h-3 w-3" />
                    {data.notifications.unread} unread
                  </Badge>
                </Link>
              ) : null}
              <Button variant="outline" size="sm" onClick={() => void load()}>
                <RefreshCw
                  className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")}
                />
                Refresh
              </Button>
            </div>
          </>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {data && !data.is_complete ? (
        // The most important thing on this screen. Without it, a source that
        // fell over is indistinguishable from a quiet day.
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>This list is incomplete</AlertTitle>
          <AlertDescription>
            {data.broken_sources.map((entry) => entry.label).join(", ")}
            {data.broken_sources.length === 1 ? " could" : " could"} not be
            read, so there may be more waiting than is shown here. Open the
            module directly rather than treating this as empty.
          </AlertDescription>
        </Alert>
      ) : null}

      {data && data.approvals.length === 0 && data.is_complete ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <CheckCircle2 className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">Nothing is waiting for you.</p>
              <p className="text-xs text-muted-foreground">
                Every source was read successfully, so this is a real nothing
                rather than a quiet failure.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {data && data.approvals.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          {/*
            "At least" when a source failed. The number is a claim, and a claim
            the system cannot support should not be stated flatly.
          */}
          {data.is_complete ? "" : "At least "}
          <span className="font-medium text-foreground">
            {data.approvals_total}
          </span>{" "}
          {data.approvals_total === 1 ? "thing is" : "things are"} waiting on
          your decision.
        </p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        {(data?.approvals ?? []).map((group) => (
          <Card key={group.type}>
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm">{group.label}</CardTitle>
              <Badge variant={group.urgency >= 8 ? "destructive" : "outline"}>
                {group.count}
              </Badge>
            </CardHeader>
            <CardContent className="space-y-2 pb-3">
              {group.items.slice(0, 5).map((item) => (
                <div
                  key={item.uuid}
                  className="flex items-start justify-between gap-3 border-b pb-2 last:border-b-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm">{item.title}</p>
                    {item.detail ? (
                      <p className="truncate text-xs text-muted-foreground">
                        {item.detail}
                      </p>
                    ) : null}
                  </div>
                  {/*
                    How long it has been sitting, not when it arrived. "Waiting
                    9 days" is the number somebody acts on; a timestamp is one
                    they have to do arithmetic on first.
                  */}
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {waitingFor(item.waiting_since)}
                  </span>
                </div>
              ))}
              {group.count > 5 ? (
                <p className="text-xs text-muted-foreground">
                  and {group.count - 5} more
                </p>
              ) : null}
              {/*
                A link, not an approve button. Approving a payroll run out of a
                summary, without the run in front of you, is the habit
                maker-checker exists to prevent.
              */}
              <Link
                to={group.screen}
                className="inline-flex items-center gap-1 text-xs font-medium hover:underline"
              >
                Open {group.label.toLowerCase()}
                <ArrowRight className="h-3 w-3" />
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
