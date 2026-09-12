/**
 * Getting a list out of the screen.
 *
 * Attached to `DataView`, so **every list in the product gains export the day
 * its screen adopts the component** rather than each one growing its own
 * button. That is the whole argument for having done the lists once.
 *
 * The columns already declare a `value` accessor — it is what search and sort
 * use — so the export is the same data the reader is looking at, in the same
 * order, with the same filter applied. An export that silently returns
 * everything when the screen shows a filtered subset is worse than none: it is
 * the sort of thing somebody reconciles a bank statement against and cannot
 * work out why the totals differ.
 */

import * as React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import {
  downloadCsv,
  exportFilename,
  printElement,
  type ExportColumn,
} from "@/lib/export";
import { downloadListAsWorkbook } from "@/lib/xlsx";

const ITEM = cn(
  "flex cursor-pointer select-none items-start gap-2.5 rounded-md px-2 py-1.5",
  "text-sm outline-none transition-colors duration-quick",
  "focus:bg-accent focus:text-accent-foreground",
);

export function ExportMenu<T>({
  rows,
  columns,
  name,
  /** The id of the element to print. Omit to leave printing out. */
  printTarget,
  /** How many rows the export will contain, when it differs from `rows`. */
  note,
  className,
}: {
  rows: T[];
  columns: ExportColumn<T>[];
  name: string;
  printTarget?: string;
  note?: string;
  className?: string;
}) {
  const disabled = rows.length === 0;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        disabled={disabled}
        title={disabled ? "Nothing to export" : "Export or print this list"}
        className={cn(
          "inline-flex h-9 items-center gap-1.5 rounded-md border border-input bg-card px-2.5 text-sm",
          "transition-colors duration-quick hover:border-border-strong",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
      >
        <Icon name="download" size="sm" />
        <span className="hidden sm:inline">Export</span>
        <Icon name="chevronDown" size="xs" className="text-muted-foreground" />
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className={cn(
            "z-50 w-72 rounded-lg border bg-popover p-1.5 shadow-floating",
            "animate-in fade-in-0 zoom-in-95 duration-quick",
          )}
        >
          <div className="px-2 pb-1.5 pt-1">
            <p className="type-eyebrow text-muted-foreground">
              {rows.length.toLocaleString()}{" "}
              {rows.length === 1 ? "row" : "rows"}
            </p>
            {note ? <p className="mt-0.5 type-caption">{note}</p> : null}
          </div>

          <DropdownMenu.Item
            className={ITEM}
            onSelect={() => void downloadListAsWorkbook(rows, columns, name, exportFilename(name, "xlsx"))}
          >
            <Icon name="report" size="md" className="mt-0.5 text-good" />
            <span className="min-w-0">
              <span className="block font-medium">Excel</span>
              <span className="block type-caption">Workbook with a frozen header and numbers as numbers.</span>
            </span>
          </DropdownMenu.Item>

          <DropdownMenu.Item
            className={ITEM}
            onSelect={() => downloadCsv(rows, columns, name)}
          >
            <Icon name="dataImport" size="md" className="mt-0.5 text-info" />
            <span className="min-w-0">
              <span className="block font-medium">CSV</span>
              <span className="block type-caption">
                For loading into another system.
              </span>
            </span>
          </DropdownMenu.Item>

          {printTarget ? (
            <>
              <DropdownMenu.Separator className="my-1.5 h-px bg-border" />
              <DropdownMenu.Item
                className={ITEM}
                onSelect={() => {
                  // Deferred past the menu's close animation: printing while a
                  // Radix portal is still mounted captures the open menu on the
                  // first page.
                  window.setTimeout(() => printElement(printTarget), 120);
                }}
              >
                <Icon name="print" size="md" className="mt-0.5 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="block font-medium">Print, or save as PDF</span>
                  <span className="block type-caption">
                    Choose "Save as PDF" as the destination.
                  </span>
                </span>
              </DropdownMenu.Item>
            </>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/* -------------------------------------------------------------------------- */
/* Printable documents                                                         */
/* -------------------------------------------------------------------------- */

/**
 * The frame every printed document shares: an invoice, a prescription, a
 * payslip, a discharge summary, a lab report.
 *
 * **A printed document is a legal artefact, not a screenshot.** Somebody hands
 * it to an insurer, files it, or carries it to another hospital, and it has to
 * say on its face who issued it, when, about whom, and — the part everybody
 * forgets — **who printed it and when**. A document with no provenance is one
 * that cannot be challenged or verified later, and in a dispute that is the
 * only question anybody asks.
 *
 * It renders normally on screen too. A print-only component is one nobody can
 * check without wasting paper, which is how printed layouts stay broken for
 * months.
 */
export function PrintableDocument({
  id,
  title,
  reference,
  organization,
  facility,
  facilityDetail,
  issuedAt,
  printedBy,
  meta,
  footer,
  children,
  className,
}: {
  /** Must be unique on the page; `printElement` targets it. */
  id: string;
  title: string;
  /** The document's own number — invoice, prescription, payslip. */
  reference?: string;
  organization: string;
  facility?: string | null;
  /** Address, licence, PAN — whatever the document must carry legally. */
  facilityDetail?: React.ReactNode;
  issuedAt?: Date | string | null;
  /** Who is printing it. The provenance line at the foot. */
  printedBy?: string;
  /** Patient, period, payer — the identity block. */
  meta?: { label: string; value: React.ReactNode }[];
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const issued = issuedAt
    ? typeof issuedAt === "string"
      ? new Date(issuedAt)
      : issuedAt
    : null;

  return (
    <article
      id={id}
      // Read by the print stylesheet, which hides everything outside it.
      data-printable
      className={cn(
        "rounded-lg border bg-card p-6 text-card-foreground print:rounded-none print:border-0 print:p-0",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-4">
        <div className="min-w-0">
          <p className="text-lg font-semibold tracking-tight">{organization}</p>
          {facility ? (
            <p className="text-sm text-muted-foreground">{facility}</p>
          ) : null}
          {facilityDetail ? (
            <div className="mt-1 type-caption">{facilityDetail}</div>
          ) : null}
        </div>
        <div className="text-right">
          <p className="type-eyebrow text-muted-foreground">{title}</p>
          {reference ? (
            <p className="mt-1 type-code text-sm font-semibold">{reference}</p>
          ) : null}
          {issued ? (
            <p className="mt-0.5 type-caption">
              {issued.toLocaleDateString(undefined, {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}{" "}
              {issued.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          ) : null}
        </div>
      </header>

      {meta && meta.length > 0 ? (
        <dl className="grid gap-x-6 gap-y-2 border-b py-4 sm:grid-cols-2 lg:grid-cols-4">
          {meta.map((entry) => (
            <div key={entry.label} className="min-w-0">
              <dt className="type-label text-muted-foreground">{entry.label}</dt>
              {/* An em dash for a missing value, never a blank: on paper a
                  blank reads as "this was left off", which on a clinical
                  document is a different claim from "not recorded". */}
              <dd className="mt-0.5 truncate text-sm">{entry.value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div className="py-4">{children}</div>

      <footer className="mt-2 border-t pt-3">
        {footer}
        <p className="mt-2 type-caption">
          {/* The provenance line. Not decoration — it is what makes the sheet
              answerable to somebody later. */}
          Printed
          {printedBy ? ` by ${printedBy}` : ""} on{" "}
          {new Date().toLocaleString(undefined, {
            day: "numeric",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
          . Generated by Nirova — this document is a record of what was in the
          system at that moment.
        </p>
      </footer>
    </article>
  );
}

/**
 * A signature block.
 *
 * Every clinical and financial document in Nepal needs one, and the ruled line
 * has to be printed rather than drawn by hand — a document where somebody has
 * to find a ruler is one that gets signed crookedly across the total.
 */
export function SignatureBlock({
  signatories,
}: {
  signatories: { role: string; name?: string | null }[];
}) {
  return (
    <div className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
      {signatories.map((signatory) => (
        <div key={signatory.role}>
          <div className="h-10" />
          <div className="border-t border-foreground/40 pt-1.5">
            <p className="text-sm font-medium">{signatory.name ?? " "}</p>
            <p className="type-caption">{signatory.role}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
