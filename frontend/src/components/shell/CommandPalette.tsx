/**
 * ⌘K — go anywhere, find anything, without touching the mouse.
 *
 * **The highest ratio of "this is a serious tool" to effort in the whole
 * redesign.** Everything it does was already possible: every screen was in the
 * sidebar and every record was in the omnibox. What it changes is that a
 * receptionist who knows the patient's name never has to know which screen
 * they are on, and somebody demonstrating the product can cross it in one
 * gesture instead of hunting through a rail.
 *
 * Three sources in one list, in the order a person means them:
 *
 *  1. **Records** — patients, staff, invoices, batches — from `/search/`, the
 *     endpoint the omnibox already used. Typing a name means a person far more
 *     often than it means a screen.
 *  2. **Screens** — everything in `nav.ts`, matched on label *and* on the
 *     synonyms declared there, so "roster" finds Attendance and "OT" finds
 *     Theatre.
 *  3. **Actions** — the handful of verbs that are worth doing from anywhere.
 *
 * **Stale responses are dropped, not rendered.** Type "ram", then "ramesh":
 * two requests are in flight and the slower can land last, replacing the right
 * answer with the wrong one. Every request carries a sequence number and
 * anything but the newest is discarded. This is the oldest bug in search boxes
 * and it is invisible until somebody opens the wrong patient — the omnibox got
 * it right and the mistake would be easy to reintroduce here.
 */

import * as React from "react";
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Icon, type IconName } from "@/components/ui/icon";
import { Spinner } from "@/components/ui/loader";
import type { SearchResponse } from "@/types";
import type { NavGroup, NavItem } from "./nav";

const MINIMUM = 2;
const RECENT_KEY = "nirova.palette.recent";

/**
 * Where each kind of record opens, in *this* application.
 *
 * **The first version of the palette navigated to `hit.url` and was broken for
 * every record it found.** The search endpoint returns an *API* path —
 * `/api/patients/<uuid>/` — because it describes the resource, not the screen.
 * Handed to the router, that matched no route and fell through to the
 * catch-all redirect, so choosing a patient in ⌘K silently took you to your
 * home screen. The omnibox it replaced had a map for exactly this reason, and
 * the map did not come across. It has now.
 *
 * A patient opens their full record. Everything else opens the screen that
 * owns it with `?focus=`, which is what the omnibox did; inventing a detail
 * route per domain would be a promise most screens cannot keep yet.
 */
function destinationFor(hit: { type: string; uuid: string }): string | null {
  if (hit.type === "patient") return `/patients/${hit.uuid}`;
  const screen: Record<string, string> = {
    employee: "/people",
    medicine: "/pharmacy",
    supplier: "/procurement",
    invoice: "/billing",
    appointment: "/queue",
    prescription: "/pharmacy",
    admission: "/wards",
    lab: "/diagnostics",
    radiology: "/diagnostics",
  };
  const route = screen[hit.type];
  // People uses `?employee=`, which is what its profile now reads; the rest use
  // the `?focus=` convention the omnibox established.
  if (hit.type === "employee") return `${route}?employee=${hit.uuid}`;
  return route ? `${route}?focus=${hit.uuid}` : null;
}

/** Where each kind of hit lives, and the glyph that identifies it. */
const HIT_ICON: Record<string, IconName> = {
  patient: "patient",
  employee: "staff",
  medicine: "product",
  supplier: "supplier",
  invoice: "invoice",
  document: "attach",
  appointment: "appointment",
  prescription: "prescription",
  admission: "ward",
  lab: "laboratory",
  radiology: "imaging",
};

interface RecentEntry {
  to: string;
  label: string;
  icon: IconName;
}

function readRecent(): RecentEntry[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as RecentEntry[]) : [];
  } catch {
    return [];
  }
}

function pushRecent(entry: RecentEntry): void {
  try {
    const existing = readRecent().filter((item) => item.to !== entry.to);
    window.localStorage.setItem(
      RECENT_KEY,
      JSON.stringify([entry, ...existing].slice(0, 6)),
    );
  } catch {
    /* Not worth surfacing. */
  }
}

/* -------------------------------------------------------------------------- */
/* The open/close hook                                                         */
/* -------------------------------------------------------------------------- */

/**
 * ⌘K and Ctrl-K, plus `/` when nothing is focused.
 *
 * `/` is the shortcut people who live in the product will actually use, and it
 * is only bound when focus is on the body — otherwise typing a slash into a
 * dosage field would open the palette, which is the kind of clever binding that
 * makes people stop trusting a keyboard shortcut.
 */
