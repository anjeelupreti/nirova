/**
 * One patient, on one page — `/patients/:uuid`.
 *
 * **The most-used screen in any hospital system, and this product did not have
 * it.** A patient was a row in a search result that opened a side panel of
 * demographics. Their history, their results, what they are taking and what
 * they owe lived on four different screens, reached from four different places,
 * none of which could be linked to. "Patient cycle, history, records, past
 * records, documents — everything should be recordable and displayable" was
 * the brief, and the honest answer was that it was all *recorded* and almost
 * none of it was *displayable in one place*.
 *
 * **Every tab is its own tier, and loads and fails on its own.** A patient's
 * record is not one permission, it is three (`docs/ACCESS_DESIGN.md`):
 *
 * | Tier | Tab | Permission |
 * |---|---|---|
 * | Identity | the header, contact, registration | `patient.read` |
 * | Safety | allergies, active medications | `patient.safety.read` |
 * | Clinical | the timeline, diagnoses, results | `patient.clinical.read` + a care relationship |
 *
 * So a receptionist opening this page sees who the patient is and what they
 * owe, and the clinical tabs are *not offered* rather than offered and 403'd.
 * And a clinician without a care relationship sees the tabs with the reason
 * they are closed and the way through — break-glass — because a bare refusal
 * on a clinical record at three in the morning is how somebody borrows a
 * colleague's login.
 *
 * Building this page is what found two endpoints answering for a tier they did
 * not belong to: the active-medications list behind the front-desk permission
 * and unlogged, and the clinical summary returning diagnoses to anybody at the
 * facility. Both were fixed first; see `tests/test_patient_tiers.py`.
 */

import * as React from "react";
import { Link, useParams } from "react-router-dom";

import { cn } from "@/lib/utils";
import { useCan } from "@/components/ui/can";
import { Icon, type IconName } from "@/components/ui/icon";
import { Page } from "@/components/ui/layout";
import { RecordSkeleton } from "@/components/ui/loader";
import { StatusBadge } from "@/components/ui/status";
import { TabbedSection } from "@/components/ui/tabs";
import { Timeline, TimelineItem, Avatar } from "@/components/ui/data";
import { EmptyState } from "@/components/ui/feedback";
import { Button } from "@/components/ui/primitives";
import { Chart, formatValue } from "@/components/charts";
import { useResource } from "@/components/workspace/useResource";
import {
  PanelEmpty,
  PanelLoading,
  PanelProblem,
  WorkspacePanel,
} from "@/components/workspace/WorkspaceFrame";
import type { ClinicalSummary, PatientAccount, PatientDetail } from "@/types";
import { formatDate, formatDateTime } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* Shapes the API returns that had no type yet                                 */
/* -------------------------------------------------------------------------- */

interface ActiveMedication {
  uuid: string;
  prescription_reference: string;
  prescribed_at: string;
  prescriber: string;
  display_name: string;
  generic_name: string;
  sig: string;
  start_date: string | null;
  end_date: string | null;
  is_overdue_review: boolean;
  warnings: string[] | string | null;
}

interface MedicationList {
  patient_mrn: string;
  count: number;
  needs_review: ActiveMedication[];
  medications: ActiveMedication[];
}

interface ResultOrder {
  reference: string;
  test_name: string;
  modality: string;
  released_at: string;
  turnaround_minutes: number | null;
  results: {
    analyte: string;
    value: string;
    unit: string;
    reference: string;
    flag: string;
    is_abnormal: boolean;
    is_critical: boolean;
    was_amended: boolean;
  }[];
}

