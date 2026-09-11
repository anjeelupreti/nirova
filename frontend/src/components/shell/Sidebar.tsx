/**
 * The navigation rail.
 *
 * **What it replaces, and why "just a list of things" was a fair description.**
 * The old rail was ten grey headings and forty links, all at one weight, on the
 * same background as the page, with no icons on the groups, no counts, no way
 * to collapse anything and no way to keep the four screens you actually use
 * near the top. The *grouping* was sound — it had been thought about, and that
 * reasoning is preserved in `nav.ts` — but nothing about the rendering said so.
 * Structure that is invisible is not structure.
 *
 * Five changes, each aimed at one complaint:
 *
 *  1. **The rail is its own surface.** It sits on `--shell`, distinct from the
 *     page, so the application has a frame. Previously header, rail and content
 *     were all one colour and the links appeared to float on the page.
 *  2. **Groups collapse, and remember.** Stored per user per browser, so the
 *     three groups a pharmacist never opens fold away and stay folded.
 *  3. **Pins.** Any screen can be pinned to a section above the groups. This is
 *     the whole of "make it mine" for most people: a nurse pins the ward and
 *     the handover, and the other forty links stop mattering.
 *  4. **Counts.** Approvals waiting and unread notifications are shown where
 *     the eye already is, rather than only inside the screens that hold them.
 *  5. **The organization is at the top of the rail**, not in the far corner of
 *     the header — their name and their mark, in the place a product normally
 *     puts its own.
 */

import * as React from "react";
import { NavLink } from "react-router-dom";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { OrgBrand } from "@/components/ui/brand";
import type { NavGroup, NavItem } from "./nav";

/* -------------------------------------------------------------------------- */
/* Persisted rail state                                                        */
/* -------------------------------------------------------------------------- */

const COLLAPSED_KEY = "nirova.nav.collapsed";
const PINNED_KEY = "nirova.nav.pinned";
const RAIL_KEY = "nirova.nav.rail";

/**
 * Rail state in `localStorage` rather than on the server.
 *
 * Deliberate: which groups you have folded is a property of *this screen* —
 * the 13-inch laptop you carry between wards wants different folds from the
 * 27-inch monitor at the nurses' station — where the theme and density
 * genuinely should follow you between machines and are stored server-side.
 *
 * Every read is wrapped, because `localStorage` throws outright in a locked-
 * down browser profile rather than returning null, and a navigation rail that
 * refuses to render because a preference could not be read is a worse product
 * than one that forgets which groups were folded.
 */
function readStore<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeStore(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* A preference that cannot be saved is not an error worth showing. */
  }
}

export function useRailState(groups: NavGroup[]) {
  const [collapsed, setCollapsed] = React.useState<string[]>(() => {
    const stored = readStore<string[] | null>(COLLAPSED_KEY, null);
    // First run takes the defaults declared on the groups themselves, so a
    // rarely-visited section is folded before anybody has to fold it.
    return stored ?? groups.filter((group) => group.defaultCollapsed).map((group) => group.label);
  });
  const [pinned, setPinned] = React.useState<string[]>(() => readStore(PINNED_KEY, []));
  const [railOpen, setRailOpen] = React.useState<boolean>(() => readStore(RAIL_KEY, true));

  const toggleGroup = React.useCallback((label: string) => {
    setCollapsed((current) => {
      const next = current.includes(label)
        ? current.filter((entry) => entry !== label)
        : [...current, label];
      writeStore(COLLAPSED_KEY, next);
      return next;
    });
  }, []);

  const togglePin = React.useCallback((to: string) => {
    setPinned((current) => {
      const next = current.includes(to)
        ? current.filter((entry) => entry !== to)
        : [...current, to];
      writeStore(PINNED_KEY, next);
      return next;
    });
  }, []);

  const toggleRail = React.useCallback(() => {
    setRailOpen((current) => {
      writeStore(RAIL_KEY, !current);
      return !current;
    });
  }, []);

  return { collapsed, pinned, railOpen, toggleGroup, togglePin, toggleRail };
}

/* -------------------------------------------------------------------------- */
/* One link                                                                    */
/* -------------------------------------------------------------------------- */

