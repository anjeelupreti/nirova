/**
 * Notifications, where every product people already use puts them: a bell
 * in the top bar, a count on it, and a panel that opens in place.
 *
 * It used to be a sidebar item — a whole page to learn whether anything had
 * happened. The bell answers that from any screen; the panel shows the latest
 * few and lets them be opened or marked read without leaving the work; "View
 * all" goes to the full page for filtering, dismissing with a note, and
 * preferences.
 *
 * The count is **outstanding**, not unread: an approval somebody has glanced at
 * four times is still waiting for them. It turns red when anything critical
 * is open, because that is the one case where colour should interrupt.
 */

import * as React from "react";
import * as Popover from "@radix-ui/react-popover";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, ChevronRight } from "lucide-react";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { NotificationRow, NotificationSummary } from "@/types";
import { formatDayMonth } from "@/lib/dates";

const REFRESH_MS = 60_000;

function ago(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days < 7 ? `${days}d` : formatDayMonth(iso);
}

export function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [summary, setSummary] = React.useState<NotificationSummary | null>(null);
  const [rows, setRows] = React.useState<NotificationRow[] | null>(null);
  const [view, setView] = React.useState<"waiting" | "all">("waiting");

  const loadSummary = React.useCallback(() => {
    api.get<NotificationSummary>("/notifications/summary/").then(setSummary).catch(() => undefined);
  }, []);

  const loadRows = React.useCallback(() => {
    setRows(null);
    const path = view === "waiting" ? "/notifications/?outstanding=true" : "/notifications/?limit=20";
    api
      .get<{ results?: NotificationRow[] } | NotificationRow[]>(path)
      .then((data) => setRows((Array.isArray(data) ? data : data.results ?? []).slice(0, 8)))
      .catch(() => setRows([]));
  }, [view]);

  React.useEffect(() => {
    loadSummary();
    const timer = window.setInterval(loadSummary, REFRESH_MS);
    const onFocus = () => loadSummary();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [loadSummary]);

  React.useEffect(() => {
    if (open) loadRows();
  }, [open, loadRows]);

  const count = summary?.outstanding ?? 0;
  const critical = (summary?.critical ?? 0) > 0;

  const openRow = (row: NotificationRow) => {
    if (!row.read_at) void api.post(`/notifications/${row.uuid}/read/`).catch(() => undefined);
    setOpen(false);
    loadSummary();
    navigate(row.link || "/notifications");
  };

  const markAllRead = async () => {
    await api.post("/notifications/read-all/").catch(() => undefined);
    loadSummary();
    loadRows();
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={count ? `Notifications, ${count} waiting` : "Notifications"}
          className="relative grid h-9 w-9 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Bell className="h-[18px] w-[18px]" />
          {count > 0 && (
            <span
              className={cn(
                "absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full px-1 text-[10px] font-semibold leading-none text-white",
                critical ? "bg-critical" : "bg-primary",
              )}
            >
              {count > 9 ? "9+" : count}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          className="z-50 w-[22rem] overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-floating"
        >
          <div className="flex items-center justify-between border-b px-4 py-3">
            <p className="text-sm font-semibold">Notifications</p>
            <button
              type="button"
              onClick={() => void markAllRead()}
              disabled={!summary?.unread}
              className="flex items-center gap-1 text-xs font-medium text-primary hover:underline disabled:pointer-events-none disabled:opacity-40"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              Mark all read
            </button>
          </div>

          <div className="flex gap-1 border-b px-3 py-2 text-xs" role="tablist">
            {(["waiting", "all"] as const).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={view === key}
                onClick={() => setView(key)}
                className={cn(
                  "rounded-md px-2.5 py-1 font-medium transition-colors",
                  view === key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {key === "waiting" ? `Waiting${count ? ` (${count})` : ""}` : "All"}
              </button>
            ))}
          </div>

          <div className="max-h-[22rem] overflow-y-auto">
            {rows === null ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2].map((index) => (
                  <div key={index} className="h-10 animate-pulse rounded-md bg-muted" />
                ))}
              </div>
            ) : rows.length === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-muted-foreground">
                You're all caught up.
              </p>
            ) : (
              <ul>
                {rows.map((row) => (
                  <li key={row.uuid}>
                    <button
                      type="button"
                      onClick={() => openRow(row)}
                      className="flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/60"
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                          row.read_at ? "bg-transparent" : row.category === "critical" ? "bg-critical" : "bg-primary",
                        )}
                      />
                      <span className="min-w-0 flex-1">
                        <span className={cn("block truncate text-sm", !row.read_at && "font-semibold")}>
                          {row.title}
                        </span>
                        {row.body && (
                          <span className="block truncate text-xs text-muted-foreground">{row.body}</span>
                        )}
                      </span>
                      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                        {ago(row.raised_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              setOpen(false);
              navigate("/notifications");
            }}
            className="flex w-full items-center justify-center gap-1 border-t px-4 py-2.5 text-sm font-medium text-primary hover:bg-accent/60"
          >
            View all
            <ChevronRight className="h-4 w-4" />
          </button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
