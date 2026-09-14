/**
 * Start a discharge from a template, or keep this one as a template.
 *
 * A template fills only the fields still empty: whatever the clinician has
 * already written about this patient stays. See
 * `apps/inpatient/discharge_templating.py` for why the patient's half --
 * advice, food, activity, specific warning signs -- is part of it.
 */

import { useCallback, useEffect, useState } from "react";
import { BookmarkPlus, FileText, Loader2 } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { Alert, AlertDescription, Button, Input, Select } from "@/components/ui/primitives";

export interface DischargeTemplate {
  uuid: string;
  name: string;
  diagnosis: string;
  shared: boolean;
  owner_name: string;
  course: string;
  advice: string;
  diet: string;
  activity: string;
  warning_signs: string[];
  follow_up_days: number | null;
  times_used: number;
}

export interface AppliedDischarge extends DischargeTemplate {
  follow_up_on: string | null;
}

export interface DischargeDraft {
  diagnosis: string;
  course: string;
  advice: string;
  diet: string;
  activity: string;
  warning_signs: string[];
}

export function DischargeTemplates({
  draft,
  onApply,
}: {
  draft: DischargeDraft;
  onApply: (applied: AppliedDischarge) => void;
}) {
  const [templates, setTemplates] = useState<DischargeTemplate[]>([]);
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
      const body = await api.get<{ results: DischargeTemplate[]; may_curate: boolean }>(
        "/ipd/discharge-templates/",
      );
      setTemplates(body.results);
      setMayCurate(body.may_curate);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setAvailable(false);
      else setProblem(err instanceof ApiError ? err.message : "Templates could not be read.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!available) return null;

  async function apply(uuid: string) {
    setBusy(true);
    setProblem(null);
    try {
      onApply(await api.post<AppliedDischarge>(`/ipd/discharge-templates/${uuid}/`));
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That template could not be applied.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setProblem(null);
    try {
      const created = await api.post<DischargeTemplate>("/ipd/discharge-templates/", {
        ...draft,
        name,
        shared,
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

  const ours = templates.filter((row) => row.shared);
  const mine = templates.filter((row) => !row.shared);

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
            {templates.length > 0 ? "Start from a template…" : "No discharge templates yet"}
          </option>
          {ours.length > 0 ? (
            <optgroup label="Organization">
              {ours.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name}
                </option>
              ))}
            </optgroup>
          ) : null}
          {mine.length > 0 ? (
            <optgroup label="Mine">
              {mine.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name}
                </option>
              ))}
            </optgroup>
          ) : null}
        </Select>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
        <Button type="button" variant="outline" size="sm" onClick={() => setSaving((open) => !open)}>
          <BookmarkPlus className="mr-1.5 h-4 w-4" />
          Save as template
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        A template fills only the fields you have left empty.
      </p>

      {saving ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="Template name"
            placeholder="Name, e.g. Pneumonia, uncomplicated"
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
