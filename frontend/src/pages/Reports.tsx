/**
 * The report library.
 *
 * Thirteen reports that already existed, written beside the modules that
 * understand them, and until §105 unreachable unless you knew the URL. This
 * screen is the front of that register, and it takes four positions.
 *
 * **Each report is listed by the question it answers, not by its name.**
 * "Trial balance" means nothing to the person who needs to know whether the
 * books balance. The name is the small print here and the question is the
 * headline, which is the opposite of how report menus are usually built.
 *
 * **Reports you cannot run are shown, greyed, with the permission named.**
 * Somebody who cannot see a report they have heard of concludes the system
 * does not have it; somebody who sees it greyed out asks for the permission,
 * which is the conversation that should happen.
 *
 * **A result that is not a table is shown as what it is.** Several of these
 * answer with a shape -- a census with wards inside it, a turnaround summary
 * with buckets -- and flattening those into a grid produces a table whose
 * columns mean different things further down the page. Tabular results get a
 * table; the rest get their structure, plainly.
 *
 * **Heavy reports say so before you press the button, not after.**
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Download,
  Loader2,
  Lock,
  Play,
  TableIcon,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Facility, Paginated, ReportEntry, ReportLibrary, ReportRun } from "@/types";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/layout";

type Values = { facility: string; since: string; until: string; days: string };

const EMPTY: Values = { facility: "", since: "", until: "", days: "" };

/**
 * Pull out every table in a result, and everything that is not one.
 *
 * The first version of this took the *first* nested list it found. On a
 * balance sheet that is `assets`, so the screen would have shown the assets
 * alone under the heading "Balance sheet" and left the liabilities off -- a
 * half balance sheet, which is worse than none because it looks complete. The
 * backend now names the sections and this renders all of them.
 *
 * The leftovers matter too: a census is `{by_ward: [...], occupied: 41,
 * total: 60}`, and dropping the two numbers to show the table loses the
 * headline.
 */
