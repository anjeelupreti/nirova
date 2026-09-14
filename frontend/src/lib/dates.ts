/**
 * Every date the console writes, in the calendar the reader chose.
 *
 * Nepal runs on Bikram Sambat. A patient asks for an appointment in Ashoj; a
 * ward sister writes the round in BS in the paper register; a ministry return
 * is filed in BS. The console showed Gregorian everywhere and claimed
 * otherwise on its own sign-in page — which is how a product for Nepali
 * hospitals ends up needing a conversion table on the wall beside it.
 *
 * **The calendar is a preference, not a locale.** English with BS dates is a
 * perfectly ordinary combination here — most hospital staff read English and
 * write dates in BS — so this is independent of language, and the preference
 * lives beside theme and density.
 *
 * **Bikram Sambat comes from a maintained library**, not a table typed here.
 * BS month lengths are not computable: they are published year by year, and a
 * hand-copied table in a clinical system is a way to record the wrong day.
 * `nepali-date-converter` is the same library the patient app uses, and it was
 * checked against the known new-year dates (1 Baishakh 2081, 2082, 2083).
 *
 * **Read from the document, not from React.** A date is formatted inside chart
 * tooltips, printable documents and Excel exports, none of which have a
 * component to take context from. `usePreferences` writes the choice onto
 * `<html data-calendar>` and this reads it there — one source, no prop
 * threading, and a preference change repaints because the components that show
 * dates re-render with it.
 *
 * **What stays Gregorian.** Times of day, durations and anything a machine
 * reads back — an ISO string in a query, a `type="date"` input. And documents
 * that leave the building carry both (`withGregorian`), because an insurer's
 * clerk and a tax inspector read different calendars from the same page.
 */

import NepaliDate from "nepali-date-converter";

export type Calendar = "gregorian" | "bikram_sambat";

/** The active calendar, as the document has it. Gregorian until told otherwise. */
export function activeCalendar(): Calendar {
  if (typeof document === "undefined") return "gregorian";
  return document.documentElement.dataset.calendar === "bikram_sambat"
    ? "bikram_sambat"
    : "gregorian";
}

export function asDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * A Bikram Sambat date, or `null` when it is outside the library's range.
 *
 * The range matters: BS conversion is table-driven and the tables stop. A
 * date of birth in 1935 or a licence expiring in 2100 falls off the end, and
 * the honest answer is to show the Gregorian date rather than a guess.
 */
function bs(date: Date): NepaliDate | null {
  try {
    return new NepaliDate(date);
  } catch {
    return null;
  }
}

/** "12 Sept 2026", or "२७ भाद्र २०८३". */
export function formatDate(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "—";
  if (activeCalendar() === "bikram_sambat") {
    const nepali = bs(date);
    if (nepali) return nepali.format("DD MMMM YYYY", "np");
  }
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** Without the year, for a date inside the current one: "12 Sept" / "२७ भाद्र". */
export function formatDayMonth(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "—";
  if (activeCalendar() === "bikram_sambat") {
    const nepali = bs(date);
    if (nepali) return nepali.format("DD MMMM", "np");
  }
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** The weekday too: "Sat 12 Sept" / "शनि, २७ भाद्र". */
export function formatWeekday(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "—";
  if (activeCalendar() === "bikram_sambat") {
    const nepali = bs(date);
    if (nepali) return nepali.format("ddd, DD MMMM", "np");
  }
  return date.toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short",
  });
}

/** The clock, always 24-hour and always Gregorian — a time has no calendar. */
export function formatTime(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "—";
  return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** "12 Sept 2026, 15:04" / "२७ भाद्र २०८३, १५:०४" — the date converts, the clock does not. */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "—";
  return `${formatDate(date)}, ${formatTime(date)}`;
}

/**
 * Both calendars, for anything that leaves the building.
 *
 * An invoice, a discharge summary, a laboratory report: the hospital files it
 * in BS, an insurer's system reads AD, and a page that carries only one of
 * them makes somebody convert by hand — which is where the transcription
 * errors come from.
 */
export function withGregorian(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "—";
  if (activeCalendar() !== "bikram_sambat") return formatDate(date);
  const nepali = bs(date);
  if (!nepali) return formatDate(date);
  const gregorian = date.toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric",
  });
  return `${nepali.format("DD MMMM YYYY", "np")} (${gregorian})`;
}

/** The BS year a date falls in — "2083" — for a heading or a filename. */
export function bikramYear(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "";
  const nepali = bs(date);
  return nepali ? String(nepali.getYear()) : "";
}

/**
 * What a `type="date"` input needs: `YYYY-MM-DD`, always Gregorian.
 *
 * Never converted. The browser's own date control speaks Gregorian ISO, and
 * so does every filter this feeds; a BS string here would be rejected by the
 * control and sent to the API as a date 57 years out.
 */
export function isoDate(value: string | number | Date | null | undefined): string {
  const date = asDate(value);
  if (date === null) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}
