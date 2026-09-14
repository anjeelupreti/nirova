/**
 * The laboratory report, as it is handed to a patient or filed in a chart.
 *
 * **Only a verified order prints.** The results screen shows values as they
 * are entered, which is right for the laboratory; a *report* is a statement
 * that a second person has checked them, and a report printed between entry
 * and verification is exactly the document verification exists to stop. So
 * the print action is offered only once the order is verified, and the report
 * names both the person who entered the values and the person who released
 * them.
 *
 * **Abnormal values say so in words, not only in colour.** Reports are
 * photocopied, faxed and printed on monochrome lasers; a red "6.8" becomes a
 * grey "6.8" and the only flag was the colour. Each abnormal row carries H, L
 * or CRITICAL beside the value, and a critical value says who was told.
 */

import { cn } from "@/lib/utils";
import { PrintableDocument, SignatureBlock } from "@/components/ui/export";
import type { DiagnosticOrderDetail } from "@/types";
import { formatDateTime } from "@/lib/dates";
import { reportSections } from "@/components/documents/reportSections";

const FLAG_TEXT: Record<string, string> = {
  low: "L",
  high: "H",
  critical_low: "CRITICAL LOW",
  critical_high: "CRITICAL HIGH",
  abnormal: "ABNORMAL",
};

const when = (iso: string | null | undefined) =>
  iso
    ? formatDateTime(iso)
    : "—";

export function LabReportDocument({
  order,
  organization,
  printedBy,
}: {
  order: DiagnosticOrderDetail;
  organization: string;
  printedBy?: string;
}) {
  const entered = order.results[0]?.entered_by_name;
  const critical = order.critical_alerts ?? [];
  // Imaging and other written reports print as sections, not table rows.
  const narrative = order.modality !== "laboratory";

  return (
    <PrintableDocument
      id={`lab-report-${order.uuid}`}
      title={narrative ? "Imaging report" : "Laboratory report"}
      reference={order.accession_number || order.reference}
      organization={organization}
      facility={order.facility_name}
      issuedAt={order.released_at}
      printedBy={printedBy}
      meta={[
        { label: "Patient", value: `${order.patient_name} · ${order.patient_mrn}` },
        { label: "Test", value: order.test_name },
        { label: "Requested by", value: order.ordered_by_name || "—" },
        { label: "Clinical indication", value: order.clinical_indication || "—" },
        { label: "Specimen", value: order.specimen_type || "—" },
        { label: "Order", value: order.reference },
      ]}
      footer={
        <SignatureBlock
          signatories={[
            { role: narrative ? "Reported by" : "Results entered by", name: entered },
            { role: "Verified and released by", name: order.verified_by_name },
          ]}
        />
      }
    >
      {narrative ? (
        <NarrativeReport results={order.results} />
      ) : (
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">Investigation</th>
            <th className="py-2 pr-3 text-right font-medium">Result</th>
            <th className="py-2 pr-3 font-medium">Flag</th>
            <th className="py-2 pr-3 font-medium">Unit</th>
            <th className="py-2 font-medium">Reference range</th>
          </tr>
        </thead>
        <tbody>
          {order.results.map((result) => (
            <tr key={result.uuid} className="border-b last:border-b-0">
              <td className="py-2 pr-3">
                {result.analyte_name}
                {result.was_amended && <span className="ml-1 text-xs">(amended)</span>}
              </td>
              <td
                className={cn(
                  "py-2 pr-3 text-right tabular-nums",
                  result.is_abnormal && "font-semibold",
                  result.is_critical && "text-critical",
                )}
              >
                {result.display_value}
              </td>
              <td className={cn("py-2 pr-3 text-xs font-semibold", result.is_critical && "text-critical")}>
                {FLAG_TEXT[result.flag] ?? ""}
              </td>
              <td className="py-2 pr-3 text-muted-foreground">{result.unit}</td>
              <td className="py-2 text-muted-foreground">{result.reference_text || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      )}

      {critical.length > 0 && (
        <div className="mt-4 rounded-md border border-critical/40 p-3 text-sm">
          <p className="font-semibold text-critical">Critical values communicated</p>
          <ul className="mt-1 space-y-0.5">
            {critical.map((alert) => (
              <li key={alert.uuid}>
                {alert.analyte} {alert.value} — {alert.notified_person
                  ? `told to ${alert.notified_person}${alert.notified_via ? ` by ${alert.notified_via}` : ""} at ${when(alert.notified_at)}`
                  : "notification pending"}
              </li>
            ))}
          </ul>
        </div>
      )}

      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-4">
        <div>
          <dt>Ordered</dt>
          <dd className="text-foreground">{when(order.ordered_at)}</dd>
        </div>
        <div>
          <dt>Collected by</dt>
          <dd className="text-foreground">{order.collected_by_name || "—"}</dd>
        </div>
        <div>
          <dt>Released</dt>
          <dd className="text-foreground">{when(order.released_at)}</dd>
        </div>
        <div>
          <dt>Turnaround</dt>
          <dd className="text-foreground">
            {order.turnaround_minutes !== null ? `${order.turnaround_minutes} min` : "—"}
          </dd>
        </div>
      </dl>
      {narrative ? null : (
        <p className="mt-4 text-xs text-muted-foreground">
          Results are interpreted against reference ranges for the patient's age
          and sex. Please correlate clinically.
        </p>
      )}
    </PrintableDocument>
  );
}

/**
 * A written report, as the sections it was written under.
 *
 * Imaging and other narrative results were printed in the "Result" column of
 * the numeric table: a paragraph of findings squeezed beside empty Flag, Unit
 * and Reference columns. They print as a report now, the impression set apart
 * because it is the part the requesting clinician reads first.
 */
function NarrativeReport({ results }: { results: DiagnosticOrderDetail["results"] }) {
  return (
    <div className="space-y-4 text-sm">
      {results.map((result) => (
        <div key={result.uuid} className="space-y-3">
          {reportSections(String(result.display_value ?? "")).map((section, index) => (
            <section key={`${section.heading ?? "text"}-${index}`} className="break-inside-avoid">
              {section.heading ? (
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {section.heading}
                </h3>
              ) : null}
              <p className={cn("whitespace-pre-line", section.heading === "IMPRESSION" && "font-medium")}>
                {section.body}
              </p>
            </section>
          ))}
          {result.was_amended ? <p className="text-xs text-muted-foreground">(amended)</p> : null}
        </div>
      ))}
    </div>
  );
}