function RailLink({
  item,
  count,
  pinned,
  onTogglePin,
  compact,
}: {
  item: NavItem;
  count?: number;
  pinned: boolean;
  onTogglePin: (to: string) => void;
  compact: boolean;
}) {
  return (
    <NavLink
      to={item.to}
      title={compact ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-2.5 rounded-md py-1.5 text-sm transition-colors duration-quick ease-smooth",
          compact ? "justify-center px-0" : "px-2",
          isActive
            ? // **The selected item carries the brand, not a grey.** It was
              // `bg-shell-active` — a neutral lift — which is what every
              // scaffold does and is indistinguishable from a hover at a
              // glance. The brand tint is the one place in the chrome where
              // the identity should be unmistakable, and it is also the only
              // way "where am I" reads from across a room.
              "bg-shell-selected font-medium text-shell-selected-foreground"
            : "text-shell-foreground hover:bg-shell-hover hover:text-shell-active-foreground",
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* A 2px spine on the active item. The colour block alone reads as a
              hover state; the spine is what says "you are here". */}
          <span
            aria-hidden
            className={cn(
              "absolute -left-2 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-full transition-colors duration-quick",
              isActive ? "bg-primary" : "bg-transparent",
            )}
          />
          <Icon
            name={item.icon}
            size="md"
            className={isActive ? "text-primary" : undefined}
          />
          {compact ? null : (
            <>
              <span className="min-w-0 flex-1 truncate">{item.label}</span>

              {count ? (
                <span
                  className={cn(
                    "shrink-0 rounded-full px-1.5 py-px text-[0.625rem] font-semibold tabular-nums",
                    // Counts that represent a decision somebody is waiting on
                    // are not decoration; they carry the brand tint so they
                    // register without shouting.
                    "bg-primary-subtle text-primary-subtle-foreground",
                  )}
                >
                  {count > 99 ? "99+" : count}
                </span>
              ) : null}

              {/*
                The pin. Hidden until the row is hovered or the screen is
                already pinned, so forty pin buttons are not competing with
                forty labels — but it is a real button in the tab order, not a
                CSS-only affordance.
              */}
              <button
                type="button"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onTogglePin(item.to);
                }}
                aria-label={pinned ? `Unpin ${item.label}` : `Pin ${item.label}`}
                className={cn(
                  "shrink-0 rounded-sm p-0.5 transition-opacity duration-quick",
                  "opacity-0 focus-visible:opacity-100 group-hover:opacity-100",
                  pinned && "opacity-100 text-primary",
                )}
              >
                <Icon name="pin" size="xs" />
              </button>
            </>
          )}
        </>
      )}
    </NavLink>
  );
}

/* -------------------------------------------------------------------------- */
/* The rail                                                                    */
/* -------------------------------------------------------------------------- */

export interface SidebarProps {
  groups: NavGroup[];
  organizationName: string;
  organizationLogo?: string | null;
  facilityName?: string | null;
  planCode?: string | null;
  counts?: { notifications?: number; workspace?: number };
  state: ReturnType<typeof useRailState>;
  className?: string;
}

