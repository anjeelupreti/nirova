/**
 * A tax invoice, as paper.
 *
 * **Every invoice this product raised could only be printed as a screenshot of
 * the billing screen** — the navigation rail down the side, the patient search
 * box across the top, the charge-entry form underneath. An insurer, a TPA or
 * the Inland Revenue Department receiving one of those has a document that
 * does not say who issued it or under which PAN, and cannot be filed.
 *
 * What a Nepali tax invoice has to carry, and therefore what this renders:
 *
 * - **The issuer's PAN** and registered address. Without the PAN the patient
 *   cannot claim it and the hospital cannot defend it in an audit.
 * - **The fiscal year** beside the number. Invoice numbers restart each Nepali
 *   fiscal year, so `INV-000318` alone is ambiguous across years and the pair
 *   is the identifier.
 * - **Discount and tax per line and in total.** A total that is only a total
 *   cannot be reconciled against the price list, which is the first thing a
 *   payer's auditor does.
 * - **Payments received against it** and the balance. An invoice that looks
 *   unpaid when it was settled at the counter produces a second payment.
 * - **A credit note is labelled as one**, on its face, with its reason. A
 *   credit note that looks like an invoice gets paid.
 * - **Who printed it and when.** From `PrintableDocument`: a copy with no
 *   provenance cannot be verified or challenged later.
 *
 * Money arrives from the API as strings and is **formatted, never computed
 * with here**. The backend's rounding is the record, and re-deriving a total
 * in floating point is how a printed invoice ends up a paisa off the ledger.
 */

import { cn } from "@/lib/utils";
import { PrintableDocument, SignatureBlock } from "@/components/ui/export";
import type { Invoice } from "@/types";

