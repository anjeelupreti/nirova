/**
 * Patient search and registration.
 *
 * Search is one box, not a form with fields. At a counter the clerk has
 * whatever the patient can give them — a card, a phone number, half a name —
 * and should not have to decide which box it belongs in before they can look.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CircleAlert,
  Search,
  ShieldAlert,
  UserPlus,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import type { Facility, Paginated, Patient, PatientDetail } from "@/types";
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
} from "@/components/ui/primitives";

interface DuplicateCandidate {
  uuid: string;
  mrn: string;
  name: string;
  phone: string;
  age: number | null;
  score: number;
  matched_on: string[];
}

const CATEGORY_LABELS: Record<string, string> = {
  general: "General",
  corporate: "Corporate",
  insurance: "Insurance",
  government: "Government",
  staff: "Staff",
  charity: "Charity",
  foreign: "Foreign national",
};

function PatientRow({
  patient,
  onOpen,
}: {
  patient: Patient;
  onOpen: (patient: Patient) => void;
}) {
  return (
    <TableRow
      className="cursor-pointer"
      onClick={() => onOpen(patient)}
    >
      <TableCell className="font-mono text-xs">{patient.mrn}</TableCell>
      <TableCell className="font-medium">{patient.full_name}</TableCell>
      <TableCell className="capitalize">{patient.gender}</TableCell>
      <TableCell>{patient.age_years ?? "—"}</TableCell>
      <TableCell>{patient.phone || "—"}</TableCell>
      <TableCell>{patient.district || "—"}</TableCell>
      <TableCell>
        <Badge variant="secondary">
          {CATEGORY_LABELS[patient.category] ?? patient.category}
        </Badge>
      </TableCell>
    </TableRow>
  );
}

function PatientDetailPanel({ patient }: { patient: PatientDetail }) {
  // Allergies that block prescribing come first and loudly. A severe
  // penicillin allergy buried below an address is a patient-safety problem,
  // not a layout preference.
  const blocking = patient.allergies.filter((a) => a.blocks_prescribing);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>{patient.full_name}</CardTitle>
            <CardDescription className="mt-1 font-mono">
              {patient.mrn}
            </CardDescription>
          </div>
          <Badge variant={patient.is_merged ? "secondary" : "success"}>
            {patient.is_merged
              ? `merged → ${patient.merged_into_mrn}`
              : patient.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {patient.alerts && (
          <Alert variant="warning">
            <ShieldAlert className="h-4 w-4" />
            <AlertTitle>Alert</AlertTitle>
            <AlertDescription>{patient.alerts}</AlertDescription>
          </Alert>
        )}

        {blocking.length > 0 && (
          <Alert variant="destructive">
            <CircleAlert className="h-4 w-4" />
            <AlertTitle>
              {blocking.length === 1 ? "Allergy" : "Allergies"}
            </AlertTitle>
            <AlertDescription>
              <ul className="ml-4 list-disc space-y-0.5">
                {blocking.map((allergy) => (
                  <li key={allergy.uuid}>
                    <span className="font-medium">{allergy.substance}</span> —{" "}
                    {allergy.reaction || allergy.severity.replace(/_/g, " ")}
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">Age</dt>
            <dd>
              {patient.age_years ?? "unknown"}
              {patient.is_dob_estimated && (
                <span className="ml-1 text-xs text-amber-600">(estimated)</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Blood group</dt>
            <dd>{patient.blood_group}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Phone</dt>
            <dd>{patient.phone || "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Category</dt>
            <dd>{CATEGORY_LABELS[patient.category] ?? patient.category}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-muted-foreground">Address</dt>
            <dd>
              {[patient.tole, patient.municipality, patient.district]
                .filter(Boolean)
                .join(", ") || "—"}
            </dd>
          </div>
          {patient.guardian_name && (
            <div className="col-span-2">
              <dt className="text-muted-foreground">Guardian</dt>
              <dd>
                {patient.guardian_name} ({patient.guardian_relationship}){" "}
                {patient.guardian_phone}
              </dd>
            </div>
          )}
        </dl>

        {patient.conditions.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Conditions
            </p>
            <div className="flex flex-wrap gap-1.5">
              {patient.conditions.map((condition) => (
                <Badge key={condition.uuid} variant="outline">
                  {condition.name}
                  {condition.icd10_code && (
                    <span className="ml-1 opacity-60">
                      {condition.icd10_code}
                    </span>
                  )}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function PatientsPage() {
  const [term, setTerm] = useState("");
  const [results, setResults] = useState<Patient[]>([]);
  const [selected, setSelected] = useState<PatientDetail | null>(null);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [searching, setSearching] = useState(false);

  // Registration form
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    first_name: "",
    middle_name: "",
    last_name: "",
    gender: "female",
    date_of_birth: "",
    phone: "",
    district: "",
    facility_uuid: "",
  });
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        setFacilities(page.results);
        const clinic =
          page.results.find((f) => f.facility_type === "clinic") ??
          page.results[0];
        if (clinic) setForm((f) => ({ ...f, facility_uuid: clinic.uuid }));
      })
      .catch(() => undefined);
  }, []);

  const runSearch = useCallback(async (value: string) => {
    if (value.trim().length < 2) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const data = await api.get<{ results: Patient[] }>(
        `/clinical/patients/search/?q=${encodeURIComponent(value.trim())}`,
      );
      setResults(data.results);
    } finally {
      setSearching(false);
    }
  }, []);

  // Debounced so typing a name does not fire a request per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => void runSearch(term), 300);
    return () => clearTimeout(handle);
  }, [term, runSearch]);

  async function openPatient(patient: Patient) {
    const detail = await api.get<PatientDetail>(
      `/clinical/patients/${patient.uuid}/`,
    );
    setSelected(detail);
  }

  async function submitRegistration(force: boolean) {
    setError(null);
    setNotice(null);
    try {
      const payload: Record<string, unknown> = { ...form, force };
      if (!payload.date_of_birth) delete payload.date_of_birth;
      const created = await api.post<PatientDetail>(
        "/clinical/patients/",
        payload,
      );
      setNotice(`Registered ${created.mrn} — ${created.full_name}`);
      setDuplicates(null);
      setShowForm(false);
      setSelected(created);
      setForm((f) => ({
        ...f,
        first_name: "",
        middle_name: "",
        last_name: "",
        date_of_birth: "",
        phone: "",
      }));
    } catch (err) {
      if (err instanceof ApiError && err.code === "possible_duplicate_patient") {
        // Not a failure — the server is asking the clerk to look before
        // creating a second record for the same person.
        setDuplicates(
          (err.detail.candidates as DuplicateCandidate[] | undefined) ?? [],
        );
        return;
      }
      setError(err instanceof ApiError ? err.message : "Registration failed.");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Patients</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Search by name, MRN, phone or document number.
          </p>
        </div>
        <Button onClick={() => setShowForm((open) => !open)}>
          <UserPlus className="h-4 w-4" />
          {showForm ? "Close" : "Register patient"}
        </Button>
      </div>

      {showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle>Register a patient</CardTitle>
            <CardDescription>
              A name, a gender and an age are the minimum. Everything else can
              follow — an unconscious patient still has to be registered.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="first_name">First name</Label>
                <Input
                  id="first_name"
                  value={form.first_name}
                  onChange={(e) =>
                    setForm({ ...form, first_name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="middle_name">Middle name</Label>
                <Input
                  id="middle_name"
                  value={form.middle_name}
                  onChange={(e) =>
                    setForm({ ...form, middle_name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="last_name">Last name</Label>
                <Input
                  id="last_name"
                  value={form.last_name}
                  onChange={(e) =>
                    setForm({ ...form, last_name: e.target.value })
                  }
                />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-4">
              <div className="space-y-1.5">
                <Label htmlFor="gender">Gender</Label>
                <Select
                  id="gender"
                  value={form.gender}
                  onChange={(e) => setForm({ ...form, gender: e.target.value })}
                >
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                  <option value="other">Other</option>
                  <option value="unknown">Not stated</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dob">Date of birth</Label>
                <Input
                  id="dob"
                  type="date"
                  value={form.date_of_birth}
                  onChange={(e) =>
                    setForm({ ...form, date_of_birth: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="phone">Phone</Label>
                <Input
                  id="phone"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="district">District</Label>
                <Input
                  id="district"
                  value={form.district}
                  onChange={(e) =>
                    setForm({ ...form, district: e.target.value })
                  }
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="facility">Registering facility</Label>
              <Select
                id="facility"
                value={form.facility_uuid}
                onChange={(e) =>
                  setForm({ ...form, facility_uuid: e.target.value })
                }
              >
                {facilities.map((facility) => (
                  <option key={facility.uuid} value={facility.uuid}>
                    {facility.name}
                  </option>
                ))}
              </Select>
            </div>

            {duplicates && (
              <Alert variant="warning">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>This person may already be registered</AlertTitle>
                <AlertDescription className="space-y-2">
                  <ul className="ml-4 list-disc space-y-1">
                    {duplicates.map((candidate) => (
                      <li key={candidate.uuid}>
                        <span className="font-mono text-xs">
                          {candidate.mrn}
                        </span>{" "}
                        {candidate.name}
                        {candidate.age !== null && `, ${candidate.age}`}
                        {candidate.phone && ` · ${candidate.phone}`}
                        <span className="ml-1 text-xs opacity-70">
                          (matched {candidate.matched_on.join(", ")})
                        </span>
                      </li>
                    ))}
                  </ul>
                  <div className="flex gap-2 pt-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDuplicates(null)}
                    >
                      Use an existing record
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => void submitRegistration(true)}
                    >
                      This is a different person — register anyway
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {!duplicates && (
              <Button
                onClick={() => void submitRegistration(false)}
                disabled={!form.first_name || !form.last_name}
              >
                Register
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {notice && (
        <Alert variant="info">
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Name, MRN, phone or document number…"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
            />
          </div>

          <Card>
            <CardContent className="pt-6">
              {term.trim().length < 2 ? (
                <p className="text-sm text-muted-foreground">
                  Type at least two characters to search.
                </p>
              ) : searching ? (
                <p className="text-sm text-muted-foreground">Searching…</p>
              ) : results.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No patients match “{term}”.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>MRN</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Gender</TableHead>
                      <TableHead>Age</TableHead>
                      <TableHead>Phone</TableHead>
                      <TableHead>District</TableHead>
                      <TableHead>Category</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((patient) => (
                      <PatientRow
                        key={patient.uuid}
                        patient={patient}
                        onOpen={(p) => void openPatient(p)}
                      />
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          {selected ? (
            <PatientDetailPanel patient={selected} />
          ) : (
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">
                  Select a patient to see their record.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
