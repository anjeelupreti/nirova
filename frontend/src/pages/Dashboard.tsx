/**
 * The home screen, shaped by whose it is.
 *
 * **Two problems, and the second is the one that mattered.**
 *
 * The first was that there was no dashboard at all: `home` was hardcoded to
 * `/patients`, so every one of the seventeen seeded roles opened onto a patient
 * list — a pharmacist, a controller and a payroll officer included.
 *
 * The second survived the fix. The dashboard that replaced it was *one* screen
 * with permission-gated panels, so a pharmacist and a medical director still
 * saw the same product; the only difference was which panels disappeared. That
 * is not personalisation, it is subtraction, and it is why "the system itself
 * is confused whom to show what" was a fair description.
 *
 * So this screen resolves a **persona** from what somebody can actually do —
 * not from their role code, which a customer can rename or invent — and hands
 * off to a home composed for that job. A ward is beds in deterioration order.
 * A clinic is a list of people with waiting times. A cash position is money
 * moving. Forcing all three into a grid of stat tiles is what made the product
 * read as a database browser with a hospital theme.
 *
 * The person can override the inference and the choice is remembered, because
 * inference is a good default and a bad law: a matron who wants the front desk
 * on a Monday should have it.
 */

import * as React from "react";
import { Link } from "react-router-dom";

import { useCan } from "@/components/ui/can";
import { Icon, type IconName } from "@/components/ui/icon";
import { Page } from "@/components/ui/layout";
import { useSession } from "@/hooks/useSession";
import { Chart, formatValue } from "@/components/charts";
import {
  availablePersonas,
  resolvePersona,
  type PersonaId,
} from "@/components/shell/personas";
import {
  PanelEmpty,
  PanelLoading,
  PanelProblem,
  WorkspaceHero,
  WorkspacePanel,
} from "@/components/workspace/WorkspaceFrame";
import { useResource } from "@/components/workspace/useResource";
import {
  ApprovalsPanel,
} from "@/components/workspace/homes";
import type {
  DepartmentSummary,
  Facility,
  MyWorkspace,
  NurseWorkspaceSummary,
  ProcurementDashboard,
  SalesSummary,
} from "@/types";
import { formatWeekday } from "@/lib/dates";

const PERSONA_KEY = "nirova.persona";

/**
 * The organization's day, from `/org/today/`. A block is absent when the
 * viewer may not see it or the plan does not include it -- never zero.
 */
interface OrganizationToday {
  as_of: string;
  facility: string | null;
  outpatients?: { seen: number; waiting: number; appointments: number; no_shows: number };
  emergency?: { arrivals: number; in_department: number };
  inpatients?: {
    occupied: number;
    beds: number;
    occupancy_percent: number | null;
    admitted: number;
    discharged: number;
  };
  laboratory?: { outstanding: number; critical_open: number; released: number };
  billing?: { collected: string; outstanding: string; overdue_invoices: number };
  pharmacy?: { takings: string; sales: number };
  /**
   * The same blocks for comparison: events up to this time yesterday, levels
   * from last night's snapshot. A figure with no yesterday has no delta.
   */
  previous?: {
    label: string;
    snapshot_date: string | null;
    blocks: Record<string, Record<string, number | string | null> | undefined>;
  };
}

/** The selector's value for "every facility", which no facility uuid can collide with. */
const ALL_FACILITIES = "all";

