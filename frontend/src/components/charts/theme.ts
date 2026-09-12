/**
 * The rules every chart in this product obeys, in one place.
 *
 * **Why a layer at all, rather than importing Recharts per screen.** Because
 * the decisions that make a set of charts read as one system are the decisions
 * a busy screen author will not make: which hue is series three, how heavy a
 * gridline is, whether a legend appears, what happens at the ninth series.
 * Left to each page those come out differently every time, and a dashboard of
 * six charts that each chose their own blue looks like six dashboards.
 *
 * **Colours are CSS variables, not hex.** `hsl(var(--series-1))` is resolved by
 * the browser at paint time, so a chart re-colours itself when the theme
 * changes without React re-rendering and without any chart knowing a theme
 * exists. The alternative — reading `getComputedStyle` on mount — is what most
 * dashboards do, and it is why their charts stay light-mode-coloured until you
 * navigate away and back.
 */

/* -------------------------------------------------------------------------- */
/* Palette                                                                     */
/* -------------------------------------------------------------------------- */

/** Categorical slots, in the fixed validated order. Never reordered, never cycled. */
export const SERIES = [
  "hsl(var(--series-1))",
  "hsl(var(--series-2))",
  "hsl(var(--series-3))",
  "hsl(var(--series-4))",
  "hsl(var(--series-5))",
  "hsl(var(--series-6))",
  "hsl(var(--series-7))",
  "hsl(var(--series-8))",
] as const;

/** The sequential ramp, light→dark on a light ground and the reverse on dark. */
export const SCALE = [
  "hsl(var(--scale-1))",
  "hsl(var(--scale-2))",
  "hsl(var(--scale-3))",
  "hsl(var(--scale-4))",
  "hsl(var(--scale-5))",
  "hsl(var(--scale-6))",
  "hsl(var(--scale-7))",
  "hsl(var(--scale-8))",
] as const;

/**
 * Status hues, reserved.
 *
 * **Never used as "series 4".** A chart with a red line meaning "theatre 3"
 * and a red badge meaning "critical" on the same screen has taught the reader
 * that red means nothing.
 */
export const SIGNAL = {
  good: "hsl(var(--good))",
  warning: "hsl(var(--warning))",
  serious: "hsl(var(--serious))",
  critical: "hsl(var(--critical))",
  info: "hsl(var(--info))",
  neutral: "hsl(var(--quiet))",
} as const;

export const ACUITY = [
  "hsl(var(--acuity-1))",
  "hsl(var(--acuity-2))",
  "hsl(var(--acuity-3))",
  "hsl(var(--acuity-4))",
  "hsl(var(--acuity-5))",
] as const;

/** Chrome: the scaffolding a chart is drawn on, all of it recessive. */
export const CHROME = {
  grid: "hsl(var(--chart-grid))",
  axis: "hsl(var(--chart-axis))",
  label: "hsl(var(--chart-label))",
  surface: "hsl(var(--chart-surface))",
  emphasis: "hsl(var(--chart-emphasis))",
  recede: "hsl(var(--chart-recede))",
} as const;

/**
 * The colour for series `index`.
 *
 * **Past eight it returns the recede grey rather than inventing a hue.** A
 * generated ninth colour is indistinguishable from an existing one under
 * colour-vision deficiency, and it breaks the separation guarantees the eight
 * were validated against. Callers that can have many series should fold the
 * tail into "Other" before it gets here; `foldSeries` below does that.
 */
export function seriesColor(index: number): string {
  return SERIES[index] ?? CHROME.recede;
}

/**
 * The number of distinct colours a chart form can safely carry.
 *
 * `adjacent` forms — stacked bars, grouped bars, lines — only ever put
 * neighbouring slots side by side, and all eight clear the separation gates on
 * that pairlist. `all` forms — scatter, bubble, choropleth, small multiples —
 * put every pair on screen simultaneously, and only the first three clear it.
 * The distinction is not cosmetic and the components pass their own kind.
 */
export const SERIES_CAP = { adjacent: 8, all: 3 } as const;

/**
 * Fold a long series list down to the cap, with the remainder as "Other".
 *
 * Sorted by magnitude first, so the tail that gets folded is genuinely the
 * tail rather than whatever happened to be last in the array.
 */
