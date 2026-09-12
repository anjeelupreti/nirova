/**
 * Sales over a period: the owner's view of the counter.
 *
 * The counter's own summary answers "how did today go" for one till. This
 * answers the questions an owner asks of a month: is it up on last month,
 * which products carry the margin, how much comes by eSewa or Khalti, when is
 * the counter busiest, which till is short. Every figure is compared with the
 * period of the same length just before it, because a number with nothing to
 * compare it against cannot be good or bad news.
 *
 * The figures come from the same rules as the till's summary, so a one-day
 * report here and the counter's own close agree to the paisa.
 */

import { useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { downloadWorkbook } from "@/lib/xlsx";
import { useSession } from "@/hooks/useSession";
import { Chart, formatValue } from "@/components/charts";
import { SegmentedControl } from "@/components/ui/data";
import { Page, PageHeader, Section, StatGrid, Toolbar } from "@/components/ui/layout";
import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";
import type { Facility, Paginated } from "@/types";

interface SalesReport {
  start: string;
  end: string;
  facility: string | null;
  totals: {
    sales: number;
    gross_revenue: string;
    discounts: string;
    refunds: string;
    returns: number;
    net_revenue: string;
    tax: string;
    cost_of_goods: string;
    gross_margin: string;
    margin_percent: number;
    average_sale: string;
    return_rate_percent: number;
  };
  by_day: { date: string; sales: number; revenue: string; refunds: string; net: string }[];
  by_hour: { hour: number; sales: number; revenue: string }[];
  by_product: { product: string; quantity: string; sales: number; revenue: string; cost: string; margin: string }[];
  by_tender: { method: string; label: string; count: number; amount: string }[];
  by_cashier: { cashier: string; till: string; sales: number; revenue: string }[];
}

type Preset = "today" | "7" | "30" | "90" | "custom";

const PRESETS: { value: Preset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "custom", label: "Custom" },
];

const DAY = 86_400_000;

function iso(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function presetRange(preset: Preset): { start: string; end: string } {
  const today = new Date();
  const days = preset === "today" ? 1 : Number(preset);
  return { start: iso(new Date(today.getTime() - (days - 1) * DAY)), end: iso(today) };
}

/** The period of the same length immediately before [start, end]. */
function previousRange(start: string, end: string): { start: string; end: string } {
  const from = new Date(`${start}T00:00:00`);
  const to = new Date(`${end}T00:00:00`);
  const length = Math.round((to.getTime() - from.getTime()) / DAY) + 1;
  return {
    start: iso(new Date(from.getTime() - length * DAY)),
    end: iso(new Date(from.getTime() - DAY)),
  };
}

function change(now: number, before: number | undefined): number | null {
  if (before === undefined || before === 0) return null;
  return Math.round(((now - before) / Math.abs(before)) * 1000) / 10;
}

function shortDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function longDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric",
  });
}

const money = (value: string | number) => formatValue(Number(value), "money");

