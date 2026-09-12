/**
 * Real Excel workbooks.
 *
 * The "Excel" export used to be a CSV with a byte-order mark: it opened in
 * Excel, but every number was text, every column a default width, there was
 * no header row to freeze and no room for a second sheet — so a finance export
 * arrived as something to be tidied before anybody could use it. This writes
 * `.xlsx`: a title and the period at the top, who generated it and when, a bold
 * frozen header, numbers as numbers in the formats an accountant expects,
 * columns sized to their content, a totals row, and as many sheets as the
 * report has parts.
 *
 * `write-excel-file` is loaded only when somebody exports — it has no business
 * in the bundle every page load pays for.
 *
 * **Formula injection does not arise here** as it does for CSV: every text
 * value is written as a typed string cell, which Excel never evaluates.
 */

export type XlsxKind = "text" | "number" | "integer" | "money" | "percent" | "date";

export interface XlsxColumn {
  header: string;
  kind?: XlsxKind;
  /** Characters; estimated from the content when omitted. */
  width?: number;
}

export type XlsxValue = string | number | Date | null | undefined;

export interface XlsxSheet {
  /** The tab name. Excel allows 31 characters and no `[]:*?/\`. */
  name: string;
  title: string;
  /** Period, facility — one line under the title. */
  subtitle?: string;
  columns: XlsxColumn[];
  rows: XlsxValue[][];
  /** A bold last row, e.g. ["Total", null, 1200.5]. */
  totals?: XlsxValue[];
}

const FORMATS: Partial<Record<XlsxKind, string>> = {
  number: "#,##0.###",
  integer: "#,##0",
  money: "#,##0.00",
  percent: '0.0"%"',
  date: "dd mmm yyyy",
};

/** Decimal strings from the API ("1250.00") become numbers; digit-only
 *  strings (batch numbers, references) stay text so leading zeros survive. */
function coerce(value: XlsxValue, kind: XlsxKind | undefined): XlsxValue {
  if (value === null || value === undefined || value === "") return null;
  if (kind === "date") {
    if (value instanceof Date) return value;
    const parsed = new Date(String(value));
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed;
  }
  if (typeof value === "string" && kind && kind !== "text" && /^-?\d+(\.\d+)?$/.test(value)) {
    return Number(value);
  }
  if (typeof value === "string" && !kind && /^-?\d+\.\d+$/.test(value)) return Number(value);
  return value;
}

function cell(value: XlsxValue, kind: XlsxKind | undefined, extra: Record<string, unknown> = {}) {
  const coerced = coerce(value, kind);
  if (coerced === null || coerced === undefined) return null;
  if (coerced instanceof Date) return { value: coerced, type: Date, format: FORMATS.date, ...extra };
  if (typeof coerced === "number") {
    return { value: coerced, type: Number, format: FORMATS[kind ?? "number"] ?? FORMATS.number, ...extra };
  }
  return { value: String(coerced), type: String, ...extra };
}

function widthOf(column: XlsxColumn, rows: XlsxValue[][], index: number): number {
  if (column.width) return column.width;
  const longest = rows.slice(0, 200).reduce((max, row) => {
    const value = row[index];
    const text = value instanceof Date ? "00 Mmm 0000" : String(value ?? "");
    return Math.max(max, text.length);
  }, column.header.length);
  return Math.min(Math.max(longest + 2, 8), 60);
}

export async function downloadWorkbook(
  fileName: string,
  sheets: XlsxSheet[],
  meta: { organization?: string; generatedBy?: string } = {},
): Promise<void> {
  const { default: writeXlsxFile } = await import("write-excel-file/browser");
  const stamp = new Date().toLocaleString("en-GB", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });

  const built = sheets.map((sheet) => {
    const provenance = [meta.organization, `Generated ${stamp}`, meta.generatedBy ? `by ${meta.generatedBy}` : ""]
      .filter(Boolean)
      .join(" · ");
    const data: unknown[][] = [
      [{ value: sheet.title, type: String, fontWeight: "bold", fontSize: 14 }],
      [{ value: [sheet.subtitle, provenance].filter(Boolean).join("   ·   "), type: String, color: "#666666" }],
      [],
      sheet.columns.map((column) => ({
        value: column.header,
        type: String,
        fontWeight: "bold",
        backgroundColor: "#E8F0EE",
        align: column.kind && column.kind !== "text" ? "right" : "left",
        wrap: true,
      })),
      ...sheet.rows.map((row) => sheet.columns.map((column, index) => cell(row[index], column.kind))),
    ];
    if (sheet.totals) {
      data.push(
        sheet.columns.map((column, index) =>
          cell(sheet.totals![index], column.kind, { fontWeight: "bold", topBorderStyle: "thin" }),
        ),
      );
    }
    return {
      data,
      sheet: sheet.name.replace(/[[\]:*?/\\]/g, " ").slice(0, 31),
      columns: sheet.columns.map((column, index) => ({ width: widthOf(column, sheet.rows, index) })),
      stickyRowsCount: 4,
    };
  });

  // The library's types describe cells precisely; the shapes above are those
  // cells, built dynamically.
  await (writeXlsxFile as unknown as (sheets: unknown[]) => { toFile: (name: string) => Promise<void> })(built).toFile(
    fileName.endsWith(".xlsx") ? fileName : `${fileName}.xlsx`,
  );
}

/** One sheet from a list's export columns — what `ExportMenu` offers. */
export async function downloadListAsWorkbook<T>(
  rows: T[],
  columns: { header: string; value: (row: T) => unknown }[],
  title: string,
  fileName: string,
): Promise<void> {
  await downloadWorkbook(fileName, [
    {
      name: title,
      title,
      columns: columns.map((column) => ({ header: column.header })),
      rows: rows.map((row) =>
        columns.map((column) => {
          const value = column.value(row);
          if (value === null || value === undefined) return null;
          if (typeof value === "number" || value instanceof Date) return value;
          return String(value);
        }),
      ),
    },
  ]);
}
