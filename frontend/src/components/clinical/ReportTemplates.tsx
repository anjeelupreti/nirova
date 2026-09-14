/**
 * Start a narrative report from a template, or keep this one as a template.
 *
 * Applying fills the entry box under FINDINGS, IMPRESSION and ADVICE; if
 * something is already written, the reporter is asked before it is replaced.
 * Saving reads the same headings back, so a report written by hand under them
 * becomes a template without retyping. See `apps/diagnostics/report_templates.py`.
 */

import { useCallback, useEffect, useState } from "react";
import { BookmarkPlus, FileText, Loader2 } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { reportSections } from "@/components/documents/reportSections";
import { Alert, AlertDescription, Button, Input, Select } from "@/components/ui/primitives";

interface ReportTemplate {
  uuid: string;
  name: string;
  shared: boolean;
  text: string;
}

export function ReportTemplates({
  testCode,
  modality,
  text,
  onApply,
}: {
  testCode: string;
  modality: string;
  /** What is in the entry box now. */
  text: string;
  onApply: (text: string) => void;
}) {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [available, setAvailable] = useState(true);
  const [mayCurate, setMayCurate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api.get<{ results: ReportTemplate[]; may_curate: boolean }>(
        `/diagnostics/report-templates/?test=${encodeURIComponent(testCode)}&modality=${encodeURIComponent(modality)}`,
      );
      setTemplates(body.results);
      setMayCurate(body.may_curate);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setAvailable(false);
      else setProblem(err instanceof ApiError ? err.message : "Templates could not be read.");
    }
  }, [testCode, modality]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!available) return null;

  async function apply(uuid: string) {
    if (text.trim() && !window.confirm("Replace what is written with this template?")) return;
    setBusy(true);
    setProblem(null);
    try {
      const applied = await api.post<ReportTemplate>(`/diagnostics/report-templates/${uuid}/`);
      onApply(applied.text);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That template could not be applied.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    const sections = reportSections(text);
    const part = (heading: string) =>
      sections.find((section) => section.heading === heading)?.body ?? "";
    const untitled = sections.filter((section) => !section.heading).map((section) => section.body).join("\n\n");

    setBusy(true);
    setProblem(null);
    try {
      const created = await api.post<ReportTemplate>("/diagnostics/report-templates/", {
        name,
        shared,
        test_code: testCode,
        modality,
        findings: part("FINDINGS") || untitled,
        impression: part("IMPRESSION"),
        advice: part("ADVICE"),
      });
      setSaved(created.name);
      setSaving(false);
      setName("");
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "The template was not saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
        <Select
          aria-label="Start from a template"
          value=""
          disabled={busy || templates.length === 0}
          onChange={(event) => {
            if (event.target.value) void apply(event.target.value);
          }}
          className="min-w-0 flex-1"
        >
          <option value="">
            {templates.length > 0 ? "Start from a template…" : "No report templates for this test yet"}
          </option>
          {templates.map((row) => (
            <option key={row.uuid} value={row.uuid}>
              {row.name}
              {row.shared ? "" : " (mine)"}
            </option>
          ))}
        </Select>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!text.trim()}
          onClick={() => setSaving((open) => !open)}
        >
          <BookmarkPlus className="mr-1.5 h-4 w-4" />
          Save as template
        </Button>
      </div>

      {saving ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Template name"
            placeholder="Name, e.g. Chest X-ray: normal"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="min-w-0 flex-1"
          />
          {mayCurate ? (
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={shared}
                onChange={(event) => setShared(event.target.checked)}
              />
              For everyone
            </label>
          ) : null}
          <Button type="button" size="sm" disabled={busy || !name.trim()} onClick={() => void save()}>
            Save
          </Button>
        </div>
      ) : null}

      {saved ? <p className="text-xs text-good">Saved “{saved}”.</p> : null}
      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
