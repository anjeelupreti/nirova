/**
 * Part-to-whole, and the forms that only make sense when the parts sum to
 * something.
 *
 * **A note on the donut, because it is the chart people ask for and the chart
 * that is usually wrong.** Angle is the hardest visual channel to judge: two
 * slices at 22% and 26% are indistinguishable, and a donut with seven slices
 * is a colour key with a hole in it. It is kept here for the two cases where
 * it genuinely wins — a small number of parts where the *composition* is the
 * message rather than the ranking, and the case where a reader expects one
 * because every other system they have used shows one. Past five slices
 * `Donut` folds the tail into "Other" rather than drawing a pinwheel, and for
 * anything ranked, `Chart.Bar` horizontal is the honest form.
 */

import * as React from "react";
import {
  Cell,
  Pie,
  PieChart as RPieChart,
  ResponsiveContainer,
  Tooltip,
  Treemap as RTreemap,
} from "recharts";

import { cn } from "@/lib/utils";
import {
  CHROME,
  SCALE,
  SIGNAL,
  foldSeries,
  formatValue,
  seriesColor,
  type ValueFormat,
} from "./theme";
import { ChartFrame, ChartTooltip, type ChartFrameProps } from "./frame";

interface Slice {
  name: string;
  value: number;
  /** Override for a slice whose meaning is a status rather than an identity. */
  color?: string;
}

/* -------------------------------------------------------------------------- */
/* Donut                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Composition, with the total in the middle.
 *
 * The hole is not decoration: it is where the total goes, and a total in the
 * centre is the one thing a donut does that a bar cannot. Without it, use a
 * bar.
 */
