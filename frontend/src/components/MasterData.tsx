/**
 * One screen for every list of things a hospital configures.
 *
 * Written after hand-building three of these — the medicine catalogue, wards
 * and beds, services and prices. By the third the shape was identical and only
 * the fields differed, and a fourth copy would have been the point at which
 * they started drifting apart: four ideas of what "add" means, four empty
 * states, four ways of showing a required field.
 *
 * So the shape lives here and each list is a description of itself. A holiday
 * calendar is twenty lines of configuration rather than three hundred of JSX.
 *
 * **What it deliberately does not do.** It has no opinion about relationships,
 * approval flows or anything that needs a service call rather than a POST. A
 * ward with a run of beds and a payroll run are not this; they are their own
 * screens, and trying to express them here would produce a configuration
 * language nobody can read.
 *
 * **Reading and writing are separate permissions**, because they nearly always
 * are: everybody who works a shift should see the shift patterns, and few
 * people should change them. Somebody without the write permission sees the
 * list and the detail and no form, rather than a form that fails on save.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Search, TriangleAlert } from "lucide-react";

import { useSession } from "@/hooks/useSession";
import api, { ApiError } from "@/lib/api";
import type { Paginated } from "@/types";
import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DetailPanel,
  DetailRow,
  Input,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";

export type FieldKind =
  | "text"
  | "number"
  | "date"
  | "time"
  | "select"
  | "checkbox"
  | "textarea"
  /** A foreign key, chosen from another endpoint's rows. */
  | "reference";

export interface MasterField {
  key: string;
  label: string;
  kind?: FieldKind;
  options?: string[];
  required?: boolean;
  /** Fixed once the row exists — a code other records already refer to. */
  fixedAfterCreate?: boolean;
  placeholder?: string;
  help?: string;
  /** Shown in the detail panel under this heading. */
  group?: string;
  /** For `reference`: where the options come from, and what to show for each. */
  optionsFrom?: string;
  optionLabel?: string;
}

export interface MasterColumn {
  key: string;
  label: string;
  align?: "left" | "right";
  render?: (row: Record<string, unknown>) => React.ReactNode;
}

export interface MasterSpec {
  title: string;
  description: string;
  /** Singular, for buttons and empty states: "holiday", "shift pattern". */
  noun: string;
  endpoint: string;
  /** What it takes to change one. Reading is the screen's own permission. */
  writePermission: string;
  /**
   * The field this endpoint looks a row up by, when it is not `uuid`.
   *
   * Not a detail to guess at. `/hr/leave-types/` is addressed by `code`, and
   * PATCHing it by uuid returns **404** — which looks exactly like a
   * permissions problem and is not one. Measured per endpoint rather than
   * assumed.
   */
  lookupField?: string;
  writeScope?: string;
  columns: MasterColumn[];
  fields: MasterField[];
  searchable?: boolean;
  /** Sorted client-side by this key when the endpoint does not order usefully. */
  sortBy?: string;
  emptyHint?: string;
}

function humanise(value: unknown): string {
  return typeof value === "string" ? value.replace(/_/g, " ") : String(value ?? "");
}

type Row = Record<string, unknown>;