export function usePaletteShortcut(onOpen: () => void) {
  React.useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        target?.isContentEditable;

      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpen();
        return;
      }
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        onOpen();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onOpen]);
}

/* -------------------------------------------------------------------------- */
/* The palette                                                                 */
/* -------------------------------------------------------------------------- */

export interface PaletteAction {
  id: string;
  label: string;
  icon: IconName;
  keywords?: string[];
  run: () => void;
}

export function CommandPalette({
  open,
  onOpenChange,
  groups,
  actions = [],
  canSearchRecords = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: NavGroup[];
  actions?: PaletteAction[];
  /** False for a platform operator, who has no tenant to search. */
  canSearchRecords?: boolean;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<SearchResponse | null>(null);
  const [searching, setSearching] = React.useState(false);
  const [recent, setRecent] = React.useState<RecentEntry[]>([]);

  // The sequence guard. A ref rather than state: it must be readable by a
  // response that resolves after several renders, and it must never itself
  // trigger one.
  const sequence = React.useRef(0);

  React.useEffect(() => {
    if (open) setRecent(readRecent());
    else {
      // Cleared on close so reopening never shows the last search's answers
      // against an empty box.
      setQuery("");
      setResults(null);
    }
  }, [open]);

  React.useEffect(() => {
    if (!open || !canSearchRecords) return;
    const term = query.trim();
    if (term.length < MINIMUM) {
      setResults(null);
      setSearching(false);
      return;
    }

    const mine = ++sequence.current;
    setSearching(true);
    // Debounced: 180ms is under the point at which a list feels laggy and
    // comfortably above a fast typist's inter-key gap, so a nine-letter name
    // costs one request rather than nine.
    const timer = window.setTimeout(() => {
      void api
        .get<SearchResponse>(`/search/?q=${encodeURIComponent(term)}`)
        .then((response) => {
          if (mine !== sequence.current) return;
          setResults(response);
        })
        .catch(() => {
          if (mine !== sequence.current) return;
          // A failed search shows the screens and actions rather than an
          // error: the palette is still useful for navigation, and a modal
          // that turns into an error message is a modal people close.
          setResults(null);
        })
        .finally(() => {
          if (mine === sequence.current) setSearching(false);
        });
    }, 180);

    return () => window.clearTimeout(timer);
  }, [query, open, canSearchRecords]);

  const go = React.useCallback(
    (item: { to: string; label: string; icon: IconName }) => {
      pushRecent(item);
      navigate(item.to);
      onOpenChange(false);
    },
    [navigate, onOpenChange],
  );

  const flatItems = React.useMemo(
    () => groups.flatMap((group) => group.items.map((item) => ({ group: group.label, item }))),
    [groups],
  );

  const hits = results?.groups.flatMap((group) => group.results) ?? [];

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Search and navigate"
      // The overlay dims and blurs. The blur is not decoration: it stops the
      // page behind competing for the eye with a list of near-identical rows.
      className="fixed inset-0 z-50 flex items-start justify-center bg-background/70 p-4 pt-[12vh] backdrop-blur-sm"
      shouldFilter={false}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border bg-popover shadow-modal animate-in fade-in-0 zoom-in-[0.98] duration-quick"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b px-3.5">
          <Icon name="search" size="md" className="text-muted-foreground" />
          <Command.Input
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search patients, staff, invoices — or jump to a screen"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {searching ? <Spinner size="xs" className="text-muted-foreground" /> : null}
          <kbd className="hidden rounded border bg-muted px-1.5 py-0.5 text-[0.625rem] font-medium text-muted-foreground sm:block">
            esc
          </kbd>
        </div>

        <Command.List className="max-h-[min(24rem,55vh)] overflow-y-auto overscroll-contain p-1.5">
          <Command.Empty className="px-3 py-8 text-center type-caption">
            {query.trim().length < MINIMUM
              ? "Type at least two characters to search records."
              : searching
                ? "Searching…"
                : "Nothing matched."}
          </Command.Empty>

          {/* Records first: a typed name means a person far more often than a
              screen, and putting the screens first would make somebody arrow
              past six of them every time. */}
          {hits.length > 0 ? (
            <Group heading={`Records (${results?.count ?? hits.length})`}>
              {hits.slice(0, 8).map((hit) => (
                <Item
                  key={`${hit.type}-${hit.uuid}`}
                  value={`record-${hit.type}-${hit.uuid}`}
                  icon={HIT_ICON[hit.type] ?? "view"}
                  label={hit.label}
                  detail={hit.sublabel}
                  // A hit reached past the care relationship — legitimately,
                  // by reference — is labelled, so a clinician opening one
                  // knows which door they came through rather than finding out
                  // from a privacy report a month later.
                  tag={hit.by_reference ? "by reference" : undefined}
                  onSelect={() => {
                    const target = destinationFor(hit);
                    // A document has no screen of its own yet. Closing the
                    // palette on it would look like the selection worked and
                    // then do nothing, so it stays open instead.
                    if (!target) return;
                    navigate(target);
                    onOpenChange(false);
                  }}
                />
              ))}
            </Group>
          ) : null}

          {/* Refused sources are shown, not filtered out. Somebody who cannot
              see a domain they know exists concludes the system lacks it;
              somebody told which permission is missing asks for it. */}
          {results?.refused?.length ? (
            <div className="px-3 pb-1.5 pt-2">
              <p className="type-caption">
                Not searched, for want of permission:{" "}
                {results.refused.map((source) => source.type).join(", ")}
              </p>
            </div>
          ) : null}

          {query.trim().length === 0 && recent.length > 0 ? (
            <Group heading="Recent">
              {recent.map((entry) => (
                <Item
                  key={`recent-${entry.to}`}
                  value={`recent-${entry.to}`}
                  icon={entry.icon}
                  label={entry.label}
                  onSelect={() => go(entry)}
                />
              ))}
            </Group>
          ) : null}

          <Group heading="Screens">
            {flatItems
              .filter(({ item }) => matches(item, query))
              .slice(0, 12)
              .map(({ group, item }) => (
                <Item
                  key={item.to}
                  value={`nav-${item.to}`}
                  icon={item.icon}
                  label={item.label}
                  detail={group}
                  onSelect={() => go({ to: item.to, label: item.label, icon: item.icon })}
                />
              ))}
          </Group>

          {actions.length > 0 ? (
            <Group heading="Actions">
              {actions
                .filter(
                  (action) =>
                    !query ||
                    action.label.toLowerCase().includes(query.toLowerCase()) ||
                    action.keywords?.some((word) =>
                      word.toLowerCase().includes(query.toLowerCase()),
                    ),
                )
                .map((action) => (
                  <Item
                    key={action.id}
                    value={`action-${action.id}`}
                    icon={action.icon}
                    label={action.label}
                    onSelect={() => {
                      action.run();
                      onOpenChange(false);
                    }}
                  />
                ))}
            </Group>
          ) : null}
        </Command.List>

        <div className="flex items-center gap-3 border-t bg-muted/40 px-3.5 py-2 type-caption">
          <Legend keys={["↑", "↓"]} action="navigate" />
          <Legend keys={["↵"]} action="open" />
          <Legend keys={["esc"]} action="close" />
        </div>
      </div>
    </Command.Dialog>
  );
}

