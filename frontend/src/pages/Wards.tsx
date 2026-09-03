/**
 * The ward: who is in which bed, and what is stopping them going home.
 *
 * Built for two people who never sit down. A nurse coming on shift opens the
 * bed board and needs the whole ward at a glance — occupant, ward, anything
 * unusual — without clicking into six beds. A ward clerk chasing discharges
 * needs to know which department to ring, not that a discharge is "blocked".
 *
 * Three things the screen keeps honest.
 *
 * **An unusable bed is not an available one.** A bed being cleaned and a bed
 * with a broken rail are both empty and neither can take a patient. The board
 * shows them in their own state, and the occupancy figure counts them against
 * total beds — so a ward with half its beds broken reads as a maintenance
 * problem rather than as a full ward.
 *
 * **Bed history is visible on the patient, not just the current bed.** A
 * transfer writes an interval; the stay shows the intervals, because "who was
 * in that bed on the night of the 14th?" is a question asked later and
 * answered here.
 *
 * **A blocked discharge names the department.** Five clearances and a balance
 * check, each with a person attached, and the override is a deliberate act
 * with a stated reason rather than a button that makes the warning go away.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  BedDouble,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Droplets,
  Hospital,
  Loader2,
  LogOut,
  ShieldAlert,
  Siren,
  Sparkles,
  Stethoscope,
  UserPlus,
  Wrench,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Admission,
  AdmissionSummary,
  Bed,
  Census,
  DailyAccrual,
  DischargeBlockers,
  Facility,
  FluidBalance,
  NursingRound,
  Paginated,
  StayCharges,
  Ward,
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "@/components/ui/primitives";

type Tab = "board" | "patients" | "census";

const TABS: { id: Tab; label: string; icon: typeof BedDouble }[] = [
  { id: "board", label: "Bed board", icon: BedDouble },
  { id: "patients", label: "Patients", icon: Stethoscope },
  { id: "census", label: "Census", icon: Hospital },
];

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const humanise = (value: string) => value.replace(/_/g, " ");

/** Colour a bed by what it can do, not by what it looks like. */
const BED_TONE: Record<string, string> = {
  available: "border-emerald-500/40 bg-emerald-50 dark:bg-emerald-950/30",
  occupied: "border-sky-500/40 bg-sky-50 dark:bg-sky-950/30",
  reserved: "border-amber-500/40 bg-amber-50 dark:bg-amber-950/30",
  cleaning: "border-amber-500/40 bg-amber-50/60 dark:bg-amber-950/20",
  maintenance: "border-destructive/40 bg-destructive/5",
  blocked: "border-destructive/40 bg-destructive/5",
};

const BED_ICON: Record<string, typeof BedDouble> = {
  cleaning: Sparkles,
  maintenance: Wrench,
  blocked: Wrench,
};

