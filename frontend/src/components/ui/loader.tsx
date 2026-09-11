/**
 * Waiting, done properly.
 *
 * The console had one loading state — lucide's `Loader2` with `animate-spin` —
 * and used it for everything from a 40ms refetch to a lazy route chunk. That
 * is wrong in both directions: a spinner for a fast response is a flash of
 * anxiety, and a spinner for a slow one tells you nothing about what is coming.
 *
 * Five distinct waits, five treatments:
 *
 * | Wait | Treatment | Why |
 * |---|---|---|
 * | Under ~250ms | **nothing** | `Delayed` swallows it. A spinner that appears and vanishes reads as a glitch. |
 * | A screen's first load | **skeleton** in the shape of the thing | The layout does not jump when data lands. |
 * | A route chunk | **`RouteProgress`** at the top | Navigation already happened; the page is coming. |
 * | A refresh of what is already on screen | **`Refreshing`** — dim, not replace | Replacing a table you are reading with a spinner loses your place. |
 * | A button you pressed | **`Spinner` inside the button** | The feedback belongs where the action was. |
 *
 * The spinner itself is drawn here rather than borrowed. Lucide's is an icon
 * being rotated; this is an arc on a track, so the *remaining* circle is
 * visible and the motion reads as progress around something rather than as a
 * glyph tumbling.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/feedback";

/* -------------------------------------------------------------------------- */
/* Spinner                                                                     */
/* -------------------------------------------------------------------------- */

const SPINNER_SIZES = {
  xs: { className: "h-3 w-3", stroke: 3 },
  sm: { className: "h-4 w-4", stroke: 2.75 },
  md: { className: "h-5 w-5", stroke: 2.5 },
  lg: { className: "h-8 w-8", stroke: 2 },
} as const;

/**
 * An arc rotating on a visible track.
 *
 * **SVG rather than a spinning bordered `<span>`, and the reason is a defect
 * worth remembering.** The first version was
 * `border-current/25 border-t-current`, which reads perfectly and does not
 * work: Tailwind cannot apply an alpha modifier to `currentColor`, so the
 * class was never emitted at all. The track silently fell through to the
 * global border colour, and the spinner looked subtly wrong in a way nobody
 * would have filed a bug about. Checked in the built stylesheet, not assumed:
 * `grep border-current dist/assets/*.css` returned nothing.
 *
 * `strokeOpacity` on an SVG circle has no such limitation, so the track is a
 * genuine 20% of whatever colour the spinner inherits — which is the point,
 * since it appears on buttons, on cards and on the brand fill.
 */
export function Spinner({
  size = "sm",
  className,
  label,
}: {
  size?: keyof typeof SPINNER_SIZES;
  className?: string;
  /** Announced to screen readers. Omit inside a button that already says it. */
  label?: string;
}) {
  const spec = SPINNER_SIZES[size];

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("inline-block shrink-0 animate-spin", spec.className, className)}
      style={{ animationDuration: "700ms" }}
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth={spec.stroke}
        strokeOpacity={0.2}
      />
      {/*
        A quarter-turn arc. `strokeDasharray` of the full circumference with a
        three-quarter gap, so the visible sweep is exactly 90° at every size —
        a fixed dash length would grow and shrink with the radius.
      */}
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth={spec.stroke}
        strokeLinecap="round"
        strokeDasharray="15.7 47.1"
      />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Delayed                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Show nothing until the wait has actually become a wait.
 *
 * **The most valuable component in this file, and the least visible.** On a
 * fast connection most requests in this product return inside 200ms, and a
 * spinner that appears for 120ms is a flicker — it makes a fast application
 * feel unstable. Below the threshold the user simply sees the old state and
 * then the new one.
 *
 * 250ms because it is comfortably under the ~400ms at which a delay starts to
 * feel like an unexplained hang, and comfortably over the flicker range.
 */
export function Delayed({
  children,
  delay = 250,
}: {
  children: React.ReactNode;
  delay?: number;
}) {
  const [show, setShow] = React.useState(false);

  React.useEffect(() => {
    const timer = window.setTimeout(() => setShow(true), delay);
    return () => window.clearTimeout(timer);
  }, [delay]);

  return show ? <>{children}</> : null;
}

/* -------------------------------------------------------------------------- */
/* Route progress                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The bar at the top of the window while a lazy route chunk downloads.
 *
 * **It never reaches the end on its own.** The `creep` keyframe decelerates
 * towards 90% and stops there; the chunk landing is what completes it. A bar
 * that fills to 100% and then waits is worse than no bar, because it has told
 * a lie you can watch.
 *
 * Rendered as the `Suspense` fallback for the route outlet, replacing a
 * centred spinner that pushed the whole page down and then let it snap back.
 */
