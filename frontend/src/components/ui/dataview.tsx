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
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

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

/**
 * A facet the reader can narrow the list by.
 *
 * The screen says which field a facet reads and, optionally, the order its
 * values should appear in; everything else — the options, their counts, the
 * cross-filtering — is derived from the rows themselves. A filter that has to
 * be told its own options goes stale the first time somebody adds a
 * department, and a list whose filter offers a value that matches nothing is
 * worse than a list with no filter.
 */
export interface FilterSpec<T> {
  key: string;
  label: string;
  /** The row's value(s) for this facet. An array means a row can match many. */
  value: (row: T) => string | string[] | null | undefined;
  /** Fixed options, when the order or the wording matters (a severity ladder,
   *  a status the customer knows by a different name). Omit to derive them. */
  options?: { value: string; label: string }[];
  icon?: IconName;
}

/**
 * Something the reader can do to one row without leaving the list.
 *
 * **The complaint this answers is "not much actions available for items".** A
 * list where every row does exactly one thing — open — forces a round trip
 * through a detail page to cancel an appointment or reprint a receipt, and
 * people stop using the list.
 */
export interface RowAction {
  label: string;
  icon?: IconName;
  onSelect: () => void;
  /** Destructive or irreversible: rendered in the danger colour, last. */
  danger?: boolean;
  disabled?: boolean;
  /** Why it is unavailable. Shown as the item's title when disabled. */
  reason?: string;
}

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

/** How many rows this person wants at a time, on this screen. */
function usePageSize(storageKey: string, fallback: number) {
  const [size, setSize] = React.useState<number>(() => {
    try {
      const stored = window.localStorage.getItem(`nirova.rows.${storageKey}`);
      const parsed = stored ? Number(stored) : NaN;
      if (PAGE_SIZES.includes(parsed)) return parsed;
    } catch {
      /* A locked-down profile throws rather than returning null. */
    }
    return fallback;
  });

  const change = React.useCallback(
    (next: number) => {
      setSize(next);
      try {
        window.localStorage.setItem(`nirova.rows.${storageKey}`, String(next));
      } catch {
        /* Not worth surfacing. */
      }
    },
    [storageKey],
  );

  return [size, change] as const;
}