function split(run: ReportRun): {
  tables: { name: string; rows: Record<string, unknown>[] }[];
  scalars: [string, unknown][];
} {
  const result = run.result;
  if (Array.isArray(result)) {
    return {
      tables: [{ name: "", rows: result as Record<string, unknown>[] }],
      scalars: [],
    };
  }
  if (!result || typeof result !== "object") return { tables: [], scalars: [] };

  const named = new Set(run.sections);
  const tables: { name: string; rows: Record<string, unknown>[] }[] = [];
  const scalars: [string, unknown][] = [];
  for (const [key, value] of Object.entries(result as Record<string, unknown>)) {
    if (named.has(key) && Array.isArray(value)) {
      tables.push({ name: key, rows: value as Record<string, unknown>[] });
    } else {
      scalars.push([key, value]);
    }
  }
  return { tables, scalars };
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function humanise(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export default function ReportsPage() {
  const [library, setLibrary] = useState<ReportLibrary | null>(null);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [chosen, setChosen] = useState<ReportEntry | null>(null);
  const [values, setValues] = useState<Values>(EMPTY);
  const [run, setRun] = useState<ReportRun | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ReportLibrary>("/reports/")
      .then(setLibrary)
      .catch((problem) =>
        setError(
          problem instanceof ApiError
            ? problem.message
            : "The report library could not be loaded.",
        ),
      );
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .catch(() => undefined);
  }, []);

  const query = useCallback(
    (report: ReportEntry) => {
      const search = new URLSearchParams();
      for (const parameter of report.parameters) {
        const value = values[parameter.name as keyof Values];
        if (value) search.set(parameter.name, value);
      }
      const text = search.toString();
      return text ? `?${text}` : "";
    },
    [values],
  );

  async function execute(report: ReportEntry) {
    setError(null);
    setRunning(true);
    setRun(null);
    try {
      setRun(await api.get<ReportRun>(`/reports/${report.code}/${query(report)}`));
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "The report could not be run.",
      );
    } finally {
      setRunning(false);
    }
  }

  async function exportCsv(report: ReportEntry, section = "") {
    setError(null);
    const search = query(report);
    const suffix = section ? `&section=${encodeURIComponent(section)}` : "";
    const path =
      `/reports/${report.code}/${search ? `${search}&` : "?"}export=csv${suffix}`;
    try {
      await api.download(
        path,
        section ? `${report.code}.${section}.csv` : `${report.code}.csv`,
      );
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "The export could not be produced.",
      );
    }
  }

  const groups = Array.from(
    new Set((library?.reports ?? []).map((report) => report.group)),
  ).sort();
  const shown = run ? split(run) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Each of these was written beside the module that understands it. There is no query builder, deliberately — a number assembled by hand is a number nobody can reproduce and everybody quotes."
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-4">
          {groups.map((group) => (
            <Card key={group}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{group}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 pb-3">
                {(library?.reports ?? [])
                  .filter((report) => report.group === group)
                  .map((report) => (
                    <button
                      key={report.code}
                      type="button"
                      disabled={!report.you_may_run_it}
                      onClick={() => {
                        setChosen(report);
                        setRun(null);
                        setError(null);
                      }}
                      title={
                        report.you_may_run_it
                          ? undefined
                          : `Needs ${report.permission}`
                      }
                      className={cn(
                        "w-full rounded-md px-2 py-1.5 text-left",
                        report.you_may_run_it
                          ? "hover:bg-muted"
                          : "cursor-not-allowed opacity-50",
                        chosen?.code === report.code ? "bg-muted" : "",
                      )}
                    >
                      <span className="flex items-center gap-1.5">
                        {report.you_may_run_it ? null : (
                          <Lock className="h-3 w-3 shrink-0" />
                        )}
                        <span className="text-sm font-medium">{report.name}</span>
                        {report.is_heavy ? (
                          <Badge variant="outline" className="text-[10px]">
                            heavy
                          </Badge>
                        ) : null}
                      </span>
                      {/*
                        The question is the headline and the name is the small
                        print, which is the opposite of how report menus are
                        usually built and the right way round.
                      */}
                      <span className="block text-xs text-muted-foreground">
                        {report.answers}
                      </span>
                    </button>
                  ))}
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="space-y-4">
          {chosen === null ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                Choose a report on the left.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>{chosen.name}</CardTitle>
                <CardDescription>{chosen.answers}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {chosen.parameters.length > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {chosen.parameters.map((parameter) => (
                      <div key={parameter.name} className="space-y-1">
                        <Label htmlFor={`p-${parameter.name}`}>
                          {humanise(parameter.name)}
                          {parameter.required ? (
                            <span className="text-destructive"> *</span>
                          ) : null}
                        </Label>
                        {parameter.name === "facility" ? (
                          <Select
                            id={`p-${parameter.name}`}
                            value={values.facility}
                            onChange={(event) =>
                              setValues((v) => ({
                                ...v,
                                facility: event.target.value,
                              }))
                            }
                          >
                            <option value="">
                              {parameter.required
                                ? "Choose a facility…"
                                : "The whole organization"}
                            </option>
                            {facilities.map((facility) => (
                              <option key={facility.uuid} value={facility.uuid}>
                                {facility.name}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <input
                            id={`p-${parameter.name}`}
                            type={parameter.name === "days" ? "number" : "date"}
                            value={values[parameter.name as keyof Values]}
                            onChange={(event) =>
                              setValues((v) => ({
                                ...v,
                                [parameter.name]: event.target.value,
                              }))
                            }
                            className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
                          />
                        )}
                        <p className="text-xs text-muted-foreground">
                          {parameter.description}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    This report takes no parameters.
                  </p>
                )}

                {chosen.is_heavy ? (
                  // Said before the button, not after. A report that takes a
                  // minute is a different decision from one that takes a
                  // second, and only one of them should be a surprise.
                  <Alert>
                    <AlertTriangle className="h-4 w-4" />
                    <AlertDescription>
                      This one reads a lot of history and can take a while.
                    </AlertDescription>
                  </Alert>
                ) : null}

                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => void execute(chosen)} disabled={running}>
                    {running ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    Run
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void exportCsv(chosen)}
                    disabled={running}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    CSV
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setValues(EMPTY)}
                    disabled={running}
                  >
                    Clear
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {run ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <TableIcon className="h-4 w-4" />
                  {run.name}
                </CardTitle>
                <CardDescription>
                  {Object.keys(run.parameters).length > 0
                    ? Object.entries(run.parameters)
                        .map(([key, value]) => `${humanise(key)}: ${value}`)
                        .join(" · ")
                    : "No parameters."}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {shown && shown.scalars.length > 0 ? (
                  // The numbers beside the table, not instead of it. A census
                  // is wards *and* "41 of 60 occupied", and showing only the
                  // grid loses the headline somebody actually came for.
                  <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                    {shown.scalars.map(([key, value]) => (
                      <div
                        key={key}
                        className="flex items-baseline justify-between gap-3 border-b py-1"
                      >
                        <dt className="text-xs text-muted-foreground">
                          {humanise(key)}
                        </dt>
                        <dd className="text-sm font-medium">{cell(value)}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}

                {(shown?.tables ?? []).map((table) => (
                  <div key={table.name || "rows"} className="space-y-2">
                    {table.name ? (
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium">
                          {humanise(table.name)}
                        </h3>
                        {/*
                          Per section, because the backend refuses to export a
                          multi-table report under one filename -- a CSV called
                          `finance.balance_sheet` holding only the assets looks
                          complete and is not.
                        */}
                        <Button
                          variant="ghost"
                          className="h-7 px-2 text-xs"
                          onClick={() =>
                            chosen ? void exportCsv(chosen, table.name) : undefined
                          }
                        >
                          <Download className="mr-1 h-3 w-3" />
                          CSV
                        </Button>
                      </div>
                    ) : null}
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            {Object.keys(table.rows[0]).map((key) => (
                              <TableHead key={key}>{humanise(key)}</TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {table.rows.map((row, at) => (
                            <TableRow key={at}>
                              {Object.keys(table.rows[0]).map((key) => (
                                <TableCell key={key}>{cell(row[key])}</TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                ))}

                {shown && shown.tables.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    This report answers with a shape rather than a table, so it
                    is shown as one.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
