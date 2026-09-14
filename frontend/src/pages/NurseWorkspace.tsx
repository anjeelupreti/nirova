/**
 * Nurse & Bedside Clinical Workspace (§96 My Workspace, §28 Nursing)
 *
 * Dedicated, touch- and COW-friendly clinical console built for ward duty nurses:
 * 1. Nurse-to-Patient Assignment: Assigned beds for active shift (Morning, Evening, Night).
 * 2. Bedside Vitals Rounds & NEWS2: Real-time calculation of National Early Warning Score
 *    with automated clinical deterioration alerts and doctor escalation triggers.
 * 3. Electronic Medication Administration Record (eMAR): Scheduled doses, given/held/refused
 *    logging with mandatory clinical rationale and dual-signature witness sign-off.
 * 4. SBAR Shift Handover: Structured Situation-Background-Assessment-Recommendation notes
 *    with outgoing authoring and incoming nurse acknowledgement.
 * 5. Bedside Shift Tasks: Ward checklist for monitoring, line care, and dressings.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  BedDouble,
  CheckCircle2,
  Clock,
  ListTodo,
  Loader2,
  Pill,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  UserCheck,
  X,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { BedsidePatientCard } from "@/components/nursing/BedsidePatientCard";
import { cn } from "@/lib/utils";
import type {
  EmarLine,
  EmarResponse,
  Facility,
  NEWS2Score,
  NursePatientCard,
  NurseWorkspaceSummary,
  NursingTask,
  Paginated,
  Ward,
} from "@/types";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  Input,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/layout";
import { formatTime, formatWeekday } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* Helper Functions                                                           */
/* -------------------------------------------------------------------------- */

const SHIFT_LABELS: Record<string, { label: string; time: string; color: string }> = {
  morning: { label: "Morning Shift", time: "07:00 – 15:00", color: "bg-warning/10 text-warning border-warning/40" },
  evening: { label: "Evening Shift", time: "15:00 – 23:00", color: "bg-info/10 text-info border-info/40" },
  night: { label: "Night Shift", time: "23:00 – 07:00", color: "bg-info/10 text-info border-info/40" },
};

function liveCalculateNEWS2(values: {
  rr?: number;
  spo2?: number;
  onAir?: boolean;
  sbp?: number;
  hr?: number;
  gcs?: number;
  temp?: number;
}): NEWS2Score {
  let score = 0;
  const triggers: { parameter: string; score: number; value: string }[] = [];
  let extreme = false;

  // RR
  if (values.rr !== undefined && values.rr > 0) {
    let p = 0;
    if (values.rr <= 8) p = 3;
    else if (values.rr <= 11) p = 1;
    else if (values.rr <= 20) p = 0;
    else if (values.rr <= 24) p = 2;
    else p = 3;
    if (p > 0) {
      score += p;
      if (p === 3) extreme = true;
      triggers.push({ parameter: "Respiration rate", score: p, value: `${values.rr} bpm` });
    }
  }

  // SpO2
  if (values.spo2 !== undefined && values.spo2 > 0) {
    let p = 0;
    if (values.spo2 <= 91) p = 3;
    else if (values.spo2 <= 93) p = 2;
    else if (values.spo2 <= 95) p = 1;
    else p = 0;
    if (p > 0) {
      score += p;
      if (p === 3) extreme = true;
      triggers.push({ parameter: "SpO2", score: p, value: `${values.spo2}%` });
    }
  }

  // Oxygen
  if (values.onAir === false) {
    score += 2;
    triggers.push({ parameter: "Air or Oxygen", score: 2, value: "Supplemental O2" });
  }

  // SBP
  if (values.sbp !== undefined && values.sbp > 0) {
    let p = 0;
    if (values.sbp <= 90) p = 3;
    else if (values.sbp <= 100) p = 2;
    else if (values.sbp <= 110) p = 1;
    else if (values.sbp <= 219) p = 0;
    else p = 3;
    if (p > 0) {
      score += p;
      if (p === 3) extreme = true;
      triggers.push({ parameter: "Systolic BP", score: p, value: `${values.sbp} mmHg` });
    }
  }

  // HR
  if (values.hr !== undefined && values.hr > 0) {
    let p = 0;
    if (values.hr <= 40) p = 3;
    else if (values.hr <= 50) p = 1;
    else if (values.hr <= 90) p = 0;
    else if (values.hr <= 110) p = 1;
    else if (values.hr <= 130) p = 2;
    else p = 3;
    if (p > 0) {
      score += p;
      if (p === 3) extreme = true;
      triggers.push({ parameter: "Heart Rate", score: p, value: `${values.hr} bpm` });
    }
  }

  // GCS / Consciousness
  if (values.gcs !== undefined && values.gcs > 0 && values.gcs < 15) {
    score += 3;
    extreme = true;
    triggers.push({ parameter: "Consciousness", score: 3, value: `GCS ${values.gcs}` });
  }

  // Temp
  if (values.temp !== undefined && values.temp > 0) {
    let p = 0;
    if (values.temp <= 35.0) p = 3;
    else if (values.temp <= 36.0) p = 1;
    else if (values.temp <= 38.0) p = 0;
    else if (values.temp <= 39.0) p = 1;
    else p = 2;
    if (p > 0) {
      score += p;
      if (p === 3) extreme = true;
      triggers.push({ parameter: "Temperature", score: p, value: `${values.temp}°C` });
    }
  }

  let risk: "low" | "medium" | "high" = "low";
  let color: "green" | "amber" | "red" = "green";
  let recommendation = "Routine ward observation; monitor every 4 to 6 hours.";

  if (score >= 7) {
    risk = "high";
    color = "red";
    recommendation = "EMERGENCY: Immediate clinical / critical care review; continuous vital monitoring.";
  } else if (score >= 5 || extreme) {
    risk = "medium";
    color = "amber";
    recommendation = "URGENT: Clinician review within 1 hour; increase monitoring to hourly.";
  }

  return {
    score,
    risk_level: risk,
    color,
    recommendation,
    triggers,
    single_param_extreme: extreme,
  };
}

/* -------------------------------------------------------------------------- */
/* Main Page Component                                                        */
/* -------------------------------------------------------------------------- */

