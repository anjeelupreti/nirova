/**
 * A home per persona.
 *
 * **This is the answer to "the system itself is confused whom to show what".**
 * Seventeen roles opened onto one screen, and the only difference between a
 * pharmacist's product and a controller's was which panels returned 403.
 *
 * Each home below is composed for a *job*: what that person needs in the first
 * ten seconds of a shift, in the order they need it, from the endpoints that
 * already answer those questions. None of them is a filtered view of a generic
 * dashboard — a ward is beds, a clinic is a list of people, a cash position is
 * money moving, and forcing all three into one grid of stat tiles is how the
 * product ended up feeling like a database browser with a hospital theme.
 *
 * What stays constant is deliberate: the frame, the palette, the status
 * colours, the rail. A nurse covering the front desk should find the furniture
 * where she left it. See `WorkspaceFrame.tsx`.
 */

import * as React from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { AcuityBadge, StatusBadge } from "@/components/ui/status";
import { Button } from "@/components/ui/primitives";
import { Chart, formatValue } from "@/components/charts";
import { useResource } from "./useResource";
import {
  PanelEmpty,
  PanelLoading,
  PanelProblem,
  WorkspacePanel,
  WorklistRow,
  waitedFor,
} from "./WorkspaceFrame";
import type {
  CounterSession,
  CriticalAlert,
  DailyCollection,
  DepartmentSummary,
  DiagnosticOrder,
  Encounter,
  Facility,
  HrDashboard,
  Invoice,
  MyWorkspace,
  NurseWorkspaceSummary,
  Paginated,
  ProcurementDashboard,
  QueueResponse,
  SalesSummary,
  TurnaroundReport,
} from "@/types";
import { useSession } from "@/hooks/useSession";
import { useCan } from "@/components/ui/can";

/* -------------------------------------------------------------------------- */
/* Shared                                                                      */
/* -------------------------------------------------------------------------- */

/** The approvals panel. Every persona gets it — everyone has a queue. */
export function ApprovalsPanel({ workspace }: { workspace: ReturnType<typeof useResource<MyWorkspace>> }) {
  const data = workspace.data;

  return (
    <WorkspacePanel
      title="Waiting on you"
      description="Decisions blocked until you make them"
      icon="workspace"
      to="/workspace"
    >
      {workspace.loading ? (
        <PanelLoading />
      ) : workspace.error ? (
        <PanelProblem error={workspace.error} />
      ) : !data || data.approvals.length === 0 ? (
        <PanelEmpty
          message={
            data?.is_complete === false
              ? "Nothing shown — but a source failed, so this is not a confirmed nothing."
              : "Nothing is waiting on you. Every source was read, so this is a real nothing."
          }
        />
      ) : (
        <div className="space-y-0.5">
          {data.approvals.slice(0, 5).map((group) => (
            <WorklistRow
              key={group.type}
              title={group.label}
              detail={`${group.count} ${group.count === 1 ? "item" : "items"}`}
              meta={waitedFor(group.items[0]?.waiting_since)}
              tone={group.urgency >= 8 ? "critical" : undefined}
              to={group.screen}
            />
          ))}
        </div>
      )}
    </WorkspacePanel>
  );
}

/* -------------------------------------------------------------------------- */
/* Nurse — the ward                                                            */
/* -------------------------------------------------------------------------- */

/**
 * A shift, as a nurse reads it: who is sickest, what is due, what is overdue.
 *
 * **Sorted by NEWS2 descending, not by bed number.** A ward list in bed order
 * is a filing system; a ward list in deterioration order is a handover. That
 * single decision is most of the difference between this and the table it
 * replaces.
 */
