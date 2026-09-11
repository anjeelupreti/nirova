/**
 * One list, three shapes: table, cards, board.
 *
 * **"No card view, no proper views of lists" was the complaint, and it was
 * exactly right — every list in this product is a `<Table>`.** 34 of 44 screens
 * render one directly. A table is the correct shape for a general ledger and
 * the wrong one for a set of people, a rack of products, or a queue of claims
 * moving between states, and having only one shape is why the console reads as
 * a database browser.
 *
 * **`SegmentedControl` — the exact control this needs — has existed in
 * `data.tsx` since it was written and is used by nothing.** It is used here.
 *
 * The point of doing it once rather than 34 times is not the saving. It is
 * that the *choice* is remembered per person per screen, that every list gains
 * a search and an empty state and a skeleton whether or not its author thought
 * about them, and that a screen which wants a board only has to say which
 * column a row belongs in.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Icon, type IconName } from "@/components/ui/icon";
import { EmptyState, Skeleton, TableSkeleton } from "@/components/ui/feedback";
import { Input } from "@/components/ui/primitives";
import { SegmentedControl } from "@/components/ui/data";
import { ExportMenu } from "@/components/ui/export";
import type { ExportColumn } from "@/lib/export";

/* -------------------------------------------------------------------------- */
/* Column and view descriptors                                                 */
/* -------------------------------------------------------------------------- */

export interface Column<T> {
  /** Stable identity — used by the column chooser and the stored preference. */
  key: string;
  header: React.ReactNode;
  /** How the cell renders. Given the whole row, not just a field. */
  cell: (row: T) => React.ReactNode;
  align?: "left" | "right";
  /** Hidden below `md`. For a column that is context rather than content. */
  secondary?: boolean;
  /** Numbers get tabular figures and right alignment without being asked. */
  numeric?: boolean;
  /** A plain string for searching and sorting, when the cell is markup. */
  value?: (row: T) => string | number | null;
  sortable?: boolean;
}

export type ViewMode = "table" | "cards" | "board";

export interface CardSpec<T> {
  title: (row: T) => React.ReactNode;
  subtitle?: (row: T) => React.ReactNode;
  /** Up to four label/value pairs shown in the card's body. */
  facts?: (row: T) => { label: string; value: React.ReactNode }[];
  /** The badge in the card's top-right — usually a `StatusBadge`. */
  badge?: (row: T) => React.ReactNode;
  /** A leading avatar or icon tile. */
  media?: (row: T) => React.ReactNode;
  accent?: (row: T) => string | undefined;
}

export interface BoardSpec<T> {
  /** Which column a row belongs in. */
  columnOf: (row: T) => string;
  /** The columns, in order. A column with no rows still renders — an absent
   *  "Rejected" column reads as a missing feature, not as good news. */
  columns: { id: string; label: string; tone?: string }[];
  card: CardSpec<T>;
}

/* -------------------------------------------------------------------------- */
/* Persisted view preference                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Which shape this person last used for *this* list.
 *
 * Per screen, not global: somebody who wants the patient list as cards almost
 * certainly still wants the ledger as a table, and a single global setting
 * would make the feature useless to both.
 */
function useViewMode(storageKey: string, available: ViewMode[], initial?: ViewMode) {
  const [mode, setMode] = React.useState<ViewMode>(() => {
    try {
      const stored = window.localStorage.getItem(`nirova.view.${storageKey}`);
      if (stored && available.includes(stored as ViewMode)) return stored as ViewMode;
    } catch {
      /* A locked-down profile throws rather than returning null. */
    }
    return initial ?? available[0];
  });

  const change = React.useCallback(
    (next: ViewMode) => {
      setMode(next);
      try {
        window.localStorage.setItem(`nirova.view.${storageKey}`, next);
      } catch {
        /* Not worth surfacing. */
      }
    },
    [storageKey],
  );

  return [mode, change] as const;
}

/* -------------------------------------------------------------------------- */
/* DataView                                                                    */
/* -------------------------------------------------------------------------- */