export default function SalesPage() {
  const { session } = useSession();
  const [preset, setPreset] = useState<Preset>("30");
  const [range, setRange] = useState(() => presetRange("30"));
  const [facility, setFacility] = useState("");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [report, setReport] = useState<SalesReport | null>(null);
  const [previous, setPrevious] = useState<SalesReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .catch(() => setFacilities([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const query = (start: string, end: string) => {
      const params = new URLSearchParams({ start, end });
      if (facility) params.set("facility", facility);
      return api.get<SalesReport>(`/pos/report/?${params}`);
    };
    const before = previousRange(range.start, range.end);
    setLoading(true);
    setError(null);
    Promise.all([query(range.start, range.end), query(before.start, before.end).catch(() => null)])
      .then(([current, earlier]) => {
        if (cancelled) return;
        setReport(current);
        setPrevious(earlier);
      })
      .catch((problem) => {
        if (!cancelled) setError(problem instanceof ApiError ? problem.message : "The report could not be loaded.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range, facility]);

  const choosePreset = (value: Preset) => {
    setPreset(value);
    if (value !== "custom") setRange(presetRange(value));
  };

  const facilityName = facilities.find((row) => row.uuid === facility)?.name ?? "All facilities";
  const period = report ? `${longDate(report.start)} – ${longDate(report.end)}` : "";

  const daily = useMemo(
    () => (report?.by_day ?? []).map((row) => ({ day: shortDate(row.date), net: Number(row.net), refunds: Number(row.refunds) })),
    [report],
  );
  const hourly = useMemo(() => {
    const rows = report?.by_hour ?? [];
    const active = rows.filter((row) => row.sales > 0).map((row) => row.hour);
    if (active.length === 0) return [];
    const first = Math.min(...active);
    const last = Math.max(...active);
    return rows
      .filter((row) => row.hour >= first && row.hour <= last)
      .map((row) => ({ hour: `${String(row.hour).padStart(2, "0")}:00`, sales: row.sales }));
  }, [report]);
  const tenders = useMemo(
    () => (report?.by_tender ?? []).map((row) => ({ name: row.label, value: Number(row.amount) })),
    [report],
  );
  const busiest = hourly.reduce<{ hour: string; sales: number } | null>(
    (best, row) => (best === null || row.sales > best.sales ? row : best),
    null,
  );

  const exportWorkbook = () => {
    if (!report) return;
    const subtitle = `${facilityName} · ${period}`;
    const t = report.totals;
    void downloadWorkbook(
      `sales-${report.start}-to-${report.end}`,
      [
        {
          name: "Summary",
          title: "Sales summary",
          subtitle,
          columns: [{ header: "Measure", width: 28 }, { header: "This period", kind: "money" }, { header: "Previous period", kind: "money" }],
          rows: [
            ["Sales (count)", t.sales, previous?.totals.sales],
            ["Gross revenue", t.gross_revenue, previous?.totals.gross_revenue],
            ["Discounts", t.discounts, previous?.totals.discounts],
            ["Refunds", t.refunds, previous?.totals.refunds],
            ["Net revenue", t.net_revenue, previous?.totals.net_revenue],
            ["VAT collected", t.tax, previous?.totals.tax],
            ["Cost of goods", t.cost_of_goods, previous?.totals.cost_of_goods],
            ["Gross margin", t.gross_margin, previous?.totals.gross_margin],
            ["Average sale", t.average_sale, previous?.totals.average_sale],
          ],
        },
        {
          name: "By day",
          title: "Sales by day",
          subtitle,
          columns: [
            { header: "Date", kind: "date" }, { header: "Sales", kind: "integer" },
            { header: "Revenue", kind: "money" }, { header: "Refunds", kind: "money" }, { header: "Net", kind: "money" },
          ],
          rows: report.by_day.map((row) => [row.date, row.sales, row.revenue, row.refunds, row.net]),
          totals: ["Total", t.sales, t.gross_revenue, t.refunds, t.net_revenue],
        },
        {
          name: "By product",
          title: "Sales by product",
          subtitle,
          columns: [
            { header: "Product" }, { header: "Quantity", kind: "number" }, { header: "Sales", kind: "integer" },
            { header: "Revenue", kind: "money" }, { header: "Cost", kind: "money" }, { header: "Margin", kind: "money" },
          ],
          rows: report.by_product.map((row) => [row.product, row.quantity, row.sales, row.revenue, row.cost, row.margin]),
        },
        {
          name: "By payment",
          title: "Sales by payment method",
          subtitle,
          columns: [{ header: "Method" }, { header: "Payments", kind: "integer" }, { header: "Amount", kind: "money" }],
          rows: report.by_tender.map((row) => [row.label, row.count, row.amount]),
        },
        {
          name: "By cashier",
          title: "Sales by cashier",
          subtitle,
          columns: [{ header: "Cashier" }, { header: "Till" }, { header: "Sales", kind: "integer" }, { header: "Revenue", kind: "money" }],
          rows: report.by_cashier.map((row) => [row.cashier, row.till, row.sales, row.revenue]),
        },
        {
          name: "By hour",
          title: "Sales by hour of day",
          subtitle,
          columns: [{ header: "Hour" }, { header: "Sales", kind: "integer" }, { header: "Revenue", kind: "money" }],
          rows: report.by_hour.map((row) => [`${String(row.hour).padStart(2, "0")}:00`, row.sales, row.revenue]),
        },
      ],
      { organization: session?.organization?.display_name, generatedBy: session?.user.display_name },
    );
  };

  const t = report?.totals;
  const p = previous?.totals;

  return (
    <Page>
      <PageHeader
        title="Sales"
        description="Counter revenue, margin and returns, compared with the previous period."
        actions={
          <Button variant="outline" onClick={exportWorkbook} disabled={!report}>
            <Download className="h-4 w-4" /> Export
          </Button>
        }
      />

      <Toolbar
        trailing={
          <Select
            aria-label="Facility"
            value={facility}
            onChange={(event) => setFacility(event.target.value)}
            className="w-56"
          >
            <option value="">All facilities</option>
            {facilities.map((row) => (
              <option key={row.uuid} value={row.uuid}>
                {row.name}
              </option>
            ))}
          </Select>
        }
      >
        <SegmentedControl aria-label="Period" options={PRESETS} value={preset} onChange={choosePreset} />
        {preset === "custom" ? (
          <div className="flex items-center gap-2">
            <Input
              type="date"
              aria-label="From"
              value={range.start}
              max={range.end}
              onChange={(event) => event.target.value && setRange((r) => ({ ...r, start: event.target.value }))}
              className="w-40"
            />
            <span className="text-muted-foreground">to</span>
            <Input
              type="date"
              aria-label="To"
              value={range.end}
              min={range.start}
              onChange={(event) => event.target.value && setRange((r) => ({ ...r, end: event.target.value }))}
              className="w-40"
            />
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">{period}</span>
        )}
      </Toolbar>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <StatGrid>
        <Chart.Stat
          label="Net revenue"
          icon="finance"
          value={t ? Number(t.net_revenue) : null}
          format="money"
          delta={t ? change(Number(t.net_revenue), p ? Number(p.net_revenue) : undefined) : undefined}
          goodDirection="up"
          history={daily.map((row) => row.net)}
          footnote={t ? `${money(t.gross_revenue)} gross` : undefined}
        />
        <Chart.Stat
          label="Gross margin"
          icon="trendUp"
          value={t ? Number(t.gross_margin) : null}
          format="money"
          delta={t ? change(Number(t.gross_margin), p ? Number(p.gross_margin) : undefined) : undefined}
          goodDirection="up"
          footnote={t ? `${t.margin_percent}% of sales before VAT` : undefined}
        />
        <Chart.Stat
          label="Sales"
          icon="counter"
          value={t ? t.sales : null}
          delta={t ? change(t.sales, p?.sales) : undefined}
          goodDirection="up"
          footnote={t ? `${money(t.average_sale)} average` : undefined}
        />
        <Chart.Stat
          label="Refunds"
          icon="returnGoods"
          value={t ? Number(t.refunds) : null}
          format="money"
          delta={t ? change(Number(t.refunds), p ? Number(p.refunds) : undefined) : undefined}
          goodDirection="down"
          footnote={t ? `${t.returns} returns · ${t.return_rate_percent}% of revenue` : undefined}
        />
      </StatGrid>

      <div className="grid gap-4 xl:grid-cols-3">
        <Chart.Bar
          className="xl:col-span-2"
          title="Net revenue by day"
          description="Sales less refunds, on the day each happened."
          rows={daily}
          categoryKey="day"
          categoryLabel="Day"
          series={[{ key: "net", label: "Net revenue" }]}
          format="money"
          loading={loading && !report}
          height={260}
        />
        <Chart.Donut
          title="Payment methods"
          description="How customers paid."
          slices={tenders}
          format="money"
          totalLabel="collected"
          loading={loading && !report}
          height={260}
        />
      </div>

      <Chart.Bar
        title="Busiest hours"
        description={busiest ? `Most sales at ${busiest.hour}. Staff the counter to match.` : "When the counter is busiest."}
        rows={hourly}
        categoryKey="hour"
        categoryLabel="Hour"
        series={[{ key: "sales", label: "Sales" }]}
        emphasise={busiest?.hour}
        loading={loading && !report}
        height={200}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <Section title="Top products" className="xl:col-span-2">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Product</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead className="text-right">Margin</TableHead>
                    <TableHead className="text-right">Margin %</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(report?.by_product ?? []).slice(0, 12).map((row) => {
                    const revenue = Number(row.revenue);
                    const margin = Number(row.margin);
                    return (
                      <TableRow key={row.product}>
                        <TableCell className="font-medium">{row.product}</TableCell>
                        <TableCell className="text-right tabular-nums">{Number(row.quantity).toLocaleString()}</TableCell>
                        <TableCell className="text-right tabular-nums">{money(revenue)}</TableCell>
                        <TableCell className="text-right tabular-nums">{money(margin)}</TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {revenue ? `${((margin / revenue) * 100).toFixed(1)}%` : "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {report && report.by_product.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                        No sales in this period.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </Section>

        <Section title="Cashiers">
          <Card>
            <CardHeader className="sr-only">
              <CardTitle>Sales by cashier</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cashier</TableHead>
                    <TableHead className="text-right">Sales</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(report?.by_cashier ?? []).map((row) => (
                    <TableRow key={`${row.cashier}-${row.till}`}>
                      <TableCell>
                        <span className="block font-medium">{row.cashier || "—"}</span>
                        <span className="text-xs text-muted-foreground">{row.till}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{row.sales}</TableCell>
                      <TableCell className="text-right tabular-nums">{money(row.revenue)}</TableCell>
                    </TableRow>
                  ))}
                  {report && report.by_cashier.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
                        No sales in this period.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </Section>
      </div>
    </Page>
  );
}
