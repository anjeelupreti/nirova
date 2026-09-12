/**
 * Bringing an existing practice's records in.
 *
 * **A stepper, not a form, because the steps are decisions.** Upload, map,
 * review, import. Each one is a thing a person has to agree to, and the whole
 * point of the feature is that none of them happens silently: a bulk import is
 * the one operation in this product whose mistakes cannot be undone, because two
 * records for the same patient split a clinical history and by the time anybody
 * notices there are encounters and invoices hanging off both.
 *
 * So the screen is built around the review, not around the upload. The upload is
 * two controls; the review is most of this file.
 *
 * **The mapping step shows sample values, not just column names.** A reviewer
 * asked to say what a column called "Date 2" means cannot answer from the name.
 * Three values from the file answer it immediately.
 *
 * **Duplicates are shown with what matched, not with a score.** "Matches Ram
 * Gurung (MRN 000412) on phone, name" is reviewable. "87% confidence" is not.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Download,

  RefreshCw,
  Upload,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Page, PageHeader, Section, StatGrid, ScrollX } from "@/components/ui/layout";
import { EmptyState, TableSkeleton } from "@/components/ui/feedback";
import { StatTile } from "@/components/ui/data";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

type ImportKind = {
  kind: string;
  label: string;
  noun: string;
  notes: string;
  columns: {
    field: string;
    label: string;
    required: boolean;
    aliases: string[];
    help_text: string;
  }[];
};

type Batch = {
  uuid: string;
  reference: string;
  kind: string;
  kind_label: string;
  filename: string;
  status: string;
  status_label: string;
  headers: string[];
  column_map: Record<string, string>;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  imported_rows: number;
  skipped_rows: number;
  failed_rows: number;
  error_summary: Record<string, number>;
  uploaded_by_name: string;
  validated_at: string | null;
  imported_at: string | null;
  imported_by_name: string;
  is_committed: boolean;
  created_at: string;
};

type MappingReport = {
  mapping: Record<string, string>;
  missing_required: { field: string; label: string }[];
  ignored_columns: string[];
  samples: Record<string, (string | number | boolean)[]>;
  columns: {
    field: string;
    label: string;
    required: boolean;
    help_text: string;
    mapped_to: string;
  }[];
};

type PreviewRow = {
  row_number: number;
  status: string;
  normalised: Record<string, unknown>;
  errors: { field: string; message: string }[];
  duplicate_of_label: string;
  duplicate_matched_on: string[];
  duplicate_of_row: number | null;
  duplicate_score: number;
  decision: string;
};

type Preview = {
  reference: string;
  noun: string;
  status: string;
  total_rows: number;
  will_create: number;
  will_skip: number;
  invalid_rows: number;
  duplicate_rows: number;
  awaiting_decision: number;
  error_summary: Record<string, number>;
  sample: PreviewRow[];
};

type Step = "upload" | "map" | "review" | "done";

const STEPS: { id: Step; label: string }[] = [
  { id: "upload", label: "Upload" },
  { id: "map", label: "Match columns" },
  { id: "review", label: "Review" },
  { id: "done", label: "Imported" },
];

/** Row status → how it reads. Colour is the last signal, never the only one. */
const ROW_TONE: Record<string, string> = {
  valid: "text-good",
  invalid: "text-destructive",
  duplicate: "text-warning",
  imported: "text-good",
  skipped: "text-muted-foreground",
  failed: "text-destructive",
  pending: "text-muted-foreground",
};

/* -------------------------------------------------------------------------- */
/* Screen                                                                      */
/* -------------------------------------------------------------------------- */