export function Sidebar({
  groups,
  organizationName,
  organizationLogo,
  facilityName,
  planCode,
  counts,
  state,
  className,
}: SidebarProps) {
  const { collapsed, pinned, railOpen, toggleGroup, togglePin, toggleRail } = state;
  const compact = !railOpen;

  const allItems = React.useMemo(
    () => groups.flatMap((group) => group.items),
    [groups],
  );
  const pinnedItems = React.useMemo(
    () =>
      pinned
        .map((to) => allItems.find((item) => item.to === to))
        .filter((item): item is NavItem => Boolean(item)),
    [pinned, allItems],
  );

  const countFor = (item: NavItem) =>
    item.badge ? counts?.[item.badge] : undefined;

  return (
    <nav
      aria-label="Main"
      className={cn(
        "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-shell-border bg-shell transition-[width] duration-moderate ease-smooth lg:flex",
        compact ? "w-sidebar-collapsed" : "w-sidebar",
        className,
      )}
    >
      {/*
        The customer's identity, at the top of their own system. This is the
        single cheapest thing in the whole redesign and the one that most
        changes how the product feels in a demo: a hospital sees its own name
        where every other SaaS puts the vendor's.
      */}
      <div
        className={cn(
          "flex h-header shrink-0 items-center border-b border-shell-border",
          compact ? "justify-center px-2" : "gap-2 px-3",
        )}
      >
        {compact ? (
          <div
            className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-[0.6875rem] font-semibold text-primary"
            title={organizationName}
          >
            {organizationName.slice(0, 2).toUpperCase()}
          </div>
        ) : (
          <OrgBrand
            name={organizationName}
            logoUrl={organizationLogo}
            facility={facilityName}
            className="min-w-0 flex-1"
          />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-3">
        {/* Pinned, above everything. */}
        {pinnedItems.length > 0 ? (
          <div className="mb-4">
            {compact ? null : (
              <p className="mb-1 px-2 type-eyebrow text-shell-heading">Pinned</p>
            )}
            <div className="space-y-0.5">
              {pinnedItems.map((item) => (
                <RailLink
                  key={`pinned-${item.to}`}
                  item={item}
                  count={countFor(item)}
                  pinned
                  onTogglePin={togglePin}
                  compact={compact}
                />
              ))}
            </div>
            {compact ? null : <div className="mt-4 border-t border-shell-border" />}
          </div>
        ) : null}

        <div className={cn(compact ? "space-y-2" : "space-y-1")}>
          {groups.map((group) => {
            const isCollapsed = collapsed.includes(group.label) && !compact;
            const groupCount = group.items.reduce(
              (sum, item) => sum + (countFor(item) ?? 0),
              0,
            );

            return (
              <div key={group.label}>
                {compact ? (
                  // Collapsed to icons, the headings become a rule. A group
                  // label at 11px in a 56px rail is unreadable, and truncating
                  // it to three letters is worse than omitting it.
                  <div className="my-2 border-t border-shell-border" />
                ) : (
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.label)}
                    aria-expanded={!isCollapsed}
                    className="group flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors duration-quick hover:bg-shell-hover"
                  >
                    <Icon
                      name="chevronRight"
                      size="xs"
                      className={cn(
                        "text-shell-heading transition-transform duration-quick ease-smooth",
                        !isCollapsed && "rotate-90",
                      )}
                    />
                    <span className="min-w-0 flex-1 truncate type-eyebrow text-shell-heading">
                      {group.label}
                    </span>
                    {/* A folded group still reports what is waiting inside it,
                        otherwise folding a group hides an approval queue. */}
                    {isCollapsed && groupCount > 0 ? (
                      <span className="rounded-full bg-primary-subtle px-1.5 py-px text-[0.625rem] font-semibold tabular-nums text-primary-subtle-foreground">
                        {groupCount}
                      </span>
                    ) : null}
                  </button>
                )}

                {isCollapsed ? null : (
                  <div className={cn("space-y-0.5", compact ? "" : "mt-0.5 pl-2")}>
                    {group.items.map((item) => (
                      <RailLink
                        key={item.to}
                        item={item}
                        count={countFor(item)}
                        pinned={pinned.includes(item.to)}
                        onTogglePin={togglePin}
                        compact={compact}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div
        className={cn(
          "flex shrink-0 items-center gap-2 border-t border-shell-border px-3 py-2",
          compact && "justify-center px-2",
        )}
      >
        {compact ? null : planCode ? (
          <span className="truncate rounded-full bg-shell-hover px-2 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-shell-foreground">
            {planCode}
          </span>
        ) : null}
        <button
          type="button"
          onClick={toggleRail}
          aria-label={railOpen ? "Collapse the sidebar" : "Expand the sidebar"}
          title={railOpen ? "Collapse the sidebar" : "Expand the sidebar"}
          className="ml-auto rounded-md p-1.5 text-shell-foreground transition-colors duration-quick hover:bg-shell-hover hover:text-shell-active-foreground"
        >
          <Icon name={railOpen ? "collapse" : "expand"} size="md" />
        </button>
      </div>
    </nav>
  );
}

/* -------------------------------------------------------------------------- */
/* Narrow screens                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The rail, on a phone or a tablet held in portrait.
 *
 * A horizontally scrolling strip rather than a hamburger. A hamburger hides
 * the whole product behind one tap on the device a ward round actually uses,
 * and the tap is a poor target with gloves on.
 *
 * Pinned items come first here, because on a small screen the strip is what a
 * person can reach without scrolling and it should hold their own four
 * screens rather than the alphabet.
 */
export function NarrowNav({
  groups,
  pinned,
  counts,
}: {
  groups: NavGroup[];
  pinned: string[];
  counts?: { notifications?: number; workspace?: number };
}) {
  const items = React.useMemo(() => {
    const all = groups.flatMap((group) => group.items);
    const pinnedFirst = pinned
      .map((to) => all.find((item) => item.to === to))
      .filter((item): item is NavItem => Boolean(item));
    const rest = all.filter((item) => !pinned.includes(item.to));
    return [...pinnedFirst, ...rest];
  }, [groups, pinned]);

  return (
    <nav
      aria-label="Main"
      className="sticky top-header z-30 -mx-4 flex gap-1.5 overflow-x-auto border-b border-shell-border bg-shell px-4 py-2 [scrollbar-width:none] lg:hidden [&::-webkit-scrollbar]:hidden"
    >
      {items.map((item) => {
        const count = item.badge ? counts?.[item.badge] : undefined;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                "flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors duration-quick",
                isActive
                  ? "border-transparent bg-primary text-primary-foreground"
                  : "border-shell-border bg-shell-active text-shell-foreground",
              )
            }
          >
            <Icon name={item.icon} size="sm" />
            {item.label}
            {count ? (
              <span className="rounded-full bg-background/25 px-1.5 text-[0.625rem] font-semibold tabular-nums">
                {count}
              </span>
            ) : null}
          </NavLink>
        );
      })}
    </nav>
  );
}