export function foldSeries<T extends { name: string; value: number }>(
  rows: T[],
  cap: number = SERIES_CAP.adjacent,
): { name: string; value: number; folded?: number }[] {
  if (rows.length <= cap) return rows;
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const kept = sorted.slice(0, cap - 1);
  const tail = sorted.slice(cap - 1);
  return [
    ...kept,
    {
      name: "Other",
      value: tail.reduce((sum, row) => sum + row.value, 0),
      folded: tail.length,
    },
  ];
}

/* -------------------------------------------------------------------------- */
/* Geometry                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Shared axis, grid and mark defaults.
 *
 * Spread into every Recharts element rather than retyped, so "the gridline got
 * heavier on one chart" cannot happen.
 */
export const AXIS_PROPS = {
  stroke: CHROME.axis,
  tick: { fill: CHROME.label, fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

export const GRID_PROPS = {
  stroke: CHROME.grid,
  strokeDasharray: "3 3",
  // Vertical gridlines are off by default. On a time axis they duplicate the
  // tick labels and add a lattice the data has to compete with; a chart that
  // genuinely needs them (a Gantt, a flowsheet) turns them on explicitly.
  vertical: false,
} as const;

export const MARK = {
  strokeWidth: 2,
  /** Radius on the free end of a bar; the baseline end stays square. */
  radius: 4,
  /** Minimum marker diameter — below this it stops being a hit target. */
  marker: 8,
  /** The gap punched between stacked segments, in the surface colour. */
  segmentGap: 2,
} as const;

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

export type ValueFormat =
  | "number"
  | "compact"
  | "money"
  | "money-compact"
  | "percent"
  | "duration"
  | "days";

/**
 * How a number is written on an axis, in a tooltip and on a label.
 *
 * Centralised because the same figure formatted three ways on one screen is
 * one of those defects nobody reports and everybody notices. `compact` on an
 * axis and full precision in the tooltip is the intended pairing: the axis is
 * for orientation and the tooltip is for the number.
 */
export function formatValue(
  value: number | null | undefined,
  format: ValueFormat = "number",
  currency = "NPR",
): string {
  if (value == null || Number.isNaN(value)) return "—";

  switch (format) {
    case "compact":
      return new Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
    case "money":
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency,
        maximumFractionDigits: 0,
      }).format(value);
    case "money-compact":
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency,
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
    case "percent":
      return `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
    case "duration": {
      // Minutes in, human out. Turnaround times and waits are the commonest
      // measures in this product and "142" means nothing at a glance.
      const hours = Math.floor(value / 60);
      const minutes = Math.round(value % 60);
      if (hours === 0) return `${minutes}m`;
      return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
    }
    case "days":
      return value === 1 ? "1 day" : `${Math.round(value)} days`;
    default:
      return new Intl.NumberFormat(undefined, {
        maximumFractionDigits: Math.abs(value) < 10 && value % 1 !== 0 ? 1 : 0,
      }).format(value);
  }
}

/** The axis formatter for a format — always the compact sibling. */
/**
 * How much room the value axis needs, in pixels.
 *
 * Fixed at 52 everywhere until a money axis clipped its own currency —
 * "NPR 4.5K" rendered as "PR 4.5K", which reads as a different unit rather
 * than as a truncation. A currency code plus a compact number needs more.
 */
export function axisWidth(format: ValueFormat | undefined): number {
  return format === "money" || format === "money-compact" ? 68 : 52;
}

export function axisFormatter(format: ValueFormat, currency?: string) {
  const compact: Partial<Record<ValueFormat, ValueFormat>> = {
    number: "compact",
    money: "money-compact",
  };
  return (value: number) =>
    formatValue(value, compact[format] ?? format, currency);
}

/* -------------------------------------------------------------------------- */
/* Accessibility                                                               */
/* -------------------------------------------------------------------------- */

/**
 * Whether a chart with this many series may rely on colour alone.
 *
 * At four and above, direct labels stop being optional: slot 4 (gold) and slot
 * 2 (orange) are on screen together, and while they clear the adjacent gates
 * they are the closest legitimate pair in the set. `ChartFrame` consults this
 * and turns labelling on rather than leaving it to the caller to remember.
 */
export function needsDirectLabels(seriesCount: number): boolean {
  return seriesCount >= 4;
}

/**
 * A hatch pattern id for the CVD / print / forced-colours case.
 *
 * Opt-in, never decorative. Rendered by `<TexturedDefs>` in `frame.tsx` and
 * referenced as `url(#nirova-hatch-N)`.
 */
export function hatchId(index: number): string {
  return `nirova-hatch-${index % SERIES.length}`;
}
