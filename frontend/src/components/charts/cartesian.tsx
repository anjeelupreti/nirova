/**
 * The chart forms drawn on two axes: trend, magnitude, part-to-whole,
 * polarity, correlation.
 *
 * Every one of them takes the same shape of props — rows, a category key, a
 * series list — so moving a panel from a line to a stacked bar is a one-word
 * change rather than a rewrite. That matters more than it sounds: the reason
 * dashboards end up with the wrong chart type is that changing it is work.
 *
 * **There is deliberately no second y-axis anywhere in this file.** A
 * dual-axis chart lets the author place the crossing point wherever tells the
 * best story, and readers cannot tell they are being steered. Two measures at
 * different scales become two charts, small multiples, or both indexed to a
 * common base.
 */

import * as React from "react";
import {
  Area,
  AreaChart as RAreaChart,
  Bar,
  BarChart as RBarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart as RLineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart as RScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import {
  AXIS_PROPS,
  CHROME,
  GRID_PROPS,
  MARK,
  SERIES_CAP,
  SIGNAL,
  axisFormatter,
  axisWidth,
  formatValue,
  type ValueFormat,
} from "./theme";
import {
  CURSOR_BAND,
  CURSOR_LINE,
  ChartFrame,
  ChartTable,
  ChartTooltip,
  resolveSeries,
  type ChartFrameProps,
  type SeriesSpec,
} from "./frame";

type Row = Record<string, string | number | null | undefined>;

interface CartesianProps extends Omit<ChartFrameProps, "children" | "series" | "table"> {
  rows: Row[];
  /** The key holding the category or timestamp. */
  categoryKey: string;
  categoryLabel?: string;
  series: SeriesSpec[];
  format?: ValueFormat;
  currency?: string;
  /** A target, budget or reference range drawn behind the data. */
  reference?: { value: number; label?: string; tone?: keyof typeof SIGNAL };
  /** A shaded band — a normal range, an agreed target window. */
  band?: { from: number; to: number; label?: string };
}

/** Shared frame plumbing: the table view is generated from the same rows. */
function useFrame(props: CartesianProps) {
  const resolved = React.useMemo(() => resolveSeries(props.series), [props.series]);
  const empty = props.empty ?? props.rows.length === 0;
  const table = (
    <ChartTable
      rows={props.rows}
      categoryKey={props.categoryKey}
      categoryLabel={props.categoryLabel ?? "Category"}
      series={resolved}
      format={props.format}
      currency={props.currency}
    />
  );
  return { resolved, empty, table };
}

/** The reference line and band, shared by every cartesian form. */
function References({ reference, band }: Pick<CartesianProps, "reference" | "band">) {
  return (
    <>
      {band ? (
        <ReferenceArea
          y1={band.from}
          y2={band.to}
          fill={CHROME.recede}
          fillOpacity={0.25}
          stroke="none"
          label={
            band.label
              ? { value: band.label, position: "insideTopLeft", fill: CHROME.label, fontSize: 10 }
              : undefined
          }
        />
      ) : null}
      {reference ? (
        <ReferenceLine
          y={reference.value}
          stroke={SIGNAL[reference.tone ?? "neutral"]}
          strokeDasharray="4 3"
          strokeWidth={1.5}
          label={
            reference.label
              ? {
                  value: reference.label,
                  position: "right",
                  fill: CHROME.label,
                  fontSize: 10,
                }
              : undefined
          }
        />
      ) : null}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Line                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Trend over time.
 *
 * `dot={false}` until there are few enough points to dot: a line of ninety
 * days with a marker on every day is a caterpillar, and the markers stop being
 * hit targets. Under twenty points they come back, at 8px, because then they
 * are the thing you hover.
 *
 * `connectNulls={false}` on purpose. A gap in a clinical series means the
 * observation was not taken, and drawing straight through it invents data —
 * the line should break where the record breaks.
 */
export function LineChart(props: CartesianProps & { curve?: "linear" | "smooth" }) {
  const { resolved, empty, table } = useFrame(props);
  const dense = props.rows.length > 20;

  return (
    <ChartFrame {...props} series={resolved} empty={empty} table={table}>
      <ResponsiveContainer width="100%" height="100%">
        <RLineChart data={props.rows} margin={{ top: 6, right: 10, bottom: 0, left: -8 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey={props.categoryKey} {...AXIS_PROPS} />
          <YAxis
            {...AXIS_PROPS}
            width={axisWidth(props.format)}
            tickFormatter={axisFormatter(props.format ?? "number", props.currency)}
          />
          <Tooltip
            cursor={CURSOR_LINE}
            content={<ChartTooltip format={props.format} currency={props.currency} />}
          />
          <References reference={props.reference} band={props.band} />
          {resolved.map((item) => (
            <Line
              key={item.key}
              type={props.curve === "linear" ? "linear" : "monotone"}
              dataKey={item.key}
              name={item.label}
              stroke={item.color}
              strokeWidth={MARK.strokeWidth}
              connectNulls={false}
              dot={dense ? false : { r: MARK.marker / 2, strokeWidth: 0, fill: item.color }}
              activeDot={{ r: MARK.marker / 2 + 1, strokeWidth: 2, stroke: CHROME.surface }}
            />
          ))}
        </RLineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Area                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * A single series where the volume under the line is the point — admissions,
 * revenue, throughput — or several stacked to show composition over time.
 *
 * The fill is a vertical gradient to transparent rather than a flat 20% wash.
 * A flat fill on a stack makes the boundary between two segments read as a
 * third colour; the gradient keeps each band's identity at its own top edge,
 * which is where the eye reads it.
 */
export function AreaChart(props: CartesianProps & { stacked?: boolean }) {
  const { resolved, empty, table } = useFrame(props);
  const gradientPrefix = React.useId().replace(/:/g, "");

  return (
    <ChartFrame {...props} series={resolved} empty={empty} table={table}>
      <ResponsiveContainer width="100%" height="100%">
        <RAreaChart data={props.rows} margin={{ top: 6, right: 10, bottom: 0, left: -8 }}>
          <defs>
            {resolved.map((item) => (
              <linearGradient
                key={item.key}
                id={`${gradientPrefix}-${item.key}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor={item.color} stopOpacity={props.stacked ? 0.75 : 0.32} />
                <stop offset="100%" stopColor={item.color} stopOpacity={props.stacked ? 0.55 : 0.02} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey={props.categoryKey} {...AXIS_PROPS} />
          <YAxis
            {...AXIS_PROPS}
            width={axisWidth(props.format)}
            tickFormatter={axisFormatter(props.format ?? "number", props.currency)}
          />
          <Tooltip
            cursor={CURSOR_LINE}
            content={<ChartTooltip format={props.format} currency={props.currency} />}
          />
          <References reference={props.reference} band={props.band} />
          {resolved.map((item) => (
            <Area
              key={item.key}
              type="monotone"
              dataKey={item.key}
              name={item.label}
              stackId={props.stacked ? "stack" : undefined}
              stroke={item.color}
              strokeWidth={MARK.strokeWidth}
              fill={`url(#${gradientPrefix}-${item.key})`}
              connectNulls={false}
              activeDot={{ r: MARK.marker / 2 + 1, strokeWidth: 2, stroke: CHROME.surface }}
            />
          ))}
        </RAreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Bar                                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Magnitude, grouped or stacked, vertical or horizontal.
 *
 * **Horizontal is the right default more often than people use it.** Category
 * names in this product are things like "Emergency department" and
 * "Orthopaedic outpatients"; on a vertical axis those get rotated to 45° and
 * become unreadable, and every dashboard that does it looks like a spreadsheet
 * export. `layout="horizontal"` puts the names where they read as names.
 *
 * The corner radius goes on the free end only — the end at the baseline stays
 * square, because a bar rounded at the axis appears to float above it.
 */
export function BarChart(
  props: CartesianProps & {
    stacked?: boolean;
    layout?: "vertical" | "horizontal";
    /** Paint one bar in the accent and the rest grey — the emphasis form. */
    emphasise?: string | number;
  },
) {
  const { resolved, empty, table } = useFrame(props);
  const horizontal = props.layout === "horizontal";
  const single = resolved.length === 1;

  return (
    <ChartFrame {...props} series={resolved} empty={empty} table={table}>
      <ResponsiveContainer width="100%" height="100%">
        <RBarChart
          data={props.rows}
          layout={horizontal ? "vertical" : "horizontal"}
          margin={
            horizontal
              ? { top: 4, right: 16, bottom: 0, left: 8 }
              : { top: 6, right: 10, bottom: 0, left: -8 }
          }
          barGap={2}
          barCategoryGap={horizontal ? "22%" : "26%"}
        >
          <CartesianGrid {...GRID_PROPS} vertical={horizontal} horizontal={!horizontal} />
          {horizontal ? (
            <>
              <XAxis
                type="number"
                {...AXIS_PROPS}
                tickFormatter={axisFormatter(props.format ?? "number", props.currency)}
              />
              <YAxis
                type="category"
                dataKey={props.categoryKey}
                {...AXIS_PROPS}
                width={140}
              />
            </>
          ) : (
            <>
              <XAxis dataKey={props.categoryKey} {...AXIS_PROPS} />
              <YAxis
                {...AXIS_PROPS}
                width={axisWidth(props.format)}
                tickFormatter={axisFormatter(props.format ?? "number", props.currency)}
              />
            </>
          )}
          <Tooltip
            cursor={CURSOR_BAND}
            content={<ChartTooltip format={props.format} currency={props.currency} />}
          />
          <References reference={props.reference} band={props.band} />
          {resolved.map((item, index) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              name={item.label}
              stackId={props.stacked ? "stack" : undefined}
              fill={item.color}
              // The 2px gap between stacked segments, painted in the surface
              // colour so the boundary is a gap and not a third hue.
              stroke={props.stacked ? CHROME.surface : undefined}
              strokeWidth={props.stacked ? MARK.segmentGap : 0}
              radius={
                props.stacked
                  ? index === resolved.length - 1
                    ? horizontal
                      ? [0, MARK.radius, MARK.radius, 0]
                      : [MARK.radius, MARK.radius, 0, 0]
                    : 0
                  : horizontal
                    ? [0, MARK.radius, MARK.radius, 0]
                    : [MARK.radius, MARK.radius, 0, 0]
              }
              maxBarSize={horizontal ? 22 : 44}
            >
              {/* Emphasis: one bar in the accent, the rest receding. The most
                  underused form in this product — "occupancy is high in ward
                  B" is one bar's story, not eight bars' worth of colour. */}
              {single && props.emphasise != null
                ? props.rows.map((row, rowIndex) => (
                    <Cell
                      key={rowIndex}
                      fill={
                        row[props.categoryKey] === props.emphasise
                          ? CHROME.emphasis
                          : CHROME.recede
                      }
                    />
                  ))
                : null}
            </Bar>
          ))}
        </RBarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Diverging bar                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Above and below a baseline: variance to budget, MRR movement, weight change,
 * stock adjustment.
 *
 * **Two hues and a neutral zero, never a single hue in two shades.** The whole
 * point of the form is that the two directions mean opposite things, and a
 * ramp says "more" rather than "the other way".
 */
export function DivergingBar({
  rows,
  categoryKey,
  categoryLabel = "Category",
  valueKey,
  valueLabel,
  positiveTone = "good",
  negativeTone = "critical",
  format = "number",
  currency,
  layout = "horizontal",
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  rows: Row[];
  categoryKey: string;
  categoryLabel?: string;
  valueKey: string;
  valueLabel: string;
  positiveTone?: keyof typeof SIGNAL;
  negativeTone?: keyof typeof SIGNAL;
  format?: ValueFormat;
  currency?: string;
  layout?: "vertical" | "horizontal";
}) {
  const horizontal = layout === "horizontal";
  const series = [{ key: valueKey, label: valueLabel, color: SIGNAL[positiveTone] }];
  const empty = frame.empty ?? rows.length === 0;

  return (
    <ChartFrame
      {...frame}
      empty={empty}
      table={
        <ChartTable
          rows={rows}
          categoryKey={categoryKey}
          categoryLabel={categoryLabel}
          series={series}
          format={format}
          currency={currency}
        />
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <RBarChart
          data={rows}
          layout={horizontal ? "vertical" : "horizontal"}
          margin={
            horizontal
              ? { top: 4, right: 20, bottom: 0, left: 8 }
              : { top: 6, right: 10, bottom: 0, left: -8 }
          }
        >
          <CartesianGrid {...GRID_PROPS} vertical={horizontal} horizontal={!horizontal} />
          {horizontal ? (
            <>
              <XAxis
                type="number"
                {...AXIS_PROPS}
                tickFormatter={axisFormatter(format, currency)}
              />
              <YAxis type="category" dataKey={categoryKey} {...AXIS_PROPS} width={140} />
            </>
          ) : (
            <>
              <XAxis dataKey={categoryKey} {...AXIS_PROPS} />
              <YAxis {...AXIS_PROPS} width={56} tickFormatter={axisFormatter(format, currency)} />
            </>
          )}
          <Tooltip
            cursor={CURSOR_BAND}
            content={<ChartTooltip format={format} currency={currency} />}
          />
          {/* Zero is a real line, in the axis colour rather than the grid's —
              it is the thing every bar is measured from. */}
          <ReferenceLine
            {...(horizontal ? { x: 0 } : { y: 0 })}
            stroke={CHROME.axis}
            strokeWidth={1}
          />
          <Bar dataKey={valueKey} name={valueLabel} maxBarSize={horizontal ? 22 : 44}>
            {rows.map((row, index) => {
              const value = Number(row[valueKey] ?? 0);
              return (
                <Cell
                  key={index}
                  fill={value >= 0 ? SIGNAL[positiveTone] : SIGNAL[negativeTone]}
                  radius={
                    horizontal
                      ? value >= 0
                        ? ([0, MARK.radius, MARK.radius, 0] as never)
                        : ([MARK.radius, 0, 0, MARK.radius] as never)
                      : value >= 0
                        ? ([MARK.radius, MARK.radius, 0, 0] as never)
                        : ([0, 0, MARK.radius, MARK.radius] as never)
                  }
                />
              );
            })}
          </Bar>
        </RBarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Combo                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Bars and a line **on one shared scale**.
 *
 * The legitimate use: a count and a rolling average of the same count, an
 * actual and a target in the same unit. The illegitimate one — revenue as bars
 * and margin percentage as a line — is exactly the dual-axis chart this file
 * refuses to draw, and it is refused here too, by there being nowhere to put
 * the second scale.
 */
export function ComboChart(
  props: CartesianProps & {
    bars: SeriesSpec[];
    lines: SeriesSpec[];
  },
) {
  const resolved = React.useMemo(
    () => resolveSeries([...props.bars, ...props.lines]),
    [props.bars, props.lines],
  );
  const barCount = props.bars.length;
  const empty = props.empty ?? props.rows.length === 0;

  return (
    <ChartFrame
      {...props}
      series={resolved}
      empty={empty}
      table={
        <ChartTable
          rows={props.rows}
          categoryKey={props.categoryKey}
          categoryLabel={props.categoryLabel ?? "Category"}
          series={resolved}
          format={props.format}
          currency={props.currency}
        />
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={props.rows} margin={{ top: 6, right: 10, bottom: 0, left: -8 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey={props.categoryKey} {...AXIS_PROPS} />
          <YAxis
            {...AXIS_PROPS}
            width={axisWidth(props.format)}
            tickFormatter={axisFormatter(props.format ?? "number", props.currency)}
          />
          <Tooltip
            cursor={CURSOR_BAND}
            content={<ChartTooltip format={props.format} currency={props.currency} />}
          />
          <References reference={props.reference} band={props.band} />
          {resolved.slice(0, barCount).map((item) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              name={item.label}
              fill={item.color}
              radius={[MARK.radius, MARK.radius, 0, 0]}
              maxBarSize={44}
            />
          ))}
          {resolved.slice(barCount).map((item) => (
            <Line
              key={item.key}
              type="monotone"
              dataKey={item.key}
              name={item.label}
              stroke={item.color}
              strokeWidth={MARK.strokeWidth}
              dot={false}
              connectNulls={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Scatter                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Correlation, and the outlier that is the actual reason to draw one — a
 * theatre whose utilisation is high and whose overrun is also high, a doctor
 * whose volume is normal and whose turnaround is not.
 *
 * **Capped at three groups, and that is enforced rather than documented.**
 * Scatter puts every pair of colours on screen at once, and only the first
 * three slots clear the separation gates on the all-pairs list. A fourth group
 * would be legible to me and not to a deuteranopic reader, which is the exact
 * failure the cap exists for.
 */
export function ScatterChart({
  groups,
  xKey,
  yKey,
  sizeKey,
  xLabel,
  yLabel,
  xFormat = "number",
  yFormat = "number",
  currency,
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  groups: { key: string; label: string; color?: string; points: Row[] }[];
  xKey: string;
  yKey: string;
  /** Bubble size. Area-proportional, never radius-proportional. */
  sizeKey?: string;
  xLabel: string;
  yLabel: string;
  xFormat?: ValueFormat;
  yFormat?: ValueFormat;
  currency?: string;
}) {
  const capped = groups.slice(0, SERIES_CAP.all);
  const resolved = resolveSeries(
    capped.map((group) => ({ key: group.key, label: group.label, color: group.color })),
  );
  const empty = frame.empty ?? capped.every((group) => group.points.length === 0);

  return (
    <ChartFrame {...frame} series={resolved} empty={empty}>
      <ResponsiveContainer width="100%" height="100%">
        <RScatterChart margin={{ top: 8, right: 14, bottom: 4, left: -8 }}>
          <CartesianGrid {...GRID_PROPS} vertical />
          <XAxis
            type="number"
            dataKey={xKey}
            name={xLabel}
            {...AXIS_PROPS}
            tickFormatter={axisFormatter(xFormat, currency)}
          />
          <YAxis
            type="number"
            dataKey={yKey}
            name={yLabel}
            width={axisWidth(yFormat)}
            {...AXIS_PROPS}
            tickFormatter={axisFormatter(yFormat, currency)}
          />
          {sizeKey ? <ZAxis type="number" dataKey={sizeKey} range={[40, 400]} /> : null}
          <Tooltip
            cursor={{ strokeDasharray: "3 3", stroke: CHROME.axis }}
            content={<ChartTooltip format={yFormat} currency={currency} />}
          />
          {capped.map((group, index) => (
            <Scatter
              key={group.key}
              name={group.label}
              data={group.points}
              fill={resolved[index].color}
              // A 2px ring in the surface colour, so overlapping points stay
              // countable instead of merging into one blob.
              stroke={CHROME.surface}
              strokeWidth={2}
              fillOpacity={0.85}
            />
          ))}
        </RScatterChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

/* -------------------------------------------------------------------------- */
/* Levey–Jennings                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Laboratory quality control: a control result plotted against its mean with
 * standard-deviation bands, and Westgard violations marked.
 *
 * §34 of the checklist has asked for this since the beginning. It is a domain
 * form rather than a generic one — a lab scientist reads the *pattern*, not the
 * values, and the bands are what make the pattern visible.
 *
 * Points outside ±2 SD are marked serious, outside ±3 SD critical, and both
 * carry a shape change as well as a colour, because a QC chart is read at a
 * glance across a bench.
 */
export function LeveyJennings({
  rows,
  runKey = "run",
  valueKey = "value",
  mean,
  sd,
  ...frame
}: Omit<ChartFrameProps, "children" | "series" | "table"> & {
  rows: Row[];
  runKey?: string;
  valueKey?: string;
  mean: number;
  sd: number;
}) {
  const empty = frame.empty ?? rows.length === 0;
  const bands = [
    { level: 3, tone: SIGNAL.critical, opacity: 0.06 },
    { level: 2, tone: SIGNAL.warning, opacity: 0.06 },
    { level: 1, tone: CHROME.recede, opacity: 0.18 },
  ];

  return (
    <ChartFrame {...frame} empty={empty}>
      <ResponsiveContainer width="100%" height="100%">
        <RLineChart data={rows} margin={{ top: 8, right: 40, bottom: 0, left: -8 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey={runKey} {...AXIS_PROPS} />
          <YAxis
            {...AXIS_PROPS}
            width={axisWidth("number")}
            domain={[mean - sd * 4, mean + sd * 4]}
            tickFormatter={(value: number) => formatValue(value, "number")}
          />
          <Tooltip cursor={CURSOR_LINE} content={<ChartTooltip />} />

          {bands.map((band) => (
            <ReferenceArea
              key={band.level}
              y1={mean - sd * band.level}
              y2={mean + sd * band.level}
              fill={band.tone}
              fillOpacity={band.opacity}
              stroke="none"
            />
          ))}
          {[-3, -2, 2, 3].map((multiple) => (
            <ReferenceLine
              key={multiple}
              y={mean + sd * multiple}
              stroke={Math.abs(multiple) === 3 ? SIGNAL.critical : SIGNAL.warning}
              strokeDasharray="4 3"
              strokeWidth={1}
              label={{
                value: `${multiple > 0 ? "+" : ""}${multiple}SD`,
                position: "right",
                fill: CHROME.label,
                fontSize: 10,
              }}
            />
          ))}
          <ReferenceLine y={mean} stroke={CHROME.axis} strokeWidth={1.5} />

          <Line
            type="linear"
            dataKey={valueKey}
            name="Control result"
            stroke={CHROME.emphasis}
            strokeWidth={MARK.strokeWidth}
            connectNulls={false}
            dot={(dotProps: { cx?: number; cy?: number; value?: number; index?: number }) => {
              const value = Number(dotProps.value ?? mean);
              const deviations = Math.abs(value - mean) / (sd || 1);
              const tone =
                deviations > 3 ? SIGNAL.critical : deviations > 2 ? SIGNAL.warning : CHROME.emphasis;
              // Shape carries the same message as the colour: a square for a
              // violation, a circle for a pass. Read across a bench, at a
              // glance, by somebody who may not see the hue.
              return deviations > 2 ? (
                <rect
                  key={dotProps.index}
                  x={(dotProps.cx ?? 0) - 4}
                  y={(dotProps.cy ?? 0) - 4}
                  width={8}
                  height={8}
                  fill={tone}
                  stroke={CHROME.surface}
                  strokeWidth={1.5}
                />
              ) : (
                <circle
                  key={dotProps.index}
                  cx={dotProps.cx}
                  cy={dotProps.cy}
                  r={3.5}
                  fill={tone}
                  stroke={CHROME.surface}
                  strokeWidth={1.5}
                />
              );
            }}
          />
        </RLineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