interface ResultList {
  patient_mrn: string;
  orders: ResultOrder[];
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function PatientRecordPage() {
  const { uuid } = useParams<{ uuid: string }>();
  const can = useCan();

  const mayClinical = can("patient.clinical.read", "own");
  const maySafety = can("patient.safety.read", "own");
  const mayBilling = can("invoice.read", "facility");

  const patient = useResource<PatientDetail>(uuid ? `/clinical/patients/${uuid}/` : null);
  const summary = useResource<ClinicalSummary>(
    uuid ? `/clinical/patients/${uuid}/summary/` : null,
    mayClinical,
  );
  const medications = useResource<MedicationList>(
    uuid ? `/clinical/patients/${uuid}/medications/` : null,
    maySafety,
  );
  const results = useResource<ResultList>(
    uuid ? `/diagnostics/patients/${uuid}/results/` : null,
    mayClinical,
  );
  const account = useResource<PatientAccount>(
    uuid ? `/billing/patients/${uuid}/account/` : null,
    mayBilling,
  );

  if (patient.loading) {
    return (
      <Page>
        <RecordSkeleton />
      </Page>
    );
  }

  if (patient.error || !patient.data) {
    return (
      <Page>
        <EmptyState
          title="This record could not be opened"
          description={patient.error ?? "No patient with that identifier exists."}
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/patients">Back to patients</Link>
            </Button>
          }
        />
      </Page>
    );
  }

  const record = patient.data;

  /*
    Counts on the tabs. The number is there so a clinician can tell from the
    tab row alone that there are three critical results waiting, without
    opening the tab to find out.
  */
  const criticalResults = (results.data?.orders ?? []).reduce(
    (total, order) => total + order.results.filter((row) => row.is_critical).length,
    0,
  );

