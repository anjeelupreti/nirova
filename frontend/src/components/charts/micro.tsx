/**
 * The small figures: the ones that live inside a tile, a table cell or a row,
 * where a full chart would be absurd and a bare number is not enough.
 *
 * All hand-drawn SVG rather than Recharts. A `<ResponsiveContainer>` per table
 * row is a resize observer per table row, and a ward list with eighty
 * sparklines becomes measurably slow; these are a `<path>` and nothing else.
 *
 * **`StatTile` is here rather than in `data.tsx` because a statistic without a
 * comparison is not a statistic.** The old tile took a value and a label, so
 * every dashboard tile in this product said "142" and left the reader to
 * wonder whether that was good. This one cannot be built without deciding
 * what "up" means.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Icon, type IconName } from "@/components/ui/icon";
import { TrendBadge } from "@/components/ui/status";
import { CHROME, SIGNAL, formatValue, type ValueFormat } from "./theme";

/* -------------------------------------------------------------------------- */
/* Sparkline                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * A trend with no axes, no labels and no scale.
 *
 * It answers exactly one question — "which way, and how bumpy" — and a
 * sparkline that tries to answer a second by adding a y-axis becomes a bad
 * small chart instead of a good glyph.
 *
 * The last point is dotted, because "where it ended" is the part people look
 * for and a bare line's right end is ambiguous against the container edge.
 */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  tone = "brand",
  area = true,
  className,
  label,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  tone?: "brand" | "good" | "warning" | "serious" | "critical" | "neutral";
  area?: boolean;
  className?: string;
  /** An accessible summary. Without one the glyph is hidden from readers. */
  label?: string;
}) {
  const gradientId = React.useId().replace(/:/g, "");
  const clean = values.filter((value): value is number => value != null);

  if (clean.length < 2) {
    return (
      <div
        className={cn("flex items-center", className)}
        style={{ width, height }}
        aria-hidden
      >
        <span className="type-caption">not enough history</span>
      </div>
    );
  }

  const color =
    tone === "brand" ? CHROME.emphasis : SIGNAL[tone as keyof typeof SIGNAL];
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  // A flat series would divide by zero and, worse, draw at the very top of the
  // box. A one-unit span puts it through the middle, which is what "flat"
  // should look like.
  const span = max - min || 1;
  const padding = 2;

  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * (width - padding * 2) + padding;
    const y =
      value == null
        ? null
        : height - padding - ((value - min) / span) * (height - padding * 2);
    return { x, y };
  });

  // Gaps break the line rather than being interpolated through: a missing
  // observation is missing, and drawing across it invents a reading.
  const segments: string[] = [];
  let current: string[] = [];
  for (const point of points) {
    if (point.y == null) {
      if (current.length) segments.push(current.join(" "));
      current = [];
    } else {
      current.push(`${current.length ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`);
    }
  }
  if (current.length) segments.push(current.join(" "));

  const last = [...points].reverse().find((point) => point.y != null);
  const first = points.find((point) => point.y != null);
  const areaPath =
    area && first && last
      ? `${segments.join(" ")} L${last.x.toFixed(1)},${height} L${first.x.toFixed(1)},${height} Z`
      : null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {areaPath ? (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.22} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#${gradientId})`} />
        </>
      ) : null}
      {segments.map((segment, index) => (
        <path
          key={index}
          d={segment}
          fill="none"
          stroke={color}
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
      {last?.y != null ? (
        <circle cx={last.x} cy={last.y} r={2.25} fill={color} />
      ) : null}
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Bullet                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * A value against a target, with qualitative bands behind it.
 *
 * **The right answer whenever somebody asks for a gauge.** A gauge spends a
 * semicircle of space to encode one number badly — the angle is hard to read
 * and impossible to compare between two of them. A bullet is a bar, so four
 * stacked in a column can be compared at a glance, which is what a facility
 * dashboard actually needs.
 */
export function Bullet({
  value,
  target,
  max,
  bands,
  format = "number",
  currency,
  tone = "brand",
  className,
  label,
}: {
  value: number;
  target?: number;
  max?: number;
  /** Qualitative ranges behind the bar, lightest first. */
  bands?: { to: number; tone: "good" | "warning" | "serious" | "critical" | "neutral" }[];
  format?: ValueFormat;
  currency?: string;
  tone?: "brand" | "good" | "warning" | "serious" | "critical";
  className?: string;
  label?: string;
}) {
  const ceiling = max ?? (Math.max(value, target ?? 0) * 1.15 || 1);
  const pct = (input: number) => Math.max(0, Math.min(100, (input / ceiling) * 100));
  const color = tone === "brand" ? CHROME.emphasis : SIGNAL[tone];

  return (
    <div className={cn("min-w-0", className)}>
      {label ? (
        <div className="mb-1 flex items-baseline justify-between gap-2">
          <span className="type-caption truncate">{label}</span>
          <span className="text-xs font-medium tabular-nums">
            {formatValue(value, format, currency)}
            {target != null ? (
              <span className="ml-1 font-normal text-muted-foreground">
                / {formatValue(target, format, currency)}
              </span>
            ) : null}
          </span>
        </div>
      ) : null}
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-muted">
        {/* Qualitative bands, painted first and very faint — they are context,
            and a band that competes with the measure defeats the form. */}
        {bands?.map((band, index) => (
          <div
            key={index}
            className="absolute inset-y-0 left-0"
            style={{
              width: `${pct(band.to)}%`,
              background: SIGNAL[band.tone === "neutral" ? "neutral" : band.tone],
              opacity: 0.14,
            }}
          />
        ))}
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-moderate ease-smooth"
          style={{ width: `${pct(value)}%`, background: color }}
        />
        {/* The target as a tick across the bar, not a second bar. */}
        {target != null ? (
          <div
            className="absolute inset-y-[-2px] w-0.5 rounded-full bg-foreground"
            style={{ left: `calc(${pct(target)}% - 1px)` }}
            title={`Target ${formatValue(target, format, currency)}`}
          />
        ) : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Meter                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * A single ratio against a limit, as a ring.
 *
 * Kept — despite the bullet being better for comparison — because a ring is
 * the right shape for the *one* number a card is about: bed occupancy on a
 * ward tile, plan usage against an entitlement limit. One per card, never a
 * row of them.
 *
 * The tone crosses from brand to warning to critical at thresholds the caller
 * sets, because "83% of your patient limit" and "83% bed occupancy" are not
 * the same news.
 */
export function Meter({
  value,
  max = 100,
  size = 64,
  thresholds,
  label,
  sublabel,
  format = "percent",
  className,
}: {
  value: number;
  max?: number;
  size?: number;
  /** Above `warning` the ring turns amber; above `critical`, red. */
  thresholds?: { warning: number; critical: number };
  label?: React.ReactNode;
  sublabel?: React.ReactNode;
  format?: ValueFormat;
  className?: string;
}) {
  const ratio = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const percent = ratio * 100;
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  const color =
    thresholds && percent >= thresholds.critical
      ? SIGNAL.critical
      : thresholds && percent >= thresholds.warning
        ? SIGNAL.warning
        : CHROME.emphasis;

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={CHROME.grid}
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - ratio)}
            className="transition-[stroke-dashoffset] duration-deliberate ease-smooth"
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-xs font-semibold tabular-nums">
          {formatValue(format === "percent" ? percent : value, format)}
        </span>
      </div>
      {(label || sublabel) && (
        <div className="min-w-0">
          {label ? <p className="truncate text-sm font-medium">{label}</p> : null}
          {sublabel ? <p className="truncate type-caption">{sublabel}</p> : null}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Stat tile                                                                   */
/* -------------------------------------------------------------------------- */

/** Every class spelled out, so Tailwind's scanner can see all of them. */
const TONE_INK = {
  neutral: "text-muted-foreground",
  brand: "text-primary",
  good: "text-good",
  warning: "text-warning",
  serious: "text-serious",
  critical: "text-critical",
} as const;

export interface StatTileProps {
  label: React.ReactNode;
  value: number | string | null | undefined;
  format?: ValueFormat;
  currency?: string;
  icon?: IconName;
  /** The change against the previous period, as a percentage. */
  delta?: number | null;
  /**
   * Which direction is good news. **Required, with no default**, because
   * revenue rising and infection rate rising are the same arrow and opposite
   * news — and a tile that paints every increase green is misleading on about
   * half the figures in a hospital.
   */
  goodDirection?: "up" | "down" | "neither";
  /** Recent history behind the figure. */
  history?: (number | null)[];
  /** What the figure is measured against. */
  target?: number;
  /** Where pressing the tile goes. A KPI you cannot act on is a poster. */
  onOpen?: () => void;
  footnote?: React.ReactNode;
  tone?: "neutral" | "brand" | "good" | "warning" | "serious" | "critical";
  className?: string;
}

/**
 * The unit a dashboard is built from.
 *
 * Reads top to bottom in the order a person asks: what is this, what is it
 * now, which way is it going, against what.
 */
export function StatTile({
  label,
  value,
  format = "number",
  currency,
  icon,
  delta,
  goodDirection = "neither",
  history,
  target,
  onOpen,
  footnote,
  tone = "neutral",
  className,
}: StatTileProps) {
  const Wrapper = onOpen ? "button" : "div";

  return (
    <Wrapper
      type={onOpen ? "button" : undefined}
      onClick={onOpen}
      className={cn(
        "group flex w-full flex-col gap-2.5 rounded-lg border bg-card p-4 text-left shadow-raised",
        onOpen &&
          "transition-colors duration-quick ease-smooth hover:border-border-strong hover:bg-accent/40",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {icon ? (
          // **A lookup, not a template literal.** `text-${tone}` reads fine and
          // is invisible to Tailwind's scanner, which works by finding class
          // names as literal strings in the source: the class is emitted only
          // if some *other* file happens to spell it out, so the tile is
          // correctly coloured by luck and loses its colour the day that other
          // file changes. Written out, every one of these is scannable.
          <Icon name={icon} size="sm" className={TONE_INK[tone]} />
        ) : null}
        <span className="min-w-0 flex-1 truncate type-label text-muted-foreground">
          {label}
        </span>
        {onOpen ? (
          <Icon
            name="chevronRight"
            size="sm"
            className="text-muted-foreground opacity-0 transition-opacity duration-quick group-hover:opacity-100"
          />
        ) : null}
      </div>

      <div className="flex items-end justify-between gap-3">
        <p className="type-figure">
          {typeof value === "number" ? formatValue(value, format, currency) : (value ?? "—")}
        </p>
        {history && history.length > 1 ? (
          <Sparkline
            values={history}
            tone={tone === "neutral" ? "brand" : (tone as "brand")}
            width={72}
            height={24}
            className="mb-0.5"
          />
        ) : null}
      </div>

      {(delta !== undefined || target != null || footnote) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {delta !== undefined ? (
            <TrendBadge value={delta} goodDirection={goodDirection} />
          ) : null}
          {target != null ? (
            <span className="type-caption">
              target {formatValue(target, format, currency)}
            </span>
          ) : null}
          {footnote ? <span className="type-caption">{footnote}</span> : null}
        </div>
      )}
    </Wrapper>
  );
}

/* -------------------------------------------------------------------------- */
/* Hero figure                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * The one number a screen leads with.
 *
 * For the case where a chart would be dressing up a single fact: "34 patients
 * waiting", "NPR 1.2M collected today". Big, unadorned, with the comparison
 * underneath — and never a one-bar bar chart, which is what these become when
 * somebody feels a dashboard needs more graphics.
 */
export function HeroFigure({
  value,
  label,
  format = "number",
  currency,
  delta,
  goodDirection = "neither",
  footnote,
  className,
}: {
  value: number | string | null | undefined;
  label: React.ReactNode;
  format?: ValueFormat;
  currency?: string;
  delta?: number | null;
  goodDirection?: "up" | "down" | "neither";
  footnote?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <p className="type-label text-muted-foreground">{label}</p>
      <p className="mt-1.5 text-[2.75rem] font-semibold leading-none tracking-[-0.03em] tabular-nums">
        {typeof value === "number" ? formatValue(value, format, currency) : (value ?? "—")}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {delta !== undefined ? (
          <TrendBadge value={delta} goodDirection={goodDirection} />
        ) : null}
        {footnote ? <span className="type-caption">{footnote}</span> : null}
      </div>
    </div>
  );
}