export default function NurseWorkspacePage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [selectedFacility, setSelectedFacility] = useState<string>("");
  const [wards, setWards] = useState<Ward[]>([]);
  const [selectedWard, setSelectedWard] = useState<string>("");
  const [scope, setScope] = useState<"mine" | "ward">("mine");
  const [shiftFilter, setShiftFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [riskFilter, setRiskFilter] = useState<string>("all");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<NurseWorkspaceSummary | null>(null);

  // Active modals
  const [selectedPatientForRound, setSelectedPatientForRound] = useState<NursePatientCard | null>(null);
  const [selectedPatientForEmar, setSelectedPatientForEmar] = useState<NursePatientCard | null>(null);
  const [selectedPatientForHandover, setSelectedPatientForHandover] = useState<NursePatientCard | null>(null);
  const [selectedPatientForTasks, setSelectedPatientForTasks] = useState<NursePatientCard | null>(null);
  const [showAssignModal, setShowAssignModal] = useState(false);

  // Initial facilities and wards load
  useEffect(() => {
    async function loadMeta() {
      try {
        const facRes = await api.get<Paginated<Facility>>("/org/facilities/");
        const facs = facRes.results ?? [];
        setFacilities(facs);
        // Wards are at the hospital. Defaulting to the first facility put a
        // nurse who covers the clinic and the hospital on the clinic, which
        // has one three-bed ward, and her fifty-bed hospital was a dropdown
        // away that nothing told her to open.
        const home = facs.find((row) => row.facility_type === "hospital") ?? facs[0];
        if (home) setSelectedFacility(home.uuid);

        const wardRes = await api.get<Paginated<Ward>>("/ipd/wards/");
        const wList = wardRes.results ?? [];
        setWards(wList);
      } catch (err) {
        console.error("Failed to load facility metadata", err);
      }
    }
    loadMeta();
  }, []);

  // Fetch summary
  const fetchSummary = useCallback(async (isBackground = false) => {
    if (!isBackground) setLoading(true);
    else setRefreshing(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (selectedFacility) params.set("facility", selectedFacility);
      if (selectedWard) params.set("ward", selectedWard);
      if (shiftFilter) params.set("shift", shiftFilter);
      params.set("scope", scope);

      const res = await api.get<NurseWorkspaceSummary>(`/ipd/nurse-workspace/summary/?${params.toString()}`);
      setSummary(res);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to load nurse workspace.");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedFacility, selectedWard, shiftFilter, scope]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  // Filtered patients
  const filteredPatients = useMemo(() => {
    if (!summary) return [];
    return summary.patients.filter((p) => {
      if (riskFilter !== "all" && p.news2.risk_level !== riskFilter) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = p.patient_name.toLowerCase().includes(q);
        const matchesMrn = p.patient_mrn.toLowerCase().includes(q);
        const matchesBed = p.bed_code.toLowerCase().includes(q);
        const matchesDiag = p.admitting_diagnosis.toLowerCase().includes(q);
        if (!matchesName && !matchesMrn && !matchesBed && !matchesDiag) {
          return false;
        }
      }
      return true;
    });
  }, [summary, riskFilter, searchQuery]);

  return (
    <div className="space-y-6">
      {/* -------------------------------------------------------------------- */}
      {/* Top Header & Workstation Bar                                         */}
      {/* -------------------------------------------------------------------- */}
      <div className="flex flex-col gap-4 border-b pb-4 lg:flex-row lg:items-center lg:justify-between">
        {/* The controls beside this stay where they are: there are six of them
            and they belong to the workstation bar, not to the heading. Only
            the title block moves to `PageHeader`, so this screen's heading
            matches the other twenty-nine. */}
        <PageHeader
          title="Nurse workspace"
          meta={
            <>
              {summary && (
                <Badge
                  variant="outline"
                  className={cn("px-2.5 py-0.5 font-medium", SHIFT_LABELS[summary.shift]?.color || "bg-muted")}
                >
                  <Clock className="mr-1.5 h-3.5 w-3.5" />
                  {SHIFT_LABELS[summary.shift]?.label || summary.shift}
                </Badge>
              )}
              <span className="text-sm text-muted-foreground">
                {formatWeekday(new Date())}
              </span>
            </>
          }
          description="Your patients this shift — who needs seeing first, when observations are due, medicines and handover."
        />

        <div className="flex flex-wrap items-center gap-2">
          {facilities.length > 1 && (
            <Select
              value={selectedFacility}
              onChange={(e) => setSelectedFacility(e.target.value)}
              className="w-56 text-xs"
            >
              {facilities.map((f) => (
                <option key={f.uuid} value={f.uuid}>
                  {f.name}
                </option>
              ))}
            </Select>
          )}

          {/* Ward filter */}
          <Select
            value={selectedWard}
            onChange={(e) => setSelectedWard(e.target.value)}
            className="w-40 text-xs"
          >
            <option value="">All wards</option>
            {wards
              .filter((w) => !selectedFacility || w.facility === selectedFacility)
              .map((w) => (
              <option key={w.uuid} value={w.uuid}>
                {w.name}
              </option>
            ))}
          </Select>

          {/* Shift filter */}
          <Select
            value={shiftFilter}
            onChange={(e) => setShiftFilter(e.target.value)}
            className="w-32 text-xs"
          >
            <option value="">This shift</option>
            <option value="morning">Morning</option>
            <option value="evening">Evening</option>
            <option value="night">Night</option>
          </Select>

          {/* Scope switch: My Patients vs Entire Ward */}
          <div className="inline-flex rounded-md border bg-muted/40 p-1 text-xs">
            <button
              type="button"
              onClick={() => setScope("mine")}
              className={cn(
                "rounded px-3 py-1 font-medium transition-all",
                scope === "mine" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              My patients
            </button>
            <button
              type="button"
              onClick={() => setScope("ward")}
              className={cn(
                "rounded px-3 py-1 font-medium transition-all",
                scope === "ward" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              Whole ward
            </button>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAssignModal(true)}
            className="text-xs"
          >
            <UserCheck className="mr-1.5 h-3.5 w-3.5 text-primary" />
            Assign
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchSummary(true)}
            disabled={refreshing}
            className="text-xs"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          </Button>
        </div>
      </div>

      {/* -------------------------------------------------------------------- */}
      {/* KPI Triage Strip                                                     */}
      {/* -------------------------------------------------------------------- */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Card className="p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Inpatients</span>
              <BedDouble className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{summary.total_patients}</div>
            <span className="text-[11px] text-muted-foreground">
              {summary.showing_whole_ward
                ? "None assigned to you yet"
                : scope === "mine"
                  ? "Assigned to you"
                  : "Whole ward"}
            </span>
          </Card>

          <Card
            className={cn(
              "cursor-pointer p-3 transition-all",
              riskFilter === "high" && "border-primary ring-1 ring-primary",
              summary.high_risk_count > 0 && "border-critical/40"
            )}
            onClick={() => setRiskFilter(riskFilter === "high" ? "all" : "high")}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Emergency response</span>
              <AlertOctagon className="h-4 w-4 text-critical" />
            </div>
            <div className={cn("mt-1 text-2xl font-semibold tabular-nums", summary.high_risk_count > 0 ? "text-critical" : "text-foreground")}>{summary.high_risk_count}</div>
            <span className="text-[11px] text-muted-foreground">NEWS2 of 7 or more</span>
          </Card>

          <Card
            className={cn(
              "cursor-pointer p-3 transition-all",
              riskFilter === "medium" && "border-primary ring-1 ring-primary",
              summary.medium_risk_count > 0 && "border-warning/40"
            )}
            onClick={() => setRiskFilter(riskFilter === "medium" ? "all" : "medium")}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Urgent review</span>
              <AlertTriangle className="h-4 w-4 text-warning" />
            </div>
            <div className={cn("mt-1 text-2xl font-semibold tabular-nums", summary.medium_risk_count > 0 ? "text-warning" : "text-foreground")}>
              {summary.medium_risk_count}
            </div>
            <span className="text-[11px] text-muted-foreground">NEWS2 of 5 or 6</span>
          </Card>

          <Card className="p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Shift tasks</span>
              <ListTodo className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{summary.total_tasks_pending}</div>
            <span className="text-[11px] text-muted-foreground">Still to do this shift</span>
          </Card>
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Search & Filter Bar                                                  */}
      {/* -------------------------------------------------------------------- */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 sm:max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Find a patient, bed, MRN or diagnosis"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 text-xs"
          />
        </div>

        <div className="inline-flex rounded-lg border bg-muted/40 p-0.5 text-sm" role="tablist" aria-label="NEWS2 band">
          {(
            [
              ["all", "Everyone"],
              ["high", "Emergency"],
              ["medium", "Urgent"],
              ["low", "Routine"],
            ] as const
          ).map(([r, label]) => (
            <button
              key={r}
              type="button"
              role="tab"
              aria-selected={riskFilter === r}
              onClick={() => setRiskFilter(r)}
              className={cn(
                "rounded-md px-3 py-1 transition-colors",
                riskFilter === r
                  ? "bg-background font-medium shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {summary?.showing_whole_ward && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-info/30 bg-info-subtle px-4 py-3 text-sm text-info-subtle-foreground">
          <span>
            Nobody has assigned you patients for this shift, so the whole ward is
            shown. Take your beds to see only yours.
          </span>
          <Button size="sm" variant="outline" onClick={() => setShowAssignModal(true)}>
            <UserCheck className="mr-1.5 h-3.5 w-3.5" />
            Take beds
          </Button>
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Error state                                                          */}
      {/* -------------------------------------------------------------------- */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Error loading nursing workspace</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Loading state                                                        */}
      {/* -------------------------------------------------------------------- */}
      {loading && (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Empty state                                                          */}
      {/* -------------------------------------------------------------------- */}
      {!loading && filteredPatients.length === 0 && (
        <Card className="flex h-64 flex-col items-center justify-center p-6 text-center">
          <BedDouble className="h-10 w-10 text-muted-foreground/50 mb-2" />
          <h3 className="text-base font-semibold">No patients found</h3>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm">
            {scope === "mine"
              ? "You do not have any patients assigned for this shift yet. Switch to 'Ward Census' to claim beds or browse."
              : "No in-house patients currently admitted to this ward."}
          </p>
          {scope === "mine" && (
            <Button
              variant="outline"
              size="sm"
              className="mt-4 text-xs"
              onClick={() => setScope("ward")}
            >
              View Entire Ward Census
            </Button>
          )}
        </Card>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Bedside Patient Cards Grid                                           */}
      {/* -------------------------------------------------------------------- */}
      {!loading && filteredPatients.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {filteredPatients.map((patient) => (
            <BedsidePatientCard
              key={patient.admission_uuid}
              patient={patient}
              onObserve={() => setSelectedPatientForRound(patient)}
              onMeds={() => setSelectedPatientForEmar(patient)}
              onHandover={() => setSelectedPatientForHandover(patient)}
              onTasks={() => setSelectedPatientForTasks(patient)}
            />
          ))}
        </div>
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Bedside Round & Vitals Modal                                         */}
      {/* -------------------------------------------------------------------- */}
      {selectedPatientForRound && (
        <BedsideRoundModal
          patient={selectedPatientForRound}
          onClose={() => setSelectedPatientForRound(null)}
          onSuccess={() => {
            setSelectedPatientForRound(null);
            fetchSummary(true);
          }}
        />
      )}

      {/* -------------------------------------------------------------------- */}
      {/* eMAR Drawer / Modal                                                  */}
      {/* -------------------------------------------------------------------- */}
      {selectedPatientForEmar && (
        <EmarModal
          patient={selectedPatientForEmar}
          onClose={() => setSelectedPatientForEmar(null)}
          onAdministered={() => fetchSummary(true)}
        />
      )}

      {/* -------------------------------------------------------------------- */}
      {/* SBAR Shift Handover Modal                                            */}
      {/* -------------------------------------------------------------------- */}
      {selectedPatientForHandover && (
        <SbarHandoverModal
          patient={selectedPatientForHandover}
          onClose={() => setSelectedPatientForHandover(null)}
          onSuccess={() => {
            setSelectedPatientForHandover(null);
            fetchSummary(true);
          }}
        />
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Nursing Shift Tasks Modal                                            */}
      {/* -------------------------------------------------------------------- */}
      {selectedPatientForTasks && (
        <NursingTasksModal
          patient={selectedPatientForTasks}
          onClose={() => setSelectedPatientForTasks(null)}
          onUpdated={() => fetchSummary(true)}
        />
      )}

      {/* -------------------------------------------------------------------- */}
      {/* Nurse Bed Assignment Modal                                           */}
      {/* -------------------------------------------------------------------- */}
      {showAssignModal && (
        <NurseAssignmentModal
          wards={wards}
          patients={summary?.patients || []}
          onClose={() => setShowAssignModal(false)}
          onSuccess={() => {
            setShowAssignModal(false);
            fetchSummary(true);
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 1. Bedside Round & Vitals Modal with Live NEWS2                            */
/* -------------------------------------------------------------------------- */

function BedsideRoundModal({
  patient,
  onClose,
  onSuccess,
}: {
  patient: NursePatientCard;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [temp, setTemp] = useState<string>(patient.vitals?.temp?.toString() || "36.8");
  const [pulse, setPulse] = useState<string>(patient.vitals?.pulse?.toString() || "76");
  const [rr, setRr] = useState<string>(patient.vitals?.rr?.toString() || "16");
  const [sbp, setSbp] = useState<string>(patient.vitals?.bp ? patient.vitals.bp.split("/")[0] : "120");
  const [dbp, setDbp] = useState<string>(patient.vitals?.bp ? patient.vitals.bp.split("/")[1] : "80");
  const [spo2, setSpo2] = useState<string>(patient.vitals?.spo2?.toString() || "98");
  const [onAir, setOnAir] = useState<boolean>(true);
  const [o2Flow, setO2Flow] = useState<string>("");
  const [pain, setPain] = useState<string>(patient.vitals?.pain?.toString() || "0");
  const [gcs, setGcs] = useState<string>("15");
  const [glucose, setGlucose] = useState<string>("");

  const [intake, setIntake] = useState<string>("0");
  const [output, setOutput] = useState<string>("0");
  const [observations, setObservations] = useState<string>("");
  const [interventions, setInterventions] = useState<string>("");
  const [escalate, setEscalate] = useState<boolean>(false);
  const [escalateReason, setEscalateReason] = useState<string>("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Live calculated NEWS2
  const liveNews = useMemo(() => {
    return liveCalculateNEWS2({
      rr: parseFloat(rr) || undefined,
      spo2: parseFloat(spo2) || undefined,
      onAir: onAir,
      sbp: parseFloat(sbp) || undefined,
      hr: parseFloat(pulse) || undefined,
      gcs: parseFloat(gcs) || undefined,
      temp: parseFloat(temp) || undefined,
    });
  }, [rr, spo2, onAir, sbp, pulse, gcs, temp]);

  // Auto-flag escalation suggestion if NEWS2 is high
  useEffect(() => {
    if (liveNews.score >= 7 && !escalate) {
      setEscalate(true);
      setEscalateReason(`Critical NEWS2 score: ${liveNews.score} (${liveNews.risk_level.toUpperCase()})`);
    }
  }, [liveNews.score, liveNews.risk_level, escalate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);

    try {
      await api.post("/ipd/nurse-workspace/bedside-round/", {
        admission: patient.admission_uuid,
        temperature_c: temp ? parseFloat(temp) : null,
        pulse_bpm: pulse ? parseInt(pulse) : null,
        respiratory_rate: rr ? parseInt(rr) : null,
        systolic_bp: sbp ? parseInt(sbp) : null,
        diastolic_bp: dbp ? parseInt(dbp) : null,
        spo2_percent: spo2 ? parseInt(spo2) : null,
        on_room_air: onAir,
        oxygen_flow_lpm: !onAir && o2Flow ? parseFloat(o2Flow) : null,
        blood_glucose_mmol: glucose ? parseFloat(glucose) : null,
        pain_score: pain ? parseInt(pain) : null,
        gcs_total: gcs ? parseInt(gcs) : null,
        intake_ml: intake ? parseInt(intake) : 0,
        output_ml: output ? parseInt(output) : 0,
        observations,
        interventions,
        escalated: escalate,
        escalation_reason: escalateReason,
      });
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) setSubmitError(err.message);
      else setSubmitError("Failed to save bedside observations.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-2xl rounded-xl border bg-background p-6 shadow-xl my-8">
        <div className="flex items-center justify-between border-b pb-3">
          <div>
            <h2 className="text-lg font-bold">Record Bedside Round & Vitals</h2>
            <p className="text-xs text-muted-foreground">
              {patient.bed_code} • {patient.patient_name} ({patient.patient_mrn})
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-muted">
            <X className="h-5 w-5" />
          </button>
        </div>

        {submitError && (
          <Alert variant="destructive" className="mt-4">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {/* Live NEWS2 Score Card */}
          <div
            className={cn(
              "rounded-lg border p-3 flex items-center justify-between transition-all",
              liveNews.color === "red" && "bg-destructive/10 border-destructive/40 text-destructive",
              liveNews.color === "amber" && "bg-warning/10 border-warning/40 text-warning",
              liveNews.color === "green" && "bg-good/10 border-good/40 text-good"
            )}
          >
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider">
                Live NEWS2 Score: <span className="text-base font-extrabold">{liveNews.score}</span> / 20
              </div>
              <p className="text-xs mt-0.5 opacity-90">{liveNews.recommendation}</p>
            </div>
            <Badge
              className={cn(
                "font-bold text-xs px-2.5 py-1",
                liveNews.color === "red" && "bg-destructive text-destructive-foreground",
                liveNews.color === "amber" && "bg-warning text-white",
                liveNews.color === "green" && "bg-good text-white"
              )}
            >
              {liveNews.risk_level.toUpperCase()}
            </Badge>
          </div>

          {/* Core Vitals Inputs */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <Label className="text-xs">Temp (°C)</Label>
              <Input
                type="number"
                step="0.1"
                value={temp}
                onChange={(e) => setTemp(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">Heart Rate (bpm)</Label>
              <Input
                type="number"
                value={pulse}
                onChange={(e) => setPulse(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">Resp Rate (bpm)</Label>
              <Input
                type="number"
                value={rr}
                onChange={(e) => setRr(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">SpO2 (%)</Label>
              <Input
                type="number"
                value={spo2}
                onChange={(e) => setSpo2(e.target.value)}
                className="text-xs font-mono"
              />
            </div>

            <div>
              <Label className="text-xs">Systolic BP (mmHg)</Label>
              <Input
                type="number"
                value={sbp}
                onChange={(e) => setSbp(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">Diastolic BP (mmHg)</Label>
              <Input
                type="number"
                value={dbp}
                onChange={(e) => setDbp(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">Pain Score (0–10)</Label>
              <Input
                type="number"
                min="0"
                max="10"
                value={pain}
                onChange={(e) => setPain(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">GCS (3–15)</Label>
              <Input
                type="number"
                min="3"
                max="15"
                value={gcs}
                onChange={(e) => setGcs(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">Blood Glucose (mmol/L)</Label>
              <Input
                type="number"
                step="0.1"
                placeholder="e.g. 5.6"
                value={glucose}
                onChange={(e) => setGlucose(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
          </div>

          {/* Supplemental Oxygen Toggle */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg border bg-muted/20 p-3">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="onRoomAirCheck"
                checked={onAir}
                onChange={(e) => setOnAir(e.target.checked)}
                className="h-4 w-4 rounded border-input text-primary"
              />
              <Label htmlFor="onRoomAirCheck" className="text-xs font-medium cursor-pointer">
                Patient is breathing Room Air
              </Label>
            </div>
            {!onAir && (
              <div>
                <Label className="text-xs">O2 Flow Rate (L/min)</Label>
                <Input
                  type="number"
                  step="0.5"
                  placeholder="e.g. 2, 4, 6"
                  value={o2Flow}
                  onChange={(e) => setO2Flow(e.target.value)}
                  className="text-xs font-mono"
                />
              </div>
            )}
          </div>

          {/* Fluid Balance */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Intake This Round (mL)</Label>
              <Input
                type="number"
                value={intake}
                onChange={(e) => setIntake(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
            <div>
              <Label className="text-xs">Output This Round (mL)</Label>
              <Input
                type="number"
                value={output}
                onChange={(e) => setOutput(e.target.value)}
                className="text-xs font-mono"
              />
            </div>
          </div>

          {/* Observations & Interventions */}
          <div className="space-y-2">
            <div>
              <Label className="text-xs">Nursing Observations</Label>
              <Textarea
                placeholder="Bedside clinical notes, patient complaints, respiratory effort, skin condition…"
                rows={2}
                value={observations}
                onChange={(e) => setObservations(e.target.value)}
                className="text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">Nursing Interventions</Label>
              <Input
                placeholder="e.g. Suctioned airway, nebulised, repositioned, ice pack applied…"
                value={interventions}
                onChange={(e) => setInterventions(e.target.value)}
                className="text-xs"
              />
            </div>
          </div>

          {/* Doctor Escalation Trigger */}
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="escalateDoctor"
                checked={escalate}
                onChange={(e) => setEscalate(e.target.checked)}
                className="h-4 w-4 rounded border-destructive text-destructive"
              />
              <Label htmlFor="escalateDoctor" className="text-xs font-semibold text-destructive cursor-pointer">
                Escalate patient to attending physician / Rapid Response Team
              </Label>
            </div>
            {escalate && (
              <Input
                placeholder="Reason for doctor escalation (e.g. Sudden hypotension, Rigors, SpO2 drop)…"
                value={escalateReason}
                onChange={(e) => setEscalateReason(e.target.value)}
                className="text-xs"
                required={escalate}
              />
            )}
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t">
            <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
              Save Observations & Vitals
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 2. eMAR (Electronic Medication Administration Record) Modal                */
/* -------------------------------------------------------------------------- */

function EmarModal({
  patient,
  onClose,
  onAdministered,
}: {
  patient: NursePatientCard;
  onClose: () => void;
  onAdministered: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [emarData, setEmarData] = useState<EmarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Administer action dialog state
  const [selectedLineForAdmin, setSelectedLineForAdmin] = useState<EmarLine | null>(null);
  const [adminStatus, setAdminStatus] = useState<"given" | "held" | "refused" | "omitted">("given");
  const [doseGiven, setDoseGiven] = useState("");
  const [routeGiven, setRouteGiven] = useState("");
  const [heldReason, setHeldReason] = useState("");
  const [site, setSite] = useState("");
  const [witness, setWitness] = useState("");
  const [adminNotes, setAdminNotes] = useState("");
  const [administering, setAdministering] = useState(false);

  const fetchEmar = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<EmarResponse>(`/ipd/nurse-workspace/emar/?admission=${patient.admission_uuid}`);
      setEmarData(res);
    } catch (err) {
      setError("Failed to load medication administration record.");
    } finally {
      setLoading(false);
    }
  }, [patient.admission_uuid]);

  useEffect(() => {
    fetchEmar();
  }, [fetchEmar]);

  const handleOpenAdminister = (line: EmarLine) => {
    setSelectedLineForAdmin(line);
    setAdminStatus("given");
    setDoseGiven(line.dose);
    setRouteGiven(line.route);
    setHeldReason("");
    setSite("");
    setWitness("");
    setAdminNotes("");
  };

  const handleRecordAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedLineForAdmin) return;
    setAdministering(true);

    try {
      await api.post("/ipd/nurse-workspace/emar/administer/", {
        prescription_line: selectedLineForAdmin.uuid,
        admission: patient.admission_uuid,
        status: adminStatus,
        dose_given: doseGiven,
        route: routeGiven,
        reason: heldReason,
        injection_site: site,
        witness_name: witness,
        notes: adminNotes,
      });
      setSelectedLineForAdmin(null);
      fetchEmar();
      onAdministered();
    } catch (err) {
      if (err instanceof ApiError) alert(err.message);
      else alert("Failed to log medication administration.");
    } finally {
      setAdministering(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-4xl rounded-xl border bg-background p-6 shadow-xl my-8">
        <div className="flex items-center justify-between border-b pb-3">
          <div>
            <div className="flex items-center gap-2">
              <Pill className="h-5 w-5 text-good" />
              <h2 className="text-lg font-bold">Electronic Medication Administration Record (eMAR)</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              {patient.bed_code} • {patient.patient_name} ({patient.patient_mrn}) • Diagnosis: {patient.admitting_diagnosis}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-muted">
            <X className="h-5 w-5" />
          </button>
        </div>

        {loading && (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!loading && emarData && (
          <div className="mt-4 space-y-6">
            {/* Active Prescriptions Table */}
            <div>
              <h3 className="text-sm font-semibold mb-2">Active Prescribed Medications</h3>
              {emarData.lines.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No active medications prescribed for this patient.</p>
              ) : (
                <div className="rounded-lg border overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Medicine & Strength</TableHead>
                        <TableHead>Dose & Route</TableHead>
                        <TableHead>Frequency</TableHead>
                        <TableHead>Instructions</TableHead>
                        <TableHead>Last Dose</TableHead>
                        <TableHead className="text-right">Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {emarData.lines.map((line) => (
                        <TableRow key={line.uuid}>
                          <TableCell>
                            <span className="font-bold text-xs block">{line.display_name}</span>
                            {line.is_prn && (
                              <Badge variant="outline" className="text-[10px] text-warning border-warning/40">
                                PRN: {line.prn_indication || "As needed"}
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-xs font-mono">
                            {line.dose} via {line.route}
                          </TableCell>
                          <TableCell className="text-xs">{line.frequency_display || line.frequency}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{line.instructions || "—"}</TableCell>
                          <TableCell className="text-xs">
                            {line.last_administered ? (
                              <div>
                                <Badge
                                  variant="outline"
                                  className={cn(
                                    "text-[10px] uppercase font-bold",
                                    line.last_administered.status === "given" && "text-good bg-good-subtle border-good/40",
                                    line.last_administered.status === "held" && "text-warning bg-warning-subtle border-warning/40",
                                    line.last_administered.status === "refused" && "text-destructive bg-destructive/10 border-destructive/30"
                                  )}
                                >
                                  {line.last_administered.status}
                                </Badge>
                                <span className="block text-[10px] text-muted-foreground font-mono mt-0.5">
                                  {formatTime(line.last_administered.administered_at)}
                                </span>
                              </div>
                            ) : (
                              <span className="text-muted-foreground text-[11px]">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              size="sm"
                              className="h-7 text-xs font-medium bg-good hover:bg-good text-white"
                              onClick={() => handleOpenAdminister(line)}
                            >
                              Administer
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>

            {/* Administrations Log */}
            <div>
              <h3 className="text-sm font-semibold mb-2">Recent Administration Log (Past 48h)</h3>
              {emarData.administrations.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No administrations logged yet.</p>
              ) : (
                <div className="rounded-lg border overflow-hidden max-h-56 overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Time</TableHead>
                        <TableHead>Medication</TableHead>
                        <TableHead>Dose / Route</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Administered By</TableHead>
                        <TableHead>Clinical Reason / Notes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {emarData.administrations.map((adm) => (
                        <TableRow key={adm.uuid}>
                          <TableCell className="text-xs font-mono">
                            {formatTime(adm.administered_at)}
                          </TableCell>
                          <TableCell className="text-xs font-medium">{adm.medicine_name}</TableCell>
                          <TableCell className="text-xs font-mono">
                            {adm.dose_given} ({adm.route})
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className={cn(
                                "text-[10px] font-bold uppercase",
                                adm.status === "given" && "text-good bg-good-subtle border-good/40",
                                adm.status === "held" && "text-warning bg-warning-subtle border-warning/40",
                                adm.status === "refused" && "text-destructive bg-destructive/10 border-destructive/30"
                              )}
                            >
                              {adm.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs">
                            {adm.administered_by_name}
                            {adm.witness_by_name && (
                              <span className="block text-[10px] text-muted-foreground">
                                Witness: {adm.witness_by_name}
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {adm.reason || adm.notes || "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Nested Action Modal: Record Dose */}
        {selectedLineForAdmin && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
            <div className="w-full max-w-md rounded-xl border bg-background p-5 shadow-2xl">
              <div className="flex items-center justify-between border-b pb-2">
                <h4 className="font-bold text-sm">Log Administration: {selectedLineForAdmin.display_name}</h4>
                <button type="button" onClick={() => setSelectedLineForAdmin(null)} className="rounded p-1 hover:bg-muted">
                  <X className="h-4 w-4" />
                </button>
              </div>

              <form onSubmit={handleRecordAdmin} className="mt-3 space-y-3">
                <div>
                  <Label className="text-xs">Action Status</Label>
                  <Select
                    value={adminStatus}
                    onChange={(e) => setAdminStatus(e.target.value as any)}
                    className="text-xs font-medium"
                  >
                    <option value="given">GIVEN — Dose Administered</option>
                    <option value="held">HELD — Withheld for clinical reasons</option>
                    <option value="refused">REFUSED — Refused by patient</option>
                    <option value="omitted">OMITTED — Missed / unavailable</option>
                  </Select>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Dose</Label>
                    <Input
                      value={doseGiven}
                      onChange={(e) => setDoseGiven(e.target.value)}
                      className="text-xs font-mono"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Route</Label>
                    <Input
                      value={routeGiven}
                      onChange={(e) => setRouteGiven(e.target.value)}
                      className="text-xs font-mono"
                    />
                  </div>
                </div>

                {adminStatus !== "given" && (
                  <div>
                    <Label className="text-xs font-semibold text-destructive">
                      Mandatory Clinical Reason (Why was it {adminStatus}?)
                    </Label>
                    <Input
                      placeholder="e.g. SBP < 90 mmHg, Patient asleep, Vomiting, Refused…"
                      value={heldReason}
                      onChange={(e) => setHeldReason(e.target.value)}
                      className="text-xs border-destructive/60"
                      required
                    />
                  </div>
                )}

                <div>
                  <Label className="text-xs">Injection / Application Site</Label>
                  <Input
                    placeholder="e.g. Left deltoid, Right forearm peripheral IV, Abdomen…"
                    value={site}
                    onChange={(e) => setSite(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <div>
                  <Label className="text-xs">Witness / Co-signer Name (for high-alert drugs)</Label>
                  <Input
                    placeholder="Second nurse name if high-risk drug (Insulin, Heparin, Opioids)…"
                    value={witness}
                    onChange={(e) => setWitness(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <div>
                  <Label className="text-xs">Clinical Notes</Label>
                  <Input
                    placeholder="Patient reaction, infusion rate, flush completed…"
                    value={adminNotes}
                    onChange={(e) => setAdminNotes(e.target.value)}
                    className="text-xs"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2 border-t">
                  <Button type="button" variant="outline" size="sm" onClick={() => setSelectedLineForAdmin(null)}>
                    Cancel
                  </Button>
                  <Button type="submit" size="sm" disabled={administering}>
                    {administering ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                    Confirm {adminStatus.toUpperCase()}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 3. SBAR Shift Handover Modal                                               */
/* -------------------------------------------------------------------------- */

function SbarHandoverModal({
  patient,
  onClose,
  onSuccess,
}: {
  patient: NursePatientCard;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [codeStatus, setCodeStatus] = useState("full_code");
  const [situation, setSituation] = useState(
    patient.handover?.situation || `Admitted for ${patient.admitting_diagnosis}. Current NEWS2: ${patient.news2.score} (${patient.news2.risk_level}).`
  );
  const [background, setBackground] = useState(
    `Admitted ${patient.length_of_stay_days} days ago under ${patient.consultant_name}. Bed ${patient.bed_code}.`
  );
  const [assessment, setAssessment] = useState(
    patient.vitals
      ? `Vitals: BP ${patient.vitals.bp}, HR ${patient.vitals.pulse}, RR ${patient.vitals.rr}, SpO2 ${patient.vitals.spo2}%, Temp ${patient.vitals.temp}°C. Net fluid 24h: ${patient.fluid_balance_24h.net_ml} mL.`
      : "Awaiting vital signs round."
  );
  const [recommendation, setRecommendation] = useState(
    patient.handover?.recommendation || "Continue scheduled ward monitoring. Recheck vitals as indicated by NEWS2."
  );

  const [saving, setSaving] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);

  const handleSaveHandover = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/ipd/nurse-workspace/handovers/", {
        admission: patient.admission_uuid,
        code_status: codeStatus,
        situation,
        background,
        assessment,
        recommendation,
      });
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) alert(err.message);
      else alert("Failed to save handover.");
    } finally {
      setSaving(false);
    }
  };

  const handleAcknowledge = async () => {
    if (!patient.handover) return;
    setAcknowledging(true);
    try {
      await api.post(`/ipd/nurse-workspace/handovers/${patient.handover.uuid}/acknowledge/`, {});
      onSuccess();
    } catch (err) {
      alert("Failed to acknowledge handover.");
    } finally {
      setAcknowledging(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-2xl rounded-xl border bg-background p-6 shadow-xl my-8">
        <div className="flex items-center justify-between border-b pb-3">
          <div>
            <div className="flex items-center gap-2">
              <Send className="h-5 w-5 text-info" />
              <h2 className="text-lg font-bold">Shift Handover (SBAR)</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              {patient.bed_code} • {patient.patient_name} ({patient.patient_mrn})
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-muted">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Previous Handover Ack Banner if exists */}
        {patient.handover && (
          <div className="mt-4 rounded-lg border bg-muted/40 p-3 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold">
                Last Handover by {patient.handover.outgoing_nurse_name} ({patient.handover.shift} shift)
              </span>
              {patient.handover.is_acknowledged ? (
                <Badge variant="outline" className="bg-good-subtle text-good border-good/40">
                  <ShieldCheck className="mr-1 h-3 w-3" /> Acknowledged by {patient.handover.incoming_nurse_name}
                </Badge>
              ) : (
                <Badge variant="outline" className="bg-warning-subtle text-warning border-warning/40">
                  Pending Incoming Nurse Receipt
                </Badge>
              )}
            </div>

            {!patient.handover.is_acknowledged && (
              <div className="flex items-center justify-between pt-2 border-t">
                <span className="text-muted-foreground">Are you taking over this patient for the current shift?</span>
                <Button size="sm" onClick={handleAcknowledge} disabled={acknowledging} className="h-7 text-xs">
                  {acknowledging ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />}
                  Acknowledge & Accept Handover
                </Button>
              </div>
            )}
          </div>
        )}

        {/* SBAR Editor Form */}
        <form onSubmit={handleSaveHandover} className="mt-4 space-y-3">
          <div>
            <Label className="text-xs">Resuscitation / Code Status</Label>
            <Select
              value={codeStatus}
              onChange={(e) => setCodeStatus(e.target.value)}
              className="text-xs font-bold"
            >
              <option value="full_code">FULL CODE — Full Resuscitation / CPR</option>
              <option value="dnr">DNR — Do Not Resuscitate (AND)</option>
              <option value="dni">DNI — Do Not Intubate</option>
            </Select>
          </div>

          <div>
            <Label className="text-xs font-bold text-info">S — Situation (Current Clinical State & Concerns)</Label>
            <Textarea
              rows={2}
              value={situation}
              onChange={(e) => setSituation(e.target.value)}
              className="text-xs"
              required
            />
          </div>

          <div>
            <Label className="text-xs font-bold text-info">B — Background (History, Allergies, Surgeries)</Label>
            <Textarea
              rows={2}
              value={background}
              onChange={(e) => setBackground(e.target.value)}
              className="text-xs"
            />
          </div>

          <div>
            <Label className="text-xs font-bold text-warning">A — Assessment (Vitals, NEWS2, Lines, Fluid, Drains)</Label>
            <Textarea
              rows={2}
              value={assessment}
              onChange={(e) => setAssessment(e.target.value)}
              className="text-xs"
              required
            />
          </div>

          <div>
            <Label className="text-xs font-bold text-good">R — Recommendation (Incoming Shift Plan & Orders)</Label>
            <Textarea
              rows={2}
              value={recommendation}
              onChange={(e) => setRecommendation(e.target.value)}
              className="text-xs"
              required
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t">
            <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={saving}>
              Close
            </Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
              Sign & Publish SBAR Note
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 4. Nursing Shift Tasks Modal                                               */
/* -------------------------------------------------------------------------- */

function NursingTasksModal({
  patient,
  onClose,
  onUpdated,
}: {
  patient: NursePatientCard;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [tasks, setTasks] = useState<NursingTask[]>([]);
  const [loading, setLoading] = useState(true);

  // New task inputs
  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState("general");
  const [newNotes, setNewNotes] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Paginated<NursingTask>>(
        `/ipd/nurse-workspace/tasks/?admission=${patient.admission_uuid}`
      );
      setTasks(res.results || []);
    } catch (err) {
      console.error("Failed to load tasks", err);
    } finally {
      setLoading(false);
    }
  }, [patient.admission_uuid]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const handleAddTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setAdding(true);
    try {
      await api.post("/ipd/nurse-workspace/tasks/", {
        admission: patient.admission_uuid,
        title: newTitle,
        category: newCategory,
        notes: newNotes,
      });
      setNewTitle("");
      setNewNotes("");
      fetchTasks();
      onUpdated();
    } catch (err) {
      alert("Failed to add task.");
    } finally {
      setAdding(false);
    }
  };

  const handleCompleteTask = async (task: NursingTask) => {
    try {
      await api.post(`/ipd/nurse-workspace/tasks/${task.uuid}/complete/`, {
        notes: "Completed at bedside",
      });
      fetchTasks();
      onUpdated();
    } catch (err) {
      alert("Failed to complete task.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-xl rounded-xl border bg-background p-6 shadow-xl my-8">
        <div className="flex items-center justify-between border-b pb-3">
          <div>
            <div className="flex items-center gap-2">
              <ListTodo className="h-5 w-5 text-warning" />
              <h2 className="text-lg font-bold">Shift Duties & Nursing Tasks</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              {patient.bed_code} • {patient.patient_name} ({patient.patient_mrn})
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-muted">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Existing Tasks List */}
        <div className="mt-4 space-y-2 max-h-60 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center p-4">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : tasks.length === 0 ? (
            <p className="text-xs text-muted-foreground italic text-center py-4">No tasks logged for this patient.</p>
          ) : (
            tasks.map((t) => (
              <div
                key={t.uuid}
                className={cn(
                  "flex items-center justify-between p-2.5 rounded-lg border text-xs",
                  t.status === "completed" ? "bg-muted/30 opacity-70" : "bg-card"
                )}
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className={cn("font-medium", t.status === "completed" && "line-through text-muted-foreground")}>
                      {t.title}
                    </span>
                    <Badge variant="outline" className="text-[10px] uppercase">
                      {t.category}
                    </Badge>
                  </div>
                  {t.completed_by_name && (
                    <span className="text-[10px] text-good font-medium block">
                      ✓ Done by {t.completed_by_name} at {formatTime(t.completed_at!)}
                    </span>
                  )}
                </div>

                {t.status !== "completed" && (
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => handleCompleteTask(t)}>
                    Mark Done
                  </Button>
                )}
              </div>
            ))
          )}
        </div>

        {/* Add Task Form */}
        <form onSubmit={handleAddTask} className="mt-4 pt-3 border-t space-y-2">
          <h4 className="text-xs font-semibold">Add New Bedside Task</h4>
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2">
              <Input
                placeholder="e.g. Check blood sugar, Dress IV cannula, Foley care…"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                className="text-xs"
                required
              />
            </div>
            <div>
              <Select value={newCategory} onChange={(e) => setNewCategory(e.target.value)} className="text-xs">
                <option value="general">General</option>
                <option value="vitals">Vitals</option>
                <option value="medication">Medication</option>
                <option value="wound_care">Wound Care</option>
                <option value="fluid_balance">Fluid</option>
                <option value="hygiene">Hygiene</option>
              </Select>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Close
            </Button>
            <Button type="submit" size="sm" disabled={adding}>
              {adding ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Plus className="mr-1.5 h-3.5 w-3.5" />}
              Add Task
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 5. Nurse Assignment Modal                                                  */
/* -------------------------------------------------------------------------- */

function NurseAssignmentModal({
  wards,
  patients,
  onClose,
  onSuccess,
}: {
  wards: Ward[];
  patients: NursePatientCard[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [selectedWard, setSelectedWard] = useState(wards[0]?.uuid || "");
  const [selectedAdmission, setSelectedAdmission] = useState(patients[0]?.admission_uuid || "");
  const [nurseName, setNurseName] = useState("");
  const [shift, setShift] = useState("morning");
  const [role, setRole] = useState("primary");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWard || !nurseName.trim()) return;
    setSubmitting(true);
    try {
      await api.post("/ipd/nurse-workspace/assignments/", {
        ward: selectedWard,
        admission: selectedAdmission || null,
        nurse_id: "00000000-0000-0000-0000-000000000001",
        nurse_name: nurseName,
        shift,
        role,
        notes,
      });
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) alert(err.message);
      else alert("Failed to assign nurse.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-md rounded-xl border bg-background p-6 shadow-xl">
        <div className="flex items-center justify-between border-b pb-2">
          <h3 className="font-bold text-base">Assign Duty Nurse to Bed</h3>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <Label className="text-xs">Ward</Label>
            <Select value={selectedWard} onChange={(e) => setSelectedWard(e.target.value)} className="text-xs">
              {wards.map((w) => (
                <option key={w.uuid} value={w.uuid}>
                  {w.name}
                </option>
              ))}
            </Select>
          </div>

          <div>
            <Label className="text-xs">Patient / Bed</Label>
            <Select
              value={selectedAdmission}
              onChange={(e) => setSelectedAdmission(e.target.value)}
              className="text-xs"
            >
              <option value="">Whole Ward Coverage</option>
              {patients.map((p) => (
                <option key={p.admission_uuid} value={p.admission_uuid}>
                  {p.bed_code} — {p.patient_name} ({p.patient_mrn})
                </option>
              ))}
            </Select>
          </div>

          <div>
            <Label className="text-xs">Duty Nurse Name</Label>
            <Input
              placeholder="e.g. Maya Adhikari, RN"
              value={nurseName}
              onChange={(e) => setNurseName(e.target.value)}
              className="text-xs"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Shift</Label>
              <Select value={shift} onChange={(e) => setShift(e.target.value)} className="text-xs">
                <option value="morning">Morning (07:00–15:00)</option>
                <option value="evening">Evening (15:00–23:00)</option>
                <option value="night">Night (23:00–07:00)</option>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Role</Label>
              <Select value={role} onChange={(e) => setRole(e.target.value)} className="text-xs">
                <option value="primary">Primary Bedside</option>
                <option value="buddy">Buddy / Relief</option>
                <option value="charge">Charge Nurse</option>
              </Select>
            </div>
          </div>

          <div>
            <Label className="text-xs">Notes</Label>
            <Input
              placeholder="Shift coverage notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="text-xs"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t">
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
              Save Assignment
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
