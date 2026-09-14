/**
 * What is for sale — edited here, by the people who sell it.
 *
 * The catalogue has been complete since the platform app was written and
 * reachable only by a seed: pricing a module or opening a trial meant a
 * developer and a deployment. This is the screen that ends that.
 *
 * **A plan is a matrix, so it is edited as one.** Modules down the page,
 * included or not, with the price to add one that is not. Features the same.
 * Limits with their ceiling, their enforcement and the point at which the
 * customer is warned. Each block saves on its own, because they are separate
 * promises and a half-saved plan is worse than an unsaved one.
 *
 * **A change that takes something away stops and says who loses what.** The
 * API refuses with the number of live organizations and their names attached
 * (`catalog/editing.py`), and this screen shows exactly that before asking
 * again. "Are you sure?" is a dialogue nobody reads; "this removes Laboratory
 * from 14 organizations, including Manakamana Health" is one they do.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Plus, Save } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
} from "@/components/ui/primitives";

interface ModuleRow {
  code: string;
  name: string;
  description: string;
  is_core: boolean;
  is_active: boolean;
  known: boolean;
}

interface FeatureRow {
  code: string;
  name: string;
  module: string;
  is_active: boolean;
  known: boolean;
}

interface PlanRow {
  uuid: string;
  code: string;
  name: string;
  tagline: string;
  description: string;
  base_price: string;
  currency: string;
  billing_interval: string;
  setup_fee: string;
  trial_days: number;
  grace_days: number;
  is_public: boolean;
  is_active: boolean;
  display_order: number;
  version: number;
  modules: Record<string, { is_included: boolean; additional_price: string }>;
  features: Record<string, boolean>;
  limits: Record<
    string,
    {
      value: number | null;
      enforcement: string;
      warn_at_percent: number;
      overage_unit_price: string | null;
    }
  >;
  subscribers: number;
}

interface Catalogue {
  modules: ModuleRow[];
  features: FeatureRow[];
  limit_keys: string[];
  plans: PlanRow[];
}

interface Impact {
  organizations: number;
  names: string[];
  removes_modules: string[];
  removes_features: string[];
  lowers_limits: string[];
  loses_something: boolean;
}

const humanise = (value: string) => value.replace(/_/g, " ");

export function Catalogue() {
  const [data, setData] = useState<Catalogue | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api.get<Catalogue>("/platform/catalogue/", {
        withoutOrganization: true,
      });
      setData(body);
      setChosen((current) => current || body.plans[0]?.code || "");
      setProblem(null);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "The catalogue could not be read.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (problem) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    );
  }
  if (!data) return <p className="text-sm text-muted-foreground">Loading the catalogue…</p>;

  const plan = data.plans.find((row) => row.code === chosen) ?? data.plans[0];

  return (
    <div className="space-y-4">
      {note ? (
        <Alert>
          <Check className="h-4 w-4" />
          <AlertDescription>{note}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Plans</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 px-2 pb-3">
            {data.plans.map((row) => (
              <button
                key={row.code}
                type="button"
                onClick={() => setChosen(row.code)}
                className={cn(
                  "w-full rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-accent",
                  row.code === plan?.code && "bg-accent",
                  !row.is_active && "opacity-60",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{row.name}</span>
                  {!row.is_public ? <Badge variant="outline">private</Badge> : null}
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {row.currency} {Number(row.base_price).toLocaleString("en-IN")} ·{" "}
                  {row.subscribers} live
                </span>
              </button>
            ))}
            <NewPlan onCreated={(code) => { setChosen(code); void load(); }} />
          </CardContent>
        </Card>

        {plan ? (
          <div className="space-y-4">
            <PlanFields plan={plan} onSaved={(message) => { setNote(message); void load(); }} />
            <PlanMatrix
              plan={plan}
              catalogue={data}
              onSaved={(message) => { setNote(message); void load(); }}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The plan's own fields                                                       */
/* -------------------------------------------------------------------------- */

