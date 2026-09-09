/**
 * The grammar of a screen: heading, tools, sections.
 *
 * **This is the fix for "no proper placement or arrangement", and it is not a
 * widget.** Every one of the 34 screens in this console opened with its own
 * hand-built heading — some `text-xl`, some `text-2xl`, some with a
 * description, some without, the action button on the left on three of them
 * and the right on the rest. Nothing was *wrong* on any single screen; they
 * simply did not agree, and a product where the title moves between pages
 * reads as thirty-four small applications rather than one.
 *
 * So the heading is a component with one shape, and the shape carries the
 * decisions: title left, description under it, actions right, breadcrumb
 * above, and a toolbar row underneath that owns search and filters. A screen
 * that wants something different has to say so, which is the point — the
 * exception becomes visible in the diff instead of being invented silently.
 */

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * The outermost wrapper of every screen.
 *
 * Owns the vertical rhythm so that individual screens stop choosing their own
 * `space-y`, which ranged from 3 to 8 across the console. It also carries the
 * enter animation: content that fades and lifts a few pixels on mount reads as
 * arriving rather than blinking into place, and because it is here it happens
 * on every screen instead of the three somebody remembered.
 */
export function Page({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "space-y-6",
        "animate-in fade-in-0 slide-in-from-bottom-1 duration-300",
        className,
      )}
    >
      {children}
    </div>
  );
}

export interface Crumb {
  label: string;
  to?: string;
}

/**
 * Title, description, and the actions that belong to the whole screen.
 *
 * Actions are for the *page* — "Invite someone", "New invoice". Anything that
 * acts on a selection or a filter belongs in the `Toolbar` below, because a
 * button that changes meaning depending on what is selected should not sit
 * next to the page title where it reads as always-available.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumbs?: Crumb[];
  className?: string;
}) {
  return (
    <header className={cn("space-y-3", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb">
          <ol className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            {breadcrumbs.map((crumb, index) => (
              <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                {index > 0 && (
                  <ChevronRight aria-hidden className="h-3 w-3 opacity-60" />
                )}
                {crumb.to ? (
                  <Link
                    to={crumb.to}
                    className="rounded transition-colors hover:text-foreground"
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="text-foreground">
                    {crumb.label}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      {/* Wraps rather than truncating. A long title on a narrow screen should
          take two lines; a page whose heading is cut off with an ellipsis is
          a page nobody can identify. */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}

/**
 * The row under the heading: search, filters, view switches.
 *
 * Two slots rather than one flex row, because the split is the convention:
 * things that *narrow* what you see go left, things that *change how* you see
 * it go right. Once that holds everywhere, somebody looking for the date
 * filter looks left without thinking about it.
 */
export function Toolbar({
  children,
  trailing,
  className,
}: {
  children?: React.ReactNode;
  trailing?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">{children}</div>
      {trailing && (
        <div className="flex flex-wrap items-center gap-2">{trailing}</div>
      )}
    </div>
  );
}

/**
 * A titled block within a screen.
 *
 * For pages that are several things at once -- a patient's record is
 * demographics, allergies, encounters and invoices -- so those stop being
 * four cards with four differently-sized headings.
 */
export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {title && (
              <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
            )}
            {description && (
              <p className="mt-0.5 text-sm text-muted-foreground">
                {description}
              </p>
            )}
          </div>
          {actions && (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          )}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * A responsive grid for stat tiles.
 *
 * Named rather than repeated, because the breakpoints are a decision: two
 * columns on a tablet at the nurses' station, four on a desk. Six dashboards
 * had six slightly different versions of this line.
 */
export function StatGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid gap-4 sm:grid-cols-2 xl:grid-cols-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * A horizontally scrollable wrapper for anything wide.
 *
 * Wide content is the commonest way a page ends up scrolling sideways on a
 * phone, which breaks every fixed element on it. The rule is that the
 * *container* scrolls and the page never does; this is that rule, named, so
 * it is applied rather than remembered.
 */
export function ScrollX({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("-mx-1 overflow-x-auto px-1", className)}>
      {children}
    </div>
  );
}