export function NurseHome({ workspace }: { workspace: ReturnType<typeof useResource<MyWorkspace>> }) {
  const ward = useResource<NurseWorkspaceSummary>(
    "/ipd/nurse-workspace/summary/",
  );
  const data = ward.data;

  const patients = React.useMemo(() => {
    const list = [...(data?.patients ?? [])];
    // Highest score first; a missing score sorts last rather than as zero,
    // because "not scored" is not "well".
    return list.sort((a, b) => (b.news2?.score ?? -1) - (a.news2?.score ?? -1));
  }, [data]);

  const mine = patients.filter((patient) => patient.is_mine);
  const shown = mine.length > 0 ? mine : patients;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel
        title={mine.length > 0 ? "Your patients" : "On the ward"}
        description="Sickest first — deterioration order, not bed order"
        icon="nurse"
        to="/nurse-workspace"
        toLabel="Open workspace"
        span={2}
      >
        {ward.loading ? (
          <PanelLoading height={280} />
        ) : ward.error ? (
          <PanelProblem error={ward.error} />
        ) : shown.length === 0 ? (
          <PanelEmpty message="No inpatients on this ward right now." />
        ) : (
          <div className="space-y-0.5">
            {shown.slice(0, 8).map((patient) => {
              const score = patient.news2?.score;
              const risk = patient.news2?.risk_level;
              return (
                <WorklistRow
                  key={patient.admission_uuid}
                  tone={
                    risk === "high" ? "critical" : risk === "medium" ? "warning" : undefined
                  }
                  leading={
                    <span className="flex h-8 w-11 shrink-0 flex-col items-center justify-center rounded-md bg-muted">
                      <span className="type-code text-[0.625rem] leading-none text-muted-foreground">
                        {patient.bed_code}
                      </span>
                      <span
                        className={cn(
                          "text-xs font-bold leading-none tabular-nums",
                          risk === "high" && "text-critical",
                          risk === "medium" && "text-warning",
                        )}
                      >
                        {score ?? "—"}
                      </span>
                    </span>
                  }
                  person={patient.patient_name}
                  title={patient.patient_name}
                  detail={
                    <>
                      {patient.patient_age} {patient.patient_gender} ·{" "}
                      {patient.admitting_diagnosis || "No diagnosis recorded"}
                    </>
                  }
                  meta={
                    patient.tasks.pending_count > 0
                      ? `${patient.tasks.pending_count} due`
                      : undefined
                  }
                  trailing={
                    patient.vitals ? (
                      <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
                        obs {waitedFor(patient.vitals.recorded_at)} ago
                      </span>
                    ) : (
                      <StatusBadge status="pending" label="no obs" />
                    )
                  }
                />
              );
            })}
          </div>
        )}
      </WorkspacePanel>

      <div className="space-y-4">
        <WorkspacePanel title="Risk mix" icon="vitals" to="/wards">
          {ward.loading ? (
            <PanelLoading height={110} />
          ) : ward.error ? (
            <PanelProblem error={ward.error} />
          ) : !data ? (
            <PanelEmpty message="Nothing on the ward." />
          ) : (
            <div className="space-y-3">
              <Chart.StackedProgress
                segments={[
                  { label: "High", value: data.high_risk_count, tone: "critical" },
                  { label: "Medium", value: data.medium_risk_count, tone: "warning" },
                  {
                    label: "Routine",
                    value: Math.max(
                      0,
                      data.total_patients - data.high_risk_count - data.medium_risk_count,
                    ),
                    tone: "good",
                  },
                ]}
              />
              <p className="type-caption">
                {data.total_tasks_pending} tasks pending across{" "}
                {data.total_patients} patients on the {data.shift} shift.
              </p>
            </div>
          )}
        </WorkspacePanel>

        <ApprovalsPanel workspace={workspace} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Front desk — the queue                                                      */
/* -------------------------------------------------------------------------- */

/**
 * The desk: who is waiting, how long, and who is next.
 *
 * **Waiting time is the headline and it is coloured.** A receptionist's whole
 * job on a busy morning is noticing the person who has been there ninety
 * minutes before they come and tell you, and a queue sorted by token number
 * hides exactly that.
 */
export function FrontDeskHome({
  workspace,
  facility,
}: {
  workspace: ReturnType<typeof useResource<MyWorkspace>>;
  facility: string | null;
}) {
  const queue = useResource<QueueResponse>(
    facility ? `/clinical/queue/?facility=${facility}` : null,
  );
  const data = queue.data;
  const waiting = (data?.queue ?? []).filter(
    (token) => token.status !== "completed" && token.status !== "left",
  );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel
        title="Waiting now"
        description="Longest wait first — not token order"
        icon="queue"
        to="/queue"
        toLabel="Open queue"
        span={2}
        actions={
          <Button size="sm" variant="outline" asChild>
            <Link to="/patients">
              <Icon name="add" size="sm" className="mr-1.5" />
              Register
            </Link>
          </Button>
        }
      >
        {queue.loading ? (
          <PanelLoading height={280} />
        ) : queue.error ? (
          <PanelProblem error={queue.error} />
        ) : !facility ? (
          <PanelEmpty message="Choose a facility to see its queue." icon="facility" />
        ) : waiting.length === 0 ? (
          <PanelEmpty message="Nobody is waiting. The queue is clear." />
        ) : (
          <div className="space-y-0.5">
            {[...waiting]
              .sort((a, b) => b.waiting_minutes - a.waiting_minutes)
              .slice(0, 9)
              .map((token) => (
                <WorklistRow
                  key={token.uuid}
                  tone={
                    token.is_emergency || token.waiting_minutes > 90
                      ? "critical"
                      : token.waiting_minutes > 45
                        ? "warning"
                        : undefined
                  }
                  leading={
                    <span className="flex h-8 w-11 shrink-0 items-center justify-center rounded-md bg-muted type-code text-xs font-semibold">
                      {token.token_number}
                    </span>
                  }
                  person={token.patient_name}
                  title={token.patient_name}
                  detail={
                    <>
                      <span className="type-code">{token.patient_mrn}</span>
                      {token.chief_complaint ? ` · ${token.chief_complaint}` : ""}
                    </>
                  }
                  meta={`${token.waiting_minutes}m`}
                  trailing={
                    token.is_emergency ? (
                      <StatusBadge status="critical" label="Emergency" />
                    ) : (
                      <StatusBadge status={token.status} />
                    )
                  }
                />
              ))}
          </div>
        )}
      </WorkspacePanel>

      <div className="space-y-4">
        <WorkspacePanel title="This morning" icon="appointment" to="/appointments">
          {queue.loading ? (
            <PanelLoading height={110} />
          ) : queue.error ? (
            <PanelProblem error={queue.error} />
          ) : !data ? (
            <PanelEmpty message="No queue data." />
          ) : (
            <div className="space-y-3">
              {/*
                A donut because the question is a share: of everybody through
                the door today, how many are still waiting. The total sits in
                the hole, and the same numbers are one keystroke away as a
                table for anybody who needs the figure exactly.
              */}
              <Chart.Donut
                slices={[
                  { name: "Waiting", value: data.statistics.waiting },
                  { name: "Being seen", value: data.statistics.in_service },
                  { name: "Done", value: data.statistics.completed },
                  { name: "Left or skipped", value: data.statistics.left + data.statistics.skipped },
                ]}
                totalLabel="today"
                height={170}
                emptyMessage="Nobody through the door yet today."
                asOf={queue.at}
              />
              <div className="grid grid-cols-2 gap-3">
              <Figure
                label="Median wait"
                value={`${data.statistics.average_wait_minutes}m`}
                tone={data.statistics.average_wait_minutes > 45 ? "warning" : undefined}
              />
              <Figure
                label="Longest"
                value={`${data.statistics.longest_wait_minutes}m`}
                tone={data.statistics.longest_wait_minutes > 90 ? "critical" : undefined}
              />
              </div>
            </div>
          )}
        </WorkspacePanel>

        <ApprovalsPanel workspace={workspace} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Doctor — the clinic                                                         */
/* -------------------------------------------------------------------------- */

export function DoctorHome({
  workspace,
  facility,
}: {
  workspace: ReturnType<typeof useResource<MyWorkspace>>;
  facility: string | null;
}) {
  const { session } = useSession();
  const queue = useResource<QueueResponse>(
    facility ? `/clinical/queue/?facility=${facility}` : null,
  );
  const ed = useResource<DepartmentSummary>(
    facility ? `/ed/summary/?facility=${facility}` : null,
  );
  /*
    The two things a consultant carries home if nobody shows them.

    A critical value that nobody acknowledged is the single most dangerous
    thing on a clinician's desk, and an open encounter is a note that was
    never finished — both were reachable only by remembering to go and look.
    Neither is facility-scoped here on purpose: a doctor covering two sites
    still has to answer for the result, wherever it was taken.
  */
  const criticals = useResource<{ results: CriticalAlert[] }>(
    "/diagnostics/critical-alerts/?open=true",
  );
  const mine = useResource<{ results: Encounter[] }>(
    session?.user.uuid
      ? `/clinical/encounters/?provider_uuid=${session.user.uuid}&open=true`
      : null,
  );

  const inService = (queue.data?.queue ?? []).filter(
    (token) => token.status !== "completed" && token.status !== "left",
  );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel
        title="Your list"
        description="Waiting to be seen"
        icon="doctor"
        to="/queue"
        toLabel="Open queue"
        span={2}
      >
        {queue.loading ? (
          <PanelLoading height={260} />
        ) : queue.error ? (
          <PanelProblem error={queue.error} />
        ) : !facility ? (
          <PanelEmpty message="Choose a facility to see the clinic list." icon="facility" />
        ) : inService.length === 0 ? (
          <PanelEmpty message="Nobody waiting. The clinic is clear." />
        ) : (
          <div className="space-y-0.5">
            {[...inService]
              .sort((a, b) => b.waiting_minutes - a.waiting_minutes)
              .slice(0, 8)
              .map((token) => (
                <WorklistRow
                  key={token.uuid}
                  tone={token.is_emergency ? "critical" : undefined}
                  leading={
                    <span className="flex h-8 w-11 shrink-0 items-center justify-center rounded-md bg-muted type-code text-xs font-semibold">
                      {token.token_number}
                    </span>
                  }
                  person={token.patient_name}
                  title={token.patient_name}
                  detail={
                    <>
                      <span className="type-code">{token.patient_mrn}</span>
                      {token.chief_complaint ? ` · ${token.chief_complaint}` : ""}
                    </>
                  }
                  meta={`${token.waiting_minutes}m`}
                  trailing={<StatusBadge status={token.status} />}
                  // Straight into the consultation. The single most-repeated
                  // action of a clinic day should not be three clicks.
                  to={`/consultation/${token.patient_uuid}`}
                />
              ))}
          </div>
        )}
      </WorkspacePanel>

      <div className="space-y-4">
        <WorkspacePanel
          title="Emergency department"
          description="Since midnight"
          icon="emergency"
          to="/emergency"
        >
          {ed.loading ? (
            <PanelLoading height={150} />
          ) : ed.error ? (
            <PanelProblem error={ed.error} />
          ) : !ed.data ? (
            <PanelEmpty message="Nothing recorded today." />
          ) : (
            <div className="space-y-2.5">
              {Object.entries(ed.data.summary.by_triage_category)
                .map(([category, count]) => ({ level: Number(category), count }))
                .filter((row) => Number.isFinite(row.level))
                .sort((a, b) => a.level - b.level)
                .map((row) => {
                  const total =
                    Object.values(ed.data!.summary.by_triage_category).reduce(
                      (sum, value) => sum + value,
                      0,
                    ) || 1;
                  return (
                    <div key={row.level} className="flex items-center gap-2.5">
                      <AcuityBadge level={row.level} />
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: `${(row.count / total) * 100}%`,
                            background: `hsl(var(--acuity-${Math.min(5, Math.max(1, row.level))}))`,
                          }}
                        />
                      </div>
                      <span className="w-5 text-right text-xs font-medium tabular-nums">
                        {row.count}
                      </span>
                    </div>
                  );
                })}
            </div>
          )}
        </WorkspacePanel>

        <ApprovalsPanel workspace={workspace} />
      </div>

      <WorkspacePanel
        title="Results to acknowledge"
        description="Critical values, oldest first"
        icon="laboratory"
        to="/diagnostics"
        toLabel="Open laboratory"
      >
        {criticals.loading ? (
          <PanelLoading height={140} />
        ) : criticals.notIncluded ? null : criticals.error ? (
          <PanelProblem error={criticals.error} />
        ) : (criticals.data?.results ?? []).length === 0 ? (
          <PanelEmpty message="Every critical result has been acknowledged." />
        ) : (
          <div className="space-y-0.5">
            {(criticals.data?.results ?? []).slice(0, 5).map((alert) => (
              <WorklistRow
                key={alert.uuid}
                tone="critical"
                person={alert.patient_name}
                title={alert.patient_name}
                detail={
                  <>
                    <span className="type-code">{alert.patient_mrn}</span>
                    {alert.analyte ? ` · ${alert.analyte} ${alert.value}` : ""}
                  </>
                }
                meta={waitedFor(alert.raised_at)}
                to="/diagnostics"
              />
            ))}
          </div>
        )}
      </WorkspacePanel>

      <WorkspacePanel
        title="Consultations left open"
        description="Notes not finished"
        icon="consultation"
        to="/queue"
        toLabel="Open queue"
        span={2}
      >
        {mine.loading ? (
          <PanelLoading height={140} />
        ) : mine.error ? (
          <PanelProblem error={mine.error} />
        ) : (mine.data?.results ?? []).length === 0 ? (
          <PanelEmpty message="Nothing left open. Every consultation is written up." />
        ) : (
          <div className="space-y-0.5">
            {(mine.data?.results ?? []).slice(0, 6).map((encounter) => (
              <WorklistRow
                key={encounter.uuid}
                person={encounter.patient_name}
                title={encounter.patient_name}
                detail={
                  <>
                    <span className="type-code">{encounter.reference}</span>
                    {encounter.chief_complaint ? ` · ${encounter.chief_complaint}` : ""}
                  </>
                }
                meta={waitedFor(encounter.started_at)}
                trailing={<StatusBadge status={encounter.status} />}
                to={`/consultation/${encounter.patient}`}
              />
            ))}
          </div>
        )}
      </WorkspacePanel>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Pharmacy                                                                    */
/* -------------------------------------------------------------------------- */

export function PharmacyHome({
  workspace,
  facility,
}: {
  workspace: ReturnType<typeof useResource<MyWorkspace>>;
  facility: string | null;
}) {
  const can = useCan();
  /*
    Both endpoints are per-building and **404 without `?facility=`**, because
    their views resolve the facility with `get_object_or_404`. The first
    version called them bare, so this board rendered two permanent failures —
    and the leadership board, which had the same bug, hid them entirely. Found
    by screenshotting the running app, not by reading the code.

    **And both are asked for only by somebody who may read them.** A counter
    assistant holds neither `report.read` nor `purchase.read`, so their own
    board greeted them with two red permission refusals for panels they never
    asked for — which reads as a broken product rather than as a board that is
    not theirs. `enabled` is what that argument on `useResource` is for.
  */
  const mayReadTakings = can("report.read", "facility");
  const mayReadSupply = can("purchase.read", "facility");
  const sales = useResource<SalesSummary>(
    facility ? `/pos/summary/?facility=${facility}` : null,
    mayReadTakings,
  );
  const procurement = useResource<ProcurementDashboard>(
    facility ? `/procurement/dashboard/?facility=${facility}` : null,
    mayReadSupply,
  );
  // What a counter assistant *does* have: the till they are standing at.
  const till = useResource<{ results: CounterSession[] }>(
    !mayReadTakings && facility
      ? `/pos/sessions/?facility=${facility}&status=open`
      : null,
  );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {!mayReadTakings ? (
        <WorkspacePanel
          title="Your till"
          description="Open the counter and sell"
          icon="counter"
          to="/counter"
          toLabel="Open counter"
          span={2}
        >
          {till.loading ? (
            <PanelLoading height={140} />
          ) : (till.data?.results ?? []).length === 0 ? (
            <PanelEmpty message="No till open. Open one from the counter to start selling." />
          ) : (
            <div className="space-y-0.5">
              {(till.data?.results ?? []).map((session) => (
                <WorklistRow
                  key={session.uuid}
                  title={`${session.counter} · ${session.location_code}`}
                  detail={`Opened by ${session.cashier_name}`}
                  meta={waitedFor(session.opened_at)}
                  to="/counter"
                />
              ))}
            </div>
          )}
        </WorkspacePanel>
      ) : (
      <WorkspacePanel
        title="Counter today"
        description="Takings and margin"
        icon="counter"
        to="/counter"
        span={2}
      >
        {sales.loading ? (
          <PanelLoading height={220} />
        ) : sales.error ? (
          <PanelProblem error={sales.error} />
        ) : !sales.data ? (
          <PanelEmpty message="No sales recorded today." />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <Figure
                label="Net revenue"
                value={formatValue(Number(sales.data.net_revenue), "money")}
                large
              />
              <Figure label="Sales" value={sales.data.sales_count} />
              <Figure
                label="Returns"
                value={sales.data.returns_count}
                tone={sales.data.returns_count > 5 ? "warning" : undefined}
              />
            </div>
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
            {sales.data.top_products.length > 0 ? (
              <Chart.Bar
                title="Top products"
                rows={sales.data.top_products.slice(0, 5).map((product) => ({
                  name: product.product_name,
                  total: Number(product.total),
                }))}
                categoryKey="name"
                categoryLabel="Product"
                series={[{ key: "total", label: "Revenue" }]}
                layout="horizontal"
                format="money"
                height={140}
                asOf={sales.at}
              />
            ) : null}
          </div>
        )}
      </WorkspacePanel>
      )}

      <div className="space-y-4">
        {mayReadSupply ? (
        <WorkspacePanel title="Supply" icon="procurement" to="/procurement">
          {procurement.loading ? (
            <PanelLoading height={140} />
          ) : procurement.error ? (
            <PanelProblem error={procurement.error} />
          ) : !procurement.data ? (
            <PanelEmpty message="Nothing on order." />
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Figure label="Orders open" value={procurement.data.orders_open} />
                <Figure
                  label="Overdue"
                  value={procurement.data.orders_overdue}
                  tone={procurement.data.orders_overdue > 0 ? "critical" : undefined}
                />
                <Figure
                  label="To check in"
                  value={procurement.data.receipts_awaiting_check}
                />
                <Figure
                  label="Licences expiring"
                  value={procurement.data.licences_expiring}
                  tone={procurement.data.licences_expiring > 0 ? "warning" : undefined}
                />
              </div>
            </div>
          )}
        </WorkspacePanel>
        ) : null}

        <ApprovalsPanel workspace={workspace} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* People                                                                      */
/* -------------------------------------------------------------------------- */

export function PeopleHome({ workspace }: { workspace: ReturnType<typeof useResource<MyWorkspace>> }) {
  const hr = useResource<HrDashboard>("/hr/dashboard/");
  const data = hr.data;

  const byDepartment =
    data?.headcount.by_department
      .filter((row) => row.department__name)
      .slice(0, 7)
      .map((row) => ({
        department: row.department__name ?? "Unassigned",
        count: row.count,
      })) ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel
        title="Headcount"
        description="Filled against budgeted, by department"
        icon="staff"
        to="/people"
        span={2}
      >
        {hr.loading ? (
          <PanelLoading height={250} />
        ) : hr.error ? (
          <PanelProblem error={hr.error} />
        ) : !data ? (
          <PanelEmpty message="No employee records." />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <Figure label="Headcount" value={data.headcount.total} large />
              <Figure
                label="Vacancies"
                value={data.headcount.vacancies}
                tone={data.headcount.vacancies > 0 ? "warning" : undefined}
              />
              <Figure
                label="Probation overdue"
                value={data.headcount.probation_overdue}
                tone={data.headcount.probation_overdue > 0 ? "critical" : undefined}
              />
            </div>
            {byDepartment.length > 0 ? (
              <Chart.Bar
                rows={byDepartment}
                categoryKey="department"
                categoryLabel="Department"
                series={[{ key: "count", label: "Employees" }]}
                layout="horizontal"
                height={180}
                asOf={hr.at}
              />
            ) : null}
          </div>
        )}
      </WorkspacePanel>

      <div className="space-y-4">
        <WorkspacePanel
          title="Credentials expiring"
          description="A lapsed registration stops somebody practising"
          icon="credential"
          to="/people"
        >
          {hr.loading ? (
            <PanelLoading height={150} />
          ) : hr.error ? (
            <PanelProblem error={hr.error} />
          ) : !data?.expiring_credentials.length ? (
            <PanelEmpty message="No credentials expiring soon." />
          ) : (
            <div className="space-y-0.5">
              {data.expiring_credentials.slice(0, 6).map((credential) => (
                <WorklistRow
                  key={credential.credential}
                  tone={credential.is_expired ? "critical" : "warning"}
                  title={credential.employee_name}
                  detail={`${credential.type} · ${credential.reference_number}`}
                  trailing={
                    <StatusBadge
                      status={credential.is_expired ? "expired" : "expiring"}
                      label={
                        credential.is_expired
                          ? "expired"
                          : `${credential.days_to_expiry}d`
                      }
                    />
                  }
                />
              ))}
            </div>
          )}
        </WorkspacePanel>

        <ApprovalsPanel workspace={workspace} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bits                                                                        */
/* -------------------------------------------------------------------------- */

function Figure({
  label,
  value,
  tone,
  large,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "warning" | "critical" | "good";
  large?: boolean;
}) {
  return (
    <div className="min-w-0">
      <p className="type-label text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 font-semibold tabular-nums",
          large ? "text-2xl" : "text-lg",
          tone === "warning" && "text-warning",
          tone === "critical" && "text-critical",
          tone === "good" && "text-good",
        )}
      >
        {value}
      </p>
    </div>
  );
}

export type { Facility };

/* -------------------------------------------------------------------------- */
/* Laboratory                                                                  */
/* -------------------------------------------------------------------------- */

const STAGE: Record<string, string> = {
  ordered: "to collect",
  collected: "collected",
  received: "at the bench",
  in_progress: "in progress",
  resulted: "to verify",
  verified: "verified, not released",
};

/**
 * The bench: what to pick up next, what is critical, and how fast it goes.
 *
 * **A technician was shown the dispensary.** The role holds `stock.read` for
 * reagents, and the persona ladder matched it to pharmacy -- a board of
 * takings and orders for somebody whose day is samples. The worklist comes
 * first and in the order work should be picked up (STAT, urgent, then oldest,
 * as the server sorts it), with the stage each order is at, because "to
 * collect" and "to verify" are different people walking to different places.
 */
export function LabHome({ facility }: { facility: string | null }) {
  const bench = useResource<{ count: number; overdue: number; orders: DiagnosticOrder[] }>(
    facility ? `/diagnostics/worklist/?facility=${facility}` : null,
  );
  const alerts = useResource<Paginated<CriticalAlert>>("/diagnostics/critical-alerts/?open=true");
  const turnaround = useResource<TurnaroundReport>(
    facility ? `/diagnostics/turnaround/?facility=${facility}` : null,
  );

  const orders = bench.data?.orders ?? [];
  const count = (statuses: string[]) => orders.filter((order) => statuses.includes(order.status)).length;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel
        title="Worklist"
        description="STAT first, then urgent, then oldest"
        icon="laboratory"
        to="/diagnostics"
        toLabel="Open laboratory"
        span={2}
      >
        {bench.loading ? (
          <PanelLoading height={220} />
        ) : bench.error ? (
          <PanelProblem error={bench.error} />
        ) : orders.length === 0 ? (
          <PanelEmpty message="Nothing on the bench. Every order is released." />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Figure label="To collect" value={count(["ordered"])} />
              <Figure label="At the bench" value={count(["collected", "received", "in_progress"])} />
              <Figure label="To verify" value={count(["resulted", "verified"])} />
              <Figure
                label="Overdue"
                value={bench.data?.overdue ?? 0}
                tone={(bench.data?.overdue ?? 0) > 0 ? "critical" : undefined}
              />
            </div>
            <div className="space-y-0.5">
              {orders.slice(0, 8).map((order) => (
                <WorklistRow
                  key={order.uuid}
                  person={order.patient_name}
                  title={order.patient_name}
                  detail={`${order.priority === "routine" ? "" : `${order.priority.toUpperCase()} · `}${order.test_name} · ${STAGE[order.status] ?? order.status.replace("_", " ")}`}
                  meta={waitedFor(order.ordered_at)}
                  trailing={
                    <StatusBadge
                      status={order.status}
                      label={STAGE[order.status] ?? undefined}
                    />
                  }
                  tone={
                    order.priority === "stat" || order.is_overdue
                      ? "critical"
                      : order.priority === "urgent"
                        ? "warning"
                        : undefined
                  }
                  to="/diagnostics"
                />
              ))}
              {orders.length > 8 ? (
                <p className="pt-1 type-caption">and {orders.length - 8} more on the worklist</p>
              ) : null}
            </div>
          </div>
        )}
      </WorkspacePanel>

      <div className="space-y-4">
        <WorkspacePanel title="Critical values" description="Not yet communicated" icon="warning" to="/diagnostics">
          {alerts.loading ? (
            <PanelLoading />
          ) : alerts.error ? (
            <PanelProblem error={alerts.error} />
          ) : (alerts.data?.results ?? []).length === 0 ? (
            <PanelEmpty message="No critical value is waiting to be called through." />
          ) : (
            <div className="space-y-0.5">
              {(alerts.data?.results ?? []).slice(0, 5).map((alert) => (
                <WorklistRow
                  key={alert.uuid}
                  person={alert.patient_name}
                  title={`${alert.analyte} ${alert.value}`}
                  detail={`${alert.patient_name} · ${alert.order_reference}`}
                  meta={waitedFor(alert.raised_at)}
                  tone="critical"
                  to="/diagnostics"
                />
              ))}
            </div>
          )}
        </WorkspacePanel>

        <WorkspacePanel title="Turnaround" description="Last seven days" icon="duration">
          {turnaround.loading ? (
            <PanelLoading />
          ) : turnaround.error ? (
            <PanelProblem error={turnaround.error} />
          ) : !turnaround.data ? (
            <PanelEmpty message="Nothing released in the last week." />
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <Figure
                label="Bench time"
                value={formatValue(turnaround.data.average_lab_minutes, "duration")}
              />
              <Figure
                label="Past target"
                value={formatValue(turnaround.data.breach_rate_percent, "percent")}
                tone={turnaround.data.breach_rate_percent > 10 ? "warning" : undefined}
              />
              <Figure label="Released" value={turnaround.data.released} />
              <Figure
                label="Rejected samples"
                value={turnaround.data.rejected}
                tone={turnaround.data.rejected > 0 ? "warning" : undefined}
              />
            </div>
          )}
        </WorkspacePanel>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Accounts                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Accounts: what came in today, and who still owes.
 *
 * **An accountant was shown the owner's overview as their own day**, because
 * the ladder's leadership rung asked only for two permissions the accountant
 * also holds. Their day is the cash-up and the receivables: today's takings by
 * method, because the drawer is counted apart from the wallets, and the unpaid
 * invoices oldest first, because the oldest is the one least likely to be paid.
 */
export function AccountsHome({ facility }: { facility: string | null }) {
  const can = useCan();
  const collection = useResource<DailyCollection>(
    facility ? `/billing/collection/?facility=${facility}` : null,
  );
  /*
    Receivables follow the role's reach, not the building. An accountant's
    grant is the whole organization, and the demo's one unpaid invoice was at
    the clinic while this board looked at the hospital -- "every invoice here
    is paid" beside "NPR 1,400 still owed" across the organization.
  */
  const everySite = can("invoice.read", "organization");
  const unpaid = useResource<Paginated<Invoice>>(
    everySite
      ? "/billing/invoices/?unpaid=true&is_credit_note=false&ordering=issued_at"
      : facility
        ? `/billing/invoices/?unpaid=true&is_credit_note=false&facility=${facility}&ordering=issued_at`
        : null,
  );
  const organization = useResource<{
    billing?: { collected: string; outstanding: string; overdue_invoices: number };
  }>("/org/today/", can("analytics.read", "organization"));

  const methods = Object.values(collection.data?.by_method ?? {}).filter(
    (method) => Number(method.total) !== 0,
  );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel
        title="Collected today"
        description={collection.data?.facility ?? "This facility"}
        icon="payment"
        to="/billing"
        toLabel="Open billing"
      >
        {collection.loading ? (
          <PanelLoading height={160} />
        ) : collection.error ? (
          <PanelProblem error={collection.error} />
        ) : !collection.data ? (
          <PanelEmpty message="Choose where you work to see its cash-up." />
        ) : (
          <div className="space-y-3">
            <Figure
              label="Net collected"
              value={formatValue(Number(collection.data.net_collected), "money")}
              large
            />
            <p className="type-caption">
              {collection.data.payment_count} payments · {collection.data.invoices_issued} invoices issued
              {Number(collection.data.refunded) > 0
                ? ` · ${formatValue(Number(collection.data.refunded), "money")} refunded`
                : ""}
            </p>
            {methods.length > 0 ? (
              <ul className="divide-y divide-border text-sm">
                {methods.map((method) => (
                  <li key={method.label} className="flex justify-between py-1.5">
                    <span className="text-muted-foreground">{method.label}</span>
                    <span className="tabular-nums">{formatValue(Number(method.total), "money")}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="type-caption">Nothing received yet today.</p>
            )}
          </div>
        )}
      </WorkspacePanel>

      <WorkspacePanel
        title="Unpaid invoices"
        description={
          unpaid.data
            ? `${unpaid.data.count} open${everySite ? " across every site" : ""}, oldest first`
            : "Oldest first"
        }
        icon="invoice"
        to="/billing"
        span={2}
      >
        {unpaid.loading ? (
          <PanelLoading height={160} />
        ) : unpaid.error ? (
          <PanelProblem error={unpaid.error} />
        ) : (unpaid.data?.results ?? []).length === 0 ? (
          <PanelEmpty message={everySite ? "Every invoice is paid." : "Every invoice here is paid."} />
        ) : (
          <div className="space-y-0.5">
            {(unpaid.data?.results ?? []).slice(0, 8).map((invoice) => {
              const days = invoice.issued_at
                ? Math.floor((Date.now() - new Date(invoice.issued_at).getTime()) / 86_400_000)
                : 0;
              return (
                <WorklistRow
                  key={invoice.uuid}
                  person={invoice.bill_to_name}
                  title={invoice.bill_to_name}
                  detail={[invoice.number, invoice.patient_mrn].filter(Boolean).join(" · ")}
                  meta={waitedFor(invoice.issued_at)}
                  trailing={
                    <span className="text-sm font-semibold tabular-nums">
                      {formatValue(Number(invoice.balance_due), "money")}
                    </span>
                  }
                  tone={days > 30 ? "critical" : days > 7 ? "warning" : undefined}
                  to="/billing"
                />
              );
            })}
          </div>
        )}
      </WorkspacePanel>

      {organization.data?.billing ? (
        <WorkspacePanel title="Across the organization" description="Every site, today" icon="finance" to="/billing">
          <div className="grid grid-cols-2 gap-4">
            <Figure
              label="Collected"
              value={formatValue(Number(organization.data.billing.collected), "money")}
            />
            <Figure
              label="Still owed"
              value={formatValue(Number(organization.data.billing.outstanding), "money")}
            />
            <Figure
              label="Past due"
              value={organization.data.billing.overdue_invoices}
              tone={organization.data.billing.overdue_invoices > 0 ? "critical" : undefined}
            />
          </div>
        </WorkspacePanel>
      ) : null}
    </div>
  );
}