/** Today as `YYYY-MM-DD` in the browser's own timezone. */
function localIsoDate(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** The first facility of the first matching type, in the order the types are given. */
function pickFacility(list: Facility[], types: string[]): Facility | undefined {
  for (const type of types) {
    const found = list.find((row) => row.facility_type === type);
    if (found) return found;
  }
  return list[0];
}

export default function DashboardPage() {
  const can = useCan();
  const { session } = useSession();

  const isPlatformOnly =
    Boolean(session?.user.is_platform_staff) &&
    (session?.memberships.length ?? 0) === 0;

  /*
    The override, in `localStorage` rather than on the server.

    Deliberate: which board somebody wants *this week* is closer to a rail
    fold than to a theme. The theme follows you between machines because it is
    about your eyes; this is about your rota.
  */
  const [override, setOverride] = React.useState<PersonaId | "auto">(() => {
    try {
      return (window.localStorage.getItem(PERSONA_KEY) as PersonaId) ?? "auto";
    } catch {
      return "auto";
    }
  });

  const choose = React.useCallback((next: PersonaId | "auto") => {
    setOverride(next);
    try {
      window.localStorage.setItem(PERSONA_KEY, next);
    } catch {
      /* A preference that cannot be saved still works for this session. */
    }
  }, []);

  const persona = resolvePersona({ can, isPlatformOnly, override });
  const options = React.useMemo(() => availablePersonas(can), [can]);

  /*
    The facility. Several boards are per-building rather than per-customer, and
    a three-hospital group asking "how is the queue" has to mean one of them.
  */
  const facilities = useResource<{ results?: Facility[] } | Facility[]>(
    "/org/facilities/",
    can("facility.read", "facility"),
  );
  const facilityList = React.useMemo(() => {
    const raw = facilities.data;
    if (!raw) return [];
    return Array.isArray(raw) ? raw : (raw.results ?? []);
  }, [facilities.data]);

  /*
    **Defaulting to the first facility put every board on the clinic** — first
    alphabetically, and the one place with no emergency department, no wards
    and no counter. A director opening the product saw "0 in department · NPR 0"
    for a group whose hospital had had twenty-seven arrivals that day.

    So the default follows the work. Leadership and finance get the whole
    organization, where each panel goes to the facility its department runs
    at; a pharmacist gets the pharmacy; everyone else the hospital. Choosing a
    facility still narrows every panel to it.
  */
  const [facility, setFacility] = React.useState<string | null>(null);
  const wholeOrganization = persona.id === "leadership" || persona.id === "finance";
  React.useEffect(() => {
    if (facility || facilityList.length === 0) return;
    if (wholeOrganization && facilityList.length > 1) {
      setFacility(ALL_FACILITIES);
      return;
    }
    const preferred = persona.id === "pharmacy" ? ["pharmacy"] : ["hospital"];
    setFacility(pickFacility(facilityList, preferred)?.uuid ?? facilityList[0].uuid);
  }, [facility, facilityList, persona.id, wholeOrganization]);

  /* Read once here and passed down: six homes want it and six requests for the
     same answer is the busiest endpoint in the product for no clinical reason. */
  const workspace = useResource<MyWorkspace>("/me/workspace/");

  /*
    For whoever runs the place, the band at the top is the organization's day
    -- patients seen, beds, money -- rather than their own inbox, which is
    what My day is for. Each figure opens the list it counts.
  */
  const today = useResource<OrganizationToday>(
    wholeOrganization && facility
      ? `/org/today/${facility === ALL_FACILITIES ? "" : `?facility=${facility}`}`
      : null,
    can("analytics.read", "facility"),
  );
  const organizationFigures = wholeOrganization ? organizationStats(today.data) : undefined;

  const firstName = (session?.user.display_name ?? "").split(/\s+/)[0];

  return (
    <Page>
      <WorkspaceHero
        persona={persona}
        name={firstName || undefined}
        context={
          <>
            {formatWeekday(new Date())}
            {session?.organization ? ` · ${session.organization.display_name}` : ""}
          </>
        }
        asOf={wholeOrganization ? today.at : workspace.at}
        stats={organizationFigures ?? heroStats(workspace.data)}
        actions={
          <>
            {facilityList.length > 1 ? (
              <label className="flex items-center gap-2 text-sm">
                <span className="sr-only">Facility</span>
                <select
                  value={facility ?? ""}
                  onChange={(event) => setFacility(event.target.value)}
                  className="h-9 rounded-md border border-input bg-card px-2 text-sm"
                >
                  {wholeOrganization && (
                    <option value={ALL_FACILITIES}>Whole organization</option>
                  )}
                  {facilityList.map((entry) => (
                    <option key={entry.uuid} value={entry.uuid}>
                      {entry.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            {/*
              The override. Only rendered when there is more than one board
              this person could legitimately open — a control that does nothing
              is worse than no control.
            */}
            {options.length > 1 ? (
              <label className="flex items-center gap-2 text-sm">
                <Icon name="viewGrid" size="sm" className="text-muted-foreground" />
                <span className="sr-only">Which board to show</span>
                <select
                  value={override}
                  onChange={(event) => choose(event.target.value as PersonaId)}
                  className="h-9 rounded-md border border-input bg-card px-2 text-sm"
                >
                  <option value="auto">Suits my role</option>
                  {options.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </>
        }
      />

      {/*
        The organization's day, and only that. The boards about *one person* —
        the nurse's shift, the doctor's clinic, the counter's till — moved to
        My workspace when the two screens were separated (§143): a product
        with two screens both claiming to be "your day" is a product nobody
        knows where to start in.
      */}
      {persona.id === "leadership" || persona.id === "finance" ? (
        <LeadershipHome
          workspace={workspace}
          today={today}
          facility={facility}
          facilities={facilityList}
        />
      ) : (
        <GeneralHome workspace={workspace} />
      )}
    </Page>
  );
}

/**
 * The four figures in the hero band.
 *
 * From `/me/workspace/`, which every signed-in user can read — so the band
 * never disappears, and the screen is never empty for somebody whose role
 * reaches none of the panels below.
 */
function heroStats(data: MyWorkspace | null) {
  if (!data) return undefined;

  const oldest = data.approvals
    .flatMap((group) => group.items)
    .map((item) => item.waiting_since)
    .filter((value): value is string => Boolean(value))
    .map((value) => new Date(value).getTime())
    .sort((a, b) => a - b)[0];

  const days = oldest
    ? Math.floor((Date.now() - oldest) / 86_400_000)
    : null;

  return [
    {
      label: "Waiting on you",
      icon: "workspace" as IconName,
      value: data.approvals_total,
      tone:
        data.approvals_total > 8
          ? ("critical" as const)
          : data.approvals_total > 0
            ? ("warning" as const)
            : undefined,
    },
    {
      label: "Unread",
      icon: "notification" as IconName,
      // `null` when the notification source itself failed. An em dash is
      // honest; a zero would claim there is nothing unread.
      value: data.notifications.unread ?? "—",
    },
    { label: "Queues", icon: "queue" as IconName, value: data.approvals.length },
    {
      label: "Longest wait",
      icon: "duration" as IconName,
      value: days === null ? "—" : days === 0 ? "today" : `${days}d`,
      tone: (days ?? 0) > 5 ? ("critical" as const) : undefined,
    },
  ];
}

/**
 * How a figure moved since yesterday, and whether that is good.
 *
 * `better` is the caller's judgement: money collected rising is good, money
 * owed rising is not, beds filling is neither. Nothing is shown when there is
 * no yesterday, or when both days are zero -- "0%" beside two zeros is noise.
 */
function change(
  now: number | string | null | undefined,
  before: number | string | null | undefined,
  better: "up" | "down" | "none",
  label = "this time yesterday",
) {
  if (before === undefined || before === null || now === undefined || now === null) return undefined;
  const current = Number(now);
  const previous = Number(before);
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return undefined;
  if (current === 0 && previous === 0) return undefined;
  const difference = current - previous;
  const text =
    difference === 0
      ? "same"
      : previous === 0
        ? `${difference > 0 ? "↑" : "↓"} new`
        : `${difference > 0 ? "↑" : "↓"} ${Math.abs(Math.round((difference / previous) * 100))}%`;
  const intent: "good" | "bad" | "neutral" =
    difference === 0 || better === "none"
      ? "neutral"
      : (difference > 0) === (better === "up")
        ? "good"
        : "bad";
  return { text, intent, title: `Compared with ${label}` };
}

/**
 * The organization's four figures, each a door to its list. `undefined` until
 * at least two can be shown, so the band falls back rather than half-empties.
 */
function organizationStats(data: OrganizationToday | null) {
  if (!data) return undefined;
  const figures: {
    label: string;
    value: React.ReactNode;
    tone?: "good" | "warning" | "critical";
    to?: string;
    icon?: IconName;
    delta?: { text: string; intent: "good" | "bad" | "neutral"; title?: string };
  }[] = [];
  const before = data.previous?.blocks ?? {};
  const label = data.previous?.label;

  if (data.outpatients) {
    figures.push({
      label: "Seen in outpatients",
      icon: "patient",
      delta: change(data.outpatients.seen, before.outpatients?.seen, "up", label),
      value: data.outpatients.seen,
      to: "/queue",
    });
  }
  if (data.inpatients) {
    const percent = data.inpatients.occupancy_percent;
    figures.push({
      label: data.facility ? "Beds occupied" : "Beds occupied, all sites",
      icon: "ward",
      delta: change(data.inpatients.occupied, before.inpatients?.occupied, "none", "last night"),
      value:
        percent === null
          ? `${data.inpatients.occupied}`
          : `${data.inpatients.occupied}/${data.inpatients.beds} · ${Math.round(percent)}%`,
      tone: percent !== null && percent >= 90 ? "warning" : undefined,
      to: "/wards",
    });
  }
  if (data.billing) {
    figures.push({
      label: "Collected today",
      icon: "payment",
      delta: change(data.billing.collected, before.billing?.collected, "up", label),
      value: formatValue(Number(data.billing.collected), "money"),
      to: "/billing",
    });
    figures.push({
      label: "Still owed",
      icon: "invoice",
      delta: change(data.billing.outstanding, before.billing?.outstanding, "down", "last night"),
      value: formatValue(Number(data.billing.outstanding), "money"),
      tone: data.billing.overdue_invoices > 0 ? "warning" : undefined,
      to: "/billing",
    });
  }
  if (figures.length < 4 && data.pharmacy) {
    figures.push({
      label: "Pharmacy takings",
      icon: "pharmacy",
      delta: change(data.pharmacy.takings, before.pharmacy?.takings, "up", label),
      value: formatValue(Number(data.pharmacy.takings), "money"),
      to: "/counter",
    });
  }
  if (figures.length < 4 && data.laboratory) {
    figures.push({
      label: "Lab work outstanding",
      icon: "laboratory",
      delta: change(data.laboratory.outstanding, before.laboratory?.outstanding, "down", "last night"),
      value: data.laboratory.outstanding,
      tone: data.laboratory.critical_open > 0 ? "critical" : undefined,
      to: "/diagnostics",
    });
  }
  return figures.length >= 2 ? figures.slice(0, 4) : undefined;
}

/* -------------------------------------------------------------------------- */
/* Leadership                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The facility, for whoever is answerable for it.
 *
 * **Every panel renders its state; none of them disappears.** The first version
 * wrote `{sales.data ? <Panel/> : null}` for each one, so a request that failed
 * made its panel vanish — and the screen looked complete. That is precisely the
 * failure this product's dashboards exist to avoid: "no counter takings" and
 * "we could not ask" must not look the same, and a missing panel looks like
 * neither, it looks like nothing. It was found by screenshotting the running
 * app, where two of the five panels had silently gone.
 *
 * The two that had gone were the counter takings and the supply pipeline, and
 * the reason was a wrong URL rather than a real outage: both summary views
 * resolve the facility with `get_object_or_404`, so called without
 * `?facility=` they 404. They had never worked on this screen. Now they are
 * passed the facility — and if one fails anyway, it says so where it sits.
 *
 * A panel the viewer may not open is still left out: that is a permission
 * decision, not a failure, and an empty "you may not see this" card on a
 * director's board is noise.
 */
function LeadershipHome({
  workspace,
  today,
  facility,
  facilities,
}: {
  workspace: ReturnType<typeof useResource<MyWorkspace>>;
  today: ReturnType<typeof useResource<OrganizationToday>>;
  facility: string | null;
  facilities: Facility[];
}) {
  /*
    With the whole organization chosen, each department is read where it
    runs: emergency and wards at the hospital, the counter at the pharmacy.
    The panel names the facility, so a group with two hospitals is never shown
    one of them as though it were both.
  */
  const whole = facility === ALL_FACILITIES;
  const at = (types: string[]) => (whole ? pickFacility(facilities, types) : facilities.find((row) => row.uuid === facility)) ?? null;
  const edAt = at(["hospital"]);
  const wardAt = at(["hospital"]);
  const salesAt = at(["pharmacy"]);
  const supplyAt = at(["pharmacy", "hospital"]);
  const where = (row: Facility | null, suffix: string) =>
    whole && row ? `${row.name} · ${suffix}` : suffix;
  const can = useCan();
  const mayEd = can("encounter.read", "own");
  const mayWards = can("patient.clinical.read", "facility");
  const maySales = can("sale.read", "facility");
  const maySupply = can("purchase.read", "facility");
  const mayMoney = can("invoice.read", "facility");
  const mayLab = can("encounter.read", "own");
  const scopeLabel = whole
    ? "Whole organization"
    : facilities.find((row) => row.uuid === facility)?.name ?? "";

  /*
    `since` today, explicitly. The summary's own default is the last seven
    days, so this panel -- labelled "since midnight" -- said "96 arrived
    today" two minutes after midnight.
  */
  const sinceMidnight = localIsoDate();
  const ed = useResource<DepartmentSummary>(
    edAt ? `/ed/summary/?facility=${edAt.uuid}&since=${sinceMidnight}` : null,
    mayEd,
  );
  const ward = useResource<NurseWorkspaceSummary>(
    wardAt ? `/ipd/nurse-workspace/summary/?facility=${wardAt.uuid}&scope=ward` : null,
    mayWards,
  );
  const sales = useResource<SalesSummary>(
    salesAt ? `/pos/summary/?facility=${salesAt.uuid}` : null,
    maySales,
  );
  const supply = useResource<ProcurementDashboard>(
    supplyAt ? `/procurement/dashboard/?facility=${supplyAt.uuid}` : null,
    maySupply,
  );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {mayEd ? (
        <WorkspacePanel
          title="Emergency department"
          description={where(edAt, "since midnight")}
          icon="emergency"
          to="/emergency"
          span={2}
        >
          {ed.loading ? (
            <PanelLoading height={120} />
          ) : ed.error ? (
            <PanelProblem error={ed.error} />
          ) : !ed.data ? (
            <PanelEmpty message="Choose a facility to see its department." icon="facility" />
          ) : (
            <div className="grid gap-5 sm:grid-cols-4">
              <Chart.Hero
                value={ed.data.summary.in_department}
                label="In department"
                footnote={`${ed.data.summary.arrivals} arrived today`}
              />
              <Figure
                label="Median wait"
                value={formatValue(ed.data.summary.median_wait_minutes, "duration")}
              />
              <Figure
                label="Longest"
                value={formatValue(ed.data.summary.longest_wait_minutes, "duration")}
                tone={ed.data.summary.longest_wait_minutes > 240 ? "critical" : undefined}
              />
              <Figure
                label="Breached"
                value={formatValue(ed.data.summary.breach_percent, "percent")}
                tone={ed.data.summary.breach_percent > 10 ? "critical" : undefined}
              />
            </div>
          )}
        </WorkspacePanel>
      ) : null}

      {mayWards ? (
        <WorkspacePanel title="Inpatients" description={where(wardAt, "on the wards now")} icon="ward" to="/wards">
          {ward.loading ? (
            <PanelLoading height={120} />
          ) : ward.error ? (
            <PanelProblem error={ward.error} />
          ) : !ward.data ? (
            <PanelEmpty message="Nobody on the wards." icon="ward" />
          ) : (
            <div className="space-y-3">
              <Chart.Hero
                value={ward.data.total_patients}
                label="On the wards"
                footnote={`${ward.data.total_tasks_pending} tasks pending`}
              />
              <Chart.StackedProgress
                segments={[
                  { label: "High risk", value: ward.data.high_risk_count, tone: "critical" },
                  { label: "Medium", value: ward.data.medium_risk_count, tone: "warning" },
                  {
                    label: "Routine",
                    value: Math.max(
                      0,
                      ward.data.total_patients -
                        ward.data.high_risk_count -
                        ward.data.medium_risk_count,
                    ),
                    tone: "good",
                  },
                ]}
              />
            </div>
          )}
        </WorkspacePanel>
      ) : null}

      {maySales ? (
        <WorkspacePanel title="Counter takings" description={where(salesAt, "today")} icon="payment" to="/counter">
          {sales.loading ? (
            <PanelLoading height={140} />
          ) : sales.error ? (
            <PanelProblem error={sales.error} />
          ) : !sales.data ? (
            <PanelEmpty message="Choose a facility to see its counter." icon="facility" />
          ) : (
            <div className="space-y-3">
              <Chart.Hero
                value={Number(sales.data.net_revenue)}
                format="money"
                label="Net revenue"
                footnote={`${sales.data.sales_count} sales · ${sales.data.returns_count} returns`}
              />
              <Chart.Bullet
                label="Gross margin"
                value={Number(sales.data.margin_percent)}
                max={100}
                format="percent"
                bands={[
                  { to: 15, tone: "critical" },
                  { to: 30, tone: "warning" },
                  { to: 100, tone: "good" },
                ]}
              />
            </div>
          )}
        </WorkspacePanel>
      ) : null}

      {maySupply ? (
        <WorkspacePanel title="Supply" description={where(supplyAt, "requisition to receipt")} icon="procurement" to="/procurement">
          {supply.loading ? (
            <PanelLoading height={170} />
          ) : supply.error ? (
            <PanelProblem error={supply.error} />
          ) : !supply.data ? (
            <PanelEmpty message="Choose a facility to see its supply pipeline." icon="facility" />
          ) : (
            <SupplyQueues data={supply.data} />
          )}
        </WorkspacePanel>
      ) : null}

      {mayMoney ? (
        <WorkspacePanel
          title="Money"
          description={scopeLabel ? `${scopeLabel} · today` : "today"}
          icon="billing"
          to="/billing"
        >
          {today.loading ? (
            <PanelLoading height={120} />
          ) : today.error ? (
            <PanelProblem error={today.error} />
          ) : !today.data?.billing ? (
            <PanelEmpty message="Billing is not part of this view." icon="billing" />
          ) : (
            <div className="space-y-3">
              <Chart.Hero
                value={Number(today.data.billing.collected)}
                format="money"
                label="Collected today"
                footnote={`${formatValue(Number(today.data.billing.outstanding), "money")} still owed`}
              />
              {today.data.billing.overdue_invoices > 0 ? (
                <Link
                  to="/billing"
                  className="inline-flex items-center gap-1 text-sm font-medium text-critical hover:underline"
                >
                  {today.data.billing.overdue_invoices} invoice
                  {today.data.billing.overdue_invoices === 1 ? "" : "s"} past due
                  <Icon name="chevronRight" size="xs" />
                </Link>
              ) : (
                <p className="type-caption">Nothing past its due date.</p>
              )}
            </div>
          )}
        </WorkspacePanel>
      ) : null}

      {mayEd && today.data?.outpatients ? (
        <WorkspacePanel
          title="Outpatients"
          description={scopeLabel ? `${scopeLabel} · today` : "today"}
          icon="queue"
          to="/queue"
        >
          <Chart.Donut
            slices={[
              {
                name: "Seen",
                value: Math.max(0, today.data.outpatients.seen - today.data.outpatients.waiting),
              },
              { name: "Waiting", value: today.data.outpatients.waiting },
              { name: "Did not attend", value: today.data.outpatients.no_shows },
            ]}
            totalLabel="patients"
            height={180}
            emptyMessage="No outpatients yet today."
            asOf={today.at}
          />
          <p className="mt-2 type-caption">
            {today.data.outpatients.appointments} booked for today.
          </p>
        </WorkspacePanel>
      ) : null}

      {mayLab && today.data?.laboratory ? (
        <WorkspacePanel
          title="Laboratory"
          description={scopeLabel ? `${scopeLabel} · now` : "now"}
          icon="laboratory"
          to="/diagnostics"
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Figure label="Outstanding" value={today.data.laboratory.outstanding} />
            <Figure
              label="Critical, open"
              value={today.data.laboratory.critical_open}
              tone={today.data.laboratory.critical_open > 0 ? "critical" : undefined}
            />
            <Figure label="Released today" value={today.data.laboratory.released} />
          </div>
        </WorkspacePanel>
      ) : null}

      <ApprovalsPanel workspace={workspace} />
    </div>
  );
}

/**
 * The supply pipeline as the queues it is.
 *
 * **It was drawn as a funnel, and it is not one.** A funnel is stages that
 * only shrink; these are independent queues, each waiting on a different
 * person. With one requisition waiting and one delivery to check, the funnel
 * drew "-1 (100%)" between them and pushed the first label off the panel.
 * Each row opens the tab that does the work.
 */
function SupplyQueues({ data }: { data: ProcurementDashboard }) {
  const rows = [
    { label: "Requisitions to approve", value: data.requisitions_awaiting_approval, tab: "requisitions", critical: false },
    { label: "Approved, not yet ordered", value: data.requisitions_approved_unordered, tab: "requisitions", critical: false },
    { label: "Orders to approve", value: data.orders_awaiting_approval, tab: "orders", critical: false },
    { label: "Deliveries to check", value: data.receipts_awaiting_check, tab: "receipts", critical: false },
    { label: "Orders overdue", value: data.orders_overdue, tab: "orders", critical: true },
  ];

  return (
    <ul className="-mx-2 divide-y divide-border">
      {rows.map((row) => (
        <li key={row.label}>
          <Link
            to={`/procurement?tab=${row.tab}`}
            className="flex items-center justify-between gap-3 rounded-md px-2 py-2 text-sm transition-colors duration-quick hover:bg-accent/40"
          >
            <span className={row.value === 0 ? "text-muted-foreground" : undefined}>
              {row.label}
            </span>
            <span
              className={
                row.value === 0
                  ? "tabular-nums text-muted-foreground"
                  : row.critical
                    ? "font-semibold tabular-nums text-critical"
                    : "font-semibold tabular-nums"
              }
            >
              {row.value}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * A secondary figure in a panel.
 *
 * Plain markup rather than a nested `Chart.Stat`. A stat tile is a *card* —
 * border, shadow, padding — and putting three of them inside a panel that is
 * itself a card drew boxes inside a box, which the screenshot showed plainly
 * and the code did not: `className="border-0 shadow-none"` was passed to strip
 * them, and it did not win (see `lib/utils.ts` on tailwind-merge).
 */
function Figure({
  label,
  value,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "critical" | "warning";
}) {
  return (
    <div className="min-w-0">
      <p className="type-label text-muted-foreground">{label}</p>
      <p
        className={
          tone === "critical"
            ? "mt-1.5 text-2xl font-semibold tabular-nums text-critical"
            : tone === "warning"
              ? "mt-1.5 text-2xl font-semibold tabular-nums text-warning"
              : "mt-1.5 text-2xl font-semibold tabular-nums"
        }
      >
        {value}
      </p>
    </div>
  );
}


/* -------------------------------------------------------------------------- */
/* General                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * For somebody the ladder could not place.
 *
 * **Generic on purpose.** A persona that is wrong is worse than one that is
 * plain: somebody shown a ward board who does not work on a ward concludes the
 * product does not understand them, whereas "what needs you" is true of
 * everybody and is never embarrassing.
 */
function GeneralHome({ workspace }: { workspace: ReturnType<typeof useResource<MyWorkspace>> }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <ApprovalsPanel workspace={workspace} />
      </div>
      <WorkspacePanel title="Your day" icon="home">
        <div className="space-y-2 type-caption">
          <p>
            {workspace.data?.today.has_employee_record
              ? [
                  workspace.data.today.employee,
                  workspace.data.today.department,
                  workspace.data.today.facility,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "You are signed in without an employee record, so attendance and payroll will be empty."}
          </p>
          <p>
            No specialised board matched what you can do. Everything you are
            permitted is in the rail, and ⌘K reaches any of it.
          </p>
        </div>
      </WorkspacePanel>
    </div>
  );
}
