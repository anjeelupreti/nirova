/**
 * The consultation screen: one encounter, from vitals to prescription.
 *
 * Laid out in the order a consultation actually happens, top to bottom, so a
 * clinician with ninety seconds per patient never has to hunt for the next
 * step. Safety information — allergies, alerts — sits above everything and
 * stays there, because it is the one thing that must not be scrolled past.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  FlaskConical,
  Pill,
  ShieldAlert,
  Stethoscope,
  Trash2,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  ClinicalSummary,
  DiagnosticOrder,
  EncounterDetail,
  Paginated,
  PrescriptionLineInput,
  SafetyReport,
  TestDefinition,
} from "@/types";
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
  Textarea,
} from "@/components/ui/primitives";

const SEVERITY_STYLE: Record<string, string> = {
  critical: "border-destructive/50 bg-destructive/10 text-destructive",
  high: "border-destructive/40 bg-destructive/5 text-destructive",
  moderate: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  info: "border-primary/30 bg-primary/5",
};

const EMPTY_LINE: PrescriptionLineInput = {
  generic_name: "",
  strength: "",
  dose: "",
  route: "PO",
  frequency: "BD",
  duration_days: 5,
  is_prn: false,
  prn_indication: "",
  instructions: "",
};

/* -------------------------------------------------------------------------- */
/* Safety banner                                                               */
/* -------------------------------------------------------------------------- */

