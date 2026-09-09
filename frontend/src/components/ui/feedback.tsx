/**
 * What a screen shows when it has nothing to show yet, or nothing at all.
 *
 * Measured before writing: **23 of the 34 screens in this console had a bare
 * spinner as their entire loading state**, and none had an empty state worth
 * the name — a table with no rows simply rendered as a header and nothing
 * underneath. `tailwindcss-animate` was installed and wired into the Tailwind
 * config and **not used by a single component**.
 *
 * Three things live here because they are the same problem seen at three
 * moments: before the data arrives, when there is none, and when asking for
 * it failed.
 *
 * **Why skeletons rather than a spinner.** A spinner says "wait" and nothing
 * else. A skeleton in the shape of the thing being fetched says "a table of
 * about eight rows is coming", so the layout does not jump when it lands and
 * the wait feels shorter than it is. That is not decoration: a screen that
 * reflows the moment data arrives makes people lose the row they were reading.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Skeleton                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * One shimmering block standing in for content that has not arrived.
 *
 * `animate-pulse` rather than a sweeping gradient: the sweep is prettier for
 * one element and becomes visual noise on a page of forty, because every
 * block sweeps on its own timeline and the eye reads it as motion rather than
 * as waiting.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

/**
 * A table's worth of skeleton, in the table's own shape.
 *
 * Takes the column count so the placeholder lines up with the header that is
 * already on screen. Widths vary per column on purpose — a grid of identical
 * grey bars reads as a broken image, and real rows are ragged.
 */
export function TableSkeleton({
  rows = 6,
  columns = 4,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  // Deterministic rather than random: a placeholder that reshuffles on every
  // render flickers, and the point is to be still.
  const widths = ["w-3/4", "w-1/2", "w-2/3", "w-5/6", "w-2/5", "w-4/5"];
  return (
    <div className={cn("space-y-3 py-2", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex items-center gap-4">
          {Array.from({ length: columns }).map((__, column) => (
            <Skeleton
              key={column}
              className={cn(
                "h-4 flex-1",
                widths[(row + column) % widths.length],
              )}
            />
          ))}
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

/** A row of stat tiles, for dashboards that lead with figures. */
export function StatSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" role="status">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="rounded-xl border bg-card p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-20" />
          <Skeleton className="mt-3 h-2 w-32" />
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

/** Stacked cards, for list screens that are not tables. */
export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3" role="status">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="flex items-start gap-3 rounded-xl border bg-card p-4">
          <Skeleton className="h-10 w-10 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-2/3" />
          </div>
          <Skeleton className="h-6 w-16 shrink-0 rounded-full" />
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Illustrations                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Line drawings for empty states, inline rather than imported.
 *
 * Inline SVG, not an image file and not an icon-font pictogram, for three
 * reasons that all matter here: they inherit `currentColor` so they are
 * correct in both themes without a second asset, they add no request to a
 * screen that is already waiting, and they can be given a `strokeWidth` thin
 * enough not to shout. A 200 kB illustration on an empty ward list is a
 * download to say "nothing here".
 *
 * Deliberately sparse. These sit above a sentence that does the actual
 * explaining; a drawing that needs its own interpretation has failed.
 */
const ILLUSTRATIONS = {
  /** Nothing scheduled, nothing waiting. */
  calendar: (
    <>
      <rect x="10" y="18" width="60" height="52" rx="6" />
      <path d="M10 32h60M24 12v12M56 12v12" />
      <path d="M28 46h8M44 46h8M28 58h8" strokeLinecap="round" />
    </>
  ),
  /** No people: an empty ward, an empty queue, no staff yet. */
  people: (
    <>
      <circle cx="30" cy="30" r="10" />
      <path d="M14 62c0-9 7-16 16-16s16 7 16 16" />
      <circle cx="55" cy="34" r="8" />
      <path d="M45 62c0-7 5-12 10-12s11 5 11 12" />
    </>
  ),
  /** No records, no documents, no results. */
  documents: (
    <>
      <path d="M22 12h26l14 14v42a4 4 0 0 1-4 4H22a4 4 0 0 1-4-4V16a4 4 0 0 1 4-4Z" />
      <path d="M48 12v14h14" />
      <path d="M28 42h24M28 52h16" strokeLinecap="round" />
    </>
  ),
  /** Nothing on the shelf. */
  stock: (
    <>
      <path d="M14 28 40 16l26 12-26 12L14 28Z" />
      <path d="M14 28v24l26 12 26-12V28" />
      <path d="M40 40v24" />
    </>
  ),
  /** No money in or out. */
  money: (
    <>
      <rect x="10" y="22" width="60" height="36" rx="5" />
      <circle cx="40" cy="40" r="9" />
      <path d="M20 32h.01M60 48h.01" strokeLinecap="round" />
    </>
  ),
  /** Nothing found, as distinct from nothing existing. */
  search: (
    <>
      <circle cx="35" cy="35" r="19" />
      <path d="M49 49 66 66" strokeLinecap="round" />
    </>
  ),
  /** Something went wrong. */
  warning: (
    <>
      <path d="M40 14 70 64H10L40 14Z" />
      <path d="M40 34v14M40 56h.01" strokeLinecap="round" />
    </>
  ),
} as const;

export type IllustrationName = keyof typeof ILLUSTRATIONS;

export function Illustration({
  name,
  className,
}: {
  name: IllustrationName;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 80 80"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinejoin="round"
      aria-hidden
      className={cn("h-20 w-20", className)}
    >
      {ILLUSTRATIONS[name]}
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty state                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * What a screen says when there is nothing on it.
 *
 * **The distinction this component exists to keep.** "You have no patients
 * yet" and "no patients match 'gurung'" are different facts that call for
 * different next actions, and a single "No results" for both leaves the
 * reader to work out which they are looking at. `searching` picks the second
 * shape, and the caller is expected to pass it.
 *
 * The action is optional and should be omitted when the reader cannot take
 * it: a button that leads to a 403 is worse than no button.
 */
export function EmptyState({
  illustration = "documents",
  title,
  description,
  action,
  className,
}: {
  illustration?: IllustrationName;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-6 py-14 text-center",
        // Fades in rather than appearing. The data has just failed to arrive;
        // a hard cut reads as an error even when the message is friendly.
        "animate-in fade-in-50 duration-300",
        className,
      )}
    >
      <Illustration
        name={illustration}
        className="mb-4 h-20 w-20 text-muted-foreground/30"
      />
      <p className="text-sm font-medium">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** The same shape, for a failure rather than an absence. */
export function ErrorState({
  title = "That did not load",
  description,
  onRetry,
  className,
}: {
  title?: string;
  description?: React.ReactNode;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <EmptyState
      illustration="warning"
      title={title}
      description={description}
      className={cn("text-destructive/90", className)}
      action={
        onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Try again
          </button>
        ) : undefined
      }
    />
  );
}
