/**
 * Opening a row, described rather than written out.
 *
 * Twenty-three screens in this console are a table and nothing else: rows you
 * can read, with no way to see the thing behind one. `DetailPanel` and
 * `DetailRow` gave those screens a *shape* to fill; this gives them a way to
 * say what goes in it without each one inventing its own loading, error and
 * empty handling. Six screens had panels written by hand before this existed
 * and they had already started to diverge — which is the argument for it.
 *
 * A screen supplies a `RecordSpec`: what to call the thing, what to put in the
 * heading, and which facts belong in which section. That is usually twenty
 * lines, and the twenty-first screen behaves exactly like the first.
 *
 * **The detail fetch is the point.** Most list rows in this API are summaries
 * — an admission row carries a bed code and not the diagnosis, a payslip row
 * carries a net figure and not the lines behind it. A panel that only
 * re-displays what was already on screen is a slide-over that tells you
 * nothing. So `detailPath` fetches the fuller record when the panel opens, and
 * the spec renders whichever of the two it has: the summary immediately, the
 * detail when it arrives.
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  DetailPanel,
  DetailRow,
} from "@/components/ui/primitives";
import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/dates";
import { formatDateTime } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* The spec                                                                   */
/* -------------------------------------------------------------------------- */

/** One labelled fact. */
export interface FieldSpec<T> {
  label: string;
  /**
   * Read the value. Given the merged record — the list row with the detail
   * response layered over it, so a field present in either resolves.
   */
  value: (row: T) => React.ReactNode;
  /**
   * Hide the row entirely rather than show an em dash. For facts that do not
   * apply rather than facts that are missing: a discharge date on a patient
   * still in the ward is not an absent value, it is a question that has no
   * answer yet, and a dash invites somebody to go looking for it.
   */
  when?: (row: T) => boolean;
}

export interface SectionSpec<T> {
  heading?: string;
  fields: FieldSpec<T>[];
  /** Anything the fields cannot express — a table of lines, a chart, a note. */
  render?: (row: T) => React.ReactNode;
  when?: (row: T) => boolean;
}

export interface RecordSpec<T> {
  title: (row: T) => React.ReactNode;
  subtitle?: (row: T) => React.ReactNode;
  sections: SectionSpec<T>[];
  /**
   * Where to fetch the fuller record, if there is one. Returning `null` means
   * the list row is all there is, which is honest for screens whose API has no
   * detail route — better than inventing one and 404ing.
   */
  detailPath?: (row: T) => string | null;
  /** Buttons. Kept out of the sections so they sit in the panel's footer. */
  actions?: (row: T, reload: () => void) => React.ReactNode;
}

/* -------------------------------------------------------------------------- */
/* Formatting helpers, shared so screens stop each inventing their own        */
/* -------------------------------------------------------------------------- */

/** A date, or "" so `DetailRow` shows its em dash rather than "Invalid Date". */
export function date(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? ""
    : formatDate(parsed);
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : formatDateTime(parsed);
}

/**
 * Money, kept as the string the API sent.
 *
 * The API renders decimals as strings on purpose (`NirovaJSONRenderer`), so
 * that a rupee amount never passes through a float. Parsing it here to format
 * it would undo that in the last thirty centimetres of the journey, so this
 * only adds the separator and the symbol.
 */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value);
  const [whole, fraction] = text.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `Rs ${grouped}${fraction ? `.${fraction}` : ""}`;
}

/** A status, as a badge rather than a bare lowercase word. */
export function status(value: string | null | undefined): React.ReactNode {
  if (!value) return "";
  return <Badge variant="secondary">{value.replace(/_/g, " ")}</Badge>;
}

/** snake_case to something a person reads. */
export function words(value: string | null | undefined): string {
  return value ? value.replace(/_/g, " ") : "";
}

/* -------------------------------------------------------------------------- */
/* The panel                                                                  */
/* -------------------------------------------------------------------------- */

export function RecordPanel<T extends object>({
  row,
  spec,
  onClose,
}: {
  row: T | null;
  spec: RecordSpec<T>;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Partial<T> | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const path = row && spec.detailPath ? spec.detailPath(row) : null;

  useEffect(() => {
    setDetail(null);
    setProblem(null);
    if (!path) return;

    // A sequence guard, the same one `GlobalSearch` uses. Opening one row,
    // closing it and opening another faster than the first request returns
    // would otherwise render the first row's detail under the second row's
    // heading — which looks like a data leak and is worse than a spinner.
    let current = true;
    setLoading(true);
    api
      .get<T>(path)
      .then((full) => {
        if (current) setDetail(full);
      })
      .catch((err) => {
        if (!current) return;
        // Reported, not swallowed. The summary is still shown underneath, so
        // the panel degrades to what the list already knew rather than to a
        // blank sheet.
        setProblem(
          err instanceof ApiError
            ? err.message
            : "Could not load the full record.",
        );
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [path, nonce]);

  if (!row) {
    return (
      <DetailPanel open={false} title="" onClose={onClose}>
        {null}
      </DetailPanel>
    );
  }

  // The detail layered over the summary, so a field present in either
  // resolves and a field the detail endpoint omits keeps the list's value.
  const merged = { ...row, ...(detail ?? {}) } as T;
  const reload = () => setNonce((n) => n + 1);

  return (
    <DetailPanel
      open
      title={spec.title(merged)}
      subtitle={spec.subtitle?.(merged)}
      onClose={onClose}
      footer={spec.actions?.(merged, reload)}
    >
      {problem && (
        <Alert variant="warning" className="mb-4">
          <AlertTitle>Showing what the list knew</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {loading && !detail && (
        <p className="pb-4 text-center text-sm text-muted-foreground">
          <Loader2 className="inline h-4 w-4 animate-spin" />
        </p>
      )}

      <div className="space-y-6">
        {spec.sections.map((section, index) => {
          if (section.when && !section.when(merged)) return null;
          const fields = section.fields.filter(
            (field) => !field.when || field.when(merged),
          );
          const extra = section.render?.(merged);
          if (fields.length === 0 && !extra) return null;
          return (
            <section key={section.heading ?? index}>
              {section.heading && (
                <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {section.heading}
                </h3>
              )}
              {fields.map((field) => (
                <DetailRow key={field.label} label={field.label}>
                  {field.value(merged)}
                </DetailRow>
              ))}
              {extra}
            </section>
          );
        })}
      </div>
    </DetailPanel>
  );
}

/* -------------------------------------------------------------------------- */
/* The hook                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The three lines every screen would otherwise repeat.
 *
 * Returns the selected row, a setter to pass to `onClick`, and the props for
 * the panel. Keeping it a hook rather than asking each screen to hold the
 * state means "click a row, see the row" is one import and cannot be wired up
 * subtly differently on the twelfth screen.
 */
export function useRecordPanel<T extends object>() {
  const [open, setOpen] = useState<T | null>(null);
  return {
    open,
    show: setOpen,
    close: () => setOpen(null),
    /**
     * Spread onto a `TableRow`. The extra class is merged rather than
     * replaced, because several tables already colour a row by its state --
     * an emergency token, an overdue invoice -- and losing that to gain a
     * cursor would be a bad trade.
     */
    rowProps: (row: T, className?: string) => ({
      onClick: () => setOpen(row),
      className: cn("cursor-pointer", className),
    }),
    /**
     * Spread onto the cell holding row actions. Without it, clicking "Start"
     * also opens the panel behind the click -- the button does its job and
     * the reader is left looking at a slide-over they did not ask for.
     */
    stopProps: {
      onClick: (event: React.MouseEvent) => event.stopPropagation(),
    },
  };
}
