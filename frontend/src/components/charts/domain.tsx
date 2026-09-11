/**
 * Forms that exist because this product's questions need them, rather than
 * because a charting library ships them.
 *
 * A waterfall because "where did the money go between opening and closing"
 * is a finance question a bar chart cannot answer. A dumbbell because
 * "before and after, per item" is what every quality initiative reports. A
 * population pyramid because a case-mix by age and sex is how a medical
 * director describes a catchment, and it is the one chart a hospital board
 * will recognise instantly.
 */

import * as React from "react";
import {
  Bar,
  BarChart as RBarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/utils";
import {
  AXIS_PROPS,
  CHROME,
  GRID_PROPS,
  MARK,
  SIGNAL,
  axisFormatter,
  formatValue,
  seriesColor,
  type ValueFormat,
} from "./theme";
import { CURSOR_BAND, ChartFrame, type ChartFrameProps } from "./frame";

/* -------------------------------------------------------------------------- */
/* Waterfall                                                                   */
/* -------------------------------------------------------------------------- */

export interface WaterfallStep {
  label: string;
  /** Signed. Positive adds, negative subtracts. Ignored on a total step. */
  value: number;
  /** A subtotal or closing balance: drawn from the baseline, not floating. */
  isTotal?: boolean;
}

/**
 * How a figure got from its opening balance to its closing one.
 *
 * MRR movement — new, expansion, contraction, churn. Cash: opening,
 * collections, payments, closing. Bed days: available, blocked, occupied.
 *
 * **The floating-bar trick is the whole form**, and it is done here with a
 * transparent spacer bar underneath each step. Recharts has no waterfall, and
 * every third-party one adds a dependency to draw two rectangles.
 */
export function Waterfall({
  steps,
  format = "number",
  currency,
  positiveTone = "good",
  negativeTone = "critical",
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  steps: WaterfallStep[];
  format?: ValueFormat;
  currency?: string;
  positiveTone?: keyof typeof SIGNAL;
  negativeTone?: keyof typeof SIGNAL;
}) {
  const rows = React.useMemo(() => {
    let running = 0;
    return steps.map((step) => {
      if (step.isTotal) {
        // A total is drawn from zero. Its value is wherever the running sum
        // has reached, unless the caller states one — which they should when
        // the closing balance is known independently and ought to be shown
        // even if the steps do not reconcile to it.
        const total = step.value || running;
        running = total;
        return { label: step.label, base: 0, delta: total, total, kind: "total" as const };
      }
      const base = step.value >= 0 ? running : running + step.value;
      const previous = running;
      running += step.value;
      return {
        label: step.label,
        base,
        delta: Math.abs(step.value),
        total: running,
        from: previous,
        kind: step.value >= 0 ? ("up" as const) : ("down" as const),
      };
    });
  }, [steps]);

  const empty = frame.empty ?? steps.length === 0;

  return (
    <ChartFrame
      {...frame}
      empty={empty}
      table={
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-1.5 pr-3 type-label text-muted-foreground">Step</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Change</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Running</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{row.label}</th>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {row.kind === "total"
                    ? "—"
                    : `${row.kind === "down" ? "−" : "+"}${formatValue(row.delta, format, currency)}`}
                </td>
                <td className="py-1.5 pl-3 text-right font-medium tabular-nums">
                  {formatValue(row.total, format, currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <RBarChart data={rows} margin={{ top: 8, right: 10, bottom: 0, left: -8 }} barCategoryGap="24%">
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey="label" {...AXIS_PROPS} interval={0} />
          <YAxis
            {...AXIS_PROPS}
            width={58}
            tickFormatter={axisFormatter(format, currency)}
          />
          <Tooltip
            cursor={CURSOR_BAND}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0]?.payload as (typeof rows)[number];
              return (
                <div className="rounded-lg border bg-popover px-2.5 py-2 text-xs shadow-floating">
                  <p className="mb-1 font-medium">{row.label}</p>
                  {row.kind === "total" ? (
                    <p className="tabular-nums">
                      Balance {formatValue(row.total, format, currency)}
                    </p>
                  ) : (
                    <>
                      <p
                        className={cn(
                          "tabular-nums",
                          row.kind === "up" ? "text-good" : "text-critical",
                        )}
                      >
                        {row.kind === "up" ? "+" : "−"}
                        {formatValue(row.delta, format, currency)}
                      </p>
                      <p className="text-muted-foreground tabular-nums">
                        {formatValue(row.from, format, currency)} →{" "}
                        {formatValue(row.total, format, currency)}
                      </p>
                    </>
                  )}
                </div>
              );
            }}
          />
          <ReferenceLine y={0} stroke={CHROME.axis} strokeWidth={1} />
          {/* The invisible plinth each floating bar stands on. */}
          <Bar dataKey="base" stackId="waterfall" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="delta" stackId="waterfall" radius={[MARK.radius, MARK.radius, 0, 0]} maxBarSize={48}>
            {rows.map((row, index) => (
              <Cell
                key={index}
                fill={
                  row.kind === "total"
                    ? CHROME.emphasis
                    : row.kind === "up"
                      ? SIGNAL[positiveTone]
                      : SIGNAL[negativeTone]
                }
              />
            ))}
          </Bar>
        </RBarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Dumbbell                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Before and after, per item.
 *
 * Turnaround this quarter against last, per test. Waiting time per clinic
 * before and after a rota change. Price against the payer's allowed amount.
 *
 * **A grouped bar chart is the usual answer and it is the wrong one**: it
 * shows two magnitudes and makes the reader compute the gap, when the gap *is*
 * the finding. Here the gap is a drawn line whose length is the answer, and
 * whose direction is coloured by whether it went the right way.
 */
export function Dumbbell({
  rows,
  beforeLabel,
  afterLabel,
  goodDirection,
  format = "number",
  currency,
  className,
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table" | "height"> & {
  rows: { label: string; before: number; after: number }[];
  beforeLabel: string;
  afterLabel: string;
  /** Which way is improvement. Colours the connector, nothing else. */
  goodDirection: "up" | "down";
  format?: ValueFormat;
  currency?: string;
  className?: string;
}) {
  const values = rows.flatMap((row) => [row.before, row.after]);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const span = max - min || 1;
  const position = (value: number) => ((value - min) / span) * 100;
  const empty = frame.empty ?? rows.length === 0;

  const series = [
    { key: "before", label: beforeLabel, color: CHROME.recede },
    { key: "after", label: afterLabel, color: seriesColor(0) },
  ];

  return (
    <ChartFrame
      {...frame}
      series={series}
      empty={empty}
      height={Math.max(140, rows.length * 34 + 20)}
      className={className}
      table={
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-1.5 pr-3 type-label text-muted-foreground">Item</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">{beforeLabel}</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">{afterLabel}</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{row.label}</th>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(row.before, format, currency)}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(row.after, format, currency)}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {row.after > row.before ? "+" : ""}
                  {formatValue(row.after - row.before, format, currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="flex h-full flex-col justify-center gap-2">
        {rows.map((row) => {
          const from = position(row.before);
          const to = position(row.after);
          const improved =
            goodDirection === "up" ? row.after > row.before : row.after < row.before;
          const unchanged = row.after === row.before;
          return (
            <div key={row.label} className="flex items-center gap-3">
              <span className="w-[8rem] shrink-0 truncate text-xs" title={row.label}>
                {row.label}
              </span>
              <div className="relative h-5 flex-1">
                {/* The connector carries the verdict; the dots carry the values. */}
                <span
                  className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full"
                  style={{
                    left: `${Math.min(from, to)}%`,
                    width: `${Math.abs(to - from)}%`,
                    background: unchanged
                      ? CHROME.recede
                      : improved
                        ? SIGNAL.good
                        : SIGNAL.critical,
                  }}
                />
                <span
                  className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2"
                  style={{
                    left: `${from}%`,
                    background: CHROME.recede,
                    // A 2px ring in the surface colour so two dots that land on
                    // top of each other stay countable.
                    ["--tw-ring-color" as string]: CHROME.surface,
                  }}
                  title={`${beforeLabel}: ${formatValue(row.before, format, currency)}`}
                />
                <span
                  className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2"
                  style={{
                    left: `${to}%`,
                    background: seriesColor(0),
                    ["--tw-ring-color" as string]: CHROME.surface,
                  }}
                  title={`${afterLabel}: ${formatValue(row.after, format, currency)}`}
                />
              </div>
              <span className="w-16 shrink-0 text-right text-xs tabular-nums">
                {formatValue(row.after, format, currency)}
              </span>
            </div>
          );
        })}
      </div>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Population pyramid                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Case mix by age band and sex.
 *
 * The chart a medical director draws on a whiteboard when describing a
 * catchment, and the one a board recognises without a legend. Two mirrored bar
 * charts sharing a category axis — which is exactly what it is, and why it
 * does not need a library.
 */
export function PopulationPyramid({
  bands,
  leftLabel = "Male",
  rightLabel = "Female",
  format = "number",
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table" | "height"> & {
  bands: { band: string; left: number; right: number }[];
  leftLabel?: string;
  rightLabel?: string;
  format?: ValueFormat;
}) {
  const max = Math.max(1, ...bands.flatMap((row) => [row.left, row.right]));
  const empty = frame.empty ?? bands.every((row) => row.left === 0 && row.right === 0);

  const series = [
    { key: "left", label: leftLabel, color: seriesColor(0) },
    { key: "right", label: rightLabel, color: seriesColor(2) },
  ];

  return (
    <ChartFrame
      {...frame}
      series={series}
      empty={empty}
      height={Math.max(160, bands.length * 26 + 24)}
      table={
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-1.5 pr-3 type-label text-muted-foreground">Age band</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">{leftLabel}</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">{rightLabel}</th>
            </tr>
          </thead>
          <tbody>
            {bands.map((row) => (
              <tr key={row.band} className="border-b last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{row.band}</th>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(row.left, format)}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(row.right, format)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="flex h-full flex-col justify-center gap-1">
        {/* Oldest at the top, which is the convention and also how the shape
            reads — a pyramid narrows upward. */}
        {[...bands].reverse().map((row) => (
          <div key={row.band} className="flex items-center gap-2 text-[0.6875rem]">
            <div className="flex flex-1 justify-end">
              <span
                className="h-4 rounded-l-sm"
                style={{
                  width: `${(row.left / max) * 100}%`,
                  background: seriesColor(0),
                }}
                title={`${leftLabel} ${row.band}: ${formatValue(row.left, format)}`}
              />
            </div>
            <span className="w-14 shrink-0 text-center tabular-nums text-muted-foreground">
              {row.band}
            </span>
            <div className="flex flex-1">
              <span
                className="h-4 rounded-r-sm"
                style={{
                  width: `${(row.right / max) * 100}%`,
                  background: seriesColor(2),
                }}
                title={`${rightLabel} ${row.band}: ${formatValue(row.right, format)}`}
              />
            </div>
          </div>
        ))}
      </div>
    </ChartFrame>
  );
}
