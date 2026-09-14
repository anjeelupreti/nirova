/**
 * Templates, where the prescribing happens.
 *
 * A clinic doctor writes "Amoxicillin 500 mg, 1 capsule three times daily for
 * five days, after food" forty times in a morning. Forty chances to type 5 mg
 * for 500, or to leave the duration off. This is the list of scripts they
 * already agreed with themselves, one click from the form.
 *
 * **Applying one fills the form; it does not prescribe.** The lines land in
 * the editor, the allergy and interaction checks run on them as on anything
 * typed, and the prescriber signs. A template that wrote a prescription would
 * be a prescription nobody read — which is the whole risk of templates in a
 * clinical system and the reason this one stops short of it.
 *
 * **Mine and ours.** Everybody sees the organization's list and their own;
 * saving into the organization's needs `catalog.manage`, because it changes
 * what every prescriber here is offered.
 */

import { useCallback, useEffect, useState } from "react";
import { BookmarkPlus, ChevronDown, FileText, Loader2, Trash2 } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { PrescriptionLineInput } from "@/types";
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Input,
  Label,
} from "@/components/ui/primitives";

export interface TemplateLine extends PrescriptionLineInput {
  quantity?: string;
  quantity_unit?: string;
  frequency_label?: string;
}

export interface Template {
  uuid: string;
  name: string;
  description: string;
  shared: boolean;
  owner_name: string;
  tags: string[];
  patient_instructions: string;
  times_used: number;
  lines: TemplateLine[];
}

export function PrescriptionTemplates({
  lines,
  onApply,
}: {
  /** What is on the form now, for "save these as a template". */
  lines: PrescriptionLineInput[];
  onApply: (lines: PrescriptionLineInput[], patientInstructions: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [mayCurate, setMayCurate] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api.get<{ results: Template[]; may_curate: boolean }>(
        "/clinical/prescription-templates/",
      );
      setTemplates(body.results);
      setMayCurate(body.may_curate);
      setProblem(null);
    } catch (err) {
      // A prescriber without the permission simply has no templates; this is
      // an aid, not a part of the record.
      if (err instanceof ApiError && err.status === 403) return;
      setProblem(err instanceof ApiError ? err.message : "Templates could not be read.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function apply(template: Template) {
    setBusy(true);
    setProblem(null);
    try {
      const body = await api.post<Template>(`/clinical/prescription-templates/${template.uuid}/`);
      onApply(
        body.lines.map((line) => ({
          generic_name: line.generic_name,
          brand_name: line.brand_name ?? "",
          strength: line.strength,
          dose: line.dose,
          route: line.route,
          frequency: line.frequency,
          duration_days: line.duration_days,
          is_prn: line.is_prn,
          prn_indication: line.prn_indication,
          instructions: line.instructions,
        })),
        body.patient_instructions,
      );
      setOpen(false);
      void load();
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
      await api.post("/clinical/prescription-templates/", {
        name,
        shared,
        lines: lines.filter((line) => line.generic_name.trim()),
      });
      setSaving(false);
      setName("");
      setShared(false);
      void load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function retire(template: Template) {
    try {
      await api.del(`/clinical/prescription-templates/${template.uuid}/`);
      void load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That could not be removed.");
    }
  }

  const writable = lines.some((line) => line.generic_name.trim());

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => setOpen((value) => !value)}>
          <FileText className="h-4 w-4" />
          Templates
          {templates.length > 0 ? (
            <Badge variant="secondary" className="ml-1">
              {templates.length}
            </Badge>
          ) : null}
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
        </Button>

        {writable ? (
          <Button size="sm" variant="ghost" onClick={() => setSaving((value) => !value)}>
            <BookmarkPlus className="h-4 w-4" />
            Save as template
          </Button>
        ) : null}
      </div>

      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}

      {saving ? (
        <div className="flex flex-wrap items-end gap-2 rounded-md border p-3">
          <div className="min-w-[14rem] flex-1 space-y-1">
            <Label className="text-xs">Name it as you would search for it</Label>
            <Input
              autoFocus
              placeholder="Adult URTI"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          {mayCurate ? (
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={shared}
                onChange={(event) => setShared(event.target.checked)}
              />
              Share with everybody here
            </label>
          ) : null}
          <Button size="sm" disabled={!name.trim() || busy} onClick={() => void save()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSaving(false)}>
            Cancel
          </Button>
        </div>
      ) : null}

      {open ? (
        <div className="divide-y rounded-md border">
          {templates.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              No templates yet. Write a prescription you use often and save it here.
            </p>
          ) : (
            templates.map((template) => (
              <div key={template.uuid} className="flex items-start gap-3 p-3">
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  disabled={busy}
                  onClick={() => void apply(template)}
                >
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">{template.name}</span>
                    {template.shared ? (
                      <Badge variant="secondary">Shared</Badge>
                    ) : null}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {template.lines
                      .map((line) =>
                        [line.generic_name, line.strength, line.frequency_label ?? line.frequency]
                          .filter(Boolean)
                          .join(" "),
                      )
                      .join(" · ")}
                  </span>
                </button>
                <span className="shrink-0 pt-0.5 text-xs text-muted-foreground">
                  used {template.times_used}×
                </span>
                {!template.shared || mayCurate ? (
                  <button
                    type="button"
                    aria-label={`Remove ${template.name}`}
                    className="shrink-0 rounded-sm p-1 text-muted-foreground hover:text-destructive"
                    onClick={() => void retire(template)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
