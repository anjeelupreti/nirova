/**
 * The discharge summary: the document a patient carries out of the hospital.
 *
 * It is read by the next clinician — a GP in Banepa, a follow-up clinic, an
 * emergency department at two in the morning — who has none of the record and
 * only this sheet. So it answers, in the order they will ask: who, how long,
 * why they came in, what it turned out to be, what was done and found, what
 * they are to keep taking, and when they are to be seen again.
 *
 * **What the reader may not see is said, not dropped.** The investigations
 * and the medicines are fetched with the permissions of whoever is printing.
 * A ward clerk printing a summary without clinical access gets a sheet that
 * says "investigations not included — printed without clinical access"
 * rather than one that silently omits them, because a summary that looks
 * complete and is not is worse than one that says what is missing.
 *
 * **Only a finished stay has one.** Offered after discharge, never during:
 * a summary of a stay still in progress is a draft of a document, and drafts
 * of discharge summaries have a way of being handed over.
 */

import * as React from "react";

import api, { ApiError } from "@/lib/api";
import { PrintableDocument, SignatureBlock } from "@/components/ui/export";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import type { Admission } from "@/types";
import { formatDate } from "@/lib/dates";

interface Medication {
  uuid: string;
  display_name: string;
  sig: string;
  end_date: string | null;
}

interface ResultOrder {
  reference: string;
  test_name: string;
  released_at: string;
  results: { analyte: string; value: string; unit: string; flag: string; is_abnormal: boolean }[];
}

interface PatientFacts {
  gender: string;
  age_years?: number | null;
  date_of_birth?: string | null;
  phone?: string;
}

type Loaded<T> = { data: T } | { refused: true } | { failed: string };

async function load<T>(path: string): Promise<Loaded<T>> {
  try {
    return { data: await api.get<T>(path) };
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) return { refused: true };
    return { failed: err instanceof ApiError ? err.message : "did not load" };
  }
}

const day = (iso: string | null | undefined) =>
  iso
    ? formatDate(iso)
    : "—";

/** Printed when the discharging clinician gave no specific warning signs. */
const GENERAL_WARNING_SIGNS = [
  "Difficulty breathing",
  "Chest pain",
  "Confusion or fainting",
  "Bleeding",
  "A fever that does not settle",
];

const FLAG: Record<string, string> = {
  low: "L", high: "H", critical_low: "CRIT L", critical_high: "CRIT H", abnormal: "ABN",
};

export function DischargeSummaryPreview({
  admission,
  organization,
  printedBy,
  onClose,
}: {
  admission: Admission;
  organization: string;
  printedBy?: string;
  onClose: () => void;
}) {
  const [patient, setPatient] = React.useState<Loaded<PatientFacts> | null>(null);
  const [medicines, setMedicines] = React.useState<Loaded<{ medications: Medication[] }> | null>(null);
  const [results, setResults] = React.useState<Loaded<{ orders: ResultOrder[] }> | null>(null);

  React.useEffect(() => {
    let live = true;
    void Promise.all([
      load<PatientFacts>(`/clinical/patients/${admission.patient}/`),
      load<{ medications: Medication[] }>(`/clinical/patients/${admission.patient}/medications/`),
      load<{ orders: ResultOrder[] }>(`/diagnostics/patients/${admission.patient}/results/`),
    ]).then(([p, m, r]) => {
      if (!live) return;
      setPatient(p);
      setMedicines(m);
      setResults(r);
    });
    return () => {
      live = false;
    };
  }, [admission.patient]);

  const ready = patient && medicines && results;

  return (
    <DocumentPreview
      open
      onClose={onClose}
      title={`Discharge summary · ${admission.reference}`}
      subtitle={admission.patient_name}
      printTarget={ready ? `discharge-${admission.uuid}` : "none"}
    >
      {!ready ? (
        <p className="p-6 type-caption">Gathering the stay…</p>
      ) : (
        <DischargeSummaryDocument
          admission={admission}
          organization={organization}
          printedBy={printedBy}
          patient={"data" in patient ? patient.data : null}
          medicines={medicines}
          results={results}
        />
      )}
    </DocumentPreview>
  );
}