export function RouteProgress() {
  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden"
      role="status"
      aria-label="Loading page"
    >
      <div className="h-full w-full origin-left animate-creep bg-primary" />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Refreshing                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Content that is being refetched, dimmed rather than replaced.
 *
 * The rule this enforces: **once a screen has data, it never goes back to a
 * skeleton.** Somebody reading row forty of a ward list who presses refresh
 * should still be looking at row forty. Dimming and blocking clicks says
 * "this is a moment out of date" without taking it away.
 */
export function Refreshing({
  active,
  children,
  className,
}: {
  active: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <div
        className={cn(
          "transition-opacity duration-quick ease-smooth",
          active && "pointer-events-none opacity-55",
        )}
        aria-busy={active || undefined}
      >
        {children}
      </div>
      {active ? (
        <Delayed>
          <div className="absolute right-3 top-3 flex items-center gap-2 rounded-full bg-popover/90 px-2.5 py-1 text-xs text-muted-foreground shadow-floating backdrop-blur">
            <Spinner size="xs" />
            Updating
          </div>
        </Delayed>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Skeletons the existing set was missing                                      */
/* -------------------------------------------------------------------------- */

/**
 * A chart's shape while its data loads.
 *
 * Bars of varying height rather than one grey rectangle: the rectangle reads
 * as a failed image, and the ragged silhouette reads as "a chart is coming".
 */
export function ChartSkeleton({
  height = 220,
  className,
}: {
  height?: number;
  className?: string;
}) {
  // Deterministic heights — a placeholder that reshuffles every render
  // flickers, and the point of it is to be still.
  const bars = [46, 68, 38, 82, 57, 74, 44, 90, 61, 52, 78, 40];
  return (
    <div
      className={cn("flex items-end gap-1.5 px-1", className)}
      style={{ height }}
      role="status"
      aria-label="Loading chart"
    >
      {bars.map((value, index) => (
        <Skeleton
          key={index}
          className="flex-1 rounded-sm"
          style={{ height: `${value}%` }}
        />
      ))}
      <span className="sr-only">Loading chart</span>
    </div>
  );
}

/** A record page: identity block, then the tabbed body. */
export function RecordSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading record">
      <div className="flex items-start gap-4">
        <Skeleton className="h-14 w-14 shrink-0 rounded-full" />
        <div className="min-w-0 flex-1 space-y-2 pt-1">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-3.5 w-72" />
        </div>
        <Skeleton className="h-8 w-24 shrink-0 rounded-md" />
      </div>
      <div className="flex gap-2">
        {[64, 80, 72, 56].map((width, index) => (
          <Skeleton key={index} className="h-8 rounded-md" style={{ width }} />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <Skeleton className="h-32 rounded-lg" />
          <Skeleton className="h-48 rounded-lg" />
        </div>
        <Skeleton className="h-64 rounded-lg" />
      </div>
      <span className="sr-only">Loading record</span>
    </div>
  );
}

/**
 * The whole shell, before the session is known.
 *
 * Replaces a centred "Loading…" on an otherwise blank page. Drawing the frame
 * that is about to exist means the application appears to assemble rather than
 * to appear, and — more practically — a blank page for 400ms during sign-in
 * looks identical to a page that failed.
 */
export function ShellSkeleton() {
  return (
    <div className="flex min-h-screen bg-shell" role="status" aria-label="Loading">
      <div className="hidden w-sidebar shrink-0 flex-col gap-6 border-r border-shell-border p-3 lg:flex">
        <Skeleton className="h-9 w-full rounded-lg" />
        {[4, 5, 3].map((count, group) => (
          <div key={group} className="space-y-1.5">
            <Skeleton className="h-2.5 w-16" />
            {Array.from({ length: count }).map((_, item) => (
              <Skeleton key={item} className="h-8 w-full rounded-md" />
            ))}
          </div>
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-header items-center gap-4 border-b border-shell-border px-4">
          <Skeleton className="h-8 w-72 rounded-md" />
          <Skeleton className="ml-auto h-8 w-8 rounded-full" />
        </div>
        <div className="flex-1 space-y-6 bg-background p-6">
          <Skeleton className="h-8 w-64" />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-24 rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-72 rounded-lg" />
        </div>
      </div>
      <span className="sr-only">Loading</span>
    </div>
  );
}
