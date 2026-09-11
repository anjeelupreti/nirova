/**
 * The counter receipt, at the width of the paper it prints on.
 *
 * **Print used to print the application.** The receipt screen called
 * `window.print()`, which sent the whole page — the "Sale complete" banner,
 * the buttons, the till bar — to an 80 mm thermal printer that then fed a
 * foot of paper. It now prints this element alone, through `printElement`,
 * sized to the roll.
 *
 * **What a Nepali pharmacy receipt carries.** The seller's name, address and
 * PAN, because it is a tax document; the invoice number, because returns and
 * complaints are found by it; each line with its batch and expiry, because a
 * recall is traced to a customer by the batch on the receipt they kept; every
 * tender with its wallet reference, which is what a customer checks against
 * their phone; and the return terms, which are otherwise argued about at the
 * counter.
 *
 * Monospace here is the medium, not a style: thermal receipts are set in a
 * fixed pitch so columns line up without a table.
 */

import type { Sale } from "@/types";

const money = (value: string | number) =>
  Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const expiry = (iso: string) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { month: "2-digit", year: "2-digit" }) : "";

export function CounterReceipt({
  sale,
  change,
}: {
  sale: Sale;
  /** Cash handed back, when known at the till. Not stored on the sale. */
  change?: number;
}) {
  const issuer = sale.issuer;
  const when = new Date(sale.sold_at);

  return (
    <div
      id={`receipt-${sale.uuid}`}
      data-printable
      className="mx-auto w-full max-w-[80mm] bg-white p-4 font-mono text-[11px] leading-snug text-black print:p-0"
    >
      <header className="text-center">
        <p className="text-[13px] font-bold uppercase">{issuer?.name ?? "Pharmacy"}</p>
        {issuer?.address && <p>{issuer.address}</p>}
        {issuer?.phone && <p>Tel {issuer.phone}</p>}
        {issuer?.pan && <p>PAN {issuer.pan}</p>}
        {issuer?.licence && <p>DDA licence {issuer.licence}</p>}
        <p className="mt-2 font-bold">TAX INVOICE</p>
        <p>{sale.invoice_number}</p>
      </header>

      <div className="mt-2 border-t border-dashed border-black pt-1">
        <Row left={when.toLocaleDateString("en-GB")} right={when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} />
        <Row left={`Till ${sale.session_reference}`} right={sale.sold_by_name} />
        <p>Customer: {sale.customer_label || sale.customer_name || "Walk-in"}</p>
        {sale.customer_pan && <p>Buyer PAN: {sale.customer_pan}</p>}
        {sale.prescription_reference && <p>Rx: {sale.prescription_reference}</p>}
      </div>

      <div className="mt-1 border-t border-dashed border-black pt-1">
        {sale.lines.map((line) => (
          <div key={line.uuid} className="py-0.5">
            <p className="font-semibold">{line.product_name}</p>
            <Row
              left={`${Number(line.quantity)} × ${money(line.unit_price)}`}
              right={money(line.total)}
            />
            <p className="text-[10px]">
              Batch {line.batch_number}
              {line.expires_on ? ` · exp ${expiry(line.expires_on)}` : ""}
              {Number(line.discount_amount) > 0 ? ` · disc ${money(line.discount_amount)}` : ""}
              {Number(line.tax_amount) > 0 ? ` · VAT ${money(line.tax_amount)}` : ""}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-1 space-y-0.5 border-t border-dashed border-black pt-1">
        <Row left="Subtotal" right={money(sale.subtotal)} />
        {Number(sale.discount_total) > 0 && <Row left="Discount" right={`-${money(sale.discount_total)}`} />}
        {Number(sale.tax_total) > 0 && <Row left="VAT 13%" right={money(sale.tax_total)} />}
        {Number(sale.rounding_adjustment) !== 0 && <Row left="Rounding" right={money(sale.rounding_adjustment)} />}
        <Row left="TOTAL NPR" right={money(sale.total)} bold />
      </div>

      {(sale.payments ?? []).length > 0 && (
        <div className="mt-1 space-y-0.5 border-t border-dashed border-black pt-1">
          {(sale.payments ?? []).map((payment, index) => (
            <div key={index}>
              <Row left={payment.method_label} right={money(payment.amount)} />
              {payment.reference && <p className="text-[10px]">Ref {payment.reference}</p>}
            </div>
          ))}
          {change !== undefined && change > 0 && <Row left="Change" right={money(change)} />}
        </div>
      )}

      <footer className="mt-2 border-t border-dashed border-black pt-2 text-center text-[10px]">
        <p>Sealed, unopened items may be returned within 7 days with this receipt.</p>
        <p>Cold-chain and controlled medicines cannot be returned.</p>
        <p className="mt-1">Thank you. Please keep medicines out of reach of children.</p>
        <p className="mt-1">{sale.reference}</p>
      </footer>
    </div>
  );
}

function Row({ left, right, bold = false }: { left: string; right: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between gap-2 ${bold ? "text-[12px] font-bold" : ""}`}>
      <span className="min-w-0 truncate">{left}</span>
      <span className="shrink-0 tabular-nums">{right}</span>
    </div>
  );
}