function DischargeSummaryDocument({
  admission,
  organization,
  printedBy,
  patient,
  medicines,
  results,
}: {
  admission: Admission;
  organization: string;
  printedBy?: string;
  patient: PatientFacts | null;
  medicines: Loaded<{ medications: Medication[] }>;
  results: Loaded<{ orders: ResultOrder[] }>;
}) {
  // Only what was released during this stay, not the patient's whole history.
  const from = new Date(admission.admitted_at).getTime();
  const to = admission.discharged_at ? new Date(admission.discharged_at).getTime() : Date.now();
  const investigations =
    "data" in results
      ? results.data.orders.filter((order) => {
          const at = new Date(order.released_at).getTime();
          return at >= from && at <= to + 60 * 60 * 1000;
        })
      : [];

  const sex = patient?.gender ? patient.gender.charAt(0).toUpperCase() : "";
  const age = patient?.age_years ?? null;

  return (
    <PrintableDocument
      id={`discharge-${admission.uuid}`}
      title="Discharge summary"
      reference={admission.reference}
      organization={organization}
      issuedAt={admission.discharged_at}
      printedBy={printedBy}
      meta={[
        {
          label: "Patient",
          value: `${admission.patient_name} · ${admission.patient_mrn}${age !== null ? ` · ${age}${sex}` : ""}`,
        },
        { label: "Admitted", value: `${day(admission.admitted_at)} · from ${admission.source.replace(/_/g, " ")}` },
        { label: "Discharged", value: `${day(admission.discharged_at)} · ${admission.length_of_stay_days} night${admission.length_of_stay_days === 1 ? "" : "s"}` },
        { label: "Consultant", value: admission.consultant_name || "—" },
        { label: "Outcome", value: admission.status.replace(/_/g, " ") },
        { label: "Follow-up", value: admission.follow_up_on ? day(admission.follow_up_on) : "As needed" },
      ]}
      footer={
        <SignatureBlock
          signatories={[
            { role: "Discharging clinician", name: admission.consultant_name },
            { role: "Nurse in charge" },
            { role: "Received by patient / attendant", name: admission.attendant_name || null },
          ]}
        />
      }
    >
      <Section title="Diagnosis">
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted-foreground">On admission</dt>
          <dd>{admission.admitting_diagnosis || admission.provisional_diagnosis || "—"}</dd>
          <dt className="text-muted-foreground">Final</dt>
          <dd className="font-medium">{admission.final_diagnosis || admission.admitting_diagnosis || "—"}</dd>
        </dl>
      </Section>

      <Section title="Course in hospital">
        <p className="whitespace-pre-line text-sm">{admission.discharge_summary || "—"}</p>
        {admission.bed_assignments.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Cared for in{" "}
            {admission.bed_assignments
              .map((stay) => `${stay.ward_name} (${stay.bed_code}, ${stay.nights} night${stay.nights === 1 ? "" : "s"})`)
              .join(" → ")}
          </p>
        )}
      </Section>

      <Section title="Investigations">
        {"refused" in results ? (
          <Withheld what="Investigations" />
        ) : "failed" in results ? (
          <p className="text-sm text-muted-foreground">Investigations could not be retrieved ({results.failed}).</p>
        ) : investigations.length === 0 ? (
          <p className="text-sm text-muted-foreground">None released during this stay.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {investigations.map((order) => (
                <tr key={order.reference} className="border-b align-top last:border-b-0">
                  <td className="w-40 py-1.5 pr-3 font-medium">
                    {order.test_name}
                    <span className="block text-xs font-normal text-muted-foreground">{day(order.released_at)}</span>
                  </td>
                  <td className="py-1.5">
                    {order.results
                      .map((row) => `${row.analyte} ${row.value}${row.unit ? ` ${row.unit}` : ""}${FLAG[row.flag] ? ` (${FLAG[row.flag]})` : ""}`)
                      .join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Medicines to continue">
        {"refused" in medicines ? (
          <Withheld what="Medicines" />
        ) : "failed" in medicines ? (
          <p className="text-sm text-muted-foreground">Medicines could not be retrieved ({medicines.failed}).</p>
        ) : medicines.data.medications.length === 0 ? (
          <p className="text-sm">No medicines prescribed to continue at home.</p>
        ) : (
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {medicines.data.medications.map((row) => (
              <li key={row.uuid}>
                <span className="font-medium">{row.display_name}</span> — {row.sig}
                {row.end_date && <span className="text-muted-foreground"> until {day(row.end_date)}</span>}
              </li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="At home">
        {admission.discharge_advice ? (
          <p className="whitespace-pre-line text-sm">{admission.discharge_advice}</p>
        ) : null}
        {admission.discharge_diet || admission.discharge_activity ? (
          <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[6rem_1fr]">
            {admission.discharge_diet ? (
              <>
                <dt className="text-muted-foreground">Food</dt>
                <dd className="whitespace-pre-line">{admission.discharge_diet}</dd>
              </>
            ) : null}
            {admission.discharge_activity ? (
              <>
                <dt className="text-muted-foreground">Activity</dt>
                <dd className="whitespace-pre-line">{admission.discharge_activity}</dd>
              </>
            ) : null}
          </dl>
        ) : null}
        {!admission.discharge_advice && !admission.discharge_diet && !admission.discharge_activity ? (
          <p className="text-sm">—</p>
        ) : null}
      </Section>

      <Section title="Come back to hospital at once if">
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {(admission.discharge_warning_signs?.length
            ? admission.discharge_warning_signs
            : GENERAL_WARNING_SIGNS
          ).map((sign) => (
            <li key={sign}>{sign}</li>
          ))}
        </ul>
      </Section>
    </PrintableDocument>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 break-inside-avoid">
      <h3 className="mb-1.5 border-b pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Withheld({ what }: { what: string }) {
  return (
    <p className="text-sm italic text-muted-foreground">
      {what} not included — this copy was printed without clinical access. Ask
      the ward for a clinician-printed copy.
    </p>
  );
}