function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return String(value);
  // `en-IN` grouping — 1,00,000 rather than 100,000 — because that is how
  // amounts are read in Nepal, and a lakh written with a western comma is a
  // figure somebody misreads by a factor of ten.
  return amount.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function InvoiceDocument({
  invoice,
  organization,
  facility,
  printedBy,
}: {
  invoice: Invoice;
  organization: string;
  facility?: {
    name?: string | null;
    pan_number?: string | null;
    street_address?: string | null;
    municipality?: string | null;
    district?: string | null;
    phone?: string | null;
    email?: string | null;
  } | null;
  printedBy?: string;
}) {
  const hasDiscount = Number(invoice.discount_total) !== 0;
  const hasTax = Number(invoice.tax_total) !== 0;
  const hasRounding = Number(invoice.rounding_adjustment) !== 0;

  const address = [facility?.street_address, facility?.municipality, facility?.district]
    .filter(Boolean)
    .join(", ");

  return (
    <PrintableDocument
      id={`invoice-${invoice.uuid}`}
      title={invoice.is_credit_note ? "Credit note" : "Tax invoice"}
      reference={
        invoice.number
          ? `${invoice.number}${invoice.fiscal_year ? ` · FY ${invoice.fiscal_year}` : ""}`
          : "Draft — not issued"
      }
      organization={organization}
      facility={facility?.name}
      facilityDetail={
        <>
          {address || null}
          {address && (facility?.pan_number || facility?.phone) ? <br /> : null}
          {facility?.pan_number ? <>PAN {facility.pan_number}</> : null}
          {facility?.pan_number && facility?.phone ? " · " : null}
          {facility?.phone ?? null}
          {facility?.email ? ` · ${facility.email}` : null}
        </>
      }
      issuedAt={invoice.issued_at}
      printedBy={printedBy}
      meta={[
        { label: "Bill to", value: invoice.bill_to_name || "—" },
        { label: "MRN", value: <span className="type-code">{invoice.patient_mrn}</span> },
        { label: "Status", value: invoice.status.replace(/_/g, " ") },
        {
          label: "Balance due",
          value: (
            <span
              className={cn(
                "font-semibold tabular-nums",
                Number(invoice.balance_due) > 0 && "text-warning",
              )}
            >
              NPR {money(invoice.balance_due)}
            </span>
          ),
        },
      ]}
      footer={
        <>
          {!invoice.number ? (
            // A draft printed and handed over is the start of a dispute: it
            // looks like a bill and has no number to reconcile against.
            <p className="mb-3 rounded-md border border-warning/40 bg-warning-subtle px-3 py-2 text-sm font-medium text-warning-subtle-foreground">
              This is a draft and has not been issued. It is not a tax invoice
              and cannot be used to claim or pay.
            </p>
          ) : null}
          <SignatureBlock
            signatories={[{ role: "Prepared by" }, { role: "Received by" }]}
          />
        </>
      }
    >
      {invoice.is_credit_note ? (
        <p className="mb-4 rounded-md border border-info/40 bg-info-subtle px-3 py-2 text-sm text-info-subtle-foreground">
          <strong className="font-semibold">Credit note.</strong> This reduces
          an amount previously invoiced; it is not a request for payment.
          {invoice.credit_reason ? ` Reason: ${invoice.credit_reason}` : ""}
        </p>
      ) : null}

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-border-strong text-left">
            <th className="py-2 pr-3 type-label text-muted-foreground">Service</th>
            <th className="px-3 py-2 text-right type-label text-muted-foreground">Qty</th>
            <th className="px-3 py-2 text-right type-label text-muted-foreground">Rate</th>
            {hasDiscount ? (
              <th className="px-3 py-2 text-right type-label text-muted-foreground">Discount</th>
            ) : null}
            {hasTax ? (
              <th className="px-3 py-2 text-right type-label text-muted-foreground">Tax</th>
            ) : null}
            <th className="py-2 pl-3 text-right type-label text-muted-foreground">Amount</th>
          </tr>
        </thead>
        <tbody>
          {invoice.lines.map((line) => (
            <tr key={line.uuid} className="border-b">
              <td className="py-1.5 pr-3">
                {line.description}
                {line.service_code ? (
                  <span className="ml-1.5 type-code text-xs text-muted-foreground">
                    {line.service_code}
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">{Number(line.quantity)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{money(line.unit_price)}</td>
              {hasDiscount ? (
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {Number(line.discount_amount) ? `−${money(line.discount_amount)}` : "—"}
                </td>
              ) : null}
              {hasTax ? (
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {Number(line.tax_amount) ? money(line.tax_amount) : "—"}
                </td>
              ) : null}
              <td className="py-1.5 pl-3 text-right tabular-nums">{money(line.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* The totals block: right-aligned under the amount column, each figure
          from the API rather than summed here. */}
      <dl className="ml-auto mt-4 w-full max-w-xs space-y-1 text-sm">
        <TotalRow label="Subtotal" value={money(invoice.subtotal)} />
        {hasDiscount ? (
          <TotalRow label="Discount" value={`−${money(invoice.discount_total)}`} />
        ) : null}
        {hasTax ? <TotalRow label="Tax" value={money(invoice.tax_total)} /> : null}
        {hasRounding ? (
          <TotalRow label="Rounding" value={money(invoice.rounding_adjustment)} />
        ) : null}
        <TotalRow label="Total" value={`NPR ${money(invoice.total)}`} strong />
        <TotalRow label="Paid" value={money(invoice.amount_paid)} />
        <TotalRow
          label="Balance due"
          value={`NPR ${money(invoice.balance_due)}`}
          strong
        />
      </dl>

      {invoice.payments.length > 0 ? (
        <div className="mt-5">
          <p className="mb-1.5 type-eyebrow text-muted-foreground">Payments received</p>
          <table className="w-full text-sm">
            <tbody>
              {invoice.payments.map((payment) => (
                <tr key={payment.uuid} className="border-b last:border-0">
                  <td className="py-1 pr-3 tabular-nums">
                    {new Date(payment.received_at).toLocaleDateString()}
                  </td>
                  <td className="px-3 py-1">
                    {payment.is_refund ? "Refund" : payment.method_display}
                    {payment.reference ? (
                      <span className="ml-1 text-muted-foreground">({payment.reference})</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-1 type-code text-xs text-muted-foreground">
                    {payment.receipt_number ?? ""}
                  </td>
                  <td className="py-1 pl-3 text-right tabular-nums">
                    {payment.is_refund ? "−" : ""}
                    {money(payment.amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </PrintableDocument>
  );
}

function TotalRow({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-4",
        strong && "border-t border-border-strong pt-1 font-semibold",
      )}
    >
      <dt className={strong ? "" : "text-muted-foreground"}>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}
