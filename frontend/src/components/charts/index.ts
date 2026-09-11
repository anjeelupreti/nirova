/**
 * The chart vocabulary, as one import.
 *
 * ```tsx
 * import { Chart } from "@/components/charts";
 *
 * <Chart.Bar layout="horizontal" rows={…} categoryKey="ward" series={…} />
 * <Chart.OccupancyGrid beds={…} groupBy={(bed) => bed.bay} />
 * ```
 *
 * **A namespace rather than 20 named imports**, because the point of having a
 * chart layer is that a screen author can see the whole menu by typing
 * `Chart.` — and the commonest way a dashboard ends up with a line chart where
 * a heatmap belonged is that nobody knew the heatmap existed.
 *
 * The forms, and what each is for:
 *
 * | Form | The question it answers |
 * |---|---|
 * | `Line` | which way is this going over time |
 * | `Area` | how much, over time — and what it is made of, stacked |
 * | `Bar` | how much, compared across categories |
 * | `Diverging` | above or below a baseline; variance to target |
 * | `Combo` | a count and its rolling average, on one scale |
 * | `Scatter` | are these two measures related, and which is the outlier |
 * | `LeveyJennings` | is this assay in control (§34) |
 * | `Donut` | what is this made of, with the total in the middle |
 * | `Funnel` | which stage leaks |
 * | `Treemap` | composition with many parts of very different sizes |
 * | `StackedProgress` | one bar's worth of composition, in a row |
 * | `Heatmap` | magnitude across two categorical axes |
 * | `Calendar` | seasonality across a year |
 * | `OccupancyGrid` | what have I got, spatially — the ward |
 * | `Gantt` | the day: gaps and overlaps |
 * | `Waterfall` | how it got from opening to closing |
 * | `Dumbbell` | before and after, per item |
 * | `Pyramid` | case mix by age and sex |
 * | `Sparkline` | which way, in a table cell |
 * | `Bullet` | value against target, comparably |
 * | `Meter` | one ratio against one limit |
 * | `Stat` / `Hero` | the number, when a chart would be dressing it up |
 */

import {
  AreaChart,
  BarChart,
  ComboChart,
  DivergingBar,
  LeveyJennings,
  LineChart,
  ScatterChart,
} from "./cartesian";
import { Donut, FunnelChart, StackedProgress, Treemap } from "./parts";
import { CalendarHeatmap, Gantt, Heatmap, OccupancyGrid } from "./matrix";
import { Dumbbell, PopulationPyramid, Waterfall } from "./domain";
import { Bullet, HeroFigure, Meter, Sparkline, StatTile } from "./micro";
import { ChartFrame, ChartLegend, ChartTable, ChartTooltip } from "./frame";

export const Chart = {
  /* Cartesian */
  Line: LineChart,
  Area: AreaChart,
  Bar: BarChart,
  Diverging: DivergingBar,
  Combo: ComboChart,
  Scatter: ScatterChart,
  LeveyJennings,

  /* Part-to-whole */
  Donut,
  Funnel: FunnelChart,
  Treemap,
  StackedProgress,

  /* Grids */
  Heatmap,
  Calendar: CalendarHeatmap,
  OccupancyGrid,
  Gantt,

  /* Domain */
  Waterfall,
  Dumbbell,
  Pyramid: PopulationPyramid,

  /* Micro */
  Sparkline,
  Bullet,
  Meter,
  Stat: StatTile,
  Hero: HeroFigure,

  /* Furniture, for a bespoke chart that still wants the frame */
  Frame: ChartFrame,
  Legend: ChartLegend,
  Tooltip: ChartTooltip,
  Table: ChartTable,
} as const;

export type { BedCell, GanttRow, HeatCell } from "./matrix";
export type { WaterfallStep } from "./domain";
export type { SeriesSpec } from "./frame";
export type { ValueFormat } from "./theme";
export { SERIES, SIGNAL, formatValue, seriesColor } from "./theme";
