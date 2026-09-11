/**
 * The design system, rendered — at `/design`.
 *
 * **Every dark-mode defect in this product existed because there was nowhere
 * to see all of it at once.** 325 hardcoded colour utilities across 29 files,
 * only 48 of them with a `dark:` counterpart, had been shipping for months;
 * nobody was careless,
 * there was simply no screen on which the omission was visible. Reviewing a
 * design system by clicking through 44 application screens in two themes at
 * three widths is not a review anybody performs twice.
 *
 * So this is the review. Not a demo and not documentation — a page that puts
 * every token, every state and every chart form on one scroll, so that a
 * regression is *seen* rather than reported by a user.
 *
 * Deliberately not in the sidebar. It is for whoever is building the product;
 * the route is the door.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { NirovaLogo, NirovaMark, NirovaWordmark, OrgBrand } from "@/components/ui/brand";
import { ICONS, Icon, IconTile, type IconName } from "@/components/ui/icon";
import {
  ChartSkeleton,
  RecordSkeleton,
  Refreshing,
  Spinner,
} from "@/components/ui/loader";
import {
  CardSkeleton,
  EmptyState,
  ErrorState,
  Skeleton,
  StatSkeleton,
  TableSkeleton,
} from "@/components/ui/feedback";
import {
  AcuityBadge,
  Freshness,
  StatusBadge,
  StatusDot,
  TrendBadge,
} from "@/components/ui/status";
import { Button, Card, CardContent, Input, Label } from "@/components/ui/primitives";
import { Page, PageHeader, Section, StatGrid } from "@/components/ui/layout";
import { TabbedSection } from "@/components/ui/tabs";
import { PrintableDocument, SignatureBlock } from "@/components/ui/export";
import { CounterReceipt } from "@/components/documents/CounterReceipt";
import type { Sale } from "@/types";
import { printElement } from "@/lib/export";
import { Chart } from "@/components/charts";

/* -------------------------------------------------------------------------- */
/* Sample data                                                                 */
/* -------------------------------------------------------------------------- */

/*
  Shaped like the real thing and obviously invented. Named after nothing and
  nobody: a design-system page seeded with plausible patient names is a page
  somebody eventually screenshots into a slide deck.
*/
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const ATTENDANCE = DAYS.map((day, index) => ({
  day,
  outpatients: [128, 142, 119, 156, 171, 96, 61][index],
  inpatients: [34, 36, 31, 39, 42, 40, 38][index],
  emergency: [22, 19, 27, 24, 31, 36, 29][index],
}));

const REVENUE = DAYS.map((day, index) => ({
  day,
  consultation: [82000, 91000, 76000, 99000, 112000, 61000, 38000][index],
  pharmacy: [46000, 51000, 43000, 58000, 62000, 49000, 31000][index],
  laboratory: [28000, 31000, 26000, 34000, 39000, 22000, 14000][index],
}));

const WARDS = [
  { ward: "Medical", occupied: 28, capacity: 32 },
  { ward: "Surgical", occupied: 19, capacity: 24 },
  { ward: "Paediatric", occupied: 11, capacity: 20 },
  { ward: "Maternity", occupied: 15, capacity: 16 },
  { ward: "Isolation", occupied: 3, capacity: 8 },
];

const BEDS = Array.from({ length: 24 }, (_, index) => {
  const statuses = [
    "occupied", "occupied", "occupied", "available",
    "occupied", "cleaning", "occupied", "reserved",
    "occupied", "occupied", "maintenance", "available",
  ] as const;
  return {
    id: `bed-${index}`,
    label: `${index < 12 ? "A" : "B"}-${(index % 12) + 1}`,
    status: statuses[index % statuses.length],
    patient: statuses[index % statuses.length] === "occupied" ? `Patient ${index + 1}` : null,
    group: index < 12 ? "Bay A" : "Bay B",
  };
});

const THEATRE_DAY = [
  {
    id: "ot-1",
    label: "Theatre 1",
    items: [
      { id: "a", label: "Laparoscopic chole", start: hour(8, 30), end: hour(10, 15), tone: "brand" as const },
      { id: "b", label: "Hernia repair", start: hour(10, 45), end: hour(12, 0), tone: "brand" as const },
      { id: "c", label: "Emergency appendix", start: hour(14, 0), end: hour(15, 30), tone: "critical" as const },
    ],
  },
  {
    id: "ot-2",
    label: "Theatre 2",
    items: [
      { id: "d", label: "Caesarean", start: hour(9, 0), end: hour(10, 30), tone: "brand" as const },
      { id: "e", label: "Overrunning list", start: hour(11, 0), end: hour(16, 45), tone: "serious" as const },
    ],
  },
  {
    id: "ot-3",
    label: "Day surgery",
    items: [
      { id: "f", label: "Cataract ×4", start: hour(8, 0), end: hour(11, 30), tone: "brand" as const },
    ],
  },
];

function hour(h: number, m: number): Date {
  const date = new Date();
  date.setHours(h, m, 0, 0);
  return date;
}

const ARRIVALS_BY_HOUR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].flatMap((day, dayIndex) =>
  ["00", "03", "06", "09", "12", "15", "18", "21"].map((slot, slotIndex) => ({
    row: day,
    column: slot,
    // A plausible double peak — late morning and mid-evening — with the
    // weekend nights heavier, because that is what an ED actually looks like.
    value:
      slotIndex === 0 || slotIndex === 1
        ? 2 + ((dayIndex >= 5 ? 6 : 0) + slotIndex)
        : slotIndex === 3 || slotIndex === 4
          ? 14 + dayIndex
          : slotIndex === 6
            ? 11 + (dayIndex >= 5 ? 8 : 2)
            : 5 + slotIndex,
  })),
);

