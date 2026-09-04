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
  Activity,
  AlertOctagon,
  AlertTriangle,
  BedDouble,
  CheckCircle2,
  Clock,
  Droplets,
  ListTodo,
  Loader2,
  Pill,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Stethoscope,
  UserCheck,
  X,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
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

/* -------------------------------------------------------------------------- */
/* Helper Functions                                                           */
/* -------------------------------------------------------------------------- */

const SHIFT_LABELS: Record<string, { label: string; time: string; color: string }> = {
  morning: { label: "Morning Shift", time: "07:00 – 15:00", color: "bg-amber-500/10 text-amber-700 border-amber-500/30 dark:text-amber-300" },
  evening: { label: "Evening Shift", time: "15:00 – 23:00", color: "bg-blue-500/10 text-blue-700 border-blue-500/30 dark:text-blue-300" },
  night: { label: "Night Shift", time: "23:00 – 07:00", color: "bg-indigo-500/10 text-indigo-700 border-indigo-500/30 dark:text-indigo-300" },
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
        const facRes = await api.get<Paginated<Facility>>("/api/org/facilities/");
        const facs = facRes.results ?? [];
        setFacilities(facs);
        if (facs.length > 0) {
          setSelectedFacility(facs[0].uuid);
        }

        const wardRes = await api.get<Paginated<Ward>>("/api/ipd/wards/");
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

      const res = await api.get<NurseWorkspaceSummary>(`/api/ipd/nurse-workspace/summary/?${params.toString()}`);
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
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Nurse Workspace</h1>
            {summary && (
              <Badge
                variant="outline"
                className={cn("px-2.5 py-0.5 font-medium", SHIFT_LABELS[summary.shift]?.color || "bg-muted")}
              >
                <Clock className="mr-1.5 h-3.5 w-3.5" />
                {SHIFT_LABELS[summary.shift]?.label || summary.shift}
              </Badge>
            )}
            <Badge variant="secondary" className="font-mono text-xs">
              {new Date().toLocaleDateString("en-NP", { weekday: "short", month: "short", day: "numeric" })}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Bedside rounding console: assigned patients, vital sign rounds with NEWS2 alerts, eMAR, and shift handover.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {facilities.length > 1 && (
            <Select
              value={selectedFacility}
              onChange={(e) => setSelectedFacility(e.target.value)}
              className="w-40 text-xs"
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
            <option value="">All Wards</option>
            {wards.map((w) => (
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
            <option value="">Current Shift</option>
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
              My Patients
            </button>
            <button
              type="button"
              onClick={() => setScope("ward")}
              className={cn(
                "rounded px-3 py-1 font-medium transition-all",
                scope === "ward" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              Ward Census
            </button>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAssignModal(true)}
            className="text-xs"
          >
            <UserCheck className="mr-1.5 h-3.5 w-3.5 text-primary" />
            Assign Nurse
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
            <div className="mt-1 text-2xl font-bold">{summary.total_patients}</div>
            <span className="text-[11px] text-muted-foreground">
              {scope === "mine" ? "Assigned to you" : "On duty ward board"}
            </span>
          </Card>

          <Card
            className={cn(
              "cursor-pointer p-3 transition-all",
              riskFilter === "high" && "ring-2 ring-destructive",
              summary.high_risk_count > 0 && "border-destructive/40 bg-destructive/5"
            )}
            onClick={() => setRiskFilter(riskFilter === "high" ? "all" : "high")}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-destructive">High Deterioration</span>
              <AlertOctagon className="h-4 w-4 text-destructive animate-pulse" />
            </div>
            <div className="mt-1 text-2xl font-bold text-destructive">{summary.high_risk_count}</div>
            <span className="text-[11px] text-destructive/80 font-medium">NEWS2 ≥ 7 (Critical)</span>
          </Card>

          <Card
            className={cn(
              "cursor-pointer p-3 transition-all",
              riskFilter === "medium" && "ring-2 ring-amber-500",
              summary.medium_risk_count > 0 && "border-amber-500/40 bg-amber-500/5"
            )}
            onClick={() => setRiskFilter(riskFilter === "medium" ? "all" : "medium")}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-amber-700 dark:text-amber-400">Moderate Risk</span>
              <AlertTriangle className="h-4 w-4 text-amber-600" />
            </div>
            <div className="mt-1 text-2xl font-bold text-amber-700 dark:text-amber-400">
              {summary.medium_risk_count}
            </div>
            <span className="text-[11px] text-amber-700/80 dark:text-amber-400/80 font-medium">
              NEWS2 5–6 (Urgent)
            </span>
          </Card>

          <Card className="p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Shift Tasks</span>
              <ListTodo className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-1 text-2xl font-bold">{summary.total_tasks_pending}</div>
            <span className="text-[11px] text-muted-foreground">Pending bedside duties</span>
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
            placeholder="Search bed, patient name, MRN, or diagnosis…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 text-xs"
          />
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Filter Risk:</span>
          {(["all", "high", "medium", "low"] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRiskFilter(r)}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs font-medium uppercase tracking-wider transition-all",
                riskFilter === r
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

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
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {filteredPatients.map((patient) => {
            const isCritical = patient.news2.risk_level === "high";
            const isMedium = patient.news2.risk_level === "medium";

            return (
              <Card
                key={patient.admission_uuid}
                className={cn(
                  "relative flex flex-col justify-between overflow-hidden border transition-all hover:shadow-md",
                  isCritical && "border-destructive/60 shadow-destructive/5 ring-1 ring-destructive/40 bg-gradient-to-b from-destructive/5 to-transparent",
                  isMedium && "border-amber-500/50 shadow-amber-500/5 bg-gradient-to-b from-amber-500/5 to-transparent"
                )}
              >
                {/* Bed Badge & Risk Header */}
                <div className="flex items-center justify-between border-b px-4 py-2.5 bg-muted/30">
                  <div className="flex items-center gap-2">
                    <Badge variant="default" className="font-mono text-xs font-bold tracking-wide">
                      {patient.bed_code}
                    </Badge>
                    <span className="text-xs font-medium text-muted-foreground truncate max-w-[120px]">
                      {patient.ward_name}
                    </span>
                    {patient.is_mine && (
                      <Badge variant="outline" className="border-primary/40 bg-primary/10 text-primary text-[10px]">
                        My Patient
                      </Badge>
                    )}
                  </div>

                  {/* NEWS2 Indicator Badge */}
                  <Badge
                    className={cn(
                      "font-mono font-bold text-xs px-2 py-0.5",
                      isCritical && "bg-destructive text-destructive-foreground animate-pulse",
                      isMedium && "bg-amber-500 text-white",
                      !isCritical && !isMedium && "bg-emerald-600 text-white"
                    )}
                  >
                    NEWS2: {patient.news2.score} [{patient.news2.risk_level.toUpperCase()}]
                  </Badge>
                </div>

                {/* Patient Information & Demographics */}
                <div className="p-4 space-y-3">
                  <div>
                    <div className="flex items-baseline justify-between">
                      <h3 className="text-base font-bold text-foreground truncate">{patient.patient_name}</h3>
                      <span className="font-mono text-xs text-muted-foreground">{patient.patient_mrn}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                      <span>{patient.patient_gender?.toUpperCase()}</span>
                      <span>•</span>
                      <span>{patient.patient_age || "Adult"}</span>
                      <span>•</span>
                      <span>Stay: {patient.length_of_stay_days}d</span>
                      <span>•</span>
                      <span className="truncate">{patient.consultant_name}</span>
                    </div>
                    <p className="text-xs font-medium text-foreground/90 mt-1 line-clamp-1">
                      {patient.admitting_diagnosis || "Under evaluation"}
                    </p>
                  </div>

                  {/* NEWS2 Triggers & Recommendation Box if deteriorated */}
                  {(isCritical || isMedium) && (
                    <div
                      className={cn(
                        "rounded-md p-2 text-xs space-y-1",
                        isCritical
                          ? "bg-destructive/10 text-destructive border border-destructive/30"
                          : "bg-amber-500/10 text-amber-800 dark:text-amber-300 border border-amber-500/30"
                      )}
                    >
                      <div className="flex items-center justify-between font-semibold">
                        <span className="flex items-center gap-1">
                          <AlertTriangle className="h-3.5 w-3.5" />
                          {isCritical ? "Critical Deterioration Alert" : "Elevated Risk Warning"}
                        </span>
                        <span className="text-[10px] uppercase">{patient.news2.risk_level}</span>
                      </div>
                      <p className="text-[11px] leading-tight opacity-90">{patient.news2.recommendation}</p>
                      {patient.news2.triggers.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1 pt-1 border-t border-current/20">
                          {patient.news2.triggers.map((tr, i) => (
                            <span key={i} className="font-mono text-[10px] bg-background/60 rounded px-1.5 py-0.5">
                              {tr.parameter}: {tr.value} (+{tr.score})
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Latest Vitals Strip */}
                  <div className="rounded-lg border bg-card p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Activity className="h-3 w-3 text-primary" /> Latest Bedside Vitals
                      </span>
                      {patient.vitals?.recorded_at ? (
                        <span>{new Date(patient.vitals.recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                      ) : (
                        <span className="text-destructive font-medium">None today</span>
                      )}
                    </div>

                    {patient.vitals ? (
                      <div className="grid grid-cols-3 gap-2 text-center text-xs">
                        <div className="rounded bg-muted/40 p-1">
                          <span className="text-[10px] text-muted-foreground block">BP</span>
                          <span className="font-bold font-mono">{patient.vitals.bp || "—"}</span>
                        </div>
                        <div className="rounded bg-muted/40 p-1">
                          <span className="text-[10px] text-muted-foreground block">HR</span>
                          <span className="font-bold font-mono">{patient.vitals.pulse ? `${patient.vitals.pulse} bpm` : "—"}</span>
                        </div>
                        <div className="rounded bg-muted/40 p-1">
                          <span className="text-[10px] text-muted-foreground block">SpO2</span>
                          <span className="font-bold font-mono">{patient.vitals.spo2 ? `${patient.vitals.spo2}%` : "—"}</span>
                        </div>
                        <div className="rounded bg-muted/40 p-1">
                          <span className="text-[10px] text-muted-foreground block">RR</span>
                          <span className="font-bold font-mono">{patient.vitals.rr ? `${patient.vitals.rr} bpm` : "—"}</span>
                        </div>
                        <div className="rounded bg-muted/40 p-1">
                          <span className="text-[10px] text-muted-foreground block">Temp</span>
                          <span className="font-bold font-mono">{patient.vitals.temp ? `${patient.vitals.temp}°C` : "—"}</span>
                        </div>
                        <div className="rounded bg-muted/40 p-1">
                          <span className="text-[10px] text-muted-foreground block">Pain</span>
                          <span className="font-bold font-mono">{patient.vitals.pain !== null ? `${patient.vitals.pain}/10` : "—"}</span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground italic text-center py-2">
                        No observations recorded. Tap 'Record Vitals' to begin.
                      </p>
                    )}
                  </div>

                  {/* Operational indicators: Fluid, eMAR, Tasks */}
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div className="flex flex-col rounded border p-2 bg-muted/20">
                      <span className="text-muted-foreground flex items-center gap-1 text-[10px]">
                        <Droplets className="h-3 w-3 text-blue-500" /> Fluid 24h
                      </span>
                      <span className="font-bold font-mono mt-0.5">
                        {patient.fluid_balance_24h.net_ml >= 0 ? `+${patient.fluid_balance_24h.net_ml}` : patient.fluid_balance_24h.net_ml} mL
                      </span>
                    </div>

                    <div className="flex flex-col rounded border p-2 bg-muted/20">
                      <span className="text-muted-foreground flex items-center gap-1 text-[10px]">
                        <Pill className="h-3 w-3 text-emerald-500" /> eMAR Today
                      </span>
                      <span className="font-bold font-mono mt-0.5">
                        {patient.emar.administrations_today} doses
                      </span>
                    </div>

                    <div className="flex flex-col rounded border p-2 bg-muted/20">
                      <span className="text-muted-foreground flex items-center gap-1 text-[10px]">
                        <ListTodo className="h-3 w-3 text-amber-500" /> Open Tasks
                      </span>
                      <span className="font-bold font-mono mt-0.5">
                        {patient.tasks.pending_count} pending
                      </span>
                    </div>
                  </div>
                </div>

                {/* Card Action Footer Bar */}
                <div className="grid grid-cols-4 gap-1 border-t bg-muted/30 p-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] font-medium"
                    onClick={() => setSelectedPatientForRound(patient)}
                  >
                    <Stethoscope className="mr-1 h-3.5 w-3.5 text-primary" />
                    Vitals
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] font-medium"
                    onClick={() => setSelectedPatientForEmar(patient)}
                  >
                    <Pill className="mr-1 h-3.5 w-3.5 text-emerald-600" />
                    eMAR
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] font-medium"
                    onClick={() => setSelectedPatientForHandover(patient)}
                  >
                    <Send className="mr-1 h-3.5 w-3.5 text-blue-600" />
                    SBAR
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] font-medium"
                    onClick={() => setSelectedPatientForTasks(patient)}
                  >
                    <ListTodo className="mr-1 h-3.5 w-3.5 text-amber-600" />
                    Tasks
                  </Button>
                </div>
              </Card>
            );
          })}
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
      await api.post("/api/ipd/nurse-workspace/bedside-round/", {
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
              liveNews.color === "amber" && "bg-amber-500/10 border-amber-500/40 text-amber-800 dark:text-amber-300",
              liveNews.color === "green" && "bg-emerald-500/10 border-emerald-500/40 text-emerald-800 dark:text-emerald-300"
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
                liveNews.color === "amber" && "bg-amber-500 text-white",
                liveNews.color === "green" && "bg-emerald-600 text-white"
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
      const res = await api.get<EmarResponse>(`/api/ipd/nurse-workspace/emar/?admission=${patient.admission_uuid}`);
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
      await api.post("/api/ipd/nurse-workspace/emar/administer/", {
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
              <Pill className="h-5 w-5 text-emerald-600" />
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
                              <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-500/40">
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
                                    line.last_administered.status === "given" && "text-emerald-700 bg-emerald-50 border-emerald-300",
                                    line.last_administered.status === "held" && "text-amber-700 bg-amber-50 border-amber-300",
                                    line.last_administered.status === "refused" && "text-destructive bg-destructive/10 border-destructive/30"
                                  )}
                                >
                                  {line.last_administered.status}
                                </Badge>
                                <span className="block text-[10px] text-muted-foreground font-mono mt-0.5">
                                  {new Date(line.last_administered.administered_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                                </span>
                              </div>
                            ) : (
                              <span className="text-muted-foreground text-[11px]">—</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              size="sm"
                              className="h-7 text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white"
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
                            {new Date(adm.administered_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
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
                                adm.status === "given" && "text-emerald-700 bg-emerald-50 border-emerald-300",
                                adm.status === "held" && "text-amber-700 bg-amber-50 border-amber-300",
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
      await api.post("/api/ipd/nurse-workspace/handovers/", {
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
      await api.post(`/api/ipd/nurse-workspace/handovers/${patient.handover.uuid}/acknowledge/`, {});
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
              <Send className="h-5 w-5 text-blue-600" />
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
                <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-300">
                  <ShieldCheck className="mr-1 h-3 w-3" /> Acknowledged by {patient.handover.incoming_nurse_name}
                </Badge>
              ) : (
                <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-300">
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
            <Label className="text-xs font-bold text-blue-600">S — Situation (Current Clinical State & Concerns)</Label>
            <Textarea
              rows={2}
              value={situation}
              onChange={(e) => setSituation(e.target.value)}
              className="text-xs"
              required
            />
          </div>

          <div>
            <Label className="text-xs font-bold text-indigo-600">B — Background (History, Allergies, Surgeries)</Label>
            <Textarea
              rows={2}
              value={background}
              onChange={(e) => setBackground(e.target.value)}
              className="text-xs"
            />
          </div>

          <div>
            <Label className="text-xs font-bold text-amber-600">A — Assessment (Vitals, NEWS2, Lines, Fluid, Drains)</Label>
            <Textarea
              rows={2}
              value={assessment}
              onChange={(e) => setAssessment(e.target.value)}
              className="text-xs"
              required
            />
          </div>

          <div>
            <Label className="text-xs font-bold text-emerald-600">R — Recommendation (Incoming Shift Plan & Orders)</Label>
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
        `/api/ipd/nurse-workspace/tasks/?admission=${patient.admission_uuid}`
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
      await api.post("/api/ipd/nurse-workspace/tasks/", {
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
      await api.post(`/api/ipd/nurse-workspace/tasks/${task.uuid}/complete/`, {
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
              <ListTodo className="h-5 w-5 text-amber-600" />
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
                    <span className="text-[10px] text-emerald-600 font-medium block">
                      ✓ Done by {t.completed_by_name} at {new Date(t.completed_at!).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
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
      await api.post("/api/ipd/nurse-workspace/assignments/", {
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