function SafetyBanner({ summary }: { summary: ClinicalSummary }) {
  const { allergies, patient } = summary;
  if (!allergies.length && !patient.alerts) return null;

  return (
    <div className="space-y-2">
      {patient.alerts && (
        <Alert variant="warning">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>Alert</AlertTitle>
          <AlertDescription>{patient.alerts}</AlertDescription>
        </Alert>
      )}
      {allergies.length > 0 && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {allergies.length === 1 ? "Allergy" : "Allergies"}
          </AlertTitle>
          <AlertDescription>
            <ul className="ml-4 list-disc space-y-0.5">
              {allergies.map((allergy) => (
                <li key={allergy.substance}>
                  <span className="font-medium">{allergy.substance}</span>
                  {allergy.reaction && ` — ${allergy.reaction}`}
                  <span className="ml-1 text-xs opacity-75">
                    ({allergy.severity.replace(/_/g, " ")}
                    {allergy.status === "unconfirmed" && ", unconfirmed"})
                  </span>
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Vitals                                                                      */
/* -------------------------------------------------------------------------- */

const VITAL_FIELDS: { key: string; label: string; unit: string }[] = [
  { key: "temperature_c", label: "Temperature", unit: "°C" },
  { key: "pulse_bpm", label: "Pulse", unit: "bpm" },
  { key: "respiratory_rate", label: "Resp. rate", unit: "/min" },
  { key: "systolic_bp", label: "Systolic", unit: "mmHg" },
  { key: "diastolic_bp", label: "Diastolic", unit: "mmHg" },
  { key: "spo2_percent", label: "SpO₂", unit: "%" },
  { key: "weight_kg", label: "Weight", unit: "kg" },
  { key: "height_cm", label: "Height", unit: "cm" },
];

function VitalsPanel({
  encounter,
  onSaved,
}: {
  encounter: EncounterDetail;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setError(null);
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(values)) {
        if (value !== "") payload[key] = value;
      }
      await api.post(`/clinical/encounters/${encounter.uuid}/vitals/`, payload);
      setValues({});
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save vitals.");
    } finally {
      setBusy(false);
    }
  }

  const latest = encounter.vitals[0];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-muted-foreground" />
          Vitals
        </CardTitle>
        <CardDescription>
          Record what was measured. Nothing is required — a triage temperature
          alone is a valid set.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {latest && (
          <div className="rounded-md border bg-muted/30 p-3">
            <p className="mb-2 text-xs text-muted-foreground">
              Last recorded {new Date(latest.recorded_at).toLocaleTimeString()}
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {latest.temperature_c && <span>{latest.temperature_c} °C</span>}
              {latest.pulse_bpm && <span>{latest.pulse_bpm} bpm</span>}
              {latest.blood_pressure && <span>{latest.blood_pressure} mmHg</span>}
              {latest.spo2_percent && <span>SpO₂ {latest.spo2_percent}%</span>}
              {latest.bmi && <span>BMI {latest.bmi}</span>}
            </div>
            {latest.abnormal.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {latest.abnormal.map((flag) => (
                  <Badge
                    key={flag.field}
                    variant={flag.level === "critical" ? "destructive" : "warning"}
                  >
                    {flag.note}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {VITAL_FIELDS.map((field) => (
            <div key={field.key} className="space-y-1">
              <Label htmlFor={field.key} className="text-xs">
                {field.label}{" "}
                <span className="text-muted-foreground">{field.unit}</span>
              </Label>
              <Input
                id={field.key}
                inputMode="decimal"
                value={values[field.key] ?? ""}
                onChange={(e) =>
                  setValues({ ...values, [field.key]: e.target.value })
                }
              />
            </div>
          ))}
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button
          size="sm"
          onClick={() => void save()}
          disabled={busy || Object.values(values).every((v) => v === "")}
        >
          Record vitals
        </Button>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* SOAP note                                                                   */
/* -------------------------------------------------------------------------- */

const SOAP_FIELDS = [
  { key: "subjective", label: "Subjective", hint: "What the patient reports" },
  { key: "objective", label: "Objective", hint: "Examination and findings" },
  { key: "assessment", label: "Assessment", hint: "Your conclusion" },
  { key: "plan", label: "Plan", hint: "Treatment, orders, advice" },
] as const;

function NotePanel({
  encounter,
  onSaved,
}: {
  encounter: EncounterDetail;
  onSaved: () => void;
}) {
  const [note, setNote] = useState({
    subjective: "",
    objective: "",
    assessment: "",
    plan: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const hasContent = Object.values(note).some((v) => v.trim());

  async function save(sign: boolean) {
    setError(null);
    setBusy(true);
    try {
      await api.post(`/clinical/encounters/${encounter.uuid}/notes/`, {
        ...note,
        note_type: "soap",
        sign,
      });
      setNote({ subjective: "", objective: "", assessment: "", plan: "" });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-muted-foreground" />
          Clinical note
        </CardTitle>
        <CardDescription>
          Signing locks the note. Corrections after that are amendments, which
          stay visible alongside the original.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {encounter.notes.length > 0 && (
          <div className="space-y-2">
            {encounter.notes.map((existing) => (
              <div
                key={existing.uuid}
                className="rounded-md border bg-muted/30 p-3 text-sm"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {existing.note_type}
                    {existing.is_amendment && " · amendment"}
                  </span>
                  <Badge variant={existing.is_signed ? "success" : "secondary"}>
                    {existing.is_signed ? "signed" : "draft"}
                  </Badge>
                </div>
                {existing.assessment && (
                  <p>
                    <span className="text-muted-foreground">A: </span>
                    {existing.assessment}
                  </p>
                )}
                {existing.plan && (
                  <p>
                    <span className="text-muted-foreground">P: </span>
                    {existing.plan}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {SOAP_FIELDS.map((field) => (
          <div key={field.key} className="space-y-1">
            <Label htmlFor={field.key}>
              {field.label}{" "}
              <span className="font-normal text-muted-foreground">
                — {field.hint}
              </span>
            </Label>
            <Textarea
              id={field.key}
              rows={2}
              value={note[field.key]}
              onChange={(e) => setNote({ ...note, [field.key]: e.target.value })}
            />
          </div>
        ))}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !hasContent}
            onClick={() => void save(false)}
          >
            Save draft
          </Button>
          <Button size="sm" disabled={busy || !hasContent} onClick={() => void save(true)}>
            Sign note
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Prescription                                                                */
/* -------------------------------------------------------------------------- */

function PrescribePanel({
  encounter,
  facilityUuid,
  onSaved,
}: {
  encounter: EncounterDetail;
  facilityUuid: string;
  onSaved: () => void;
}) {
  const [lines, setLines] = useState<PrescriptionLineInput[]>([{ ...EMPTY_LINE }]);
  const [safety, setSafety] = useState<SafetyReport | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const namedLines = lines.filter((line) => line.generic_name.trim());

  // Re-check safety whenever the medicine list changes. Debounced, because an
  // allergy warning is most useful while the prescriber is still typing —
  // not as a rejection after they commit.
  useEffect(() => {
    if (namedLines.length === 0) {
      setSafety(null);
      return;
    }
    const handle = setTimeout(() => {
      api
        .post<SafetyReport>("/clinical/prescriptions/preview/", {
          patient_uuid: encounter.patient,
          lines: namedLines.map((line) => ({
            ...line,
            dose: line.dose || "1",
          })),
        })
        .then(setSafety)
        .catch(() => setSafety(null));
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(namedLines), encounter.patient]);

  function updateLine(index: number, patch: Partial<PrescriptionLineInput>) {
    setLines(lines.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }

  async function submit() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const created = await api.post<{ reference: string }>(
        "/clinical/prescriptions/",
        {
          patient_uuid: encounter.patient,
          facility_uuid: facilityUuid,
          encounter_uuid: encounter.uuid,
          lines: namedLines,
          override_reason: overrideReason,
        },
      );
      setNotice(`${created.reference} signed`);
      setLines([{ ...EMPTY_LINE }]);
      setOverrideReason("");
      setSafety(null);
      onSaved();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not write the prescription.",
      );
    } finally {
      setBusy(false);
    }
  }

  const needsReason = safety?.requires_override && !overrideReason.trim();

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <Pill className="h-4 w-4 text-muted-foreground" />
          Prescription
        </CardTitle>
        <CardDescription>
          Checked against this patient's allergies and the rest of the list as
          you type.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {lines.map((line, index) => (
          <div key={index} className="space-y-2 rounded-md border p-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="space-y-1">
                <Label className="text-xs">Medicine (generic)</Label>
                <Input
                  value={line.generic_name}
                  placeholder="Amoxicillin"
                  onChange={(e) =>
                    updateLine(index, { generic_name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Strength</Label>
                <Input
                  value={line.strength}
                  placeholder="500 mg"
                  onChange={(e) => updateLine(index, { strength: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Dose</Label>
                <Input
                  value={line.dose}
                  placeholder="1 capsule"
                  onChange={(e) => updateLine(index, { dose: e.target.value })}
                />
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-4">
              <div className="space-y-1">
                <Label className="text-xs">Route</Label>
                <Select
                  value={line.route}
                  onChange={(e) => updateLine(index, { route: e.target.value })}
                >
                  <option value="PO">By mouth</option>
                  <option value="IV">Intravenous</option>
                  <option value="IM">Intramuscular</option>
                  <option value="TOP">Topical</option>
                  <option value="INH">Inhaled</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Frequency</Label>
                <Select
                  value={line.frequency}
                  onChange={(e) =>
                    updateLine(index, {
                      frequency: e.target.value,
                      is_prn: e.target.value === "PRN",
                    })
                  }
                >
                  <option value="OD">Once daily</option>
                  <option value="BD">Twice daily</option>
                  <option value="TDS">Three times daily</option>
                  <option value="QDS">Four times daily</option>
                  <option value="NOCTE">At night</option>
                  <option value="PRN">As required</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Days</Label>
                <Input
                  type="number"
                  min={1}
                  value={line.duration_days ?? ""}
                  onChange={(e) =>
                    updateLine(index, {
                      duration_days: Number(e.target.value) || undefined,
                    })
                  }
                />
              </div>
              <div className="flex items-end">
                {lines.length > 1 && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setLines(lines.filter((_, i) => i !== index))
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                    Remove
                  </Button>
                )}
              </div>
            </div>

            {line.is_prn && (
              <div className="space-y-1">
                <Label className="text-xs">Required for</Label>
                <Input
                  value={line.prn_indication}
                  placeholder="fever or pain"
                  onChange={(e) =>
                    updateLine(index, { prn_indication: e.target.value })
                  }
                />
              </div>
            )}
          </div>
        ))}

        <Button
          size="sm"
          variant="outline"
          onClick={() => setLines([...lines, { ...EMPTY_LINE }])}
        >
          Add medicine
        </Button>

        {/* Warnings, most severe first. */}
        {safety && safety.warnings.length > 0 && (
          <div className="space-y-2">
            {[...safety.warnings]
              .sort((a, b) => {
                const order = ["critical", "high", "moderate", "info"];
                return order.indexOf(a.severity) - order.indexOf(b.severity);
              })
              .map((warning, index) => (
                <div
                  key={index}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm",
                    SEVERITY_STYLE[warning.severity] ?? SEVERITY_STYLE.info,
                  )}
                >
                  <span className="mr-1 text-xs font-semibold uppercase">
                    {warning.severity}
                  </span>
                  {warning.message}
                </div>
              ))}
          </div>
        )}

        {safety?.requires_override && (
          <div className="space-y-1">
            <Label htmlFor="override">
              Reason for prescribing despite the warning
            </Label>
            <Textarea
              id="override"
              rows={2}
              value={overrideReason}
              placeholder="This is kept on the record permanently."
              onChange={(e) => setOverrideReason(e.target.value)}
            />
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {notice && (
          <Alert variant="info">
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}

        <Button
          disabled={busy || namedLines.length === 0 || needsReason}
          onClick={() => void submit()}
        >
          {needsReason ? "Give a reason to continue" : "Sign prescription"}
        </Button>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Investigations                                                              */
/* -------------------------------------------------------------------------- */

const PRIORITY_OPTIONS = [
  ["routine", "Routine"],
  ["urgent", "Urgent"],
  ["stat", "STAT — now"],
] as const;

function InvestigationsPanel({
  encounter,
  facilityUuid,
}: {
  encounter: EncounterDetail;
  facilityUuid: string;
}) {
  const [tests, setTests] = useState<TestDefinition[]>([]);
  const [testUuid, setTestUuid] = useState("");
  const [priority, setPriority] = useState("routine");
  const [indication, setIndication] = useState("");
  const [orders, setOrders] = useState<DiagnosticOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadOrders = useCallback(async () => {
    const page = await api.get<Paginated<DiagnosticOrder>>(
      `/diagnostics/orders/?encounter=${encounter.uuid}`,
    );
    setOrders(page.results);
  }, [encounter.uuid]);

  useEffect(() => {
    // `orderable=true` hides panel members: a clinician orders the liver
    // function test, not its bilirubin component.
    api
      .get<Paginated<TestDefinition>>(
        "/diagnostics/tests/?orderable=true&page_size=200",
      )
      .then((page) => {
        setTests(page.results);
        if (page.results.length) setTestUuid(page.results[0].uuid);
      })
      .catch(() => undefined);
    void loadOrders();
  }, [loadOrders]);

  // A non-routine request must say what is being looked for. Mirrored from
  // the server so the button explains itself rather than failing on submit.
  const needsIndication = priority !== "routine" && !indication.trim();

  async function order() {
    setError(null);
    setBusy(true);
    try {
      await api.post("/diagnostics/orders/", {
        patient_uuid: encounter.patient,
        facility_uuid: facilityUuid,
        encounter_uuid: encounter.uuid,
        test_uuid: testUuid,
        priority,
        clinical_indication: indication,
      });
      setIndication("");
      setPriority("routine");
      await loadOrders();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not place the order.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-muted-foreground" />
          Investigations
        </CardTitle>
        <CardDescription>
          Ordering moves this encounter to awaiting results until everything
          is back.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {orders.length > 0 && (
          <div className="space-y-1.5">
            {orders.map((existing) => (
              <div
                key={existing.uuid}
                className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <span>
                  {existing.test_name}
                  <span className="ml-2 font-mono text-xs text-muted-foreground">
                    {existing.reference}
                  </span>
                </span>
                <Badge
                  variant={
                    existing.status === "released"
                      ? "success"
                      : existing.is_overdue
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {existing.status.replace(/_/g, " ")}
                </Badge>
              </div>
            ))}
          </div>
        )}

        <div className="space-y-1">
          <Label className="text-xs">Test</Label>
          <Select value={testUuid} onChange={(e) => setTestUuid(e.target.value)}>
            {tests.map((test) => (
              <option key={test.uuid} value={test.uuid}>
                {test.code} — {test.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Priority</Label>
          <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
            {PRIORITY_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">
            Clinical indication
            {priority !== "routine" && (
              <span className="ml-1 text-destructive">required</span>
            )}
          </Label>
          <Input
            value={indication}
            placeholder="What are you looking for?"
            onChange={(e) => setIndication(e.target.value)}
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button
          size="sm"
          disabled={busy || !testUuid || needsIndication}
          onClick={() => void order()}
        >
          {needsIndication ? "State the indication first" : "Order"}
        </Button>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function ConsultationPage() {
  const { uuid } = useParams<{ uuid: string }>();
  const [encounter, setEncounter] = useState<EncounterDetail | null>(null);
  const [summary, setSummary] = useState<ClinicalSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!uuid) return;
    try {
      const detail = await api.get<EncounterDetail>(
        `/clinical/encounters/${uuid}/`,
      );
      setEncounter(detail);
      const clinical = await api.get<ClinicalSummary>(
        `/clinical/patients/${detail.patient}/summary/`,
      );
      setSummary(clinical);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load the encounter.",
      );
    }
  }, [uuid]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!encounter || !summary) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Stethoscope className="h-5 w-5 text-muted-foreground" />
            {summary.patient.name}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {summary.patient.mrn} · {summary.patient.age ?? "age unknown"} ·{" "}
            {summary.patient.gender} · {encounter.reference}
          </p>
        </div>
        <Badge variant={encounter.is_open ? "warning" : "success"}>
          {encounter.status.replace(/_/g, " ")}
        </Badge>
      </div>

      <SafetyBanner summary={summary} />

      {encounter.chief_complaint && (
        <Card>
          <CardContent className="py-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Presenting complaint
            </p>
            <p className="mt-0.5">{encounter.chief_complaint}</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-5">
          <VitalsPanel encounter={encounter} onSaved={() => void load()} />
          <NotePanel encounter={encounter} onSaved={() => void load()} />
        </div>
        <div className="space-y-5">
          <PrescribePanel
            encounter={encounter}
            facilityUuid={encounter.facility ?? ""}
            onSaved={() => void load()}
          />

          <InvestigationsPanel
            encounter={encounter}
            facilityUuid={encounter.facility ?? ""}
          />

          {summary.conditions.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>Ongoing conditions</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {summary.conditions.map((condition) => (
                    <Badge key={condition.name} variant="outline">
                      {condition.name}
                      {condition.icd10_code && (
                        <span className="ml-1 opacity-60">
                          {condition.icd10_code}
                        </span>
                      )}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
