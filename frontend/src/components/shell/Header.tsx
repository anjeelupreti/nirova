/**
 * The top bar.
 *
 * Deliberately thin, because the rail now carries the identity and the
 * navigation. What is left here is the three things that must be reachable
 * from every screen without scrolling: the way to find anything, the way to
 * change which organization you are looking at, and you.
 *
 * **The search box is a button, not an input.** It opens the command palette.
 * A second real search field beside a palette that does the same job better
 * splits people between two habits, and the one in the header is always the
 * weaker of the two — no keyboard navigation, no screens, no actions. Showing
 * the shortcut on it teaches the better habit rather than competing with it.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { StatusBadge } from "@/components/ui/status";
import UserMenu from "@/components/UserMenu";
import { NotificationBell } from "@/components/shell/NotificationBell";
import { usePreferences } from "@/hooks/usePreferences";
import type { Membership, Organization } from "@/types";

export function Header({
  organization,
  memberships,
  onSwitchOrganization,
  onOpenPalette,
  user,
  onSignOut,
  isPlatformOnly,
  readOnly,
}: {
  organization: Organization | null;
  memberships: Membership[];
  onSwitchOrganization: (slug: string) => void;
  onOpenPalette: () => void;
  user: { name: string; email: string; role?: string | null };
  onSignOut: () => void;
  isPlatformOnly: boolean;
  readOnly?: boolean;
}) {
  return (
    <header className="sticky top-0 z-40 flex h-header shrink-0 items-center gap-3 border-b border-shell-border bg-shell px-4">
      {/* The palette trigger. Wide on a desk, an icon on a phone — a 320px
          search field on a 375px screen leaves nowhere for anything else. */}
      {isPlatformOnly ? (
        <div className="flex-1" />
      ) : (
        <button
          type="button"
          onClick={onOpenPalette}
          className={cn(
            "group flex h-9 items-center gap-2 rounded-md border border-shell-border bg-shell-active px-2.5 text-sm text-muted-foreground",
            "transition-colors duration-quick ease-smooth hover:border-border-strong hover:text-foreground",
            "w-9 justify-center sm:w-72 sm:justify-start lg:w-96",
          )}
        >
          <Icon name="search" size="md" />
          <span className="hidden flex-1 text-left sm:block">Search…</span>
          <kbd className="hidden rounded border bg-background px-1.5 py-0.5 text-[0.625rem] font-medium sm:block">
            ⌘K
          </kbd>
        </button>
      )}

      <div className="ml-auto flex items-center gap-2">
        {readOnly ? (
          <StatusBadge
            status="read only"
            tone="serious"
            icon="warning"
            label="Read-only"
            className="hidden sm:inline-flex"
          />
        ) : null}

        {/*
          The context switcher, only when there is somewhere to switch to. A
          single-clinic customer should not be shown a control that does
          nothing — the old header rendered a `<select>` with one option.
        */}
        {memberships.length > 1 ? (
          <OrganizationSwitcher
            memberships={memberships}
            current={organization?.slug ?? ""}
            onSwitch={onSwitchOrganization}
          />
        ) : null}

        <ThemeToggle />

        {/* Notifications: a bell with a count and a panel, as in every product
            people already use. Platform staff have no tenant inbox. */}
        {isPlatformOnly ? null : <NotificationBell />}

        <UserMenu
          name={user.name}
          email={user.email}
          role={user.role}
          onSignOut={onSignOut}
        />
      </div>
    </header>
  );
}

/* -------------------------------------------------------------------------- */
/* Organization switcher                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The visible half of the multi-tenancy design: changing the selection changes
 * one HTTP header, and every screen re-renders against a different database.
 *
 * A real menu rather than a bare `<select>`, so each organization can show its
 * status beside its name. A customer in grace or past-due looks identical to a
 * healthy one in a select, and somebody supporting three tenants needs to know
 * which of them is suspended before they wonder why a screen is read-only.
 */
function OrganizationSwitcher({
  memberships,
  current,
  onSwitch,
}: {
  memberships: Membership[];
  current: string;
  onSwitch: (slug: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const active = memberships.find((entry) => entry.organization_slug === current);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-9 max-w-[12rem] items-center gap-1.5 rounded-md border border-shell-border bg-shell-active px-2.5 text-sm transition-colors duration-quick hover:border-border-strong"
      >
        <Icon name="organization" size="sm" className="text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">
          {active?.organization_name ?? "Choose"}
        </span>
        <Icon name="chevronUpDown" size="xs" className="text-muted-foreground" />
      </button>

      {open ? (
        <div
          role="listbox"
          className="absolute right-0 top-full z-50 mt-1 w-72 overflow-hidden rounded-lg border bg-popover p-1 shadow-floating animate-in fade-in-0 zoom-in-[0.98] duration-quick"
        >
          {memberships.map((membership) => {
            const selected = membership.organization_slug === current;
            return (
              <button
                key={membership.uuid}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onSwitch(membership.organization_slug);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors duration-quick",
                  selected ? "bg-accent" : "hover:bg-accent/60",
                )}
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-[0.625rem] font-semibold text-primary">
                  {membership.organization_name.slice(0, 2).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{membership.organization_name}</span>
                  {membership.is_organization_owner ? (
                    <span className="block type-caption">Owner</span>
                  ) : null}
                </span>
                {membership.organization_status !== "active" ? (
                  <StatusBadge status={membership.organization_status} />
                ) : null}
                {selected ? <Icon name="confirm" size="sm" className="text-primary" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Theme                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Light, dark, or whatever the device says.
 *
 * In the header rather than buried in account settings, because a dark theme
 * somebody has to go looking for is a dark theme most people never find — and
 * the ward that wants it at 3am is not going to hunt for it then.
 *
 * Cycles through the three rather than toggling two: "system" is a real
 * choice, and a two-way toggle silently strands anybody who had it.
 */
function ThemeToggle() {
  const { preferences, update } = usePreferences();
  const order = ["system", "light", "dark"] as const;
  const next = order[(order.indexOf(preferences.theme) + 1) % order.length];

  return (
    <button
      type="button"
      onClick={() => void update({ theme: next })}
      title={`Theme: ${preferences.theme}. Switch to ${next}.`}
      aria-label={`Theme: ${preferences.theme}. Switch to ${next}.`}
      className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors duration-quick hover:bg-shell-hover hover:text-foreground"
    >
      <Icon
        name={
          preferences.theme === "dark"
            ? "themeDark"
            : preferences.theme === "light"
              ? "themeLight"
              : "meter"
        }
        size="md"
      />
    </button>
  );
}