const MRR_MOVEMENT = [
  { label: "Opening", value: 1_240_000, isTotal: true },
  { label: "New", value: 186_000 },
  { label: "Expansion", value: 94_000 },
  { label: "Contraction", value: -41_000 },
  { label: "Churn", value: -68_000 },
  { label: "Closing", value: 0, isTotal: true },
];

const TURNAROUND = [
  { label: "Full blood count", before: 84, after: 46 },
  { label: "Renal profile", before: 132, after: 96 },
  { label: "Troponin", before: 61, after: 38 },
  { label: "Blood culture", before: 2880, after: 2640 },
  { label: "Histopathology", before: 7200, after: 8400 },
];

const CASE_MIX = [
  { band: "0–9", left: 142, right: 128 },
  { band: "10–19", left: 96, right: 104 },
  { band: "20–29", left: 118, right: 196 },
  { band: "30–39", left: 134, right: 188 },
  { band: "40–49", left: 156, right: 149 },
  { band: "50–59", left: 178, right: 162 },
  { band: "60–69", left: 164, right: 151 },
  { band: "70+", left: 121, right: 138 },
];

const QC_RUNS = Array.from({ length: 22 }, (_, index) => ({
  run: `${index + 1}`,
  value:
    5.2 +
    [0.1, -0.2, 0.05, 0.3, -0.1, 0.2, 0.0, -0.35, 0.15, 0.1, 0.62, 0.4, 0.2, -0.1,
     0.05, -0.25, 0.1, 0.3, -0.78, 0.2, 0.1, -0.05][index],
}));

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function KitchenPage() {
  return (
    <Page>
      <PageHeader
        title="Design system"
        description="Every token, state and chart form on one scroll. Switch the theme in the header and check this page — that is the review."
        breadcrumbs={[{ label: "Nirova" }, { label: "Design system" }]}
      />

      <TabbedSection
        tabs={[
          { id: "foundation", label: "Foundation", icon: "spark" },
          { id: "components", label: "Components", icon: "settings" },
          { id: "states", label: "States", icon: "meter" },
          { id: "charts", label: "Charts", icon: "report" },
          { id: "icons", label: "Icons", icon: "viewGrid" },
          { id: "documents", label: "Print & export", icon: "print" },
        ]}
      >
        {{
          foundation: <Foundation />,
          components: <Components />,
          states: <States />,
          charts: <Charts />,
          icons: <Icons />,
          documents: <Documents />,
        }}
      </TabbedSection>
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* Foundation                                                                  */
/* -------------------------------------------------------------------------- */

function Foundation() {
  return (
    <div className="space-y-8">
      <Section title="The mark" description="Not a lucide icon in a rounded square.">
        <div className="flex flex-wrap items-end gap-8 rounded-lg border bg-card p-6">
          <NirovaWordmark size="lg" />
          <NirovaWordmark size="md" />
          <NirovaWordmark size="sm" />
          <div className="flex items-end gap-3">
            <NirovaLogo size="lg" />
            <NirovaLogo size="md" />
            <NirovaLogo size="sm" />
          </div>
          <div className="flex items-end gap-4">
            <NirovaMark className="h-16 w-16 text-primary" />
            <NirovaMark className="h-8 w-8 text-foreground" />
            <NirovaMark className="h-4 w-4 text-foreground" />
          </div>
          <div className="rounded-lg border p-4">
            <p className="mb-2 type-eyebrow text-muted-foreground">
              The customer's, not ours
            </p>
            <OrgBrand
              name="Himalaya General Hospital"
              facility="Kathmandu — main campus"
            />
          </div>
        </div>
      </Section>

      <Section
        title="Brand and neutrals"
        description="Warm neutrals, hue 40–60. A cool grey is the default of every component library; a warm one has to be chosen."
      >
        <div className="space-y-3">
          <Ramp
            label="Brand"
            steps={[50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((step) => ({
              name: String(step),
              css: `hsl(var(--brand-${step}))`,
            }))}
          />
          <Ramp
            label="Neutral"
            steps={[0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 1000].map(
              (step) => ({ name: String(step), css: `hsl(var(--neutral-${step}))` }),
            )}
          />
        </div>
      </Section>

      <Section
        title="Chart series"
        description="Validated in both themes: worst adjacent CVD ΔE 10.1 light / 11.2 dark against a target of 8; normal-vision 21.8 / 19.2 against a floor of 15. Assigned in this order and never cycled."
      >
        <Ramp
          label="Series"
          steps={[1, 2, 3, 4, 5, 6, 7, 8].map((slot) => ({
            name: String(slot),
            css: `hsl(var(--series-${slot}))`,
          }))}
        />
        <Ramp
          label="Sequential"
          steps={[1, 2, 3, 4, 5, 6, 7, 8].map((slot) => ({
            name: String(slot),
            css: `hsl(var(--scale-${slot}))`,
          }))}
        />
      </Section>

      <Section
        title="Clinical semantics"
        description="The tokens that replace 325 hardcoded colour utilities. Each one means a state the domain actually has."
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <TokenCard
            title="Status"
            rows={[
              ["good", "Approved, paid, in stock, normal"],
              ["warning", "Pending, low stock, unpaid"],
              ["serious", "On hold, expiring, past due"],
              ["critical", "Rejected, expired, overdue"],
              ["info", "Scheduled, submitted, in progress"],
            ]}
          />
          <div className="rounded-lg border bg-card p-4">
            <p className="mb-3 type-heading">Triage acuity</p>
            <p className="mb-3 type-caption">
              The Manchester/ESI convention rather than a one-hue ramp — a
              deliberate exception, because staff are trained on it before they
              meet this software. Always rendered with its number.
            </p>
            <div className="flex flex-wrap gap-2">
              {[1, 2, 3, 4, 5].map((level) => (
                <AcuityBadge key={level} level={level} showLabel />
              ))}
            </div>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <p className="mb-3 type-heading">Elevation</p>
            <p className="mb-3 type-caption">
              Shadow on light, lightness and hairline on dark. A component asks
              for "raised" and gets the right answer in both.
            </p>
            <div className="grid grid-cols-2 gap-3">
              {/* Spelled out rather than `shadow-${level}` — Tailwind's scanner
                  finds class names as literal strings, so a constructed one is
                  emitted only if another file happens to spell it. */}
              {(
                [
                  ["flat", "shadow-flat"],
                  ["raised", "shadow-raised"],
                  ["floating", "shadow-floating"],
                  ["modal", "shadow-modal"],
                ] as const
              ).map(([level, shadow]) => (
                <div
                  key={level}
                  className={cn(
                    "flex h-14 items-center justify-center rounded-lg bg-card text-xs",
                    shadow,
                  )}
                >
                  {level}
                </div>
              ))}
            </div>
          </div>
        </div>
      </Section>

      <Section
        title="Type"
        description="Geist for the interface, Geist Mono for anything a human reads back to another human. Tabular figures by default — this product is sixty per cent numbers."
      >
        <div className="space-y-4 rounded-lg border bg-card p-6">
          <p className="type-display">Display — a page title</p>
          <p className="type-title">Title — a panel heading</p>
          <p className="type-heading">Heading — a section within a screen</p>
          <p className="type-body">
            Body — the ordinary running text of the interface, at the size most
            of the product is set in.
          </p>
          <p className="type-label">Label — a field name or a stat tile's caption</p>
          <p className="type-caption">Caption — secondary, explanatory, never load-bearing</p>
          <p className="type-eyebrow">Eyebrow — a group heading in the rail</p>
          <p className="type-code">MRN-2026-004471 · BATCH/AX-9920 · INV-000318</p>
          <p className="type-figure">148,320</p>
          <div className="border-t pt-4">
            <p className="mb-1 type-caption">
              Tabular against proportional — the reason the default matters:
            </p>
            <div className="flex gap-8 text-sm">
              <span>
                111,111
                <br />
                999,999
              </span>
              <span className="numeric-proportional">
                111,111
                <br />
                999,999
              </span>
            </div>
          </div>
        </div>
      </Section>
    </div>
  );
}

function Ramp({
  label,
  steps,
}: {
  label: string;
  steps: { name: string; css: string }[];
}) {
  return (
    <div>
      <p className="mb-1.5 type-eyebrow text-muted-foreground">{label}</p>
      <div className="flex overflow-hidden rounded-lg border">
        {steps.map((step) => (
          <div key={step.name} className="flex-1" title={step.css}>
            <div className="h-12" style={{ background: step.css }} />
            <div className="bg-card px-1 py-1 text-center text-[0.625rem] tabular-nums text-muted-foreground">
              {step.name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TokenCard({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="mb-3 type-heading">{title}</p>
      <ul className="space-y-2">
        {rows.map(([token, meaning]) => (
          <li key={token} className="flex items-center gap-2.5">
            <span
              className="h-4 w-4 shrink-0 rounded"
              style={{ background: `hsl(var(--${token}))` }}
            />
            <span className="w-16 shrink-0 type-code text-xs">{token}</span>
            <span className="min-w-0 flex-1 truncate type-caption">{meaning}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Components                                                                  */
/* -------------------------------------------------------------------------- */

function Components() {
  return (
    <div className="space-y-8">
      <Section title="Status" description="Every one of these was a hardcoded colour on some screen.">
        <div className="space-y-4 rounded-lg border bg-card p-5">
          <div className="flex flex-wrap gap-2">
            {["draft", "pending", "approved", "rejected", "expired", "paid",
              "overdue", "in stock", "low stock", "out of stock", "expiring",
              "occupied", "available", "critical", "abnormal", "on leave"].map(
              (status) => (
                <StatusBadge key={status} status={status} />
              ),
            )}
          </div>
          <div className="flex flex-wrap gap-3 border-t pt-4">
            {["approved", "pending", "rejected"].map((status) => (
              <StatusBadge key={status} status={status} variant="solid" />
            ))}
            {["approved", "pending", "rejected"].map((status) => (
              <StatusBadge key={`o-${status}`} status={status} variant="outline" />
            ))}
          </div>
          <div className="flex flex-wrap gap-4 border-t pt-4 text-sm">
            {["occupied", "cleaning", "blocked", "available"].map((status) => (
              <StatusDot key={status} status={status} />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-5 border-t pt-4">
            <TrendBadge value={12.4} goodDirection="up" />
            <TrendBadge value={-8.1} goodDirection="up" />
            <TrendBadge value={-8.1} goodDirection="down" />
            <TrendBadge value={0} goodDirection="up" />
            <TrendBadge value={null} goodDirection="up" />
            <Freshness at={new Date()} />
            <Freshness at={new Date(Date.now() - 3_600_000)} stale />
          </div>
          <p className="border-t pt-4 type-caption">
            <strong className="font-medium text-foreground">
              Up is not always good.
            </strong>{" "}
            `goodDirection` has no default, so a caller cannot accidentally paint
            a rising infection rate green.
          </p>
        </div>
      </Section>

      <Section title="Buttons and fields">
        <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-5">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button disabled>Disabled</Button>
          <Button size="sm">Small</Button>
          <Button>
            <Spinner size="sm" className="mr-2" />
            Working
          </Button>
          <div className="w-48 space-y-1.5">
            <Label htmlFor="kitchen-input">A field</Label>
            <Input id="kitchen-input" placeholder="Type here" />
          </div>
        </div>
      </Section>

      <Section
        title="Stat tiles"
        description="A statistic without a comparison is not a statistic."
      >
        <StatGrid>
          <Chart.Stat
            label="Patients today"
            value={342}
            icon="patient"
            delta={8.4}
            goodDirection="up"
            history={[280, 296, 310, 288, 322, 334, 342]}
          />
          <Chart.Stat
            label="Bed occupancy"
            value={87.5}
            format="percent"
            icon="ward"
            delta={4.2}
            goodDirection="neither"
            tone="warning"
            target={85}
          />
          <Chart.Stat
            label="Revenue today"
            value={412_500}
            format="money"
            icon="payment"
            delta={-3.1}
            goodDirection="up"
            history={[380000, 402000, 445000, 398000, 421000, 405000, 412500]}
          />
          <Chart.Stat
            label="Infection rate"
            value={2.4}
            format="percent"
            icon="warning"
            delta={0.6}
            goodDirection="down"
            tone="critical"
            footnote="rising — up is bad here"
          />
        </StatGrid>
      </Section>

      <Section title="Micro forms">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardContent className="space-y-4 pt-5">
              <p className="type-heading">Bullet — the answer to "can we have a gauge"</p>
              {WARDS.map((ward) => (
                <Chart.Bullet
                  key={ward.ward}
                  label={ward.ward}
                  value={ward.occupied}
                  target={Math.round(ward.capacity * 0.85)}
                  max={ward.capacity}
                  tone={ward.occupied / ward.capacity > 0.9 ? "critical" : "brand"}
                />
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex flex-col gap-5 pt-5">
              <p className="type-heading">Meter — one ratio, one limit</p>
              <Chart.Meter
                value={87}
                label="Bed occupancy"
                sublabel="76 of 87 beds"
                thresholds={{ warning: 80, critical: 92 }}
              />
              <Chart.Meter
                value={412}
                max={500}
                format="number"
                label="Patients this month"
                sublabel="against a plan limit of 500"
                thresholds={{ warning: 75, critical: 90 }}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-4 pt-5">
              <p className="type-heading">Sparkline — in a table cell</p>
              {["Medical", "Surgical", "Paediatric"].map((ward, index) => (
                <div key={ward} className="flex items-center justify-between gap-3">
                  <span className="text-sm">{ward}</span>
                  <Chart.Sparkline
                    values={[
                      [22, 26, 24, 29, 27, 31, 28],
                      [18, 16, 19, 15, 14, 12, 11],
                      [8, 9, null, 11, 10, 12, 13],
                    ][index]}
                    tone={index === 1 ? "critical" : "brand"}
                  />
                </div>
              ))}
              <p className="type-caption">
                The third has a gap: a missing observation breaks the line rather
                than being interpolated through.
              </p>
            </CardContent>
          </Card>
        </div>
      </Section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* States                                                                      */
/* -------------------------------------------------------------------------- */

function States() {
  const [refreshing, setRefreshing] = React.useState(false);

  return (
    <div className="space-y-8">
      <Section
        title="Waiting"
        description="Five distinct waits, five treatments. Under 250ms, the right treatment is none — Delayed swallows it."
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardContent className="space-y-4 pt-5">
              <p className="type-heading">Spinner</p>
              <div className="flex items-center gap-6">
                <Spinner size="xs" />
                <Spinner size="sm" />
                <Spinner size="md" />
                <Spinner size="lg" />
                <Spinner size="md" className="text-primary" />
              </div>
              <p className="type-caption">
                An arc on a visible track, so the motion reads as progress around
                something rather than as a glyph tumbling.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-3 pt-5">
              <div className="flex items-center justify-between">
                <p className="type-heading">Refreshing, not replacing</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setRefreshing(true);
                    window.setTimeout(() => setRefreshing(false), 2200);
                  }}
                >
                  Try it
                </Button>
              </div>
              <Refreshing active={refreshing}>
                <ul className="space-y-1.5 text-sm">
                  {WARDS.map((ward) => (
                    <li key={ward.ward} className="flex justify-between border-b pb-1.5">
                      <span>{ward.ward}</span>
                      <span className="tabular-nums">
                        {ward.occupied}/{ward.capacity}
                      </span>
                    </li>
                  ))}
                </ul>
              </Refreshing>
              <p className="type-caption">
                Once a screen has data it never goes back to a skeleton — somebody
                reading row forty should still be looking at row forty.
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardContent className="space-y-3 pt-5">
              <p className="type-heading">Table skeleton</p>
              <TableSkeleton rows={5} columns={4} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-3 pt-5">
              <p className="type-heading">Chart skeleton</p>
              <ChartSkeleton height={160} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-3 pt-5">
              <p className="type-heading">Stat skeleton</p>
              <StatSkeleton count={2} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-3 pt-5">
              <p className="type-heading">Card skeleton</p>
              <CardSkeleton count={2} />
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardContent className="space-y-3 pt-5">
            <p className="type-heading">Record skeleton</p>
            <RecordSkeleton />
          </CardContent>
        </Card>
      </Section>

      <Section
        title="Nothing, and failure"
        description="An empty table reads as a failure. A failed chart reads as a zero. Both are fixed by saying which it is."
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-5">
              <EmptyState
                title="No patients waiting"
                description="Nobody is in the queue. When somebody arrives at the front desk they will appear here."
                action={<Button size="sm">Register an arrival</Button>}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <ErrorState
                title="The ward list could not be read"
                description="The inpatient service returned an error. This is not an empty ward."
                onRetry={() => undefined}
              />
            </CardContent>
          </Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Chart.Bar
            title="A chart that failed"
            rows={[]}
            categoryKey="day"
            series={[{ key: "value", label: "Value" }]}
            error="The reporting service did not answer."
            height={160}
          />
          <Chart.Bar
            title="A chart that is genuinely empty"
            rows={[]}
            categoryKey="day"
            series={[{ key: "value", label: "Value" }]}
            empty
            emptyMessage="No admissions recorded on this ward today."
            height={160}
          />
          <Chart.Bar
            title="A chart still loading"
            rows={[]}
            categoryKey="day"
            series={[{ key: "value", label: "Value" }]}
            loading
            height={160}
          />
        </div>
      </Section>

      <Section title="Skeleton primitive">
        <div className="flex flex-wrap gap-3 rounded-lg border bg-card p-5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-8 w-24 rounded-md" />
          <Skeleton className="h-10 w-10 rounded-full" />
        </div>
      </Section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Charts                                                                      */
/* -------------------------------------------------------------------------- */

function Charts() {
  return (
    <div className="space-y-8">
      <p className="rounded-lg border border-dashed bg-muted/30 p-4 type-caption">
        Every chart here has a table view behind the icon in its corner, a hover
        layer, a legend when it has two or more series and none when it has one,
        and an as-of time. Those are not per-chart decisions — they come from{" "}
        <span className="type-code">ChartFrame</span>.
      </p>

      <Section title="Trend and magnitude">
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-5">
              <Chart.Line
                title="Attendance by day"
                description="Three series — categorical, because the series are the subject."
                rows={ATTENDANCE}
                categoryKey="day"
                categoryLabel="Day"
                series={[
                  { key: "outpatients", label: "Outpatients" },
                  { key: "inpatients", label: "Inpatients" },
                  { key: "emergency", label: "Emergency" },
                ]}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Area
                title="Revenue by stream"
                description="Stacked — composition over time."
                rows={REVENUE}
                categoryKey="day"
                categoryLabel="Day"
                stacked
                format="money"
                series={[
                  { key: "consultation", label: "Consultation" },
                  { key: "pharmacy", label: "Pharmacy" },
                  { key: "laboratory", label: "Laboratory" },
                ]}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Bar
                title="Occupancy by ward"
                description="Horizontal, because the category names are words."
                rows={WARDS}
                categoryKey="ward"
                categoryLabel="Ward"
                layout="horizontal"
                series={[{ key: "occupied", label: "Occupied" }]}
                reference={{ value: 20, label: "Target", tone: "warning" }}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Bar
                title="Emphasis — one bar is the story"
                description="One series in the accent, the rest receding. The most underused form."
                rows={WARDS}
                categoryKey="ward"
                categoryLabel="Ward"
                layout="horizontal"
                emphasise="Maternity"
                series={[{ key: "occupied", label: "Occupied" }]}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Polarity and correlation">
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-5">
              <Chart.Diverging
                title="Variance to budget"
                description="Two hues and a neutral zero — the directions mean opposite things."
                rows={[
                  { department: "Outpatients", variance: 184_000 },
                  { department: "Pharmacy", variance: 62_000 },
                  { department: "Laboratory", variance: -38_000 },
                  { department: "Theatre", variance: -126_000 },
                  { department: "Radiology", variance: 21_000 },
                ]}
                categoryKey="department"
                categoryLabel="Department"
                valueKey="variance"
                valueLabel="Variance"
                format="money"
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Scatter
                title="Utilisation against overrun"
                description="Capped at three groups — every pair is on screen at once here."
                groups={[
                  {
                    key: "elective",
                    label: "Elective",
                    points: [
                      { utilisation: 82, overrun: 14 },
                      { utilisation: 74, overrun: 9 },
                      { utilisation: 91, overrun: 26 },
                      { utilisation: 68, overrun: 6 },
                    ],
                  },
                  {
                    key: "emergency",
                    label: "Emergency",
                    points: [
                      { utilisation: 96, overrun: 41 },
                      { utilisation: 88, overrun: 33 },
                      { utilisation: 79, overrun: 22 },
                    ],
                  },
                  {
                    key: "day",
                    label: "Day surgery",
                    points: [
                      { utilisation: 61, overrun: 3 },
                      { utilisation: 70, overrun: 5 },
                    ],
                  },
                ]}
                xKey="utilisation"
                yKey="overrun"
                xLabel="Utilisation"
                yLabel="Overrun"
                xFormat="percent"
                yFormat="duration"
                asOf={new Date()}
              />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Part to whole">
        <div className="grid gap-5 lg:grid-cols-3">
          <Card>
            <CardContent className="pt-5">
              <Chart.Donut
                title="Payer mix"
                slices={[
                  { name: "Self-pay", value: 412 },
                  { name: "Insurance", value: 286 },
                  { name: "Government scheme", value: 174 },
                  { name: "Corporate", value: 92 },
                  { name: "Charity", value: 38 },
                ]}
                totalLabel="encounters"
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Funnel
                title="Claim pipeline"
                description="The drop between stages is the story, so it is labelled."
                stages={[
                  { name: "Submitted", value: 480 },
                  { name: "Accepted", value: 414 },
                  { name: "Adjudicated", value: 288 },
                  { name: "Settled", value: 265 },
                ]}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Treemap
                title="Stock value by category"
                items={[
                  { name: "Antibiotics", value: 1_240_000 },
                  { name: "Cardiac", value: 860_000 },
                  { name: "Analgesics", value: 520_000 },
                  { name: "Consumables", value: 430_000 },
                  { name: "Surgical", value: 310_000 },
                  { name: "Vaccines", value: 190_000 },
                  { name: "Diagnostics", value: 120_000 },
                ]}
                format="money"
                asOf={new Date()}
              />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Grids — the ones a hospital actually reads">
        <div className="space-y-5">
          <Card>
            <CardContent className="pt-5">
              <Chart.Heatmap
                title="Emergency arrivals by day and hour"
                description="The question a line chart cannot answer: when to roster."
                cells={ARRIVALS_BY_HOUR}
                rows={DAYS}
                columns={["00", "03", "06", "09", "12", "15", "18", "21"]}
                valueLabel="Arrivals"
                height={240}
                asOf={new Date()}
              />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-3 pt-5">
              <div>
                <p className="type-heading">Ward occupancy</p>
                <p className="type-caption">
                  The most-requested view in any hospital system, and the one this
                  product did not have.
                </p>
              </div>
              <Chart.OccupancyGrid beds={BEDS} groupBy={(bed) => bed.group ?? "Unassigned"} />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-3 pt-5">
              <div>
                <p className="type-heading">Theatre day</p>
                <p className="type-caption">
                  The gap where a case fits and the list that is overrunning — both
                  invisible in a table sorted by start time.
                </p>
              </div>
              <Chart.Gantt rows={THEATRE_DAY} now={new Date()} />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5">
              <Chart.Calendar
                title="Admissions across the year"
                description="Seasonality — monsoon peaks, festival troughs."
                days={Array.from({ length: 365 }, (_, index) => {
                  const date = new Date(Date.UTC(new Date().getFullYear(), 0, 1));
                  date.setUTCDate(date.getUTCDate() + index);
                  const month = date.getUTCMonth();
                  const monsoon = month >= 5 && month <= 8 ? 14 : 0;
                  const weekend = [0, 6].includes(date.getUTCDay()) ? -6 : 0;
                  return {
                    date: date.toISOString().slice(0, 10),
                    value: Math.max(0, 16 + monsoon + weekend + ((index * 7) % 9)),
                  };
                })}
                valueLabel="Admissions"
                asOf={new Date()}
              />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Domain forms">
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-5">
              <Chart.Waterfall
                title="MRR movement"
                description="How it got from opening to closing — a bar chart cannot answer this."
                steps={MRR_MOVEMENT}
                format="money"
                height={260}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Dumbbell
                title="Laboratory turnaround, before and after"
                description="The gap is the finding, so the gap is the mark."
                rows={TURNAROUND}
                beforeLabel="Last quarter"
                afterLabel="This quarter"
                goodDirection="down"
                format="duration"
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.Pyramid
                title="Case mix by age and sex"
                bands={CASE_MIX}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <Chart.LeveyJennings
                title="Glucose control — Levey–Jennings"
                description="§34 has asked for this since the beginning. Violations change shape as well as colour."
                rows={QC_RUNS}
                mean={5.2}
                sd={0.3}
                height={260}
                asOf={new Date()}
              />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Composition in a row">
        <Card>
          <CardContent className="space-y-5 pt-5">
            <Chart.StackedProgress
              segments={[
                { label: "Occupied", value: 76, tone: "info" },
                { label: "Available", value: 11, tone: "good" },
                { label: "Cleaning", value: 6, tone: "warning" },
                { label: "Blocked", value: 3, tone: "critical" },
              ]}
            />
            <Chart.StackedProgress
              segments={[
                { label: "Current", value: 1_240_000, tone: "good" },
                { label: "31–60 days", value: 480_000, tone: "warning" },
                { label: "61–90 days", value: 210_000, tone: "serious" },
                { label: "Over 90", value: 96_000, tone: "critical" },
              ]}
              format="money"
            />
          </CardContent>
        </Card>
      </Section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Icons                                                                       */
/* -------------------------------------------------------------------------- */

function Icons() {
  const names = Object.keys(ICONS) as IconName[];

  return (
    <div className="space-y-8">
      <Section
        title="Sizes and stroke"
        description="Stroke scales down as the icon grows. A constant stroke makes small icons muddy and large ones skeletal — the clearest tell of an icon set that was imported rather than styled."
      >
        <div className="flex flex-wrap items-end gap-6 rounded-lg border bg-card p-5">
          {(["xs", "sm", "md", "lg", "xl", "2xl"] as const).map((size) => (
            <div key={size} className="flex flex-col items-center gap-2">
              <Icon name="patient" size={size} />
              <span className="type-caption">{size}</span>
            </div>
          ))}
          <div className="flex items-end gap-3 border-l pl-6">
            {(["neutral", "brand", "good", "warning", "serious", "critical", "info"] as const).map(
              (tone) => (
                <IconTile key={tone} name="vitals" tone={tone} />
              ),
            )}
          </div>
        </div>
      </Section>

      <Section
        title={`The vocabulary — ${names.length} concepts`}
        description="Named for the concept, never for the picture. A patient was three different glyphs across the console; now it is one."
      >
        <div className="grid grid-cols-[repeat(auto-fill,minmax(8rem,1fr))] gap-2 rounded-lg border bg-card p-4">
          {names.map((name) => (
            <div
              key={name}
              className="flex flex-col items-center gap-1.5 rounded-md px-2 py-3 transition-colors duration-quick hover:bg-accent"
              title={name}
            >
              <Icon name={name} size="lg" className="text-muted-foreground" />
              <span className="w-full truncate text-center text-[0.625rem] text-muted-foreground">
                {name}
              </span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}


/* -------------------------------------------------------------------------- */
/* Print and export                                                            */
/* -------------------------------------------------------------------------- */

/**
 * The document frame, rendered on screen.
 *
 * **Deliberately not print-only.** A layout nobody can check without wasting
 * paper is a layout that stays broken for months, which is how this product
 * shipped for nine months with no print stylesheet at all — every prescription
 * and invoice came out as a screenshot of the application, navigation rail
 * included, on a dark background.
 *
 * Press Print here and what comes out is this element and nothing else: the
 * stylesheet forces the light palette, keeps the background fills Chrome would
 * otherwise drop, and stops a table row splitting across a page break.
 */
/** Illustrative only — the same fictional hospital as the invoice above. */
const SAMPLE_SALE: Sale = {
  uuid: "sample-sale",
  reference: "S2609120014",
  session: "",
  session_reference: "CS-000118",
  facility: "",
  location: "",
  sale_type: "walk_in",
  patient: null,
  customer_label: "Walk-in customer",
  customer_name: "",
  customer_phone: "",
  customer_pan: "",
  prescription_reference: "",
  status: "completed",
  sold_at: "2026-09-12T10:42:00+05:45",
  sold_by_name: "Rita Gurung",
  subtotal: "340.00",
  discount_total: "0.00",
  tax_total: "6.50",
  rounding_adjustment: "0.50",
  total: "347.00",
  invoice_number: "INV-HGH-PH-2083/84-000412",
  void_reason: "",
  notes: "",
  lines: [
    { uuid: "l1", product: "", product_name: "Cetirizine 10 mg (Cetzine)", batch: "", batch_number: "OTC001-26A", expires_on: "2027-11-30", quantity: "10", returned_quantity: "0", returnable_quantity: "10", unit_price: "3.00", mrp: "3.50", discount_percent: "0", discount_amount: "0.00", tax_percent: "0", tax_amount: "0.00", total: "30.00" },
    { uuid: "l2", product: "", product_name: "Antacid suspension 170 mL (Digene)", batch: "", batch_number: "OTC003-26A", expires_on: "2027-07-31", quantity: "1", returned_quantity: "0", returnable_quantity: "1", unit_price: "165.00", mrp: "180.00", discount_percent: "0", discount_amount: "0.00", tax_percent: "0", tax_amount: "0.00", total: "165.00" },
    { uuid: "l3", product: "", product_name: "Surgical face mask 3-ply", batch: "", batch_number: "OTC011-26A", expires_on: "2029-03-31", quantity: "10", returned_quantity: "0", returnable_quantity: "10", unit_price: "5.00", mrp: "5.00", discount_percent: "0", discount_amount: "0.00", tax_percent: "13", tax_amount: "6.50", total: "56.50" },
    { uuid: "l4", product: "", product_name: "Ibuprofen 400 mg (Brufen)", batch: "", batch_number: "OTC004-26B", expires_on: "2026-11-25", quantity: "20", returned_quantity: "0", returnable_quantity: "20", unit_price: "4.00", mrp: "4.50", discount_percent: "0", discount_amount: "0.00", tax_percent: "0", tax_amount: "0.00", total: "80.00" },
    { uuid: "l5", product: "", product_name: "Oral rehydration salts (Jeevan Jal)", batch: "", batch_number: "OTC002-26A", expires_on: "2028-03-01", quantity: "1", returned_quantity: "0", returnable_quantity: "1", unit_price: "15.00", mrp: "16.00", discount_percent: "0", discount_amount: "0.00", tax_percent: "0", tax_amount: "0.00", total: "15.00" },
  ],
  issuer: {
    name: "Himalaya General Hospital Pharmacy",
    address: "Maharajgunj, Kathmandu Metropolitan City, Ward 3",
    phone: "01-4412345",
    pan: "601234567",
    licence: "DDA-KTM-2079-0412",
  },
  payments: [
    { method: "esewa", method_label: "eSewa", amount: "200.00", reference: "ESEWA48213907" },
    { method: "cash", method_label: "Cash", amount: "147.00", reference: "" },
  ],
};

function Documents() {
  return (
    <div className="space-y-8">
      <Section
        title="A printable document"
        description="Issuer, reference, identity block, signature lines — and who printed it, which is the line everybody forgets and the only one that matters in a dispute."
      >
        <div className="space-y-3">
          <Button size="sm" variant="outline" onClick={() => printElement("demo-invoice")}>
            <Icon name="print" size="sm" className="mr-1.5" />
            Print this document
          </Button>

          <PrintableDocument
            id="demo-invoice"
            title="Tax invoice"
            reference="INV-2026-000318"
            organization="Himalaya General Hospital"
            facility="Kathmandu — main campus"
            facilityDetail={
              <>
                Maharajgunj, Kathmandu · PAN 301234567 · Licence NHL-4471
                <br />
                +977 1 4412345 · accounts@example.test
              </>
            }
            issuedAt={new Date()}
            printedBy="A. Upreti"
            meta={[
              { label: "Patient", value: "Illustrative patient" },
              { label: "MRN", value: <span className="type-code">MRN-2026-004471</span> },
              { label: "Payer", value: "Self-pay" },
              { label: "Encounter", value: <span className="type-code">ENC-88213</span> },
            ]}
            footer={
              <SignatureBlock
                signatories={[
                  { role: "Prepared by", name: "A. Upreti" },
                  { role: "Checked by" },
                  { role: "Received by" },
                ]}
              />
            }
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="py-1.5 pr-3 type-label text-muted-foreground">Item</th>
                  <th className="py-1.5 px-3 text-right type-label text-muted-foreground">Qty</th>
                  <th className="py-1.5 px-3 text-right type-label text-muted-foreground">Rate</th>
                  <th className="py-1.5 pl-3 text-right type-label text-muted-foreground">Amount</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["Consultation — general medicine", 1, 800],
                  ["Full blood count", 1, 650],
                  ["Renal profile", 1, 1200],
                  ["Ultrasound — abdomen", 1, 2500],
                ].map(([item, qty, rate]) => (
                  <tr key={String(item)} className="border-b last:border-0">
                    <td className="py-1.5 pr-3">{item}</td>
                    <td className="py-1.5 px-3 text-right tabular-nums">{qty}</td>
                    <td className="py-1.5 px-3 text-right tabular-nums">
                      {Number(rate).toLocaleString()}
                    </td>
                    <td className="py-1.5 pl-3 text-right tabular-nums">
                      {(Number(qty) * Number(rate)).toLocaleString()}
                    </td>
                  </tr>
                ))}
                <tr className="border-t-2 border-border-strong font-semibold">
                  <td className="py-2 pr-3" colSpan={3}>
                    Total
                  </td>
                  <td className="py-2 pl-3 text-right tabular-nums">5,150</td>
                </tr>
              </tbody>
            </table>
          </PrintableDocument>
        </div>
      </Section>

      <Section
        title="A counter receipt"
        description="At the roll's width, printed alone. The seller's PAN, each line's batch and expiry — which is how a recall reaches the customer — every tender with its wallet reference, and the return terms."
      >
        <div className="flex flex-wrap items-start gap-6">
          <div className="w-[80mm] overflow-hidden rounded-lg border bg-white shadow-sm">
            <CounterReceipt sale={SAMPLE_SALE} change={3} />
          </div>
          <Button size="sm" variant="outline" onClick={() => printElement(`receipt-${SAMPLE_SALE.uuid}`)}>
            <Icon name="print" size="sm" className="mr-1.5" />
            Print this receipt
          </Button>
        </div>
      </Section>

      <Section
        title="Export"
        description="Attached to every DataView, so a list gains it by adopting the component rather than by growing its own button."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              title: "The filtered rows, not all of them",
              detail:
                "An export that silently returns everything while the screen shows a subset is the sort of file somebody reconciles a bank statement against and cannot work out why the totals differ.",
              icon: "viewTable" as const,
            },
            {
              title: "Formula injection is closed",
              detail:
                "A cell beginning = + - or @ executes as a formula in Excel and Sheets. A patient named =cmd|… would be code execution on whoever opens the file. One apostrophe, stripped again on display.",
              icon: "permission" as const,
            },
            {
              title: "A byte-order mark on the Excel file",
              detail:
                "Without it Excel reads the file as the system codepage and every Devanagari name and the rupee sign arrive as mojibake — and users conclude the system stored the name wrong.",
              icon: "spark" as const,
            },
            {
              title: "Only columns that mean something",
              detail:
                "A cell rendering an avatar and a badge has no CSV form; stringifying the element puts [object Object] in a file somebody sends to an insurer.",
              icon: "confirm" as const,
            },
            {
              title: "No PDF library",
              detail:
                "jsPDF and friends are 300–800 kB and produce documents that look nothing like the screen. The browser already writes PDF, so Print opens it and the operator picks Save as PDF — which is what every hospital system that prints anything does.",
              icon: "print" as const,
            },
            {
              title: "Printing is the same element",
              detail:
                "Not a new window with re-applied styles, which is how a printed invoice ends up looking nothing like the invoice on screen. The document is stamped and everything outside the target is hidden.",
              icon: "attach" as const,
            },
          ].map((item) => (
            <div key={item.title} className="rounded-lg border bg-card p-4">
              <Icon name={item.icon} size="lg" className="mb-2 text-muted-foreground" />
              <p className="type-heading">{item.title}</p>
              <p className="mt-1 type-caption">{item.detail}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
