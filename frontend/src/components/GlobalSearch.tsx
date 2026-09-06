/**
 * The omnibox: one box, everything the person is allowed to see.
 *
 * It lives in the header rather than on a page because a search you have to
 * navigate to is a search nobody uses -- and because the thing being searched
 * for is almost always a way of *leaving* the screen you are on.
 *
 * Four decisions worth stating.
 *
 * **Stale responses are dropped, not rendered.** Type "ram", then "ramesh":
 * two requests are in flight and the slower one can land last, replacing the
 * right answer with the wrong one. Every request carries a sequence number and
 * anything but the newest is discarded. This is the oldest bug in search boxes
 * and it is invisible until somebody opens the wrong patient.
 *
 * **Refused sources are shown, greyed, with the permission named.** The API
 * takes that position and the UI would undo it by filtering them out: somebody
 * who cannot see a domain they know exists concludes the system lacks it,
 * while somebody told they lack `employee.read` asks for it.
 *
 * **Hits found by reference are labelled.** Those reached past the care
 * relationship -- legitimately, that is the documented lookup -- and a
 * clinician opening one should know which door they came through rather than
 * discover it from a privacy report a month later.
 *
 * **Two characters minimum, matching the backend.** Firing at one character
 * spends a request to be told 400, and the shorter the term the more it is a
 * fishing trip rather than a lookup.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BedDouble,
  Building2,
  CalendarClock,
  FileText,
  FlaskConical,
  Loader2,
  Lock,
  Package,
  Pill,
  Receipt,
  Scan,
  Search,
  UserCog,
  Users,
} from "lucide-react";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SearchHit, SearchResponse } from "@/types";

const MINIMUM = 2;

/** Where each kind of hit lives in this application, and what it looks like. */
const KINDS: Record<string, { icon: typeof Users; route: string | null }> = {
  patient: { icon: Users, route: "/patients" },
  employee: { icon: UserCog, route: "/people" },
  medicine: { icon: Package, route: "/pharmacy" },
  supplier: { icon: Building2, route: "/procurement" },
  invoice: { icon: Receipt, route: "/billing" },
  document: { icon: FileText, route: null },
  appointment: { icon: CalendarClock, route: "/queue" },
  prescription: { icon: Pill, route: "/pharmacy" },
  admission: { icon: BedDouble, route: "/wards" },
  lab: { icon: FlaskConical, route: "/diagnostics" },
  radiology: { icon: Scan, route: "/diagnostics" },
};

export default function GlobalSearch() {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [highlighted, setHighlighted] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  // Monotonic, and the only defence against an out-of-order response. A ref
  // rather than state because it must be read and written without a re-render
  // in between.
  const sequence = useRef(0);

  const run = useCallback(async (value: string) => {
    const trimmed = value.trim();
    if (trimmed.length < MINIMUM) {
      setData(null);
      return;
    }
    const mine = ++sequence.current;
    setBusy(true);
    try {
      const found = await api.get<SearchResponse>(
        `/search/?q=${encodeURIComponent(trimmed)}`,
      );
      if (mine === sequence.current) {
        setData(found);
        setHighlighted(0);
      }
    } catch {
      if (mine === sequence.current) setData(null);
    } finally {
      if (mine === sequence.current) setBusy(false);
    }
  }, []);

  // Debounced, so typing a name is one request rather than one per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => void run(term), 250);
    return () => clearTimeout(handle);
  }, [term, run]);

  // Ctrl/Cmd-K from anywhere. The shortcut people already try.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
        inputRef.current?.focus();
      }
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Clicking away closes it. Without this the panel sits over the screen the
  // person has just decided to go back to.
  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const flat: SearchHit[] = (data?.groups ?? []).flatMap((g) => g.results);

  function go(hit: SearchHit) {
    const kind = KINDS[hit.type];
    setOpen(false);
    setTerm("");
    setData(null);
    if (!kind?.route) return;
    // `focus` rather than a path segment: most screens are lists that own
    // their own selection, and inventing a detail route per domain would be a
    // far larger change than a search box has any business making. A screen
    // that understands the parameter opens the record; one that does not still
    // lands the person in the right place.
    navigate(`${kind.route}?focus=${hit.uuid}`);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((i) => Math.min(i + 1, flat.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && flat[highlighted]) {
      event.preventDefault();
      go(flat[highlighted]);
    }
  }

  // Walks alongside the render so keyboard position matches visual order
  // across groups. Reset here rather than inside the map, which runs again on
  // every render.
  let index = -1;

  return (
    <div ref={boxRef} className="relative max-w-md flex-1">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          ref={inputRef}
          value={term}
          onChange={(event) => {
            setTerm(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search patients, staff, stock…"
          aria-label="Search everything"
          className="h-8 w-full rounded-md border bg-background pl-8 pr-16 text-sm outline-none focus:ring-2 focus:ring-ring"
        />
        {busy ? (
          <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : (
          <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
            Ctrl K
          </kbd>
        )}
      </div>

      {open && term.trim().length >= MINIMUM ? (
        <div className="absolute left-0 top-10 z-50 max-h-[70vh] w-[32rem] max-w-[90vw] overflow-y-auto rounded-md border bg-background shadow-lg">
          {data && data.count === 0 && !busy ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">
              Nothing you can see matches “{data.query}”.
            </p>
          ) : null}

          {(data?.groups ?? []).map((group) => (
            <div key={group.type} className="border-b last:border-b-0">
              <div className="flex items-center justify-between px-3 pb-1 pt-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {group.label}
                </span>
                {group.narrowed_to_your_patients ? (
                  <span className="text-[10px] text-muted-foreground">
                    your patients only
                  </span>
                ) : null}
              </div>
              {group.results.map((hit) => {
                index += 1;
                const at = index;
                const Icon = KINDS[hit.type]?.icon ?? Search;
                return (
                  <button
                    key={`${hit.type}-${hit.uuid}`}
                    type="button"
                    onMouseEnter={() => setHighlighted(at)}
                    onClick={() => go(hit)}
                    className={cn(
                      "flex w-full items-start gap-2.5 px-3 py-2 text-left",
                      at === highlighted ? "bg-muted" : "hover:bg-muted/60",
                    )}
                  >
                    <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{hit.label}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {hit.sublabel}
                      </span>
                    </span>
                    {hit.by_reference ? (
                      // Said plainly. This hit reached past the care
                      // relationship because the reference names it exactly,
                      // and the person clicking should know that now rather
                      // than read it in a privacy report later.
                      <span className="mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        by reference
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          ))}

          {data && data.refused.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5 px-3 py-2">
              <Lock className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="text-[11px] text-muted-foreground">
                Not searched:
              </span>
              {data.refused.map((entry) => (
                <span
                  key={entry.type}
                  title={`Needs ${entry.needs}`}
                  className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {entry.label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