export default function DataImportPage() {
  const [kinds, setKinds] = useState<ImportKind[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [report, setReport] = useState<MappingReport | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [step, setStep] = useState<Step>("upload");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    // `allSettled`: the kind catalogue and the batch history are independent,
    // and the screen is usable with either one missing.
    const [kindRes, listRes] = await Promise.allSettled([
      api.get<{ kinds: ImportKind[] }>("/import/kinds/"),
      api.get<{ results: Batch[] }>("/import/batches/"),
    ]);
    if (kindRes.status === "fulfilled") setKinds(kindRes.value.kinds);
    if (listRes.status === "fulfilled") setBatches(listRes.value.results);
    if (kindRes.status === "rejected" && listRes.status === "rejected") {
      const reason = kindRes.reason;
      setProblem(
        reason instanceof ApiError ? reason.message : "Could not load.",
      );
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async <T,>(work: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setProblem(null);
    try {
      return await work();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Something failed.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const upload = async (kind: string, file: File) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    const created = await act(() =>
      api.post<Batch & { mapping_report: MappingReport }>(
        "/import/batches/",
        form,
      ),
    );
    if (!created) return;
    setBatch(created);
    setReport(created.mapping_report);
    setPreview(null);
    setStep("map");
  };

  const openBatch = async (reference: string) => {
    const found = await act(() =>
      api.get<Batch & { mapping_report: MappingReport }>(
        `/import/batches/${reference}/mapping/`,
      ),
    );
    if (!found) return;
    setBatch(found);
    setReport(found.mapping_report);
    if (found.is_committed) {
      setStep("done");
      const shown = await act(() =>
        api.get<Preview>(`/import/batches/${reference}/preview/`),
      );
      setPreview(shown);
    } else {
      setStep("map");
    }
  };

  const saveMapping = async (mapping: Record<string, string>) => {
    if (!batch) return;
    const updated = await act(() =>
      api.patch<Batch & { mapping_report: MappingReport }>(
        `/import/batches/${batch.reference}/mapping/`,
        { mapping },
      ),
    );
    if (!updated) return;
    setBatch(updated);
    setReport(updated.mapping_report);
  };

  const validate = async () => {
    if (!batch) return;
    const result = await act(() =>
      api.post<Preview>(`/import/batches/${batch.reference}/validate/`, {}),
    );
    if (!result) return;
    setPreview(result);
    setStep("review");
    const refreshed = await act(() =>
      api.get<Batch>(`/import/batches/${batch.reference}/`),
    );
    if (refreshed) setBatch(refreshed);
  };

  const decide = async (decisions: Record<string, string>) => {
    if (!batch) return;
    const result = await act(() =>
      api.post<Preview>(`/import/batches/${batch.reference}/decide/`, {
        decisions,
      }),
    );
    if (result) setPreview(result);
  };

  const commit = async () => {
    if (!batch) return;
    const result = await act(() =>
      api.post<Batch>(`/import/batches/${batch.reference}/commit/`, {}),
    );
    if (!result) return;
    setBatch(result);
    setStep("done");
    void load();
  };

  const reset = () => {
    setBatch(null);
    setReport(null);
    setPreview(null);
    setStep("upload");
    setProblem(null);
    void load();
  };

  return (
    <Page>
      <PageHeader
        title="Data import"
        description={
          "Bring a practice's patients, medicines and other records in from a " +
          "spreadsheet. Nothing is created until you have seen what will happen."
        }
        actions={
          batch && (
            <Button variant="outline" onClick={reset} disabled={busy}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Start another
            </Button>
          )
        }
      />

      <Stepper current={step} />

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>That did not work</AlertTitle>
          {/* The server's own sentence. Every failure in this pipeline is
              something in the file that somebody has to change, so the message
              is the whole response and replacing it with "an error occurred"
              would throw away the only useful part. */}
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {step === "upload" && (
        <UploadStep
          kinds={kinds}
          loading={loading}
          busy={busy}
          onUpload={upload}
          batches={batches}
          onOpen={openBatch}
        />
      )}

      {step === "map" && batch && report && (
        <MapStep
          batch={batch}
          report={report}
          busy={busy}
          onChange={saveMapping}
          onNext={validate}
        />
      )}

      {step === "review" && batch && preview && (
        <ReviewStep
          batch={batch}
          preview={preview}
          busy={busy}
          onDecide={decide}
          onCommit={commit}
          onBack={() => setStep("map")}
        />
      )}

      {step === "done" && batch && (
        <DoneStep batch={batch} onReset={reset} />
      )}
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* The step indicator                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Where you are, and what is still to come.
 *
 * Worth the space because the whole design of this feature is "nothing happens
 * until the last step", and somebody who cannot see that there *is* a last step
 * will assume the upload did it.
 */
function Stepper({ current }: { current: Step }) {
  const index = STEPS.findIndex((s) => s.id === current);
  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm">
      {STEPS.map((entry, position) => {
        const done = position < index;
        const active = position === index;
        return (
          <li key={entry.id} className="flex items-center gap-2">
            {position > 0 && (
              <ArrowRight aria-hidden className="h-3 w-3 text-muted-foreground" />
            )}
            <span
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1",
                active && "border-primary bg-primary/10 font-medium text-foreground",
                done && "border-transparent text-muted-foreground",
                !active && !done && "border-dashed text-muted-foreground",
              )}
              aria-current={active ? "step" : undefined}
            >
              {done ? (
                <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
              ) : (
                <span className="text-xs tabular-nums">{position + 1}</span>
              )}
              {entry.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/* -------------------------------------------------------------------------- */
/* Step 1: upload                                                              */
/* -------------------------------------------------------------------------- */

function UploadStep({
  kinds,
  loading,
  busy,
  onUpload,
  batches,
  onOpen,
}: {
  kinds: ImportKind[];
  loading: boolean;
  busy: boolean;
  onUpload: (kind: string, file: File) => void;
  batches: Batch[];
  onOpen: (reference: string) => void;
}) {
  const [kind, setKind] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const chosen = kinds.find((k) => k.kind === kind);

  useEffect(() => {
    if (!kind && kinds[0]) setKind(kinds[0].kind);
  }, [kind, kinds]);

  if (loading) return <TableSkeleton rows={4} />;

  return (
    <div className="space-y-4">
      <Section
        title="What are you importing?"
        description="The kind decides which columns are expected and how duplicates are recognised."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="import-kind">Kind of record</Label>
            <Select
              id="import-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              {kinds.map((entry) => (
                <option key={entry.kind} value={entry.kind}>
                  {entry.label}
                </option>
              ))}
            </Select>
            {chosen?.notes && (
              <p className="text-xs text-muted-foreground">{chosen.notes}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="import-file">Spreadsheet</Label>
            <input
              id="import-file"
              type="file"
              accept=".csv,.tsv,.xlsx,.xlsm"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="block w-full rounded-md border bg-background px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-secondary file:px-3 file:py-1 file:text-sm"
            />
            <p className="text-xs text-muted-foreground">
              CSV, TSV or Excel. The first row must be the column names.
            </p>
          </div>
        </div>

        <div className="mt-4">
          <Button
            disabled={!kind || !file || busy}
            onClick={() => file && onUpload(kind, file)}
          >
            <Upload className="mr-2 h-4 w-4" />
            Upload file
          </Button>
        </div>
      </Section>

      {chosen && (
        <Section
          title={`Columns for ${chosen.label.toLowerCase()}`}
          description="Headers are matched automatically. These are the spellings recognised."
        >
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Field</TableHead>
                  <TableHead>Required</TableHead>
                  <TableHead>Header names recognised</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {chosen.columns.map((column) => (
                  <TableRow key={column.field}>
                    <TableCell className="font-medium">
                      {column.label}
                      {column.help_text && (
                        <p className="text-xs font-normal text-muted-foreground">
                          {column.help_text}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      {column.required ? (
                        <Badge variant="secondary">Required</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">Optional</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {[column.field, ...column.aliases].join(", ")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        </Section>
      )}

      <Section
        title="Earlier imports"
        description="What has been brought in, by whom, and when."
      >
        {batches.length === 0 ? (
          <EmptyState
            illustration="documents"
            title="Nothing has been imported yet"
            description="An import you start will be listed here with what it created."
          />
        ) : (
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>File</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead className="text-right">Created</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {batches.map((entry) => (
                  <TableRow key={entry.uuid}>
                    <TableCell className="font-mono text-xs">
                      {entry.reference}
                    </TableCell>
                    <TableCell>{entry.kind_label}</TableCell>
                    <TableCell className="max-w-[16rem] truncate">
                      {entry.filename}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {entry.total_rows}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {entry.imported_rows || "—"}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          entry.status === "imported" ? "secondary" : "outline"
                        }
                      >
                        {entry.status_label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onOpen(entry.reference)}
                      >
                        {entry.is_committed ? "View" : "Continue"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        )}
      </Section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Step 2: mapping                                                             */
/* -------------------------------------------------------------------------- */

function MapStep({
  batch,
  report,
  busy,
  onChange,
  onNext,
}: {
  batch: Batch;
  report: MappingReport;
  busy: boolean;
  onChange: (mapping: Record<string, string>) => void;
  onNext: () => void;
}) {
  const blocked = report.missing_required.length > 0;

  const setField = (field: string, header: string) => {
    const next = { ...report.mapping };
    if (header) next[field] = header;
    else delete next[field];
    onChange(next);
  };

  return (
    <div className="space-y-4">
      <Section
        title={`${batch.filename} — ${batch.total_rows} rows`}
        description="Check what each column means. The sample values come from the file."
      >
        {blocked && (
          <Alert variant="destructive" className="mb-4">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Required columns are not matched</AlertTitle>
            <AlertDescription>
              {report.missing_required.map((m) => m.label).join(", ")} must be
              matched to a column before the file can be checked.
            </AlertDescription>
          </Alert>
        )}

        <ScrollX>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Column in your file</TableHead>
                <TableHead>Sample values</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.columns.map((column) => {
                const header = report.mapping[column.field] || "";
                const samples = header ? report.samples[header] ?? [] : [];
                return (
                  <TableRow key={column.field}>
                    <TableCell className="font-medium">
                      {column.label}
                      {column.required && (
                        <span className="ml-1 text-destructive" aria-label="required">
                          *
                        </span>
                      )}
                      {column.help_text && (
                        <p className="text-xs font-normal text-muted-foreground">
                          {column.help_text}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      <Select
                        aria-label={`Column for ${column.label}`}
                        value={header}
                        disabled={busy}
                        onChange={(event) =>
                          setField(column.field, event.target.value)
                        }
                      >
                        <option value="">— not in this file —</option>
                        {batch.headers.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </Select>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {samples.length > 0 ? samples.join(" · ") : "—"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </ScrollX>

        {report.ignored_columns.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            Not imported: {report.ignored_columns.join(", ")}. Match a column
            above if one of these should be.
          </p>
        )}

        <div className="mt-4">
          <Button onClick={onNext} disabled={blocked || busy}>
            Check the file
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </Section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Step 3: review                                                              */
/* -------------------------------------------------------------------------- */

function ReviewStep({
  batch,
  preview,
  busy,
  onDecide,
  onCommit,
  onBack,
}: {
  batch: Batch;
  preview: Preview;
  busy: boolean;
  onDecide: (decisions: Record<string, string>) => void;
  onCommit: () => void;
  onBack: () => void;
}) {
  const duplicates = preview.sample.filter((r) => r.status === "duplicate");
  const invalid = preview.sample.filter((r) => r.status === "invalid");

  const decideAll = (decision: string) => {
    const decisions: Record<string, string> = {};
    for (const row of duplicates) decisions[String(row.row_number)] = decision;
    if (Object.keys(decisions).length) onDecide(decisions);
  };

  return (
    <div className="space-y-4">
      <StatGrid>
        <StatTile
          label="Will be created"
          value={preview.will_create}
          hint={preview.noun}
          intent="good"
          icon={<Users className="h-4 w-4" />}
        />
        <StatTile
          label="Will be skipped"
          value={preview.will_skip}
          hint="not imported"
        />
        <StatTile
          label="Cannot be imported"
          value={preview.invalid_rows}
          hint="fix the file and upload again"
          intent={preview.invalid_rows ? "bad" : "neutral"}
        />
        <StatTile
          label="Match an existing record"
          value={preview.duplicate_rows}
          hint={
            preview.awaiting_decision
              ? `${preview.awaiting_decision} need a decision`
              : "all decided"
          }
          intent={preview.awaiting_decision ? "bad" : "neutral"}
        />
      </StatGrid>

      {preview.awaiting_decision > 0 && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {preview.awaiting_decision} row(s) look like somebody already on file
          </AlertTitle>
          <AlertDescription>
            Choose for each. There is no default on purpose: skipping silently
            would lose somebody who is genuinely a new person, and importing
            silently is how one patient ends up with two records and half a
            history in each.
          </AlertDescription>
        </Alert>
      )}

      {Object.keys(preview.error_summary).length > 0 && (
        <Section
          title="What is wrong with the file"
          description="Counted by column, because a migration is fixed in the spreadsheet."
        >
          <ul className="space-y-1 text-sm">
            {Object.entries(preview.error_summary).map(([field, count]) => (
              <li key={field} className="flex items-baseline justify-between gap-4">
                <span className="font-medium">{field}</span>
                <span className="tabular-nums text-muted-foreground">
                  {count} row{count === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {duplicates.length > 0 && (
        <Section
          title="Possible duplicates"
          description="What matched is shown, so the decision is reviewable."
          actions={
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => decideAll("skip")}
              >
                Skip all shown
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => decideAll("import")}
              >
                Import all shown
              </Button>
            </div>
          }
        >
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">Row</TableHead>
                  <TableHead>From the file</TableHead>
                  <TableHead>Matches</TableHead>
                  <TableHead>On</TableHead>
                  <TableHead>Decision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {duplicates.map((row) => (
                  <TableRow key={row.row_number}>
                    <TableCell className="tabular-nums">{row.row_number}</TableCell>
                    <TableCell>{describe(row.normalised)}</TableCell>
                    <TableCell>
                      {row.duplicate_of_row
                        ? `row ${row.duplicate_of_row} of this file`
                        : row.duplicate_of_label}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {row.duplicate_matched_on.join(", ")}
                    </TableCell>
                    <TableCell>
                      <Select
                        aria-label={`Decision for row ${row.row_number}`}
                        value={row.decision}
                        disabled={busy}
                        onChange={(event) =>
                          onDecide({
                            [String(row.row_number)]: event.target.value,
                          })
                        }
                      >
                        <option value="undecided">— choose —</option>
                        <option value="import">Import anyway</option>
                        <option value="skip">Skip</option>
                      </Select>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        </Section>
      )}

      {invalid.length > 0 && (
        <Section
          title="Rows that cannot be imported"
          description="Every problem in each row, so the file is corrected once."
          actions={
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/import/batches/${batch.reference}/errors/`}>
                <Download className="mr-2 h-4 w-4" />
                Download errors
              </a>
            </Button>
          }
        >
          <ScrollX>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">Row</TableHead>
                  <TableHead>Problems</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invalid.map((row) => (
                  <TableRow key={row.row_number}>
                    <TableCell className="tabular-nums">{row.row_number}</TableCell>
                    <TableCell>
                      <ul className="space-y-0.5 text-sm">
                        {row.errors.map((error, index) => (
                          <li key={index} className={ROW_TONE.invalid}>
                            <span className="font-medium">{error.field}</span>{" "}
                            {error.message}
                          </li>
                        ))}
                      </ul>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        </Section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" onClick={onBack} disabled={busy}>
          Back to columns
        </Button>
        <Button
          onClick={onCommit}
          disabled={busy || preview.awaiting_decision > 0 || preview.will_create === 0}
        >
          Import {preview.will_create} {preview.noun}
        </Button>
        {preview.will_create === 0 && (
          <span className="text-sm text-muted-foreground">
            Nothing would be created. Correct the file and upload it again.
          </span>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Step 4: done                                                                */
/* -------------------------------------------------------------------------- */

function DoneStep({ batch, onReset }: { batch: Batch; onReset: () => void }) {
  return (
    <div className="space-y-4">
      <StatGrid>
        <StatTile
          label="Created"
          value={batch.imported_rows}
          intent="good"
          icon={<CheckCircle2 className="h-4 w-4" />}
        />
        <StatTile label="Skipped" value={batch.skipped_rows} />
        <StatTile
          label="Failed"
          value={batch.failed_rows}
          intent={batch.failed_rows ? "bad" : "neutral"}
        />
        <StatTile label="Rows in the file" value={batch.total_rows} />
      </StatGrid>

      <Section
        title={`${batch.reference} is imported`}
        description={
          batch.imported_at
            ? `${new Date(batch.imported_at).toLocaleString()} by ${batch.imported_by_name || "—"}`
            : undefined
        }
      >
        {batch.failed_rows > 0 ? (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>{batch.failed_rows} row(s) failed while importing</AlertTitle>
            <AlertDescription>
              The rest were imported — each row is committed on its own, so one
              bad row does not undo the others. Download the report, correct
              those rows, and upload them as a new file.
            </AlertDescription>
          </Alert>
        ) : (
          <p className="text-sm text-muted-foreground">
            Every row that was meant to be imported was. This batch cannot be
            imported again.
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {(batch.failed_rows > 0 || batch.invalid_rows > 0) && (
            <Button variant="outline" asChild>
              <a href={`/api/import/batches/${batch.reference}/errors/`}>
                <Download className="mr-2 h-4 w-4" />
                Download errors
              </a>
            </Button>
          )}
          <Button onClick={onReset}>Import something else</Button>
        </div>
      </Section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * A row in a few words, for the duplicate table.
 *
 * Built from whichever identifying fields the row has rather than a fixed list,
 * because this screen serves every kind of import and a product row has no first
 * name.
 */
function describe(normalised: Record<string, unknown>): string {
  const parts = [
    normalised.first_name,
    normalised.last_name,
    normalised.generic_name,
    normalised.code,
    normalised.phone,
  ]
    .filter((v) => typeof v === "string" && v)
    .slice(0, 3);
  return parts.length ? parts.join(" · ") : "—";
}