/** `0` is "all of them" — the option somebody printing a handover needs. */
const PAGE_SIZES = [25, 50, 100, 0];

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
  /** Facets shown as narrowing menus above the list. */
  filters?: FilterSpec<T>[];
  /**
   * What the reader can do to a single row.
   *
   * A function of the row, not a fixed list: whether an invoice can be
   * cancelled depends on the invoice. Return an action with `disabled` and a
   * `reason` rather than omitting it — a menu whose contents change shape row
   * by row is one people stop trusting.
   */
  actions?: (row: T) => RowAction[];
  /**
   * Rows per page. `0` shows every row.
   *
   * On by default at 50. Two hundred rows in one scroll is not a feature: it
   * is why people say a screen "hangs", and it is how a row gets missed.
   */
  pageSize?: number;
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
  filters,
  actions,
  pageSize = 50,
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
  const [chosen, setChosen] = React.useState<Record<string, string[]>>({});
  const [size, setSize] = usePageSize(storageKey, pageSize);
  const [page, setPage] = React.useState(1);

  const facets = React.useMemo(() => filters ?? [], [filters]);
  const activeCount = Object.values(chosen).reduce((sum, list) => sum + list.length, 0);

  /*
    Search over the columns' own `value` accessors rather than over the
    rendered cells. A cell is markup — a badge, an avatar, a link — and
    searching its text either does not work or matches the word "Approved"
    inside an SVG title. `value` is the column author saying what the cell
    *means*, which is also what sorting needs.
  */
  const searched = React.useMemo(() => {
    if (!term.trim()) return rows;
    const needle = term.trim().toLowerCase();
    return rows.filter((row) =>
      columns.some((column) => {
        const value = column.value?.(row);
        return value != null && String(value).toLowerCase().includes(needle);
      }),
    );
  }, [rows, columns, term]);

  /*
    Facets narrow what the search left, and their own option lists are counted
    against every *other* facet's choices. Cross-filtering matters more than it
    sounds: a status filter that still offers "Denied (0)" after somebody picks
    a facility is a filter that sends people looking for rows that are not
    there.
  */
  const filtered = React.useMemo(
    () =>
      activeCount === 0
        ? searched
        : searched.filter((row) =>
            facets.every((facet) => matchesFacet(facet, row, chosen[facet.key] ?? [])),
          ),
    [searched, facets, chosen, activeCount],
  );

  const facetOptions = React.useMemo(
    () =>
      facets.map((facet) => {
        const others = searched.filter((row) =>
          facets.every(
            (other) =>
              other.key === facet.key ||
              matchesFacet(other, row, chosen[other.key] ?? []),
          ),
        );
        const counts = new Map<string, number>();
        for (const row of others) {
          for (const value of facetValues(facet, row)) {
            counts.set(value, (counts.get(value) ?? 0) + 1);
          }
        }
        const options = facet.options
          ? facet.options.map((option) => ({
              ...option,
              count: counts.get(option.value) ?? 0,
            }))
          : [...counts.keys()]
              .sort((a, b) => a.localeCompare(b))
              .map((value) => ({ value, label: value, count: counts.get(value) ?? 0 }));
        return { facet, options };
      }),
    [facets, searched, chosen],
  );

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

  /*
    Paging is a property of the list as read, so anything that changes what is
    in it puts the reader back on page one. Landing on an empty page 7 after
    typing into the search box looks exactly like a list that lost its rows.
  */
  const fingerprint = `${term}|${size}|${JSON.stringify(chosen)}|${rows.length}`;
  React.useEffect(() => setPage(1), [fingerprint]);

  // A board is already divided into columns; cutting it into pages as well
  // would hide the pile the board exists to show.
  const paged = mode !== "board" && size > 0;
  const pageCount = paged ? Math.max(1, Math.ceil(sorted.length / size)) : 1;
  const current = Math.min(page, pageCount);
  const visible = paged ? sorted.slice((current - 1) * size, current * size) : sorted;

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
            {facetOptions.map(({ facet, options }) => (
              <FilterMenu
                key={facet.key}
                facet={facet}
                options={options}
                chosen={chosen[facet.key] ?? []}
                onChange={(next) =>
                  setChosen((previous) => ({ ...previous, [facet.key]: next }))
                }
              />
            ))}
            {activeCount > 0 ? (
              <button
                type="button"
                onClick={() => setChosen({})}
                className="inline-flex h-9 items-center gap-1 rounded-md px-2 type-caption hover:text-foreground"
              >
                <Icon name="close" size="xs" />
                Clear {activeCount === 1 ? "filter" : `${activeCount} filters`}
              </button>
            ) : null}
            {toolbar}
          </div>

          <div className="flex shrink-0 items-center gap-3">
            {/* The count, always. "Showing 12 of 340" is the difference between
                a filtered list and a short one, and a list that does not say
                which reads as data loss. */}
            <span className="type-caption tabular-nums">
              {sorted.length !== rows.length
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
                  sorted.length !== rows.length
                    ? `Filtered${term ? ` to "${term}"` : ""} — ${
                        rows.length - sorted.length
                      } of ${rows.length} rows excluded.`
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
          description={
            term
              ? `No row in this list contains “${term}”. Clearing the search brings back all ${rows.length}.`
              : `No row matches those filters. Clearing them brings back all ${rows.length}.`
          }
          action={
            <button
              type="button"
              onClick={() => {
                setTerm("");
                setChosen({});
              }}
              className="type-caption underline underline-offset-4 hover:text-foreground"
            >
              Clear the search and filters
            </button>
          }
        />
      ) : sorted.length === 0 ? (
        <EmptyState
          title={empty?.title ?? "Nothing here yet"}
          description={empty?.description}
          action={empty?.action}
        />
      ) : mode === "table" ? (
        <TableView
          rows={visible}
          columns={columns}
          rowKey={rowKey}
          onOpen={onOpen}
          actions={actions}
          sort={sort}
          onSort={setSort}
        />
      ) : mode === "cards" && card ? (
        <CardsView
          rows={visible}
          rowKey={rowKey}
          spec={card}
          onOpen={onOpen}
          actions={actions}
        />
      ) : board ? (
        <BoardView
          rows={sorted}
          rowKey={rowKey}
          spec={board}
          onOpen={onOpen}
          actions={actions}
        />
      ) : null}

      {!loading && sorted.length > 0 && mode !== "board" ? (
        <Pager
          total={sorted.length}
          page={current}
          pageCount={pageCount}
          size={size}
          onPage={setPage}
          onSize={setSize}
        />
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Facets                                                                      */
/* -------------------------------------------------------------------------- */

function facetValues<T>(facet: FilterSpec<T>, row: T): string[] {
  const raw = facet.value(row);
  if (raw == null) return [];
  return (Array.isArray(raw) ? raw : [raw])
    .filter((value) => value != null && String(value).length > 0)
    .map(String);
}

/** Nothing chosen means everything matches — an empty filter is not a filter. */
function matchesFacet<T>(facet: FilterSpec<T>, row: T, chosen: string[]) {
  if (chosen.length === 0) return true;
  const values = facetValues(facet, row);
  return chosen.some((value) => values.includes(value));
}

const MENU_ITEM = cn(
  "flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5",
  "text-sm outline-none transition-colors duration-quick",
  "focus:bg-accent focus:text-accent-foreground",
  "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
);

const MENU_CONTENT = cn(
  "z-50 max-h-80 overflow-y-auto rounded-lg border bg-popover p-1.5 shadow-floating",
  "animate-in fade-in-0 zoom-in-95 duration-quick",
);

function FilterMenu<T>({
  facet,
  options,
  chosen,
  onChange,
}: {
  facet: FilterSpec<T>;
  options: { value: string; label: string; count: number }[];
  chosen: string[];
  onChange: (next: string[]) => void;
}) {
  // A facet with one value cannot narrow anything; showing it is furniture.
  if (options.length < 2) return null;

  const toggle = (value: string) =>
    onChange(
      chosen.includes(value)
        ? chosen.filter((entry) => entry !== value)
        : [...chosen, value],
    );

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        className={cn(
          "inline-flex h-9 items-center gap-1.5 rounded-md border border-input bg-card px-2.5 text-sm",
          "transition-colors duration-quick hover:border-border-strong",
          chosen.length > 0 && "border-primary/50 bg-primary/5 text-foreground",
        )}
      >
        <Icon name={facet.icon ?? "configuration"} size="sm" />
        <span>{facet.label}</span>
        {chosen.length > 0 ? (
          <span className="rounded-full bg-primary px-1.5 text-[0.625rem] font-semibold tabular-nums text-primary-foreground">
            {chosen.length}
          </span>
        ) : null}
        <Icon name="chevronDown" size="xs" className="text-muted-foreground" />
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content align="start" sideOffset={6} className={cn(MENU_CONTENT, "w-64")}>
          {options.map((option) => (
            <DropdownMenu.CheckboxItem
              key={option.value}
              checked={chosen.includes(option.value)}
              // Radix closes on select; a facet people tick three of should
              // not need re-opening twice.
              onSelect={(event) => event.preventDefault()}
              onCheckedChange={() => toggle(option.value)}
              className={MENU_ITEM}
            >
              <span
                className={cn(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                  chosen.includes(option.value)
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-input",
                )}
              >
                {chosen.includes(option.value) ? <Icon name="confirm" size="xs" /> : null}
              </span>
              <span className="min-w-0 flex-1 truncate">{option.label}</span>
              <span className="type-caption tabular-nums">{option.count}</span>
            </DropdownMenu.CheckboxItem>
          ))}
          {chosen.length > 0 ? (
            <>
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
              <DropdownMenu.Item className={MENU_ITEM} onSelect={() => onChange([])}>
                <Icon name="close" size="sm" />
                Clear {facet.label.toLowerCase()}
              </DropdownMenu.Item>
            </>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/* -------------------------------------------------------------------------- */
/* Row actions                                                                 */
/* -------------------------------------------------------------------------- */

function RowActions({ actions }: { actions: RowAction[] }) {
  if (actions.length === 0) return null;
  const ordered = [...actions].sort(
    (a, b) => Number(Boolean(a.danger)) - Number(Boolean(b.danger)),
  );

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label="Actions for this row"
        // The row itself usually opens something; the menu must not.
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground",
          "transition-colors duration-quick hover:bg-accent hover:text-foreground",
        )}
      >
        <Icon name="more" size="sm" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          onClick={(event) => event.stopPropagation()}
          className={cn(MENU_CONTENT, "w-56")}
        >
          {ordered.map((action, index) => (
            <React.Fragment key={action.label}>
              {action.danger && index > 0 && !ordered[index - 1]?.danger ? (
                <DropdownMenu.Separator className="my-1 h-px bg-border" />
              ) : null}
              <DropdownMenu.Item
                disabled={action.disabled}
                title={action.disabled ? action.reason : undefined}
                onSelect={() => action.onSelect()}
                className={cn(MENU_ITEM, action.danger && "text-destructive")}
              >
                {action.icon ? <Icon name={action.icon} size="sm" /> : null}
                {action.label}
              </DropdownMenu.Item>
            </React.Fragment>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

/* -------------------------------------------------------------------------- */
/* Pager                                                                       */
/* -------------------------------------------------------------------------- */

function Pager({
  total,
  page,
  pageCount,
  size,
  onPage,
  onSize,
}: {
  total: number;
  page: number;
  pageCount: number;
  size: number;
  onPage: (next: number) => void;
  onSize: (next: number) => void;
}) {
  const first = size > 0 ? (page - 1) * size + 1 : 1;
  const last = size > 0 ? Math.min(page * size, total) : total;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-1">
      {/* Which rows these are, in words. "Page 2" alone does not tell somebody
          reading a ledger whether they have seen row 51 yet. */}
      <span className="type-caption tabular-nums">
        {size > 0 && total > size
          ? `Showing ${first}–${last} of ${total}`
          : `${total} ${total === 1 ? "row" : "rows"}`}
      </span>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5 type-caption">
          <span className="hidden sm:inline">Rows</span>
          <select
            value={size}
            onChange={(event) => onSize(Number(event.target.value))}
            className="h-8 rounded-md border border-input bg-card px-1.5 text-sm"
          >
            {PAGE_SIZES.map((option) => (
              <option key={option} value={option}>
                {option === 0 ? "All" : option}
              </option>
            ))}
          </select>
        </label>

        {pageCount > 1 ? (
          <div className="flex items-center gap-1">
            <PageButton
              label="Previous page"
              icon="chevronLeft"
              disabled={page <= 1}
              onClick={() => onPage(page - 1)}
            />
            <span className="type-caption tabular-nums">
              {page} / {pageCount}
            </span>
            <PageButton
              label="Next page"
              icon="chevronRight"
              disabled={page >= pageCount}
              onClick={() => onPage(page + 1)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function PageButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: IconName;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md border border-input bg-card",
        "transition-colors duration-quick hover:border-border-strong",
        "disabled:cursor-not-allowed disabled:opacity-40",
      )}
    >
      <Icon name={icon} size="sm" />
    </button>
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
  actions,
  sort,
  onSort,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  actions?: (row: T) => RowAction[];
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
            {actions ? (
              <th scope="col" className="row-density w-10">
                <span className="sr-only">Actions</span>
              </th>
            ) : null}
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
              {actions ? (
                <td className="row-density text-right align-middle">
                  <RowActions actions={actions(row)} />
                </td>
              ) : null}
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
  actions,
}: {
  row: T;
  spec: CardSpec<T>;
  onOpen?: (row: T) => void;
  actions?: (row: T) => RowAction[];
}) {
  const accent = spec.accent?.(row);
  const facts = spec.facts?.(row) ?? [];

  /*
    A div with a button role rather than a `<button>`: the card carries an
    actions menu, and a button inside a button is invalid markup that browsers
    resolve by dropping one of them. Keyboard behaviour is supplied by hand
    instead of inherited.
  */
  return (
    <div
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen ? () => onOpen(row) : undefined}
      onKeyDown={
        onOpen
          ? (event) => {
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpen(row);
              }
            }
          : undefined
      }
      className={cn(
        "relative flex w-full flex-col gap-3 overflow-hidden rounded-lg border bg-card p-4 text-left shadow-raised",
        onOpen &&
          "cursor-pointer transition-colors duration-quick ease-smooth hover:border-border-strong hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
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
        {actions ? <RowActions actions={actions(row)} /> : null}
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
    </div>
  );
}

function CardsView<T>({
  rows,
  rowKey,
  spec,
  onOpen,
  actions,
}: {
  rows: T[];
  rowKey: (row: T) => string;
  spec: CardSpec<T>;
  onOpen?: (row: T) => void;
  actions?: (row: T) => RowAction[];
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((row) => (
        <RowCard
          key={rowKey(row)}
          row={row}
          spec={spec}
          onOpen={onOpen}
          actions={actions}
        />
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
  actions,
}: {
  rows: T[];
  rowKey: (row: T) => string;
  spec: BoardSpec<T>;
  onOpen?: (row: T) => void;
  actions?: (row: T) => RowAction[];
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
                  <RowCard
                    key={rowKey(row)}
                    row={row}
                    spec={spec.card}
                    onOpen={onOpen}
                    actions={actions}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