export default function WardsPage() {
  const [tab, setTab] = useState<Tab>("board");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        // Wards belong to hospitals, so default there rather than to whatever
        // happens to be first — a user opening this screen wants the ward.
        const withBeds =
          page.results.find((row) => row.facility_type === "hospital") ??
          page.results[0];
        setFacilities(page.results);
        if (withBeds) setFacility(withBeds.uuid);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  if (denied) {
    return (
      <Alert>
        <ShieldAlert className="h-4 w-4" />
        <AlertTitle>The ward is not visible to you</AlertTitle>
        <AlertDescription>
          Seeing who is in which bed needs clinical permissions.
        </AlertDescription>
      </Alert>
    );
  }

  if (open) {
    return <AdmissionDetail reference={open} onBack={() => setOpen(null)} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Wards</h1>
          <p className="text-sm text-muted-foreground">
            Who is in which bed, and what is stopping them going home.
          </p>
        </div>
        <Select
          className="h-9 w-auto"
          aria-label="Facility"
          value={facility}
          onChange={(event) => setFacility(event.target.value)}
        >
          {facilities.map((row) => (
            <option key={row.uuid} value={row.uuid}>
              {row.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex gap-1 border-b">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
              tab === id
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === "board" && <BedBoard facility={facility} onOpen={setOpen} />}
      {tab === "patients" && (
        <Patients facility={facility} onOpen={setOpen} />
      )}
      {tab === "census" && <CensusView facility={facility} onOpen={setOpen} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bed board                                                                   */
/* -------------------------------------------------------------------------- */

function BedBoard({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [wards, setWards] = useState<Ward[]>([]);
  const [beds, setBeds] = useState<Record<string, Bed[]>>({});
  const [admitting, setAdmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!facility) return;
    setLoading(true);
    try {
      const page = await api.get<Paginated<Ward>>(
        `/ipd/wards/?facility=${facility}&is_active=true`,
      );
      setWards(page.results);
      const boards = await Promise.all(
        page.results.map((ward) =>
          api
            .get<Bed[]>(`/ipd/wards/${ward.uuid}/beds/`)
            .then((rows) => [ward.uuid, rows] as const),
        ),
      );
      setBeds(Object.fromEntries(boards));
    } finally {
      setLoading(false);
    }
  }, [facility]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  if (wards.length === 0) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-sm text-muted-foreground">
          <BedDouble className="mx-auto mb-2 h-8 w-8 opacity-40" />
          No wards at this facility.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setAdmitting(true)}>
          <UserPlus className="h-4 w-4" />
          Admit
        </Button>
      </div>

      {wards.map((ward) => {
        const rows = beds[ward.uuid] ?? [];
        const occupied = rows.filter((bed) => bed.is_occupied).length;
        const unusable = rows.filter(
          (bed) => !bed.is_assignable && !bed.is_occupied,
        ).length;
        return (
          <Card key={ward.uuid}>
            <CardHeader className="flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  {ward.name}
                  {ward.is_critical_care && (
                    <Badge variant="destructive">critical care</Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  {occupied} of {rows.length} occupied
                  {unusable > 0 && ` · ${unusable} unusable`} · 1 nurse to{" "}
                  {ward.nurse_to_patient_ratio} patients
                </CardDescription>
              </div>
              <Badge variant="outline">{humanise(ward.ward_type)}</Badge>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                {rows.map((bed) => {
                  const Icon = BED_ICON[bed.status];
                  return (
                    <button
                      key={bed.uuid}
                      type="button"
                      disabled={!bed.occupant_admission}
                      onClick={() =>
                        bed.occupant_admission &&
                        onOpen(bed.occupant_admission)
                      }
                      className={cn(
                        "rounded-md border p-3 text-left transition-colors",
                        BED_TONE[bed.status] ?? "border-muted",
                        bed.occupant_admission
                          ? "cursor-pointer hover:brightness-95"
                          : "cursor-default",
                      )}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-sm font-medium">{bed.code}</span>
                        {Icon ? (
                          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                        ) : (
                          <BedDouble className="h-3.5 w-3.5 text-muted-foreground" />
                        )}
                      </div>
                      <p className="truncate text-xs">
                        {bed.occupant_name || (
                          <span className="text-muted-foreground">
                            {humanise(bed.status)}
                          </span>
                        )}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {bed.gender_restriction !== "any" && (
                          <Badge variant="outline" className="text-[10px]">
                            {bed.gender_restriction}
                          </Badge>
                        )}
                        {bed.has_ventilator && (
                          <Badge variant="outline" className="text-[10px]">
                            vent
                          </Badge>
                        )}
                        {bed.is_isolation && (
                          <Badge variant="outline" className="text-[10px]">
                            isolation
                          </Badge>
                        )}
                      </div>
                      {bed.status_reason && (
                        <p className="mt-1 text-[10px] text-destructive">
                          {bed.status_reason}
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        );
      })}

      <p className="text-xs text-muted-foreground">
        A bed being cleaned and a bed with a broken rail are both empty and
        neither can take a patient — which is why they have their own state
        rather than showing as available.
      </p>

      {admitting && (
        <AdmitDialog
          facility={facility}
          wards={wards}
          onClose={() => setAdmitting(false)}
          onAdmitted={(reference) => {
            setAdmitting(false);
            onOpen(reference);
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Admitting                                                                   */
/* -------------------------------------------------------------------------- */

function AdmitDialog({
  facility,
  wards,
  onClose,
  onAdmitted,
}: {
  facility: string;
  wards: Ward[];
  onClose: () => void;
  onAdmitted: (reference: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [patients, setPatients] = useState<
    { uuid: string; mrn: string; full_name: string; gender: string }[]
  >([]);
  const [form, setForm] = useState({
    patient: "",
    ward: wards[0]?.uuid ?? "",
    source: "opd",
    admitting_diagnosis: "",
    expected_discharge: "",
    deposit_expected: "0",
    attendant_name: "",
    attendant_phone: "",
    attendant_relation: "",
    is_mlc: false,
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (search.trim().length < 2) return;
    const handle = window.setTimeout(() => {
      void api
        .get<Paginated<{ uuid: string; mrn: string; full_name: string; gender: string }>>(
          `/clinical/patients/?search=${encodeURIComponent(search)}`,
        )
        .then((page) => setPatients(page.results.slice(0, 8)))
        .catch(() => setPatients([]));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [search]);

  const chosen = patients.find((row) => row.uuid === form.patient);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const admission = await api.post<Admission>("/ipd/admissions/", {
        ...form,
        facility,
        expected_discharge: form.expected_discharge || null,
      });
      onAdmitted(admission.reference);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not admitted.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>Admit a patient</CardTitle>
          <CardDescription>
            Choosing a ward takes the first assignable bed that suits the
            patient. Leaving it blank admits them as waiting for a bed, which
            is a real state.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="a-patient">Patient</Label>
            <Input
              id="a-patient"
              placeholder="Name or MRN…"
              value={chosen ? `${chosen.full_name} (${chosen.mrn})` : search}
              onChange={(event) => {
                setSearch(event.target.value);
                setForm((f) => ({ ...f, patient: "" }));
              }}
            />
            {!chosen && patients.length > 0 && (
              <ul className="divide-y rounded-md border">
                {patients.map((row) => (
                  <li key={row.uuid}>
                    <button
                      type="button"
                      className="w-full px-3 py-2 text-left text-sm hover:bg-muted/60"
                      onClick={() => {
                        setForm((f) => ({ ...f, patient: row.uuid }));
                        setPatients([]);
                      }}
                    >
                      {row.full_name}
                      <span className="text-muted-foreground"> · {row.mrn}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="a-ward">Ward</Label>
              <Select
                id="a-ward"
                value={form.ward}
                onChange={(event) =>
                  setForm((f) => ({ ...f, ward: event.target.value }))
                }
              >
                <option value="">No bed yet — waiting</option>
                {wards.map((row) => (
                  <option key={row.uuid} value={row.uuid}>
                    {row.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="a-source">Came from</Label>
              <Select
                id="a-source"
                value={form.source}
                onChange={(event) =>
                  setForm((f) => ({ ...f, source: event.target.value }))
                }
              >
                {[
                  ["opd", "Outpatients"],
                  ["emergency", "Emergency"],
                  ["referral", "Referred in"],
                  ["transfer", "Another hospital"],
                  ["direct", "Direct"],
                  ["birth", "Born here"],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="a-diagnosis">Admitting diagnosis</Label>
            <Textarea
              id="a-diagnosis"
              rows={2}
              value={form.admitting_diagnosis}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  admitting_diagnosis: event.target.value,
                }))
              }
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="a-expected">Expected out</Label>
              <Input
                id="a-expected"
                type="date"
                value={form.expected_discharge}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    expected_discharge: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="a-deposit">Deposit</Label>
              <Input
                id="a-deposit"
                inputMode="decimal"
                value={form.deposit_expected}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    deposit_expected: event.target.value,
                  }))
                }
              />
            </div>
          </div>

          <div className="space-y-2 rounded-md border p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Attendant
            </p>
            <div className="grid grid-cols-2 gap-2">
              <Input
                placeholder="Name"
                value={form.attendant_name}
                onChange={(event) =>
                  setForm((f) => ({ ...f, attendant_name: event.target.value }))
                }
              />
              <Input
                placeholder="Phone"
                value={form.attendant_phone}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    attendant_phone: event.target.value,
                  }))
                }
              />
            </div>
            <Input
              placeholder="Relationship"
              value={form.attendant_relation}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  attendant_relation: event.target.value,
                }))
              }
            />
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              checked={form.is_mlc}
              onChange={(event) =>
                setForm((f) => ({ ...f, is_mlc: event.target.checked }))
              }
            />
            <span>
              Medico-legal case
              <span className="block text-xs text-muted-foreground">
                Assault, accident, poisoning or burns. The police must be
                informed, and the admission is logged as one.
              </span>
            </span>
          </label>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || !form.patient}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <UserPlus className="h-4 w-4" />
              )}
              Admit
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Patients                                                                    */
/* -------------------------------------------------------------------------- */

function Patients({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [rows, setRows] = useState<AdmissionSummary[]>([]);
  const [inHouse, setInHouse] = useState(true);

  useEffect(() => {
    if (!facility) return;
    const query = inHouse ? "&in_house=true" : "";
    void api
      .get<Paginated<AdmissionSummary>>(
        `/ipd/admissions/?facility=${facility}${query}`,
      )
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, [facility, inHouse]);

  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          className="h-4 w-4"
          checked={inHouse}
          onChange={(event) => setInHouse(event.target.checked)}
        />
        Only patients who are here now
      </label>

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Patient</TableHead>
                <TableHead>Where</TableHead>
                <TableHead>Since</TableHead>
                <TableHead className="text-right">Nights</TableHead>
                <TableHead>Consultant</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={row.uuid}
                  className="cursor-pointer"
                  onClick={() => onOpen(row.reference)}
                >
                  <TableCell>
                    <span className="font-medium">{row.patient_name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {row.patient_mrn} · {row.reference}
                    </span>
                    {row.is_mlc && (
                      <Badge variant="destructive" className="mt-1">
                        <Siren className="mr-1 h-3 w-3" />
                        medico-legal
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {row.bed_code || (
                      <span className="text-amber-600">waiting for a bed</span>
                    )}
                    {row.ward_name && (
                      <span className="block text-xs text-muted-foreground">
                        {row.ward_name}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {new Date(row.admitted_at).toLocaleDateString()}
                    {row.expected_discharge && (
                      <span
                        className={cn(
                          "block",
                          row.is_overstaying
                            ? "font-medium text-destructive"
                            : "text-muted-foreground",
                        )}
                      >
                        out {row.expected_discharge}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.length_of_stay_days}
                  </TableCell>
                  <TableCell className="text-xs">
                    {row.consultant_name || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        row.status === "admitted"
                          ? "secondary"
                          : row.status === "discharge_initiated"
                            ? "default"
                            : "outline"
                      }
                    >
                      {humanise(row.status)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    Nobody is admitted.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One admission                                                               */
/* -------------------------------------------------------------------------- */

function AdmissionDetail({
  reference,
  onBack,
}: {
  reference: string;
  onBack: () => void;
}) {
  const [admission, setAdmission] = useState<Admission | null>(null);
  const [charges, setCharges] = useState<StayCharges | null>(null);
  const [accruals, setAccruals] = useState<DailyAccrual[]>([]);
  const [blockers, setBlockers] = useState<DischargeBlockers | null>(null);
  const [rounds, setRounds] = useState<NursingRound[]>([]);
  const [balance, setBalance] = useState<FluidBalance | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [discharging, setDischarging] = useState(false);
  const [moving, setMoving] = useState(false);

  const load = useCallback(async () => {
    const [detail, cost, accrualRows, block, roundRows, fluid] =
      await Promise.all([
        api.get<Admission>(`/ipd/admissions/${reference}/`),
        api.get<StayCharges>(`/ipd/admissions/${reference}/charges/`),
        api.get<DailyAccrual[]>(`/ipd/admissions/${reference}/accruals/`),
        api.get<DischargeBlockers>(`/ipd/admissions/${reference}/blockers/`),
        api.get<NursingRound[]>(`/ipd/admissions/${reference}/rounds/`),
        api.get<FluidBalance>(`/ipd/admissions/${reference}/fluid-balance/`),
      ]);
    setAdmission(detail);
    setCharges(cost);
    setAccruals(accrualRows);
    setBlockers(block);
    setRounds(roundRows);
    setBalance(fluid);
  }, [reference]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ipd/admissions/${reference}/${path}/`, body);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  };

  if (!admission || !charges) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        ← Back to the ward
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {admission.patient_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {admission.reference} · {admission.patient_mrn}
            {admission.bed_code && ` · ${admission.bed_code}`}
            {admission.consultant_name && ` · ${admission.consultant_name}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {admission.is_in_house && (
            <Button variant="outline" size="sm" onClick={() => setMoving(true)}>
              <ArrowRightLeft className="h-4 w-4" />
              Move
            </Button>
          )}
          {admission.status === "admitted" && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void act("initiate-discharge")}
            >
              <Clock className="h-4 w-4" />
              Start discharge
            </Button>
          )}
          {admission.is_in_house && (
            <Button size="sm" onClick={() => setDischarging(true)}>
              <LogOut className="h-4 w-4" />
              Discharge
            </Button>
          )}
        </div>
      </div>

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {admission.is_mlc && (
        <Alert variant="destructive">
          <Siren className="h-4 w-4" />
          <AlertTitle>Medico-legal case</AlertTitle>
          <AlertDescription>
            {admission.mlc_number && `MLC ${admission.mlc_number}. `}
            {admission.police_informed_at
              ? `Police informed ${new Date(admission.police_informed_at).toLocaleString()}.`
              : "The police have not been recorded as informed."}
          </AlertDescription>
        </Alert>
      )}

      {admission.is_overstaying && (
        <Alert>
          <Clock className="h-4 w-4" />
          <AlertTitle>Past the expected discharge date</AlertTitle>
          <AlertDescription>
            Expected out {admission.expected_discharge};{" "}
            {admission.length_of_stay_days} nights so far. An overstay is
            usually a deterioration nobody escalated or a discharge nobody
            completed.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Nights" value={String(admission.length_of_stay_days)} />
        <Stat label="Charged" value={rupees(charges.charge_total)} />
        <Stat
          label="Not yet invoiced"
          value={rupees(charges.uninvoiced)}
          tone={
            Number(charges.uninvoiced) > 0 ? "text-amber-600" : undefined
          }
        />
        <Stat
          label="Outstanding"
          value={rupees(charges.outstanding)}
          tone={
            Number(charges.outstanding) > 0 ? "text-destructive" : undefined
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Where they have been</CardTitle>
              <CardDescription>
                A transfer writes an interval rather than overwriting the bed —
                which is what answers a question about a particular night.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="relative space-y-4 border-l pl-6">
                {admission.bed_assignments.map((row) => (
                  <li key={row.uuid} className="relative">
                    <span
                      className={cn(
                        "absolute -left-[1.65rem] top-1 h-3 w-3 rounded-full border-2 border-background",
                        row.is_current ? "bg-primary" : "bg-muted-foreground",
                      )}
                    />
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-medium">
                        {row.ward_name} · {row.bed_code}
                      </span>
                      {row.is_current && (
                        <Badge variant="secondary">now</Badge>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {rupees(row.daily_rate)} a day
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {new Date(row.occupied_at).toLocaleString()} →{" "}
                      {row.vacated_at
                        ? new Date(row.vacated_at).toLocaleString()
                        : "still there"}
                    </p>
                    {row.reason && (
                      <p className="text-sm">{row.reason}</p>
                    )}
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Bed-days charged</CardTitle>
              <CardDescription>
                One row per night, at the rate captured on that night's bed.
                Re-running the accrual charges nothing again.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Bed</TableHead>
                    <TableHead className="text-right">Rate</TableHead>
                    <TableHead>Billed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {accruals.map((row) => (
                    <TableRow key={row.uuid}>
                      <TableCell className="tabular-nums">
                        {row.accrual_date}
                      </TableCell>
                      <TableCell className="text-xs">
                        {row.description}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {rupees(row.amount)}
                      </TableCell>
                      <TableCell>
                        {row.charge_uuid ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                        ) : (
                          <Badge variant="destructive">unbilled</Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {accruals.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={4}
                        className="py-6 text-center text-sm text-muted-foreground"
                      >
                        Nothing accrued yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
              {admission.is_in_house && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  disabled={busy}
                  onClick={() => void act("accrue")}
                >
                  Accrue any missed day
                </Button>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle className="text-base">Nursing</CardTitle>
                {balance && (
                  <CardDescription>
                    Last {balance.hours}h: in {balance.intake_ml}ml, out{" "}
                    {balance.output_ml}ml, balance{" "}
                    <span
                      className={cn(
                        balance.balance_ml < -500 && "font-medium text-destructive",
                      )}
                    >
                      {balance.balance_ml > 0 ? "+" : ""}
                      {balance.balance_ml}ml
                    </span>
                  </CardDescription>
                )}
              </div>
              <Droplets className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent className="space-y-2">
              {rounds.slice(0, 6).map((row) => (
                <div
                  key={row.uuid}
                  className={cn(
                    "rounded-md border p-2 text-sm",
                    row.escalated && "border-destructive/50 bg-destructive/5",
                  )}
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium capitalize">
                      {row.shift || "round"}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(row.recorded_at).toLocaleString()} ·{" "}
                      {row.nurse_name}
                    </span>
                    {row.escalated && (
                      <Badge variant="destructive">escalated</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    in {row.intake_ml}ml · out {row.output_ml}ml
                    {row.pain_score !== null && ` · pain ${row.pain_score}/10`}
                  </p>
                  {row.observations && <p>{row.observations}</p>}
                  {row.escalation_reason && (
                    <p className="text-destructive">{row.escalation_reason}</p>
                  )}
                </div>
              ))}
              {rounds.length === 0 && (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No rounds recorded.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Discharge</CardTitle>
              <CardDescription>
                Five sign-offs and a balance check. A blocked discharge names
                the department, so somebody knows who to ring.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {admission.clearances.map((row) => (
                <div
                  key={row.uuid}
                  className="flex items-start gap-2 text-sm"
                >
                  {row.is_cleared ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : (
                    <ClipboardCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <span className="capitalize">{humanise(row.kind)}</span>
                    {row.cleared_by_name && (
                      <span className="block text-xs text-muted-foreground">
                        {row.cleared_by_name}
                      </span>
                    )}
                    {row.blocking_reason && (
                      <span className="block text-xs text-destructive">
                        {row.blocking_reason}
                      </span>
                    )}
                  </div>
                  {!row.is_cleared && admission.is_in_house && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        void act("clear", { kind: row.kind, cleared: true })
                      }
                    >
                      Sign off
                    </Button>
                  )}
                </div>
              ))}

              {blockers && blockers.blockers.length > 0 && (
                <Alert className="mt-2">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>
                    {blockers.blockers.length} things in the way
                  </AlertTitle>
                  <AlertDescription>
                    <ul className="space-y-0.5">
                      {blockers.blockers.map((row) => (
                        <li key={row.code}>{row.message}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
              {blockers?.can_discharge && admission.is_in_house && (
                <Alert>
                  <CheckCircle2 className="h-4 w-4" />
                  <AlertDescription>
                    Everything is cleared. They can go.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Field label="Admitted" value={new Date(admission.admitted_at).toLocaleString()} />
              <Field label="From" value={humanise(admission.source)} />
              <Field
                label="Diagnosis"
                value={admission.admitting_diagnosis || "—"}
              />
              <Field
                label="Deposit"
                value={rupees(admission.deposit_expected)}
              />
              {admission.attendant_name && (
                <Field
                  label={admission.attendant_relation || "Attendant"}
                  value={`${admission.attendant_name} · ${admission.attendant_phone}`}
                />
              )}
              {admission.discharged_at && (
                <>
                  <Field
                    label="Discharged"
                    value={new Date(admission.discharged_at).toLocaleString()}
                  />
                  <Field
                    label="Final diagnosis"
                    value={admission.final_diagnosis || "—"}
                  />
                </>
              )}
            </CardContent>
          </Card>

          {admission.discharge_summary && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Discharge summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>{admission.discharge_summary}</p>
                {admission.discharge_advice && (
                  <p className="text-muted-foreground">
                    {admission.discharge_advice}
                  </p>
                )}
                {admission.follow_up_on && (
                  <p className="text-muted-foreground">
                    Follow up {admission.follow_up_on}
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {moving && (
        <MoveDialog
          admission={admission}
          onClose={() => setMoving(false)}
          onMoved={() => {
            setMoving(false);
            void load();
          }}
        />
      )}
      {discharging && blockers && (
        <DischargeDialog
          admission={admission}
          blockers={blockers}
          onClose={() => setDischarging(false)}
          onDone={() => {
            setDischarging(false);
            void load();
          }}
        />
      )}
    </div>
  );
}

function MoveDialog({
  admission,
  onClose,
  onMoved,
}: {
  admission: Admission;
  onClose: () => void;
  onMoved: () => void;
}) {
  const [beds, setBeds] = useState<Bed[]>([]);
  const [bed, setBed] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Bed[]>(`/ipd/beds/?available=true&facility=${admission.facility}`)
      .then(setBeds)
      .catch(() => setBeds([]));
  }, [admission.facility]);

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ipd/admissions/${admission.reference}/transfer/`, {
        bed,
        reason,
      });
      onMoved();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not moved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Move {admission.patient_name}</CardTitle>
          <CardDescription>
            Only beds that can actually take them are listed — a bed being
            cleaned is empty and not available.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="m-bed">New bed</Label>
            <Select
              id="m-bed"
              value={bed}
              onChange={(event) => setBed(event.target.value)}
            >
              <option value="">Choose a bed</option>
              {beds.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.ward_name} · {row.code} — {rupees(row.daily_rate)}/day
                  {row.gender_restriction !== "any" &&
                    ` (${row.gender_restriction} only)`}
                </option>
              ))}
            </Select>
            {beds.length === 0 && (
              <p className="text-xs text-destructive">
                No assignable beds at this facility.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="m-reason">Why</Label>
            <Textarea
              id="m-reason"
              rows={2}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Rising oxygen requirement; needs continuous monitoring."
            />
            <p className="text-xs text-muted-foreground">
              The new bed's rate applies from now. Nights already charged keep
              the rate they were charged at.
            </p>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={busy || !bed || reason.trim().length < 5}
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowRightLeft className="h-4 w-4" />
              )}
              Move
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DischargeDialog({
  admission,
  blockers,
  onClose,
  onDone,
}: {
  admission: Admission;
  blockers: DischargeBlockers;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    outcome: "discharged",
    summary: "",
    advice: "",
    final_diagnosis: "",
    follow_up_on: "",
    override_reason: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const compassionate = ["died", "lama"].includes(form.outcome);
  const needsOverride = !blockers.can_discharge && !compassionate;

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/ipd/admissions/${admission.reference}/discharge/`, {
        ...form,
        follow_up_on: form.follow_up_on || null,
      });
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Not discharged.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>Discharge {admission.patient_name}</CardTitle>
          <CardDescription>
            {admission.length_of_stay_days} nights. The bed goes to cleaning,
            not straight back to available.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="d-outcome">How the stay ended</Label>
            <Select
              id="d-outcome"
              value={form.outcome}
              onChange={(event) =>
                setForm((f) => ({ ...f, outcome: event.target.value }))
              }
            >
              <option value="discharged">Discharged</option>
              <option value="lama">Left against medical advice</option>
              <option value="transferred_out">
                Transferred to another hospital
              </option>
              <option value="absconded">Absconded</option>
              <option value="died">Died</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              Recorded distinctly because a mortality rate, a LAMA rate and an
              absconder rate are three different conversations with a
              regulator.
            </p>
          </div>

          {compassionate && (
            <Alert>
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>
                The balance check is skipped for this outcome. Refusing to
                release a body over an unpaid bill is not a policy anybody
                should be able to configure.
              </AlertDescription>
            </Alert>
          )}

          {needsOverride && (
            <Alert variant="destructive">
              <ShieldAlert className="h-4 w-4" />
              <AlertTitle>
                {blockers.blockers.length} things are not cleared
              </AlertTitle>
              <AlertDescription>
                <ul className="mb-2 space-y-0.5">
                  {blockers.blockers.map((row) => (
                    <li key={row.code}>{row.message}</li>
                  ))}
                </ul>
                Discharging anyway needs a stated reason, and the override is
                logged against you.
              </AlertDescription>
            </Alert>
          )}

          {needsOverride && (
            <div className="space-y-2">
              <Label htmlFor="d-override">Reason for overriding</Label>
              <Textarea
                id="d-override"
                rows={2}
                value={form.override_reason}
                onChange={(event) =>
                  setForm((f) => ({
                    ...f,
                    override_reason: event.target.value,
                  }))
                }
                placeholder="Family settling the balance by bank transfer tomorrow; authorised by the medical director."
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="d-diagnosis">Final diagnosis</Label>
            <Input
              id="d-diagnosis"
              value={form.final_diagnosis}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  final_diagnosis: event.target.value,
                }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="d-summary">Discharge summary</Label>
            <Textarea
              id="d-summary"
              rows={3}
              value={form.summary}
              onChange={(event) =>
                setForm((f) => ({ ...f, summary: event.target.value }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="d-advice">Advice on leaving</Label>
            <Textarea
              id="d-advice"
              rows={2}
              value={form.advice}
              onChange={(event) =>
                setForm((f) => ({ ...f, advice: event.target.value }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="d-followup">Follow up on</Label>
            <Input
              id="d-followup"
              type="date"
              value={form.follow_up_on}
              onChange={(event) =>
                setForm((f) => ({ ...f, follow_up_on: event.target.value }))
              }
            />
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button
              className="flex-1"
              disabled={
                busy ||
                (needsOverride && form.override_reason.trim().length < 10)
              }
              onClick={() => void submit()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LogOut className="h-4 w-4" />
              )}
              Discharge
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Census                                                                      */
/* -------------------------------------------------------------------------- */

function CensusView({
  facility,
  onOpen,
}: {
  facility: string;
  onOpen: (reference: string) => void;
}) {
  const [data, setData] = useState<Census | null>(null);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<Census>(`/ipd/census/?facility=${facility}`)
      .then(setData)
      .catch(() => setData(null));
  }, [facility]);

  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="In house" value={String(data.in_house)} />
        <Stat
          label="Occupancy"
          value={`${data.occupancy_percent}%`}
          hint={`${data.occupied} of ${data.total_beds}`}
        />
        <Stat
          label="Available"
          value={String(data.available)}
          hint={`${data.unusable} unusable`}
        />
        <Stat
          label="Waiting for a bed"
          value={String(data.awaiting_a_bed)}
          tone={data.awaiting_a_bed > 0 ? "text-amber-600" : undefined}
        />
        <Stat
          label="Today"
          value={`${data.admitted_today} in / ${data.discharged_today} out`}
          hint={
            data.discharge_in_progress > 0
              ? `${data.discharge_in_progress} in progress`
              : undefined
          }
        />
      </div>

      {data.overstaying.length > 0 && (
        <Alert>
          <Clock className="h-4 w-4" />
          <AlertTitle>
            {data.overstaying.length} past their expected discharge
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-1 space-y-0.5">
              {data.overstaying.map((row) => (
                <li key={row.reference}>
                  <button
                    type="button"
                    className="underline underline-offset-2"
                    onClick={() => onOpen(row.reference)}
                  >
                    {row.patient}
                  </button>
                  {" — expected out "}
                  {row.expected}, {row.nights} nights so far.
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">By ward</CardTitle>
          <CardDescription>
            Occupancy is against total beds. A ward with half its beds broken
            is a maintenance problem, not a full ward.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ward</TableHead>
                <TableHead className="text-right">Occupied</TableHead>
                <TableHead className="text-right">Available</TableHead>
                <TableHead className="text-right">Unusable</TableHead>
                <TableHead className="text-right">Occupancy</TableHead>
                <TableHead className="text-right">Nurses needed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.by_ward.map((row) => (
                <TableRow key={row.ward}>
                  <TableCell>
                    <span className="font-medium">{row.ward_name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {humanise(row.ward_type)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.occupied} / {row.total_beds}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.available}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      row.unusable > 0 && "text-amber-600",
                    )}
                  >
                    {row.unusable}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {row.occupancy_percent}%
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.nurses_needed ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bits                                                                        */
/* -------------------------------------------------------------------------- */

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className={cn("mt-1 text-xl font-semibold tabular-nums", tone)}>
          {value}
        </p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