function PlanFields({ plan, onSaved }: { plan: PlanRow; onSaved: (message: string) => void }) {
  const [draft, setDraft] = useState(plan);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => setDraft(plan), [plan]);

  const set = (key: keyof PlanRow, value: unknown) =>
    setDraft((current) => ({ ...current, [key]: value }) as PlanRow);

  async function save() {
    setBusy(true);
    setProblem(null);
    try {
      await api.patch(
        `/platform/catalogue/plans/${plan.code}/`,
        {
          name: draft.name,
          tagline: draft.tagline,
          base_price: draft.base_price,
          setup_fee: draft.setup_fee,
          billing_interval: draft.billing_interval,
          trial_days: Number(draft.trial_days),
          grace_days: Number(draft.grace_days),
          is_public: draft.is_public,
          is_active: draft.is_active,
          display_order: Number(draft.display_order),
        },
        { withoutOrganization: true },
      );
      onSaved(`${draft.name} saved.`);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          {plan.name}
          <Badge variant="secondary">{plan.code}</Badge>
          {plan.subscribers > 0 ? (
            <span className="text-xs font-normal text-muted-foreground">
              {plan.subscribers} organization{plan.subscribers === 1 ? "" : "s"} on it
            </span>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {problem ? (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Name">
            <Input value={draft.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Price">
            <Input
              inputMode="decimal"
              value={draft.base_price}
              onChange={(e) => set("base_price", e.target.value)}
            />
          </Field>
          <Field label="Billing">
            <Select
              value={draft.billing_interval}
              onChange={(e) => set("billing_interval", e.target.value)}
            >
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="yearly">Yearly</option>
            </Select>
          </Field>
          <Field label="Setup fee">
            <Input
              inputMode="decimal"
              value={draft.setup_fee}
              onChange={(e) => set("setup_fee", e.target.value)}
            />
          </Field>
          <Field label="Trial days">
            <Input
              inputMode="numeric"
              value={String(draft.trial_days)}
              onChange={(e) => set("trial_days", e.target.value)}
            />
          </Field>
          <Field label="Grace days">
            <Input
              inputMode="numeric"
              value={String(draft.grace_days)}
              onChange={(e) => set("grace_days", e.target.value)}
            />
          </Field>
          <Field label="Tagline" className="sm:col-span-2 lg:col-span-3">
            <Input value={draft.tagline} onChange={(e) => set("tagline", e.target.value)} />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <Toggle
            checked={draft.is_public}
            onChange={(value) => set("is_public", value)}
            label="On the public price list"
          />
          <Toggle
            checked={draft.is_active}
            onChange={(value) => set("is_active", value)}
            label="Can be sold"
          />
          <Button className="ml-auto" disabled={busy} onClick={() => void save()}>
            <Save className="h-4 w-4" />
            Save plan
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="h-4 w-4"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

/* -------------------------------------------------------------------------- */
/* Modules, features and limits                                                */
/* -------------------------------------------------------------------------- */

function PlanMatrix({
  plan,
  catalogue,
  onSaved,
}: {
  plan: PlanRow;
  catalogue: Catalogue;
  onSaved: (message: string) => void;
}) {
  const [modules, setModules] = useState(plan.modules);
  const [features, setFeatures] = useState(plan.features);
  const [limits, setLimits] = useState(plan.limits);
  const [pending, setPending] = useState<{ part: string; impact: Impact; message: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    setModules(plan.modules);
    setFeatures(plan.features);
    setLimits(plan.limits);
    setPending(null);
  }, [plan]);

  async function save(part: "modules" | "features" | "limits", confirm = false) {
    setBusy(part);
    setProblem(null);
    const payload =
      part === "modules" ? { modules } : part === "features" ? { features } : { limits };
    try {
      await api.put(
        `/platform/catalogue/plans/${plan.code}/${part}/`,
        { ...payload, confirm },
        { withoutOrganization: true },
      );
      setPending(null);
      onSaved(`${plan.name}: ${part} saved.`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "needs_confirmation") {
        const impact = (err.detail as { impact?: Impact })?.impact;
        if (impact) {
          setPending({ part, impact, message: err.message });
          return;
        }
      }
      setProblem(err instanceof ApiError ? err.message : "That could not be saved.");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      {problem ? (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      ) : null}

      {pending ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>This takes something away from live customers</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>{pending.message}</p>
            {pending.impact.names.length > 0 ? (
              <p className="text-sm">
                Affected: {pending.impact.names.join(", ")}
                {pending.impact.organizations > pending.impact.names.length
                  ? ` and ${pending.impact.organizations - pending.impact.names.length} more`
                  : ""}
                .
              </p>
            ) : null}
            <div className="flex gap-2 pt-1">
              <Button
                variant="destructive"
                size="sm"
                onClick={() => void save(pending.part as "modules", true)}
              >
                Apply anyway
              </Button>
              <Button variant="outline" size="sm" onClick={() => setPending(null)}>
                Leave it
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-base">Modules</CardTitle>
          <Button size="sm" disabled={busy === "modules"} onClick={() => void save("modules")}>
            <Save className="h-4 w-4" /> Save modules
          </Button>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2">
          {catalogue.modules.map((module) => {
            const row = modules[module.code] ?? { is_included: false, additional_price: "0.00" };
            return (
              <div
                key={module.code}
                className="flex items-center gap-3 rounded-md border px-3 py-2"
              >
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={row.is_included}
                  onChange={(event) =>
                    setModules((current) => ({
                      ...current,
                      [module.code]: { ...row, is_included: event.target.checked },
                    }))
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{module.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {module.code}
                    {!module.known ? " · not enforced by the application" : ""}
                  </span>
                </span>
                {!row.is_included ? (
                  <Input
                    className="h-8 w-24"
                    inputMode="decimal"
                    aria-label={`Price to add ${module.name}`}
                    value={row.additional_price}
                    onChange={(event) =>
                      setModules((current) => ({
                        ...current,
                        [module.code]: { ...row, additional_price: event.target.value },
                      }))
                    }
                  />
                ) : null}
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-base">Features</CardTitle>
          <Button size="sm" disabled={busy === "features"} onClick={() => void save("features")}>
            <Save className="h-4 w-4" /> Save features
          </Button>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {catalogue.features.map((feature) => (
            <label
              key={feature.code}
              className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
            >
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={Boolean(features[feature.code])}
                onChange={(event) =>
                  setFeatures((current) => ({ ...current, [feature.code]: event.target.checked }))
                }
              />
              <span className="min-w-0 truncate">{feature.name || humanise(feature.code)}</span>
            </label>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <div>
            <CardTitle className="text-base">Limits</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Blank is unlimited; 0 is none allowed. They are different promises.
            </p>
          </div>
          <Button size="sm" disabled={busy === "limits"} onClick={() => void save("limits")}>
            <Save className="h-4 w-4" /> Save limits
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {Object.entries(limits).map(([key, row]) => (
            <div key={key} className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2">
              <span className="min-w-0 flex-1 truncate text-sm">{humanise(key)}</span>
              <Input
                className="h-8 w-24"
                inputMode="numeric"
                placeholder="∞"
                aria-label={`${key} ceiling`}
                value={row.value === null ? "" : String(row.value)}
                onChange={(event) =>
                  setLimits((current) => ({
                    ...current,
                    [key]: {
                      ...row,
                      value: event.target.value === "" ? null : Number(event.target.value),
                    },
                  }))
                }
              />
              <Select
                className="h-8 w-32"
                aria-label={`${key} enforcement`}
                value={row.enforcement}
                onChange={(event) =>
                  setLimits((current) => ({
                    ...current,
                    [key]: { ...row, enforcement: event.target.value },
                  }))
                }
              >
                <option value="hard">Hard stop</option>
                <option value="soft">Warn only</option>
                <option value="metered">Metered</option>
              </Select>
            </div>
          ))}

          <AddLimit
            keys={catalogue.limit_keys.filter((key) => !(key in limits))}
            onAdd={(key) =>
              setLimits((current) => ({
                ...current,
                [key]: {
                  value: null,
                  enforcement: "hard",
                  warn_at_percent: 80,
                  overage_unit_price: null,
                },
              }))
            }
          />
        </CardContent>
      </Card>
    </>
  );
}

function AddLimit({ keys, onAdd }: { keys: string[]; onAdd: (key: string) => void }) {
  const [key, setKey] = useState("");
  if (keys.length === 0) return null;
  return (
    <div className="flex items-center gap-2 pt-1">
      <Select
        className="h-8 w-64"
        aria-label="Add a limit"
        value={key}
        onChange={(event) => setKey(event.target.value)}
      >
        <option value="">Add a limit…</option>
        {keys.map((option) => (
          <option key={option} value={option}>
            {humanise(option)}
          </option>
        ))}
      </Select>
      <Button
        size="sm"
        variant="outline"
        disabled={!key}
        onClick={() => {
          onAdd(key);
          setKey("");
        }}
      >
        <Plus className="h-4 w-4" /> Add
      </Button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* A new plan                                                                  */
/* -------------------------------------------------------------------------- */

function NewPlan({ onCreated }: { onCreated: (code: string) => void }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  if (!open) {
    return (
      <Button variant="outline" size="sm" className="mt-2 w-full" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" /> New plan
      </Button>
    );
  }

  async function create() {
    setProblem(null);
    try {
      await api.post(
        "/platform/catalogue/",
        { code, name, base_price: "0.00", is_public: false, is_active: true },
        { withoutOrganization: true },
      );
      setOpen(false);
      setCode("");
      setName("");
      onCreated(code);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That plan could not be created.");
    }
  }

  return (
    <div className="mt-2 space-y-2 rounded-md border p-2">
      <Input
        placeholder="code, e.g. practice"
        value={code}
        onChange={(event) => setCode(event.target.value.toLowerCase())}
      />
      <Input placeholder="Name" value={name} onChange={(event) => setName(event.target.value)} />
      {problem ? <p className="text-xs text-destructive">{problem}</p> : null}
      <div className="flex gap-2">
        <Button size="sm" disabled={!code} onClick={() => void create()}>
          Create
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
