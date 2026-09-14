/**
 * The prescription, as the patient carries it to a pharmacy.
 *
 * In Nepal that pharmacy is very often not the hospital's: the patient walks
 * out with a sheet of paper and fills it at the counter nearest home. Until
 * now there was no sheet — signing a prescription ended with "RX-… signed" on
 * the doctor's screen and nothing in the patient's hand.
 *
 * What an outside pharmacist needs to dispense safely and lawfully, and gets:
 *
 *  - the prescriber's name and **NMC registration number** — the Nepal Medical
 *    Council number is what makes a prescription for a scheduled drug valid;
 *  - each medicine **generic first**, then brand if one was named, with dose,
 *    route, frequency, duration and the total quantity to supply, so there is
 *    nothing to calculate;
 *  - whether **substitution** is allowed, line by line;
 *  - **how long it is valid**, so a stale prescription is not filled;
 *  - and **any safety warning the prescriber overrode, with their reason** —
 *    the one thing a second pair of eyes at the counter must not miss.
 */

import * as React from "react";

import api from "@/lib/api";
import { PrintableDocument, SignatureBlock } from "@/components/ui/export";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import { formatDate } from "@/lib/dates";

export interface PrintablePrescription {
  uuid: string;
  reference: string;
  patient: string;
  patient_mrn: string;
  patient_name: string;
  facility_name: string;
  prescriber_name: string;
  prescriber_registration: string;
  prescribed_at: string;
  signed_at: string | null;
  valid_until: string | null;
  version: number;
  has_overridden_warning: boolean;
  override_reason: string;
  patient_instructions: string;
  lines: {
    uuid: string;
    generic_name: string;
    brand_name: string;
    strength: string;
    dosage_form: string;
    sig: string;
    duration_days: number | null;
    quantity: string | null;
    quantity_unit: string;
    is_prn: boolean;
    prn_indication: string;
    instructions: string;
    allow_substitution: boolean;
  }[];
}

const day = (iso: string | null) =>
  iso ? formatDate(iso) : "—";

export function PrescriptionPreview({
  prescription,
  organization,
  printedBy,
  onClose,
}: {
  prescription: PrintablePrescription;
  organization: string;
  printedBy?: string;
  onClose: () => void;
}) {
  const [facts, setFacts] = React.useState<{ gender?: string; age_years?: number | null } | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .get<{ gender: string; age_years: number | null }>(`/clinical/patients/${prescription.patient}/`)
      .then((row) => live && setFacts(row))
      .catch(() => live && setFacts({}));
    return () => {
      live = false;
    };
  }, [prescription.patient]);

  const sex = facts?.gender ? facts.gender.charAt(0).toUpperCase() : "";
  const age = facts?.age_years;

  return (
    <DocumentPreview
      open
      onClose={onClose}
      title={`Prescription ${prescription.reference}`}
      subtitle={prescription.patient_name}
      printTarget={`rx-${prescription.uuid}`}
    >
      <PrintableDocument
        id={`rx-${prescription.uuid}`}
        title="Prescription"
        reference={prescription.version > 1 ? `${prescription.reference} v${prescription.version}` : prescription.reference}
        organization={organization}
        facility={prescription.facility_name}
        issuedAt={prescription.signed_at ?? prescription.prescribed_at}
        printedBy={printedBy}
        meta={[
          {
            label: "Patient",
            value: `${prescription.patient_name} · ${prescription.patient_mrn}${age != null ? ` · ${age}${sex}` : ""}`,
          },
          { label: "Valid until", value: day(prescription.valid_until) },
        ]}
        footer={
          <SignatureBlock
            signatories={[
              {
                role: prescription.prescriber_registration
                  ? `Prescriber · NMC ${prescription.prescriber_registration}`
                  : "Prescriber",
                name: prescription.prescriber_name,
              },
              { role: "Dispensed by (name, pharmacy, date)" },
            ]}
          />
        }
      >
        <p className="mb-3 font-serif text-3xl leading-none" aria-hidden>
          ℞
        </p>

        <ol className="space-y-3">
          {prescription.lines.map((line, index) => (
            <li key={line.uuid} className="grid grid-cols-[1.5rem_1fr] gap-1 border-b pb-3 last:border-b-0">
              <span className="text-sm font-semibold tabular-nums">{index + 1}.</span>
              <div>
                <p className="text-sm font-semibold">
                  {line.generic_name} {line.strength}{" "}
                  <span className="font-normal">{line.dosage_form}</span>
                  {line.brand_name && (
                    <span className="font-normal text-muted-foreground"> ({line.brand_name})</span>
                  )}
                </p>
                <p className="text-sm">{line.sig}</p>
                <p className="text-xs text-muted-foreground">
                  {line.duration_days ? `For ${line.duration_days} day${line.duration_days === 1 ? "" : "s"}` : ""}
                  {line.quantity ? ` · Supply ${Number(line.quantity)} ${line.quantity_unit}` : ""}
                  {line.is_prn && line.prn_indication ? ` · When needed for ${line.prn_indication}` : ""}
                  {line.allow_substitution ? " · Generic substitution allowed" : " · Dispense as written"}
                </p>
                {line.instructions && <p className="mt-0.5 text-xs">{line.instructions}</p>}
              </div>
            </li>
          ))}
        </ol>

        {prescription.patient_instructions && (
          <div className="mt-4 text-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Instructions for the patient
            </p>
            <p className="whitespace-pre-line">{prescription.patient_instructions}</p>
          </div>
        )}

        {prescription.has_overridden_warning && (
          <div className="mt-4 rounded-md border border-warning/50 p-3 text-sm">
            <p className="font-semibold">Prescribed despite a safety warning</p>
            <p>{prescription.override_reason}</p>
          </div>
        )}

        <p className="mt-4 text-xs text-muted-foreground">
          Checked against the patient's recorded allergies and current medicines
          when signed. Not valid after {day(prescription.valid_until)}.
        </p>
      </PrintableDocument>
    </DocumentPreview>
  );
}