  return (
    <Page>
      <RecordHeader patient={record} />

      <TabbedSection
        tabs={[
          { id: "overview", label: "Overview", icon: "patientSingle" },
          {
            id: "timeline",
            label: "History",
            icon: "history",
            hidden: !mayClinical,
            count: summary.data?.recent_encounters.length ?? null,
          },
          {
            id: "results",
            label: "Results",
            icon: "laboratory",
            hidden: !mayClinical,
            count: criticalResults > 0 ? criticalResults : (results.data?.orders.length ?? null),
          },
          {
            id: "medications",
            label: "Medications",
            icon: "prescription",
            hidden: !maySafety,
            count: medications.data?.count ?? null,
          },
          {
            id: "billing",
            label: "Account",
            icon: "billing",
            hidden: !mayBilling,
          },
        ]}
      >
        {{
          overview: (
            <OverviewTab
              patient={record}
              summary={summary}
              medications={medications}
              account={account}
              mayClinical={mayClinical}
              maySafety={maySafety}
              mayBilling={mayBilling}
            />
          ),
          timeline: <TimelineTab summary={summary} />,
          results: <ResultsTab results={results} />,
          medications: <MedicationsTab medications={medications} />,
          billing: <AccountTab account={account} />,
        }}
      </TabbedSection>
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* Header                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Who this is, before anything else.
 *
 * **Alerts and allergies are in the header, not in a tab.** They are the two
 * things that change what somebody does next with this patient, and a record
 * that makes you open a tab to learn the patient is anaphylactic to penicillin
 * has put the most important fact on the page behind a click.
 */
function RecordHeader({ patient }: { patient: PatientDetail }) {
  const blocking = patient.allergies.filter((allergy) => allergy.blocks_prescribing);

  return (
    <header className="overflow-hidden rounded-xl border bg-card shadow-raised">
      {patient.alerts ? (
        <div className="flex items-start gap-2 border-b border-critical/30 bg-critical-subtle px-5 py-2.5">
          <Icon name="warning" size="md" className="mt-0.5 text-critical" />
          <p className="text-sm font-medium text-critical-subtle-foreground">
            {patient.alerts}
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-start gap-5 p-5">
        <Avatar name={patient.full_name} size="lg" />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="type-title">{patient.full_name}</h1>
            <StatusBadge status={patient.status} />
            {patient.is_merged ? (
              <StatusBadge
                status="merged"
                tone="warning"
                label={`Merged into ${patient.merged_into_mrn ?? "another record"}`}
              />
            ) : null}
          </div>

          <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1.5 text-sm">
            <Fact label="MRN">
              <span className="type-code font-semibold">{patient.mrn}</span>
            </Fact>
            <Fact label="Age">
              {patient.age_years ?? "—"}
              {patient.is_dob_estimated ? (
                <span className="text-muted-foreground"> (est.)</span>
              ) : null}
            </Fact>
            <Fact label="Sex">{patient.gender || "—"}</Fact>
            <Fact label="Blood">{patient.blood_group || "—"}</Fact>
            <Fact label="Phone">{patient.phone || "—"}</Fact>
            <Fact label="Category">{patient.category || "—"}</Fact>
          </dl>

          {/*
            Allergies as chips, blocking ones first and in the critical tone.
            A blocking allergy is one the prescribing screen will refuse to
            override; an unconfirmed one still blocks, because "we are not sure"
            is not a reason to give somebody the drug.
          */}
          {patient.allergies.length > 0 ? (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="type-label text-muted-foreground">Allergies</span>
              {[...patient.allergies]
                .sort((a, b) => Number(b.blocks_prescribing) - Number(a.blocks_prescribing))
                .map((allergy) => (
                  <StatusBadge
                    key={allergy.uuid}
                    status={allergy.blocks_prescribing ? "critical" : "warning"}
                    label={`${allergy.substance}${allergy.reaction ? ` — ${allergy.reaction}` : ""}`}
                    icon={allergy.blocks_prescribing ? "warning" : false}
                  />
                ))}
            </div>
          ) : (
            <p className="mt-3 type-caption">
              No allergies recorded. That is not the same as none known —
              confirm with the patient.
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2" data-print="hide">
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to={`/appointments?patient=${patient.uuid}`}>
                <Icon name="appointment" size="sm" className="mr-1.5" />
                Book
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to={`/billing?patient=${patient.uuid}`}>
                <Icon name="invoice" size="sm" className="mr-1.5" />
                Invoice
              </Link>
            </Button>
          </div>
          {blocking.length > 0 ? (
            <span className="type-caption text-critical">
              {blocking.length} allergy {blocking.length === 1 ? "blocks" : "block"} prescribing
            </span>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="type-label text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Overview                                                                    */
/* -------------------------------------------------------------------------- */

function OverviewTab({
  patient,
  summary,
  medications,
  account,
  mayClinical,
  maySafety,
  mayBilling,
}: {
  patient: PatientDetail;
  summary: ReturnType<typeof useResource<ClinicalSummary>>;
  medications: ReturnType<typeof useResource<MedicationList>>;
  account: ReturnType<typeof useResource<PatientAccount>>;
  mayClinical: boolean;
  maySafety: boolean;
  mayBilling: boolean;
}) {
  const vitals = summary.data?.latest_vitals;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <WorkspacePanel title="Registration" icon="patientSingle" span={1}>
        <dl className="space-y-2 text-sm">
          <Row label="Registered">
            {formatDate(patient.registered_on)}
          </Row>
          <Row label="Address">
            {[patient.tole, patient.ward, patient.municipality, patient.district]
              .filter(Boolean)
              .join(", ") || "—"}
          </Row>
          {patient.is_minor || patient.guardian_name ? (
            <Row label="Guardian">
              {patient.guardian_name || "—"}
              {patient.guardian_relationship ? ` (${patient.guardian_relationship})` : ""}
              {patient.guardian_phone ? ` · ${patient.guardian_phone}` : ""}
            </Row>
          ) : null}
          {patient.notes ? <Row label="Notes">{patient.notes}</Row> : null}
        </dl>
      </WorkspacePanel>

      {mayClinical ? (
        <WorkspacePanel title="Latest vitals" icon="vitals">
          {summary.loading ? (
            <PanelLoading height={120} />
          ) : summary.error ? (
            <PanelProblem error={summary.error} />
          ) : !vitals ? (
            <PanelEmpty message="No vital signs recorded." icon="vitals" />
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Vital label="Blood pressure" value={vitals.blood_pressure} />
                <Vital label="Pulse" value={vitals.pulse_bpm} unit="bpm" />
                <Vital label="SpO₂" value={vitals.spo2_percent} unit="%" />
                <Vital label="BMI" value={vitals.bmi} />
              </div>
              {vitals.abnormal.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {vitals.abnormal.map((flag) => (
                    <StatusBadge
                      key={flag.field}
                      status={flag.level === "critical" ? "critical" : "abnormal"}
                      label={`${flag.field} ${flag.level}`}
                    />
                  ))}
                </div>
              ) : null}
              <p className="type-caption">
                Recorded {formatDateTime(vitals.recorded_at)}
              </p>
            </div>
          )}
        </WorkspacePanel>
      ) : null}

      {mayClinical ? (
        <WorkspacePanel title="Problem list" icon="diagnosis">
          {patient.conditions.length === 0 ? (
            <PanelEmpty message="No conditions recorded." icon="diagnosis" />
          ) : (
            <ul className="space-y-1.5">
              {patient.conditions.map((condition) => (
                <li key={condition.uuid} className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm">{condition.name}</span>
                    {condition.icd10_code ? (
                      <span className="type-code text-xs text-muted-foreground">
                        {condition.icd10_code}
                      </span>
                    ) : null}
                  </span>
                  <StatusBadge status={condition.status} />
                </li>
              ))}
            </ul>
          )}
        </WorkspacePanel>
      ) : null}

      {maySafety ? (
        <WorkspacePanel
          title="Taking now"
          icon="prescription"
          description="Across every prescription"
        >
          {medications.loading ? (
            <PanelLoading height={120} />
          ) : medications.error ? (
            <PanelProblem error={medications.error} />
          ) : !medications.data || medications.data.count === 0 ? (
            <PanelEmpty message="No active medications." icon="prescription" />
          ) : (
            <ul className="space-y-1.5">
              {medications.data.medications.slice(0, 6).map((medication) => (
                <li key={medication.uuid} className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">
                      {medication.display_name}
                    </span>
                    <span className="block truncate type-caption">{medication.sig}</span>
                  </span>
                  {medication.is_overdue_review ? (
                    <StatusBadge status="pending" label="review" />
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </WorkspacePanel>
      ) : null}

      {mayBilling ? (
        <WorkspacePanel title="Account" icon="billing">
          {account.loading ? (
            <PanelLoading height={120} />
          ) : account.error ? (
            <PanelProblem error={account.error} />
          ) : !account.data ? (
            <PanelEmpty message="No account activity." icon="billing" />
          ) : (
            <div className="space-y-3">
              <div>
                <p className="type-label text-muted-foreground">Outstanding</p>
                <p
                  className={cn(
                    "mt-1 text-2xl font-semibold tabular-nums",
                    Number(account.data.outstanding) > 0 && "text-warning",
                  )}
                >
                  {formatValue(Number(account.data.outstanding), "money")}
                </p>
              </div>
              <Chart.StackedProgress
                segments={[
                  { label: "Paid", value: Number(account.data.total_paid), tone: "good" },
                  { label: "Owed", value: Number(account.data.outstanding), tone: "warning" },
                ]}
                format="money"
              />
              {Number(account.data.credit_balance) > 0 ? (
                <p className="type-caption">
                  {/* Reported separately rather than netted off, because a
                      refund owed *to* the patient is a liability, not a
                      discount on what they owe. */}
                  Credit owed to the patient:{" "}
                  {formatValue(Number(account.data.credit_balance), "money")}
                </p>
              ) : null}
            </div>
          )}
        </WorkspacePanel>
      ) : null}

      {!mayClinical ? (
        <WorkspacePanel title="Clinical record" icon="privacy">
          <p className="type-caption">
            The history, results and diagnoses are the clinical tier of this
            record, and your role does not include it. That is a property of the
            role, not a fault — the front desk sees who a patient is and what
            they owe, and the clinicians treating them see the rest.
          </p>
        </WorkspacePanel>
      ) : null}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6rem_1fr] gap-2">
      <dt className="type-label text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Vital({
  label,
  value,
  unit,
}: {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
}) {
  return (
    <div>
      <p className="type-label text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">
        {value ?? "—"}
        {value != null && unit ? (
          <span className="ml-0.5 text-xs font-normal text-muted-foreground">{unit}</span>
        ) : null}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Timeline                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * The patient's care, in the order it happened.
 *
 * **`Timeline` has existed in `components/ui/data.tsx` since it was written and
 * this is the first thing to use it.** A history rendered as a table of rows
 * sorted by date is a list of facts; with a rail and markers a reader sees
 * duration and sequence — the three admissions in a month that are the actual
 * clinical finding.
 */
function TimelineTab({ summary }: { summary: ReturnType<typeof useResource<ClinicalSummary>> }) {
  if (summary.loading) return <PanelLoading height={260} />;
  if (summary.error) return <ClinicalRefusal error={summary.error} />;

  const encounters = summary.data?.recent_encounters ?? [];
  if (encounters.length === 0) {
    return <EmptyState title="No encounters recorded" description="This patient has not been seen yet." />;
  }

  return (
    <div className="max-w-3xl rounded-lg border bg-card p-5 shadow-raised">
      <Timeline>
        {encounters.map((encounter, index) => {
          const primary = encounter.diagnoses.find((diagnosis) => diagnosis.is_primary);
          return (
            <TimelineItem
              key={encounter.reference}
              last={index === encounters.length - 1}
              intent={index === 0 ? "active" : "neutral"}
              icon={<Icon name={iconForEncounter(encounter.encounter_type)} size="xs" />}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  {humanise(encounter.encounter_type)}
                  <StatusBadge status={encounter.status} />
                </span>
              }
              time={formatDate(encounter.started_at)}
              description={
                <div className="space-y-1">
                  <p>
                    {encounter.chief_complaint || "No presenting complaint recorded"}
                    <span className="text-muted-foreground"> · {encounter.facility}</span>
                  </p>
                  {encounter.diagnoses.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {encounter.diagnoses.map((diagnosis) => (
                        <span
                          key={`${diagnosis.icd10_code}-${diagnosis.name}`}
                          className={cn(
                            "rounded-md px-1.5 py-0.5 text-xs",
                            diagnosis.is_primary
                              ? "bg-primary-subtle text-primary-subtle-foreground"
                              : "bg-muted text-muted-foreground",
                          )}
                        >
                          {diagnosis.name}
                          {diagnosis.icd10_code ? (
                            <span className="ml-1 type-code opacity-70">{diagnosis.icd10_code}</span>
                          ) : null}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {!primary && encounter.diagnoses.length === 0 ? (
                    <p className="type-caption">No diagnosis recorded for this visit.</p>
                  ) : null}
                  <p className="type-code text-xs text-muted-foreground">{encounter.reference}</p>
                </div>
              }
            />
          );
        })}
      </Timeline>
    </div>
  );
}

function iconForEncounter(type: string): IconName {
  const key = type.toLowerCase();
  if (key.includes("emerg")) return "emergency";
  if (key.includes("inpatient") || key.includes("admission")) return "ward";
  if (key.includes("tele")) return "phone";
  if (key.includes("surg") || key.includes("theatre")) return "theatre";
  return "consultation";
}

function humanise(value: string): string {
  const text = value.replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The clinical tier, refused.
 *
 * **Names the way through.** The API's own refusal says "you are not
 * currently treating this patient", and the product has break-glass for
 * exactly that moment. A screen that shows a red error and nothing else is
 * how somebody decides the system is broken and uses a colleague's login.
 */
function ClinicalRefusal({ error }: { error: string }) {
  const notTreating = /treating/i.test(error);
  return (
    <div className="max-w-2xl rounded-lg border border-dashed bg-muted/30 p-5">
      <div className="flex items-start gap-3">
        <Icon name="privacy" size="lg" className="text-muted-foreground" />
        <div className="min-w-0">
          <p className="type-heading">
            {notTreating ? "You are not currently treating this patient" : "Not available"}
          </p>
          <p className="mt-1 type-caption">
            {notTreating
              ? "This organization requires a care relationship to open the clinical record. If you need it now — an emergency, cover for a colleague — you can take emergency access with a reason. It is time-limited, logged, and reviewed."
              : error}
          </p>
          {notTreating ? (
            <Button asChild size="sm" variant="outline" className="mt-3">
              <Link to="/privacy">
                <Icon name="breakGlass" size="sm" className="mr-1.5" />
                Emergency access
              </Link>
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Results                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Released results, newest first, critical values unmissable.
 *
 * **Superseded results are not shown**, by the endpoint rather than by this
 * screen: a clinician reading a chart wants the current value, and an amended
 * result carries a mark so they know it was changed.
 */
function ResultsTab({ results }: { results: ReturnType<typeof useResource<ResultList>> }) {
  if (results.loading) return <PanelLoading height={260} />;
  if (results.error) return <ClinicalRefusal error={results.error} />;

  const orders = results.data?.orders ?? [];
  if (orders.length === 0) {
    return <EmptyState title="No released results" description="Nothing has been reported for this patient yet." />;
  }

  return (
    <div className="space-y-3">
      {orders.map((order) => {
        const critical = order.results.some((row) => row.is_critical);
        return (
          <section
            key={order.reference}
            className={cn(
              "overflow-hidden rounded-lg border bg-card shadow-raised",
              critical && "border-critical/50",
            )}
          >
            <div
              className={cn(
                "flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5",
                critical && "bg-critical-subtle",
              )}
            >
              <div className="flex min-w-0 items-center gap-2">
                <Icon
                  name={order.modality.toLowerCase().includes("lab") ? "laboratory" : "imaging"}
                  size="md"
                  className={critical ? "text-critical" : "text-muted-foreground"}
                />
                <p className="truncate text-sm font-medium">{order.test_name}</p>
                {critical ? <StatusBadge status="critical" /> : null}
              </div>
              <p className="type-caption">
                <span className="type-code">{order.reference}</span> ·{" "}
                {formatDateTime(order.released_at)}
                {order.turnaround_minutes != null
                  ? ` · ${formatValue(order.turnaround_minutes, "duration")} turnaround`
                  : ""}
              </p>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="row-density type-label text-muted-foreground">Analyte</th>
                  <th className="row-density text-right type-label text-muted-foreground">Result</th>
                  <th className="row-density hidden type-label text-muted-foreground sm:table-cell">Reference</th>
                  <th className="row-density text-right type-label text-muted-foreground">Flag</th>
                </tr>
              </thead>
              <tbody>
                {order.results.map((row) => (
                  <tr key={row.analyte} className="border-b last:border-0">
                    <td className="row-density">
                      {row.analyte}
                      {row.was_amended ? (
                        <span className="ml-1.5 text-xs text-warning" title="This result was amended after release">
                          amended
                        </span>
                      ) : null}
                    </td>
                    <td
                      className={cn(
                        "row-density text-right font-medium tabular-nums",
                        row.is_critical && "text-critical",
                        !row.is_critical && row.is_abnormal && "text-serious",
                      )}
                    >
                      {row.value}
                      {row.unit ? (
                        <span className="ml-1 text-xs font-normal text-muted-foreground">{row.unit}</span>
                      ) : null}
                    </td>
                    <td className="row-density hidden text-muted-foreground sm:table-cell">
                      {row.reference || "—"}
                    </td>
                    <td className="row-density text-right">
                      {row.is_critical ? (
                        <StatusBadge status="critical" label={row.flag || "critical"} />
                      ) : row.is_abnormal ? (
                        <StatusBadge status="abnormal" label={row.flag || "abnormal"} />
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Medications                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * Everything the patient is taking, across every prescription.
 *
 * A patient on five drugs often has them on three separate scripts, so the list
 * a clinician checks before adding anything new has to be assembled across
 * them. **Courses past their end date and still open are flagged first** —
 * they are either finished and never closed, or being continued without a
 * decision, and either is worth knowing before writing another.
 */
function MedicationsTab({
  medications,
}: {
  medications: ReturnType<typeof useResource<MedicationList>>;
}) {
  if (medications.loading) return <PanelLoading height={220} />;
  if (medications.error) return <ClinicalRefusal error={medications.error} />;

  const data = medications.data;
  if (!data || data.count === 0) {
    return <EmptyState title="No active medications" description="Nothing is currently prescribed." />;
  }

  const ordered = [...data.medications].sort(
    (a, b) => Number(b.is_overdue_review) - Number(a.is_overdue_review),
  );

  return (
    <div className="space-y-3">
      {data.needs_review.length > 0 ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-warning/40 bg-warning-subtle/60 p-3">
          <Icon name="duration" size="md" className="mt-0.5 text-warning" />
          <p className="text-sm text-warning-subtle-foreground">
            {data.needs_review.length}{" "}
            {data.needs_review.length === 1 ? "course has" : "courses have"} passed
            their end date and are still open — finished and never closed, or
            continued without a decision.
          </p>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-lg border bg-card shadow-raised">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="row-density type-label text-muted-foreground">Medicine</th>
              <th className="row-density type-label text-muted-foreground">Directions</th>
              <th className="row-density hidden type-label text-muted-foreground md:table-cell">Prescriber</th>
              <th className="row-density text-right type-label text-muted-foreground">Until</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((medication) => (
              <tr key={medication.uuid} className="border-b last:border-0">
                <td className="row-density">
                  <p className="font-medium">{medication.display_name}</p>
                  <p className="type-caption">{medication.generic_name}</p>
                </td>
                <td className="row-density">{medication.sig || "—"}</td>
                <td className="row-density hidden md:table-cell">
                  <p>{medication.prescriber || "—"}</p>
                  <p className="type-code text-xs text-muted-foreground">
                    {medication.prescription_reference}
                  </p>
                </td>
                <td className="row-density text-right">
                  {medication.is_overdue_review ? (
                    <StatusBadge status="pending" label="review due" />
                  ) : medication.end_date ? (
                    <span className="tabular-nums">
                      {formatDate(medication.end_date)}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">ongoing</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Account                                                                     */
/* -------------------------------------------------------------------------- */

function AccountTab({ account }: { account: ReturnType<typeof useResource<PatientAccount>> }) {
  if (account.loading) return <PanelLoading height={220} />;
  if (account.error) return <PanelProblem error={account.error} />;

  const data = account.data;
  if (!data) return <EmptyState title="No account activity" />;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Chart.Stat label="Billed" value={Number(data.total_billed)} format="money" goodDirection="neither" />
        <Chart.Stat label="Paid" value={Number(data.total_paid)} format="money" goodDirection="neither" />
        <Chart.Stat
          label="Outstanding"
          value={Number(data.outstanding)}
          format="money"
          goodDirection="down"
          tone={Number(data.outstanding) > 0 ? "warning" : "good"}
        />
        <Chart.Stat
          label="Not yet invoiced"
          value={Number(data.uninvoiced_charges)}
          format="money"
          goodDirection="down"
          footnote={`${data.uninvoiced_count} charges`}
        />
      </div>

      {data.invoices.length === 0 ? (
        <EmptyState title="No invoices" />
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card shadow-raised">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="row-density type-label text-muted-foreground">Invoice</th>
                <th className="row-density type-label text-muted-foreground">Issued</th>
                <th className="row-density text-right type-label text-muted-foreground">Total</th>
                <th className="row-density text-right type-label text-muted-foreground">Balance</th>
                <th className="row-density text-right type-label text-muted-foreground">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.invoices.map((invoice, index) => (
                <tr key={invoice.number ?? index} className="border-b last:border-0">
                  <td className="row-density">
                    <span className="type-code">{invoice.number ?? "draft"}</span>
                    {invoice.is_credit_note ? (
                      <span className="ml-1.5 text-xs text-info">credit note</span>
                    ) : null}
                  </td>
                  <td className="row-density tabular-nums">
                    {invoice.issued_at ? formatDate(invoice.issued_at) : "—"}
                  </td>
                  <td className="row-density text-right tabular-nums">
                    {formatValue(Number(invoice.total), "money")}
                  </td>
                  <td
                    className={cn(
                      "row-density text-right tabular-nums",
                      Number(invoice.balance) > 0 && "font-medium text-warning",
                    )}
                  >
                    {formatValue(Number(invoice.balance), "money")}
                  </td>
                  <td className="row-density text-right">
                    <StatusBadge status={invoice.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