/** Label, then declared synonyms. "OT" should find Theatre. */
function matches(item: NavItem, query: string): boolean {
  if (!query.trim()) return true;
  const term = query.trim().toLowerCase();
  return (
    item.label.toLowerCase().includes(term) ||
    (item.keywords?.some((word) => word.toLowerCase().includes(term)) ?? false)
  );
}

function Group({
  heading,
  children,
}: {
  heading: string;
  children: React.ReactNode;
}) {
  // cmdk removes an empty group from the DOM but keeps its heading; rendering
  // nothing when there are no children avoids a stranded label.
  const items = React.Children.toArray(children);
  if (items.length === 0) return null;

  return (
    <Command.Group
      heading={heading}
      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:type-eyebrow [&_[cmdk-group-heading]]:text-muted-foreground"
    >
      {items}
    </Command.Group>
  );
}

function Item({
  value,
  icon,
  label,
  detail,
  tag,
  onSelect,
}: {
  value: string;
  icon: IconName;
  label: string;
  detail?: string;
  tag?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-sm",
        "data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground",
      )}
    >
      <Icon name={icon} size="md" className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {tag ? (
        <span className="shrink-0 rounded-full bg-warning-subtle px-1.5 py-px text-[0.625rem] font-medium text-warning-subtle-foreground">
          {tag}
        </span>
      ) : null}
      {detail ? (
        <span className="shrink-0 truncate type-caption">{detail}</span>
      ) : null}
    </Command.Item>
  );
}

function Legend({ keys, action }: { keys: string[]; action: string }) {
  return (
    <span className="flex items-center gap-1">
      {keys.map((key) => (
        <kbd
          key={key}
          className="rounded border bg-background px-1 py-px text-[0.625rem] font-medium"
        >
          {key}
        </kbd>
      ))}
      {action}
    </span>
  );
}
