/**
 * The settings a customer may change about their own system.
 *
 * Until the settings API existed, `ConfigSetting` had no endpoint at all —
 * so the privacy switch and the whole locale layer (time zone, financial
 * year, tax rate) could only be changed from a Django shell. This is the
 * screen that makes them reachable by the person who owns the decision.
 *
 * **Rendered from the server's registry, not from a list here.** The API
 * publishes each setting's kind, its choices, its default and its caution.
 * A second copy of the fiscal calendars in this file would be a second thing
 * to update, and the copy is always the one that gets forgotten.
 *
 * Two facts the API sends that this screen leans on:
 *
 * * `is_set` — whether somebody chose the value or whether it is simply what
 *   everybody gets. "13.00" alone does not say, and the difference is the
 *   whole question when you are deciding whether to touch it.
 * * `caution` — shown *before* the change, not after. A warning that appears
 *   once you have already saved is a receipt, not a warning.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, RotateCcw } from "lucide-react";

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
  Input,
  Label,
  Select,
} from "@/components/ui/primitives";
import { useSession } from "@/hooks/useSession";
import api, { ApiError } from "@/lib/api";

interface Choice {
  value: string;
  label: string;
}

interface SystemSetting {
  code: string;
  namespace: string;
  key: string;
  label: string;
  description: string;
  kind: "boolean" | "choice" | "decimal" | "string";
  choices: Choice[];
  default: unknown;
  value: unknown;
  per_facility: boolean;
  caution: string;
  is_set: boolean;
  set_at: string;
  is_locked: boolean;
}

export default function SystemSettings() {
  const { can } = useSession();
  const mayChange = can("config.update", "own");

  const [settings, setSettings] = useState<SystemSetting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [problem, setProblem] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setError(null);
    try {
      const body = await api.get<{ settings: SystemSetting[] }>(
        "/org/settings/",
      );
      setSettings(body.settings);
    } catch (err) {
      setSettings([]);
      setError(
        err instanceof ApiError ? err.message : "Could not load settings.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(setting: SystemSetting, value: unknown) {
    setSaving(setting.code);
    setProblem((current) => ({ ...current, [setting.code]: "" }));
    try {
      await api.put("/org/settings/", { code: setting.code, value });
      await load();
    } catch (err) {
      // The server's message is the useful part: it names the setting and
      // says what a valid answer looks like. Replacing it with "invalid"
      // throws away the only thing that tells somebody what to type instead.
      setProblem((current) => ({
        ...current,
        [setting.code]:
          err instanceof ApiError ? err.message : "That could not be saved.",
      }));
    } finally {
      setSaving(null);
    }
  }

  async function reset(setting: SystemSetting) {
    setSaving(setting.code);
    try {
      await api.del(`/org/settings/?code=${encodeURIComponent(setting.code)}`);
      await load();
    } catch (err) {
      setProblem((current) => ({
        ...current,
        [setting.code]:
          err instanceof ApiError ? err.message : "Could not reset it.",
      }));
    } finally {
      setSaving(null);
    }
  }

  if (settings === null) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  if (error) {
    return (
      <Alert variant="warning">
        <AlertTitle>Not shown</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      {!mayChange && (
        <Alert>
          <AlertTitle>Read only</AlertTitle>
          <AlertDescription>
            You can see how this system is configured. Changing it needs the
            configuration permission.
          </AlertDescription>
        </Alert>
      )}

      {settings.map((setting) => (
        <Card key={setting.code}>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <CardTitle className="text-base">{setting.label}</CardTitle>
                <CardDescription>{setting.description}</CardDescription>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {setting.is_set ? (
                  <Badge variant="secondary">
                    set · {setting.set_at || "organization"}
                  </Badge>
                ) : (
                  /* Not the same as a value. Saying "default" is what stops
                     somebody reading an inherited number as a decision. */
                  <Badge variant="outline">default</Badge>
                )}
                {setting.is_locked && <Badge>locked</Badge>}
              </div>
            </div>
          </CardHeader>

          <CardContent className="space-y-3">
            {setting.caution && (
              <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning-subtle p-2 text-xs text-warning-subtle-foreground">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {setting.caution}
              </p>
            )}

            <Control
              setting={setting}
              disabled={!mayChange || setting.is_locked || saving === setting.code}
              busy={saving === setting.code}
              onSave={(value) => void save(setting, value)}
            />

            {problem[setting.code] && (
              <p className="text-xs text-destructive">{problem[setting.code]}</p>
            )}

            {mayChange && setting.is_set && !setting.is_locked && (
              <Button
                size="sm"
                variant="ghost"
                disabled={saving === setting.code}
                onClick={() => void reset(setting)}
              >
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                Back to the default ({String(setting.default)})
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The control                                                                */
/* -------------------------------------------------------------------------- */

function Control({
  setting,
  disabled,
  busy,
  onSave,
}: {
  setting: SystemSetting;
  disabled: boolean;
  busy: boolean;
  onSave: (value: unknown) => void;
}) {
  const [draft, setDraft] = useState(String(setting.value ?? ""));

  // Re-synced when the server's value changes, so a save the server rejected
  // does not leave the box showing a value that was never stored.
  useEffect(() => {
    setDraft(String(setting.value ?? ""));
  }, [setting.value]);

  if (setting.kind === "boolean") {
    // Saved on the click. A toggle with a separate save button invites the
    // reading that it is already on, which for a privacy control is the
    // wrong thing to be wrong about.
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="h-4 w-4"
          disabled={disabled}
          checked={setting.value === true || setting.value === "true"}
          onChange={(event) => onSave(event.target.checked)}
        />
        {setting.value === true ? "On" : "Off"}
        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      </label>
    );
  }

  if (setting.kind === "choice") {
    return (
      <div className="flex items-center gap-2">
        <Select
          value={String(setting.value ?? "")}
          disabled={disabled}
          onChange={(event) => onSave(event.target.value)}
          aria-label={setting.label}
        >
          {setting.choices.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </Select>
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
      </div>
    );
  }

  const unchanged = draft === String(setting.value ?? "");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="min-w-0 flex-1">
        <Label htmlFor={setting.code} className="sr-only">
          {setting.label}
        </Label>
        <Input
          id={setting.code}
          value={draft}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={String(setting.default ?? "")}
          inputMode={setting.kind === "decimal" ? "decimal" : "text"}
        />
      </div>
      <Button
        size="sm"
        disabled={disabled || unchanged}
        onClick={() => onSave(draft)}
      >
        {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
        Save
      </Button>
    </div>
  );
}