export default function MasterData({ spec }: { spec: MasterSpec }) {
  const { can } = useSession();
  const mayEdit = can(spec.writePermission, spec.writeScope);

  const [rows, setRows] = useState<Row[]>([]);
  const [term, setTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<Row | null>(null);
  const [draft, setDraft] = useState<Row | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blank = useCallback((): Row => {
    const next: Row = {};
    for (const field of spec.fields) {
      next[field.key] = field.kind === "checkbox" ? false : "";
      if (field.kind === "select" && field.options?.length) {
        next[field.key] = field.options[0];
      }
    }
    return next;
  }, [spec.fields]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page_size: "200" });
      if (spec.searchable && term.trim()) query.set("search", term.trim());
      const page = await api.get<Paginated<Row>>(
        `${spec.endpoint}?${query}`,
      );
      const found = [...page.results];
      if (spec.sortBy) {
        found.sort((a, b) =>
          String(a[spec.sortBy as string] ?? "").localeCompare(
            String(b[spec.sortBy as string] ?? ""),
          ),
        );
      }
      setRows(found);
      setError(null);
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : `The ${spec.noun} list could not be loaded.`,
      );
    } finally {
      setLoading(false);
    }
  }, [spec.endpoint, spec.noun, spec.searchable, spec.sortBy, term]);

  useEffect(() => {
    const handle = setTimeout(() => void load(), 250);
    return () => clearTimeout(handle);
  }, [load]);

  function toDraft(row: Row): Row {
    const next = blank();
    for (const field of spec.fields) {
      const value = row[field.key];
      if (value !== null && value !== undefined) next[field.key] = value;
    }
    return next;
  }

  async function save() {
    if (draft === null) return;
    setSaving(true);
    setError(null);
    try {
      // Empty strings are omitted rather than sent. A blank optional field
      // means "not decided"; posting "" records that indecision as a choice.
      const body: Row = {};
      for (const [key, value] of Object.entries(draft)) {
        if (value !== "") body[key] = value;
      }
      const saved = open
        ? await api.patch<Row>(`${spec.endpoint}${identify(open)}/`, body)
        : await api.post<Row>(spec.endpoint, body);
      setDraft(null);
      setOpen(saved);
      await load();
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "That could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  /**
   * The identifier this endpoint looks a row up by.
   *
   * Declared by the spec where it is not `uuid`, because guessing produces a
   * PATCH to a URL that 404s while looking exactly like a permissions problem
   * — which is what leave types did before this existed.
   */
  function identify(row: Row): string {
    if (spec.lookupField) return String(row[spec.lookupField] ?? "");
    return String(row.uuid ?? row.code ?? row.reference ?? "");
  }

  /**
   * Options for every `reference` field, fetched once.
   *
   * A stock location belongs to a facility and a scheme package to a payer;
   * without this the form would ask somebody to paste a UUID, which is not a
   * form, it is a punishment.
   */
  const [options, setOptions] = useState<Record<string, Row[]>>({});
  useEffect(() => {
    for (const field of spec.fields) {
      if (field.kind !== "reference" || !field.optionsFrom) continue;
      const source = field.optionsFrom;
      api
        .get<Paginated<Row>>(`${source}?page_size=200`)
        .then((page) =>
          setOptions((current) => ({ ...current, [field.key]: page.results })),
        )
        .catch(() => undefined);
    }
  }, [spec.fields]);

  const missingRequired = spec.fields.some(
    (field) =>
      field.required && !String((draft ?? {})[field.key] ?? "").trim(),
  );

  function editor(field: MasterField) {
    const value = (draft ?? {})[field.key];
    const set = (next: unknown) =>
      setDraft((current) =>
        current ? { ...current, [field.key]: next } : current,
      );

    if (field.kind === "checkbox") {
      return (
        <label key={field.key} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => set(event.target.checked)}
          />
          {field.label}
        </label>
      );
    }

    return (
      <div key={field.key} className="space-y-1">
        <Label htmlFor={`f-${field.key}`}>
          {field.label}
          {field.required ? <span className="text-destructive"> *</span> : null}
        </Label>
        {field.kind === "reference" ? (
          <Select
            id={`f-${field.key}`}
            value={String(value ?? "")}
            onChange={(event) => set(event.target.value)}
          >
            <option value="">Choose…</option>
            {(options[field.key] ?? []).map((option) => (
              <option key={String(option.uuid)} value={String(option.uuid)}>
                {String(option[field.optionLabel ?? "name"] ?? option.uuid)}
              </option>
            ))}
          </Select>
        ) : field.kind === "select" ? (
          <Select
            id={`f-${field.key}`}
            value={String(value ?? "")}
            onChange={(event) => set(event.target.value)}
          >
            {(field.options ?? []).map((option) => (
              <option key={option} value={option}>
                {option ? humanise(option) : "—"}
              </option>
            ))}
          </Select>
        ) : field.kind === "textarea" ? (
          <textarea
            id={`f-${field.key}`}
            value={String(value ?? "")}
            onChange={(event) => set(event.target.value)}
            rows={3}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
        ) : (
          <Input
            id={`f-${field.key}`}
            type={
              field.kind === "number"
                ? "number"
                : field.kind === "date"
                  ? "date"
                  : field.kind === "time"
                    ? "time"
                    : "text"
            }
            value={String(value ?? "")}
            placeholder={field.placeholder}
            // A code other records already point at is not editable after the
            // fact: changing it would leave those records referring to
            // something that no longer answers to that name.
            disabled={field.fixedAfterCreate && open !== null}
            onChange={(event) => set(event.target.value)}
          />
        )}
        {field.help ? (
          <p className="text-xs text-muted-foreground">{field.help}</p>
        ) : null}
      </div>
    );
  }

  const boxes = spec.fields.filter((field) => field.kind === "checkbox");
  const inputs = spec.fields.filter((field) => field.kind !== "checkbox");

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="text-base">{spec.title}</CardTitle>
            <CardDescription>{spec.description}</CardDescription>
          </div>
          {mayEdit ? (
            <Button
              size="sm"
              onClick={() => {
                setOpen(null);
                setDraft(blank());
                setError(null);
              }}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Add a {spec.noun}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-3">
          {spec.searchable ? (
            <div className="relative max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={term}
                onChange={(event) => setTerm(event.target.value)}
                placeholder="Search"
                className="h-9 pl-8"
              />
            </div>
          ) : null}

          {error && draft === null ? (
            <Alert variant="destructive">
              <TriangleAlert className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {loading ? (
            <p className="py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
              Loading…
            </p>
          ) : rows.length === 0 ? (
            /*
              An empty state that says what to do next, and says something
              different to somebody who cannot act on it. "No rows" is a fact
              about the screen; this is a fact about their afternoon.
            */
            <div className="py-10 text-center">
              <p className="text-sm font-medium">
                {term ? "Nothing matches that." : `No ${spec.noun}s yet.`}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {term
                  ? "Try a shorter search."
                  : mayEdit
                    ? (spec.emptyHint ?? `Add the first ${spec.noun}.`)
                    : `Somebody who manages these needs to add them.`}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {spec.columns.map((column) => (
                      <TableHead
                        key={column.key}
                        className={column.align === "right" ? "text-right" : ""}
                      >
                        {column.label}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow
                      key={identify(row)}
                      onClick={() => {
                        setOpen(row);
                        setDraft(null);
                        setError(null);
                      }}
                      className="cursor-pointer hover:bg-muted/50"
                    >
                      {spec.columns.map((column) => (
                        <TableCell
                          key={column.key}
                          className={column.align === "right" ? "text-right" : ""}
                        >
                          {column.render
                            ? column.render(row)
                            : typeof row[column.key] === "boolean"
                              ? row[column.key]
                                ? "yes"
                                : "no"
                              : humanise(row[column.key]) || "—"}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <DetailPanel
        open={open !== null && draft === null}
        onClose={() => setOpen(null)}
        title={String(open?.name ?? open?.title ?? open?.code ?? "")}
        subtitle={open ? String(open.code ?? "") : undefined}
        footer={
          mayEdit && open ? (
            <Button className="w-full" onClick={() => setDraft(toDraft(open))}>
              Edit this {spec.noun}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Changing this needs the {spec.writePermission} permission.
            </p>
          )
        }
      >
        {open ? (
          <div className="space-y-6">
            {groupsOf(spec.fields).map(([heading, fields]) => (
              <section key={heading}>
                {heading ? (
                  <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {heading}
                  </h3>
                ) : null}
                {fields.map((field) => (
                  <DetailRow key={field.key} label={field.label}>
                    {typeof open[field.key] === "boolean" ? (
                      open[field.key] ? (
                        "Yes"
                      ) : (
                        "No"
                      )
                    ) : (
                      humanise(open[field.key]) || null
                    )}
                  </DetailRow>
                ))}
              </section>
            ))}
          </div>
        ) : null}
      </DetailPanel>

      <DetailPanel
        open={draft !== null}
        onClose={() => setDraft(null)}
        title={open ? `Edit ${spec.noun}` : `Add a ${spec.noun}`}
        subtitle={
          open
            ? String(open.code ?? open.name ?? "")
            : requiredSummary(spec.fields)
        }
        footer={
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={saving || missingRequired}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : open ? "Save changes" : `Add ${spec.noun}`}
            </Button>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
          </div>
        }
      >
        {draft ? (
          <div className="space-y-4">
            {error ? (
              <Alert variant="destructive">
                <TriangleAlert className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              {inputs.map((field) => editor(field))}
            </div>
            {boxes.length ? (
              <div className="space-y-2 border-t pt-3">
                {boxes.map((field) => editor(field))}
              </div>
            ) : null}
          </div>
        ) : null}
      </DetailPanel>
    </div>
  );
}

/** Fields in the order given, bucketed by their `group` heading. */
function groupsOf(fields: MasterField[]): [string, MasterField[]][] {
  const order: string[] = [];
  const buckets = new Map<string, MasterField[]>();
  for (const field of fields) {
    const key = field.group ?? "";
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(field);
  }
  return order.map((key) => [key, buckets.get(key)!]);
}

/** "A code and a name are required" — said once, above the form. */
function requiredSummary(fields: MasterField[]): string {
  const names = fields.filter((field) => field.required).map((f) => f.label.toLowerCase());
  if (names.length === 0) return "Nothing here is required";
  if (names.length === 1) return `Only ${names[0]} is required`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]} are required`;
}
