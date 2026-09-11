/**
 * Getting data out — the half of a hospital system that decides whether people
 * trust it.
 *
 * **Every list in this product was a dead end.** A ward sister who needs the
 * bed state for a handover meeting, an accountant reconciling against a bank
 * statement, an auditor asked for last quarter's dispensing — all of them had
 * one option, which was to read the screen and retype it. A system you cannot
 * get data out of is one people keep a spreadsheet beside, and the spreadsheet
 * becomes the record.
 *
 * Three formats, and the choice between them is not arbitrary:
 *
 * | Format | For | Why not the others |
 * |---|---|---|
 * | **CSV** | anything going into another system | universal, diffable, no library |
 * | **Excel** | anything a person will open and sort | CSV with a BOM and CRLF — Excel mangles UTF-8 without it |
 * | **Print / PDF** | anything with a signature line | the browser's own engine; see below |
 *
 * **There is deliberately no PDF library here.** `jsPDF` and friends are
 * 300-800 kB, cannot lay out a table without being told every coordinate, and
 * produce documents that look nothing like the screen. The browser has a
 * typesetting engine that already knows the layout, honours the print
 * stylesheet, and writes PDF — so "Print" opens it and the operator chooses
 * "Save as PDF", which is what every hospital system that prints anything
 * actually does. The cost is one extra keystroke; the saving is not shipping a
 * second rendering engine that disagrees with the first.
 */

/* -------------------------------------------------------------------------- */
/* CSV                                                                         */
/* -------------------------------------------------------------------------- */

/**
 * Quote a value for CSV.
 *
 * **The leading-character guard is the one that matters and it is not about
 * formatting.** A cell beginning `=`, `+`, `-` or `@` is executed as a formula
 * when the file is opened in Excel or Sheets — so a patient whose name was
 * entered as `=cmd|...` becomes remote code execution on the machine of
 * whoever opens the export. It is a real, catalogued vulnerability (CSV
 * injection), it is trivially reachable in a product where users type into
 * every field, and the fix is one apostrophe.
 */
function cell(value: unknown): string {
  if (value === null || value === undefined) return "";

  let text = String(value);

  // Formula injection. The apostrophe is stripped by the spreadsheet on
  // display, so the cell still reads correctly to a human.
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;

  // A field containing a delimiter, a quote or a newline must be quoted, and
  // an embedded quote doubled. Doing this unconditionally would be simpler and
  // makes every file noisier to read in a terminal.
  if (/[",\n\r]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;

  return text;
}

export interface ExportColumn<T> {
  key: string;
  header: string;
  /** The value as data, not as markup. */
  value: (row: T) => unknown;
}

export function toCsv<T>(rows: T[], columns: ExportColumn<T>[]): string {
  const lines = [columns.map((column) => cell(column.header)).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => cell(column.value(row))).join(","));
  }
  // CRLF, because Excel on Windows treats a lone LF inside a quoted field as
  // the end of the record and splits the row.
  return lines.join("\r\n");
}

/* -------------------------------------------------------------------------- */
/* Saving                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Hand a generated file to the browser.
 *
 * Object URL rather than a `data:` URI: Chrome caps `data:` navigations at
 * about 2 MB and a year of dispensing lines is comfortably past that. The URL
 * is revoked on the next tick — the browser has taken its own reference by the
 * time `click()` returns, and holding it leaks the blob for the session.
 */
function save(content: BlobPart, filename: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** A filename that sorts chronologically and is safe on every filesystem. */
export function exportFilename(base: string, extension: string): string {
  const stamp = new Date()
    .toISOString()
    .slice(0, 16)
    .replace("T", "-")
    .replace(":", "");
  const safe = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${safe || "export"}-${stamp}.${extension}`;
}

export function downloadCsv<T>(
  rows: T[],
  columns: ExportColumn<T>[],
  name: string,
): void {
  save(toCsv(rows, columns), exportFilename(name, "csv"), "text/csv;charset=utf-8");
}

/**
 * The same data, opened correctly by Excel.
 *
 * **The BOM is the whole difference and it is not optional.** Excel reads a
 * CSV without one as the system codepage, so on a Nepali or Windows-1252
 * machine every Devanagari name, every accented character and the rupee sign
 * arrive as mojibake. Users then conclude the *system* stored the name wrong.
 * Three bytes fix it, and every other reader ignores them.
 */
export function downloadExcel<T>(
  rows: T[],
  columns: ExportColumn<T>[],
  name: string,
): void {
  save(
    "﻿" + toCsv(rows, columns),
    exportFilename(name, "csv"),
    "text/csv;charset=utf-8",
  );
}

/* -------------------------------------------------------------------------- */
/* Printing                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Print the element with this id, and nothing else.
 *
 * **Not a new window.** Opening one and copying the markup into it loses every
 * stylesheet, so the printable has to be re-styled inline — which is how a
 * printed invoice ends up looking nothing like the invoice on screen. Instead
 * the document sets `data-printing` with the target's id, and the print
 * stylesheet in `index.css` hides everything that is not inside it. The layout
 * is the same layout, because it *is* the same element.
 *
 * The attribute is cleared on `afterprint` **and** on a timer. Safari does not
 * fire `afterprint` when the user cancels the dialog, and an application stuck
 * in print mode with its navigation hidden is unrecoverable without a reload.
 */
export function printElement(id: string): void {
  const root = document.documentElement;
  root.dataset.printing = id;

  const clear = () => {
    delete root.dataset.printing;
    window.removeEventListener("afterprint", clear);
  };
  window.addEventListener("afterprint", clear);
  window.setTimeout(clear, 60_000);

  // A frame's delay so the attribute has been applied and the layout recalculated
  // before the dialog snapshots the page. Without it, Chrome occasionally
  // prints the pre-attribute layout — the whole application, once.
  window.requestAnimationFrame(() => window.print());
}
