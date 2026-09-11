/**
 * The furniture every chart shares: title, legend, tooltip, and the four
 * states a chart can be in that are not "here is the data".
 *
 * **The states are the point.** A chart component that only knows how to draw
 * data is a chart component that renders an empty grid when the request fails,
 * which reads as "zero" — the single most dangerous defect a dashboard can
 * have. A bed-occupancy chart that says 0% because the endpoint 500'd, and a
 * bed-occupancy chart that says 0% because the ward is empty, must not look
 * the same. Here they do not.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { ChartSkeleton } from "@/components/ui/loader";
import { Freshness } from "@/components/ui/status";
import {
  CHROME,
  SERIES,
  formatValue,
  seriesColor,
  type ValueFormat,
} from "./theme";

/* -------------------------------------------------------------------------- */
/* Series descriptors                                                          */
/* -------------------------------------------------------------------------- */

export interface SeriesSpec {
  /** The key in each row. */
  key: string;
  /** What a human calls it. Used in the legend, the tooltip and the table. */
  label: string;
  /**
   * Override the slot colour. For a series whose meaning is a *status* —
   * "denied", "critical" — pass the signal colour rather than letting it take
   * a categorical slot.
   */
  color?: string;
  format?: ValueFormat;
}

/** Resolve colours for a set of series, honouring per-series overrides. */
export function resolveSeries(series: SeriesSpec[]): Required<
  Pick<SeriesSpec, "key" | "label" | "color">
>[] {
  return series.map((spec, index) => ({
    key: spec.key,
    label: spec.label,
    color: spec.color ?? seriesColor(index),
  }));
}

/* -------------------------------------------------------------------------- */
/* Legend                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Always present for two or more series; absent for one.
 *
 * A legend for a single series is a box that repeats the title, and it costs
 * the chart a quarter of its height. The title names the series — that is what
 * a title is for.
 *
 * Swatches are 8px squares rather than lines, at every chart type. A legend
 * whose marks mimic the chart's (dashes for lines, circles for scatter) looks
 * thorough and reads worse: the eye matches colour first, and varying the
 * shape adds a second thing to match on.
 */