export function Donut({
  slices,
  format = "number",
  currency,
  total,
  totalLabel,
  maxSlices = 5,
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  slices: Slice[];
  format?: ValueFormat;
  currency?: string;
  /** Defaults to the sum. Pass one when the whole is larger than the parts. */
  total?: number;
  totalLabel?: React.ReactNode;
  maxSlices?: number;
}) {
  const folded = React.useMemo(
    () => foldSeries(slices, maxSlices),
    [slices, maxSlices],
  );
  const resolved = folded.map((slice, index) => ({
    key: slice.name,
    label: slice.name,
    value: slice.value,
    color:
      (slices.find((original) => original.name === slice.name)?.color) ??
      (slice.name === "Other" ? CHROME.recede : seriesColor(index)),
  }));

  const sum = resolved.reduce((accumulator, slice) => accumulator + slice.value, 0);
  const shown = total ?? sum;
  const empty = frame.empty ?? sum === 0;

  return (
    <ChartFrame
      {...frame}
      series={resolved}
      empty={empty}
      table={
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-1.5 pr-3 type-label text-muted-foreground">Part</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Value</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Share</th>
            </tr>
          </thead>
          <tbody>
            {resolved.map((slice) => (
              <tr key={slice.key} className="border-b last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{slice.label}</th>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(slice.value, format, currency)}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums text-muted-foreground">
                  {sum ? `${((slice.value / sum) * 100).toFixed(1)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="relative h-full">
        <ResponsiveContainer width="100%" height="100%">
          <RPieChart>
            <Pie
              data={resolved}
              dataKey="value"
              nameKey="label"
              innerRadius="62%"
              outerRadius="92%"
              // A 2px gap in the surface colour between slices, so the
              // boundary is a gap rather than a hairline of a third hue.
              paddingAngle={1.5}
              stroke={CHROME.surface}
              strokeWidth={2}
              startAngle={90}
              endAngle={-270}
            >
              {resolved.map((slice) => (
                <Cell key={slice.key} fill={slice.color} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip format={format} currency={currency} />} />
          </RPieChart>
        </ResponsiveContainer>
        {/* The total, in the hole. Absolutely positioned rather than a Recharts
            label so it can use the product's type scale. */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-semibold tabular-nums">
            {formatValue(shown, format, currency)}
          </span>
          {totalLabel ? (
            <span className="type-caption">{totalLabel}</span>
          ) : null}
        </div>
      </div>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Funnel                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Stages that only ever shrink: a claim from submitted to settled, a lead from
 * enquiry to admission, a purchase requisition to receipt.
 *
 * **The drop between stages is the story, so it is labelled explicitly.** A
 * funnel that shows only the stage totals makes the reader do the subtraction,
 * and the whole reason to draw one is to find the stage that leaks.
 *
 * Coloured from the sequential ramp rather than the categorical one: the
 * stages are *ordered*, and giving each an identity hue implies they are
 * different kinds of thing rather than the same thing later.
 */
export function FunnelChart({
  stages,
  format = "number",
  currency,
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  stages: { name: string; value: number }[];
  format?: ValueFormat;
  currency?: string;
}) {
  const empty = frame.empty ?? stages.every((stage) => stage.value === 0);
  const first = stages[0]?.value ?? 0;

  const data = stages.map((stage, index) => {
    const previous = index === 0 ? stage.value : stages[index - 1].value;
    const dropped = previous - stage.value;
    return {
      ...stage,
      // Ordinal ramp: the step nearest the surface must still clear 2:1, so it
      // starts at index 2 rather than at the lightest step.
      fill: SCALE[Math.min(SCALE.length - 1, 2 + index)],
      dropped,
      dropPercent: previous > 0 ? (dropped / previous) * 100 : 0,
      conversion: first > 0 ? (stage.value / first) * 100 : 0,
    };
  });

  return (
    <ChartFrame
      {...frame}
      empty={empty}
      table={
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-1.5 pr-3 type-label text-muted-foreground">Stage</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Reached</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Lost here</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Of first</th>
            </tr>
          </thead>
          <tbody>
            {data.map((stage) => (
              <tr key={stage.name} className="border-b last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{stage.name}</th>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(stage.value, format, currency)}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums text-muted-foreground">
                  {stage.dropped > 0 ? formatValue(stage.dropped, format, currency) : "—"}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums text-muted-foreground">
                  {stage.conversion.toFixed(0)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {/*
        Drawn as stacked rows rather than with Recharts' `<Funnel>`, because the
        trapezoid shape encodes nothing the width does not, and the leak
        annotation between stages — the part that matters — has nowhere to live
        in the trapezoid version.
      */}
      <div className="flex h-full flex-col justify-center gap-1">
        {data.map((stage, index) => (
          <React.Fragment key={stage.name}>
            {index > 0 && stage.dropped > 0 ? (
              <div className="flex items-center gap-2 pl-[3%] text-[0.6875rem] text-muted-foreground">
                <span className="h-3 w-px bg-border" />
                <span
                  className={cn(
                    stage.dropPercent >= 25 && "font-medium text-serious",
                  )}
                >
                  −{formatValue(stage.dropped, format, currency)} (
                  {stage.dropPercent.toFixed(0)}%)
                </span>
              </div>
            ) : null}
            <div className="flex items-center gap-3">
              <div className="h-8 min-w-[2%] shrink-0 grow-0 basis-auto" style={{ width: `${Math.max(stage.conversion, 4)}%` }}>
                <div
                  className="flex h-full items-center rounded-sm px-2.5"
                  style={{ background: stage.fill }}
                >
                  <span className="truncate text-xs font-semibold text-background tabular-nums">
                    {formatValue(stage.value, format, currency)}
                  </span>
                </div>
              </div>
              <span className="truncate text-sm">{stage.name}</span>
            </div>
          </React.Fragment>
        ))}
      </div>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Treemap                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Composition where there are too many parts for a donut and the parts have
 * very different sizes: revenue by service line, stock value by category,
 * claims by payer.
 *
 * Area is a much better channel than angle for "how much of the whole", and a
 * treemap degrades gracefully — a tiny rectangle is still legible as tiny,
 * where a 1° slice is not legible as anything.
 */
export function Treemap({
  items,
  format = "number",
  currency,
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  items: { name: string; value: number; color?: string }[];
  format?: ValueFormat;
  currency?: string;
}) {
  const empty = frame.empty ?? items.every((item) => item.value === 0);
  const total = items.reduce((sum, item) => sum + item.value, 0);

  const data = items
    .slice()
    .sort((a, b) => b.value - a.value)
    .map((item, index) => ({
      ...item,
      // The sequential ramp by rank, so size and colour say the same thing and
      // reinforce rather than compete. Categorical hues here would imply the
      // tiles are different kinds of thing.
      fill: item.color ?? SCALE[Math.min(SCALE.length - 1, 7 - Math.min(index, 5))],
    }));

  return (
    <ChartFrame
      {...frame}
      empty={empty}
      table={
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-1.5 pr-3 type-label text-muted-foreground">Item</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Value</th>
              <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Share</th>
            </tr>
          </thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.name} className="border-b last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{item.name}</th>
                <td className="py-1.5 pl-3 text-right tabular-nums">
                  {formatValue(item.value, format, currency)}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums text-muted-foreground">
                  {total ? `${((item.value / total) * 100).toFixed(1)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <RTreemap
          data={data}
          dataKey="value"
          stroke={CHROME.surface}
          isAnimationActive={false}
          // Recharts types `content` as its own node shape; ours is a plain
          // renderer that receives the same props. The cast is at the boundary
          // rather than inside the tile, so the tile stays ordinarily typed.
          content={
            (<TreemapTile format={format} currency={currency} />) as React.ReactElement
          }
        >
          <Tooltip content={<ChartTooltip format={format} currency={currency} />} />
        </RTreemap>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/**
 * One tile, labelled only when the label fits.
 *
 * A treemap that writes into every rectangle produces overlapping text in the
 * small ones, which is the commonest way the form is got wrong. The threshold
 * is measured against the actual rectangle rather than the value.
 */
function TreemapTile(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  value?: number;
  fill?: string;
  format?: ValueFormat;
  currency?: string;
}) {
  const { x = 0, y = 0, width = 0, height = 0, name, value, fill } = props;
  const roomForName = width > 62 && height > 30;
  const roomForValue = width > 62 && height > 46;

  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={fill}
        stroke={CHROME.surface}
        strokeWidth={2}
        rx={3}
      />
      {roomForName ? (
        <text
          x={x + 8}
          y={y + 18}
          fill="hsl(var(--background))"
          fontSize={11}
          fontWeight={500}
        >
          {String(name).length > width / 7
            ? `${String(name).slice(0, Math.max(3, Math.floor(width / 7) - 1))}…`
            : name}
        </text>
      ) : null}
      {roomForValue ? (
        <text
          x={x + 8}
          y={y + 34}
          fill="hsl(var(--background))"
          fontSize={11}
          opacity={0.85}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {formatValue(value, props.format ?? "number", props.currency)}
        </text>
      ) : null}
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/* Stacked progress                                                            */
/* -------------------------------------------------------------------------- */

/**
 * One horizontal bar whose segments sum to the whole — a bed state breakdown,
 * an invoice ageing profile, a claim mix.
 *
 * **The form to reach for instead of a donut nine times out of ten.** It costs
 * one row of vertical space instead of a square, several can be stacked and
 * compared, and length is a far easier channel to judge than angle.
 */
export function StackedProgress({
  segments,
  format = "number",
  currency,
  showLegend = true,
  height = 10,
  className,
}: {
  segments: { label: string; value: number; tone?: keyof typeof SIGNAL; color?: string }[];
  format?: ValueFormat;
  currency?: string;
  showLegend?: boolean;
  height?: number;
  className?: string;
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  if (total === 0) {
    return (
      <div className={cn("space-y-2", className)}>
        <div
          className="w-full rounded-full bg-muted"
          style={{ height }}
          role="img"
          aria-label="Nothing recorded"
        />
        <p className="type-caption">Nothing recorded.</p>
      </div>
    );
  }

  const resolved = segments.map((segment, index) => ({
    ...segment,
    color: segment.color ?? (segment.tone ? SIGNAL[segment.tone] : seriesColor(index)),
    percent: (segment.value / total) * 100,
  }));

  return (
    <div className={cn("space-y-2", className)}>
      <div
        className="flex w-full overflow-hidden rounded-full bg-muted"
        style={{ height, gap: 2 }}
        role="img"
        aria-label={resolved
          .map((segment) => `${segment.label}: ${formatValue(segment.value, format, currency)}`)
          .join(", ")}
      >
        {resolved.map((segment) =>
          segment.percent > 0 ? (
            <div
              key={segment.label}
              className="h-full first:rounded-l-full last:rounded-r-full transition-[width] duration-moderate ease-smooth"
              style={{ width: `${segment.percent}%`, background: segment.color }}
              title={`${segment.label}: ${formatValue(segment.value, format, currency)}`}
            />
          ) : null,
        )}
      </div>
      {showLegend ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {resolved.map((segment) => (
            <li key={segment.label} className="flex items-center gap-1.5 text-xs">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-[2px]"
                style={{ background: segment.color }}
              />
              <span className="text-muted-foreground">{segment.label}</span>
              <span className="font-medium tabular-nums">
                {formatValue(segment.value, format, currency)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