export interface DataViewProps<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  /** Namespaces the remembered view mode and column choices. */
  storageKey: string;
  card?: CardSpec<T>;
  board?: BoardSpec<T>;
  onOpen?: (row: T) => void;
  loading?: boolean;
  /** Shown when `rows` is empty *and* nothing is filtered out. */
  empty?: { title: string; description?: string; action?: React.ReactNode; icon?: IconName };
  search?: { placeholder?: string; enabled?: boolean };
  /** Controls that belong above the list: filters, a date range, an action. */
  toolbar?: React.ReactNode;
  initialView?: ViewMode;
  /**
   * Turn export off for a list where it would be wrong.
   *
   * **On by default**, deliberately. Every list in this product was a dead
   * end — a ward sister who needs the bed state for a handover, an accountant
   * reconciling against a bank statement, an auditor asked for last quarter's
   * dispensing — and a system you cannot get data out of is one people keep a
   * spreadsheet beside, until the spreadsheet becomes the record.
   *
   * The reason to switch it off is a permission one: a list somebody may read
   * on screen but may not carry out of the building. That is a real category
   * and it needs saying out loud rather than being the accidental default.
   */
  exportable?: boolean;
  className?: string;
}

export function DataView<T>({
  rows,
  columns,
  rowKey,
  storageKey,
  card,
  board,
  onOpen,
  loading,
  empty,
  search = { enabled: true },
  toolbar,
  initialView,
  exportable = true,
  className,
}: DataViewProps<T>) {
  const available: ViewMode[] = [
    "table",
    ...(card ? (["cards"] as const) : []),
    ...(board ? (["board"] as const) : []),
  ];
  const [mode, setMode] = useViewMode(storageKey, available, initialView);
  const [term, setTerm] = React.useState("");
  const [sort, setSort] = React.useState<{ key: string; direction: "asc" | "desc" } | null>(null);

  /*
    Search over the columns' own `value` accessors rather than over the
    rendered cells. A cell is markup — a badge, an avatar, a link — and
    searching its text either does not work or matches the word "Approved"
    inside an SVG title. `value` is the column author saying what the cell
    *means*, which is also what sorting needs.
  */
  const filtered = React.useMemo(() => {
    if (!term.trim()) return rows;
    const needle = term.trim().toLowerCase();
    return rows.filter((row) =>
      columns.some((column) => {
        const value = column.value?.(row);
        return value != null && String(value).toLowerCase().includes(needle);
      }),
    );
  }, [rows, columns, term]);

  const sorted = React.useMemo(() => {
    if (!sort) return filtered;
    const column = columns.find((entry) => entry.key === sort.key);
    if (!column?.value) return filtered;
    const direction = sort.direction === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const left = column.value?.(a);
      const right = column.value?.(b);
      // Nulls sort last in both directions. A missing value is not "smallest";
      // it is absent, and burying it at the top of a descending sort makes a
      // list of ninety look like a list of six.
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * direction;
      }
      return String(left).localeCompare(String(right)) * direction;
    });
  }, [filtered, columns, sort]);

  /*
    The export columns, from the ones already declared.

    Only columns with a `value` accessor: that is the column author saying
    what the cell *means* as data, as opposed to what it renders as. A column
    whose cell is an avatar and a badge has no sensible CSV form, and guessing
    one — stringifying the React element — produces "[object Object]" in a file
    somebody sends to an insurer.
  */
  const exportColumns = React.useMemo<ExportColumn<T>[]>(
    () =>
      columns
        .filter((column) => Boolean(column.value))
        .map((column) => ({
          key: column.key,
          header: typeof column.header === "string" ? column.header : column.key,
          value: (row: T) => column.value?.(row) ?? "",
        })),
    [columns],
  );

  const filteredAway = rows.length > 0 && sorted.length === 0;

  return (
    <div className={cn("space-y-3", className)}>
      {(search.enabled !== false || toolbar || available.length > 1) && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {search.enabled !== false ? (
              <div className="relative w-full sm:w-64">
                <Icon
                  name="search"
                  size="sm"
                  className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  value={term}
                  onChange={(event) => setTerm(event.target.value)}
                  placeholder={search.placeholder ?? "Search this list"}
                  className="pl-8"
                />
                {term ? (
                  <button
                    type="button"
                    onClick={() => setTerm("")}
                    aria-label="Clear the search"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                  >
                    <Icon name="close" size="sm" />
                  </button>
                ) : null}
              </div>
            ) : null}
            {toolbar}
          </div>

          <div className="flex shrink-0 items-center gap-3">
            {/* The count, always. "Showing 12 of 340" is the difference between
                a filtered list and a short one, and a list that does not say
                which reads as data loss. */}
            <span className="type-caption tabular-nums">
              {term && sorted.length !== rows.length
                ? `${sorted.length} of ${rows.length}`
                : `${rows.length}`}
            </span>
            {exportable ? (
              <ExportMenu
                // The **sorted, filtered** rows — not `rows`. An export that
                // silently returns everything while the screen shows a subset
                // is the sort of file somebody reconciles a bank statement
                // against and cannot work out why the totals differ.
                rows={sorted}
                columns={exportColumns}
                name={storageKey}
                note={
                  term && sorted.length !== rows.length
                    ? `Filtered to "${term}" — ${rows.length - sorted.length} rows excluded.`
                    : undefined
                }
              />
            ) : null}
            {available.length > 1 ? (
              <SegmentedControl
                value={mode}
                onChange={(next) => setMode(next)}
                options={available.map((value) => ({
                  value,
                  label:
                    value === "table" ? "Table" : value === "cards" ? "Cards" : "Board",
                }))}
              />
            ) : null}
          </div>
        </div>
      )}

      {loading ? (
        mode === "table" ? (
          <TableSkeleton rows={6} columns={Math.min(columns.length, 5)} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-32 rounded-lg" />
            ))}
          </div>
        )
      ) : filteredAway ? (
        <EmptyState
          title="Nothing matches that"
          description={`No row in this list contains “${term}”. Clearing the search brings back all ${rows.length}.`}
        />
      ) : sorted.length === 0 ? (
        <EmptyState
          title={empty?.title ?? "Nothing here yet"}
          description={empty?.description}
          action={empty?.action}
        />
      ) : mode === "table" ? (
        <TableView
          rows={sorted}
          columns={columns}
          rowKey={rowKey}
          onOpen={onOpen}
          sort={sort}
          onSort={setSort}
        />
      ) : mode === "cards" && card ? (
        <CardsView rows={sorted} rowKey={rowKey} spec={card} onOpen={onOpen} />
      ) : board ? (
        <BoardView rows={sorted} rowKey={rowKey} spec={board} onOpen={onOpen} />
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Table                                                                       */
/* -------------------------------------------------------------------------- */

function TableView<T>({
  rows,
  columns,
  rowKey,
  onOpen,
  sort,
  onSort,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  sort: { key: string; direction: "asc" | "desc" } | null;
  onSort: (next: { key: string; direction: "asc" | "desc" } | null) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        {/* The header sticks. On a list of two hundred rows, scrolling past the
            header means every column becomes unlabelled — which is when people
            start reading the wrong figure. */}
        <thead className="sticky top-0 z-10 bg-card">
          <tr className="border-b border-border-strong">
            {columns.map((column) => {
              const active = sort?.key === column.key;
              const sortable = column.sortable !== false && Boolean(column.value);
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={cn(
                    "row-density text-left type-label text-muted-foreground",
                    (column.align === "right" || column.numeric) && "text-right",
                    column.secondary && "hidden md:table-cell",
                  )}
                >
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() =>
                        onSort(
                          active && sort?.direction === "asc"
                            ? { key: column.key, direction: "desc" }
                            : active && sort?.direction === "desc"
                              ? null
                              : { key: column.key, direction: "asc" },
                        )
                      }
                      className={cn(
                        "inline-flex items-center gap-1 rounded-sm transition-colors duration-quick hover:text-foreground",
                        active && "text-foreground",
                        (column.align === "right" || column.numeric) && "flex-row-reverse",
                      )}
                    >
                      {column.header}
                      <Icon
                        name={
                          active
                            ? sort?.direction === "asc"
                              ? "riseSmall"
                              : "fallSmall"
                            : "chevronUpDown"
                        }
                        size="xs"
                        className={cn(!active && "opacity-40")}
                      />
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onOpen ? () => onOpen(row) : undefined}
              className={cn(
                "border-b last:border-0",
                onOpen &&
                  "cursor-pointer transition-colors duration-quick hover:bg-accent/50",
              )}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    "row-density align-middle",
                    (column.align === "right" || column.numeric) && "text-right",
                    column.numeric && "tabular-nums",
                    column.secondary && "hidden md:table-cell",
                  )}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Cards                                                                       */
/* -------------------------------------------------------------------------- */

function RowCard<T>({
  row,
  spec,
  onOpen,
}: {
  row: T;
  spec: CardSpec<T>;
  onOpen?: (row: T) => void;
}) {
  const accent = spec.accent?.(row);
  const facts = spec.facts?.(row) ?? [];
  const Element = onOpen ? "button" : "div";

  return (
    <Element
      type={onOpen ? "button" : undefined}
      onClick={onOpen ? () => onOpen(row) : undefined}
      className={cn(
        "relative flex w-full flex-col gap-3 overflow-hidden rounded-lg border bg-card p-4 text-left shadow-raised",
        onOpen &&
          "transition-colors duration-quick ease-smooth hover:border-border-strong hover:bg-accent/30",
      )}
    >
      {/* A 3px spine rather than a tinted card. Twelve saturated cards is a
          stained-glass window and the text on top stops being readable. */}
      {accent ? (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-[3px]"
          style={{ background: accent }}
        />
      ) : null}

      <div className="flex items-start gap-3">
        {spec.media?.(row)}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{spec.title(row)}</p>
          {spec.subtitle ? (
            <p className="truncate type-caption">{spec.subtitle(row)}</p>
          ) : null}
        </div>
        {spec.badge?.(row)}
      </div>

      {facts.length > 0 ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t pt-3">
          {facts.slice(0, 4).map((fact) => (
            <div key={fact.label} className="min-w-0">
              <dt className="truncate type-label text-muted-foreground">{fact.label}</dt>
              {/* An em dash for a missing value, never a blank — blank reads as
                  "failed to load", which is the same rule `DetailRow` follows. */}
              <dd className="truncate text-sm tabular-nums">{fact.value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </Element>
  );
}

function CardsView<T>({
  rows,
  rowKey,
  spec,
  onOpen,
}: {
  rows: T[];
  rowKey: (row: T) => string;
  spec: CardSpec<T>;
  onOpen?: (row: T) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((row) => (
        <RowCard key={rowKey(row)} row={row} spec={spec} onOpen={onOpen} />
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Board                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Rows grouped into columns by their state.
 *
 * The right shape for anything that *moves*: a claim from submitted to
 * settled, a purchase requisition to receipt, a patient through triage. The
 * question a board answers and a table cannot is "where is the pile", and in a
 * revenue-cycle review that is the entire meeting.
 *
 * Read-only. Dragging a claim from "Denied" to "Settled" would be a state
 * transition with maker-checker rules behind it, and a board that performs one
 * silently is the same mistake as approving a payroll run from a summary.
 */
function BoardView<T>({
  rows,
  rowKey,
  spec,
  onOpen,
}: {
  rows: T[];
  rowKey: (row: T) => string;
  spec: BoardSpec<T>;
  onOpen?: (row: T) => void;
}) {
  const grouped = React.useMemo(() => {
    const map = new Map<string, T[]>();
    for (const column of spec.columns) map.set(column.id, []);
    for (const row of rows) {
      const id = spec.columnOf(row);
      map.set(id, [...(map.get(id) ?? []), row]);
    }
    return map;
  }, [rows, spec]);

  return (
    <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
      {spec.columns.map((column) => {
        const items = grouped.get(column.id) ?? [];
        return (
          <div
            key={column.id}
            className="flex w-72 shrink-0 flex-col gap-2 rounded-lg bg-muted/40 p-2"
          >
            <div className="flex items-center justify-between gap-2 px-1 py-1">
              <span className="flex min-w-0 items-center gap-1.5">
                {column.tone ? (
                  <span
                    aria-hidden
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: column.tone }}
                  />
                ) : null}
                <span className="truncate type-eyebrow text-muted-foreground">
                  {column.label}
                </span>
              </span>
              <span className="shrink-0 rounded-full bg-card px-1.5 py-px text-[0.625rem] font-semibold tabular-nums">
                {items.length}
              </span>
            </div>
            <div className="flex flex-col gap-2">
              {items.length === 0 ? (
                <p className="rounded-md border border-dashed px-2 py-4 text-center type-caption">
                  Nothing here
                </p>
              ) : (
                items.map((row) => (
                  <RowCard key={rowKey(row)} row={row} spec={spec.card} onOpen={onOpen} />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