export function ChartLegend({
  series,
  className,
}: {
  series: { key: string; label: string; color: string }[];
  className?: string;
}) {
  if (series.length < 2) return null;

  return (
    <ul
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1.5 pt-1",
        className,
      )}
    >
      {series.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-[2px]"
            style={{ background: item.color }}
          />
          {/* Text stays in the ink colour — never the series colour. A legend
              written in its own hue is unreadable for the light slots and
              turns the legend into decoration. */}
          <span className="text-xs text-muted-foreground">{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/* Tooltip                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The hover layer, on by default.
 *
 * An HTML chart *is* interactive, and shipping one without hover is shipping a
 * picture of a chart. Every value the reader might want to know exactly is one
 * pointer-move away, which is also what lets the axis carry compact labels
 * without losing precision.
 */
export function ChartTooltip({
  active,
  payload,
  label,
  format = "number",
  currency,
  labelFormatter,
}: {
  active?: boolean;
  payload?: { name?: string; dataKey?: string; value?: number; color?: string; payload?: Record<string, unknown> }[];
  label?: string | number;
  format?: ValueFormat;
  currency?: string;
  labelFormatter?: (label: string | number) => string;
}) {
  if (!active || !payload?.length) return null;

  return (
    <div className="min-w-[9rem] rounded-lg border bg-popover px-2.5 py-2 text-popover-foreground shadow-floating">
      {label != null ? (
        <p className="mb-1.5 text-xs font-medium">
          {labelFormatter ? labelFormatter(label) : label}
        </p>
      ) : null}
      <ul className="space-y-1">
        {payload.map((entry, index) => (
          <li
            key={`${entry.dataKey}-${index}`}
            className="flex items-center justify-between gap-4 text-xs"
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-[2px]"
                style={{ background: entry.color }}
              />
              <span className="truncate text-muted-foreground">
                {entry.name ?? entry.dataKey}
              </span>
            </span>
            <span className="shrink-0 font-medium tabular-nums">
              {formatValue(entry.value, format, currency)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The crosshair a line or area chart shows under the pointer. */
export const CURSOR_LINE = {
  stroke: CHROME.axis,
  strokeWidth: 1,
  strokeDasharray: "3 3",
} as const;

/** The band a bar chart highlights instead of a line. */
export const CURSOR_BAND = { fill: "hsl(var(--muted))", fillOpacity: 0.5 } as const;

/* -------------------------------------------------------------------------- */
/* Texture                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Hatch patterns, for the accessibility and print cases only.
 *
 * Rendered into every chart's `<defs>` so `fill="url(#nirova-hatch-2)"` is
 * available when a caller opts in. Not a default: texture on an ordinary
 * screen chart is decoration, and decoration on a clinical figure costs
 * legibility for nothing.
 */
export function TexturedDefs() {
  return (
    <defs>
      {SERIES.map((color, index) => (
        <pattern
          key={index}
          id={`nirova-hatch-${index}`}
          patternUnits="userSpaceOnUse"
          width="6"
          height="6"
          patternTransform={index % 2 === 0 ? "rotate(45)" : "rotate(135)"}
        >
          <rect width="6" height="6" fill={color} fillOpacity="0.18" />
          <line x1="0" y1="0" x2="0" y2="6" stroke={color} strokeWidth="2.5" />
        </pattern>
      ))}
    </defs>
  );
}

/* -------------------------------------------------------------------------- */
/* Frame                                                                       */
/* -------------------------------------------------------------------------- */

export interface ChartFrameProps {
  title?: React.ReactNode;
  description?: React.ReactNode;
  /**
   * When the underlying figures were read. **Required in spirit on anything on
   * a dashboard** — a KPI with no as-of time is a guess, and a stale one is
   * indistinguishable from a current one.
   */
  asOf?: Date | string | null;
  stale?: boolean;
  /** Controls belonging to this chart: a range switch, a facility filter. */
  actions?: React.ReactNode;
  series?: { key: string; label: string; color: string }[];
  loading?: boolean;
  error?: string | null;
  /** True when there is genuinely nothing — as opposed to nothing yet. */
  empty?: boolean;
  emptyMessage?: string;
  height?: number;
  /**
   * The same numbers as a table, for a screen reader, for a colour-blind
   * reader who wants certainty, and for anyone who wants to copy a figure out.
   * Present on every chart that has one — which is every chart with data.
   */
  table?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}

export function ChartFrame({
  title,
  description,
  asOf,
  stale,
  actions,
  series,
  loading,
  error,
  empty,
  emptyMessage = "Nothing recorded for this period.",
  height = 240,
  table,
  className,
  children,
}: ChartFrameProps) {
  const [showTable, setShowTable] = React.useState(false);

  return (
    <figure className={cn("flex min-w-0 flex-col gap-3", className)}>
      {(title || actions) && (
        <figcaption className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title ? <p className="type-heading">{title}</p> : null}
            {description ? (
              <p className="mt-0.5 type-caption">{description}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {actions}
            {table ? (
              <button
                type="button"
                onClick={() => setShowTable((open) => !open)}
                aria-pressed={showTable}
                title={showTable ? "Show the chart" : "Show the numbers"}
                className="rounded-sm p-1 text-muted-foreground transition-colors duration-quick hover:bg-muted hover:text-foreground"
              >
                <Icon
                  name={showTable ? "report" : "viewTable"}
                  size="sm"
                  label={showTable ? "Show the chart" : "Show the numbers"}
                />
              </button>
            ) : null}
          </div>
        </figcaption>
      )}

      {/*
        The four states, in the order they are most often got wrong:

        error   — said out loud. A chart that fails silently reports zero.
        loading — a skeleton in the chart's shape, so nothing reflows.
        empty   — a positive claim that there is nothing, not a blank grid.
        data    — the chart.
      */}
      {error ? (
        <div
          style={{ height }}
          className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-critical/40 bg-critical-subtle/40 px-4 text-center"
        >
          <Icon name="warning" size="lg" className="text-critical" />
          <p className="text-sm font-medium text-critical-subtle-foreground">
            This chart could not be loaded
          </p>
          <p className="max-w-xs type-caption">{error}</p>
        </div>
      ) : loading ? (
        <ChartSkeleton height={height} />
      ) : empty ? (
        <div
          style={{ height }}
          className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed bg-muted/30 px-4 text-center"
        >
          <Icon name="report" size="lg" className="text-muted-foreground/60" />
          <p className="max-w-xs type-caption">{emptyMessage}</p>
        </div>
      ) : showTable && table ? (
        <div style={{ minHeight: height }} className="overflow-x-auto">
          {table}
        </div>
      ) : (
        <div style={{ height }} className="min-w-0">
          {children}
        </div>
      )}

      {!loading && !error && !empty && !showTable && series ? (
        <ChartLegend series={series} />
      ) : null}

      {asOf !== undefined ? (
        <Freshness at={asOf ?? null} stale={stale} className="mt-0.5" />
      ) : null}
    </figure>
  );
}

/**
 * The table behind a chart, built from the same rows.
 *
 * Generated rather than hand-written per chart, because a table that drifts
 * from its chart is worse than no table — it is two claims about one number.
 */
export function ChartTable({
  rows,
  categoryKey,
  categoryLabel,
  series,
  format = "number",
  currency,
}: {
  rows: Record<string, unknown>[];
  categoryKey: string;
  categoryLabel: string;
  series: { key: string; label: string; color: string }[];
  format?: ValueFormat;
  currency?: string;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b text-left">
          <th scope="col" className="py-1.5 pr-3 type-label text-muted-foreground">
            {categoryLabel}
          </th>
          {series.map((item) => (
            <th
              key={item.key}
              scope="col"
              className="py-1.5 pl-3 text-right type-label text-muted-foreground"
            >
              {item.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index} className="border-b last:border-0">
            <th scope="row" className="py-1.5 pr-3 text-left font-normal">
              {String(row[categoryKey] ?? "—")}
            </th>
            {series.map((item) => (
              <td key={item.key} className="py-1.5 pl-3 text-right tabular-nums">
                {formatValue(row[item.key] as number, format, currency)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
