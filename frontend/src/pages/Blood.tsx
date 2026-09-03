/**
 * The blood bank.
 *
 * The one screen in this system where a wrong number kills somebody, so it is
 * built the way the module is: around refusals, and around showing the reason
 * before anybody walks to the fridge.
 *
 * What it refuses to soften.
 *
 * **The shelf is a grid, not a total.** Group down, component across, with
 * what expires this week in red. Forty units of O positive expiring on
 * Thursday and none of A negative is a crisis that a single number hides.
 *
 * **A quarantined donation shows every blocker at once**, and says which
 * infections are untested rather than folding them in with the reactive ones.
 * They are opposite problems: one is a laboratory that lost a sample, the
 * other is a donor who must be told.
 *
 * **Issue blockers are shown before the button**, not after the click. The
 * button is disabled and the reason is on the screen.
 *
 * **The emergency path is visually separate and deliberately unattractive.**
 * It demands a named authoriser and a reason, and says in words that this is a
 * risk the hospital is accepting rather than a step being skipped.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Droplet,
  FlaskConical,
  Loader2,
  PhoneCall,
  ShieldAlert,
  Siren,
  Snowflake,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  BloodRequest,
  BloodStock,
  BloodUnit,
  BloodWastage,
  Donation,
  Donor,
  DonorCallRow,
  Facility,
  Haemovigilance,
  LookBack,
  Paginated,
  Transfusion,
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

type Tab = "shelf" | "processing" | "requests" | "donors" | "safety";

const TABS: { id: Tab; label: string; icon: typeof Droplet }[] = [
  { id: "shelf", label: "The shelf", icon: Snowflake },
  { id: "processing", label: "In process", icon: FlaskConical },
  { id: "requests", label: "Requests", icon: Droplet },
  { id: "donors", label: "Donors", icon: Users },
  { id: "safety", label: "Safety", icon: ShieldAlert },
];

const GROUPS = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"];

const COMPONENT_LABELS: Record<string, string> = {
  whole_blood: "Whole blood",
  red_cells: "Red cells",
  plasma: "Plasma",
  platelets: "Platelets",
  cryo: "Cryoprecipitate",
};

const humanise = (value: string) => value.replace(/_/g, " ");

const day = (value: string | null) =>
  value
    ? new Date(value).toLocaleDateString([], {
        day: "2-digit",
        month: "short",
        year: "2-digit",
      })
    : "—";

export default function BloodPage() {
  const [tab, setTab] = useState<Tab>("shelf");
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facility, setFacility] = useState("");
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    void api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        const preferred =
          page.results.find((row) => row.facility_type === "hospital") ??
          page.results[0];
        setFacilities(page.results);
        if (preferred) setFacility(preferred.uuid);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true);
      });
  }, []);

  if (denied) {
    return (
      <Alert>
        <Droplet className="h-4 w-4" />
        <AlertTitle>The blood bank is not visible to you</AlertTitle>
        <AlertDescription>
          Seeing the shelf needs clinical permissions.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Blood bank</h1>
          <p className="text-sm text-muted-foreground">
            What is on the shelf, what is not safe yet, and who it went to.
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

      <div className="flex gap-1 overflow-x-auto border-b">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
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

      {tab === "shelf" && <Shelf facility={facility} />}
      {tab === "processing" && <Processing />}
      {tab === "requests" && <Requests facility={facility} />}
      {tab === "donors" && <Donors facility={facility} />}
      {tab === "safety" && <Safety facility={facility} />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The shelf                                                                   */
/* -------------------------------------------------------------------------- */

function Shelf({ facility }: { facility: string }) {
  const [stock, setStock] = useState<BloodStock | null>(null);
  const [units, setUnits] = useState<BloodUnit[]>([]);
  const [open, setOpen] = useState<BloodUnit | null>(null);

  const load = useCallback(async () => {
    if (!facility) return;
    const [holdings, page] = await Promise.all([
      api.get<BloodStock>(`/blood/reports/?report=stock&facility=${facility}`),
      api.get<Paginated<BloodUnit>>(`/blood/units/?facility=${facility}`),
    ]);
    setStock(holdings);
    setUnits(
      page.results.filter(
        (row) => !["transfused", "discarded", "expired"].includes(row.status),
      ),
    );
  }, [facility]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!stock) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  const components = Object.keys(stock.by_component);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Fact label="On the shelf" value={String(stock.total)} />
        <Fact label="Available" value={String(stock.available)} />
        <Fact label="Held" value={String(stock.held)} hint="reserved or matched" />
        <Fact
          label="Quarantined"
          value={String(stock.quarantined)}
          hint="not yet released"
          tone={stock.quarantined > 0 ? "text-amber-600" : undefined}
        />
        <Fact
          label="Expiring this week"
          value={String(stock.expiring_within_7_days)}
          tone={
            stock.expiring_within_7_days > 0 ? "text-destructive" : undefined
          }
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Group by component</CardTitle>
          <CardDescription>
            The shape rather than the total. Forty units of O positive expiring
            on Thursday and none of A negative is a crisis that a single number
            hides.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Group</TableHead>
                  {components.map((component) => (
                    <TableHead key={component} className="text-right">
                      {COMPONENT_LABELS[component] ?? humanise(component)}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {GROUPS.map((group) => {
                  const cells = components.map(
                    (component) => stock.by_component[component]?.[group],
                  );
                  const empty = cells.every((cell) => !cell);
                  return (
                    <TableRow key={group} className={cn(empty && "opacity-50")}>
                      <TableCell className="font-mono font-medium">
                        {group}
                      </TableCell>
                      {cells.map((cell, index) => (
                        <TableCell
                          key={index}
                          className="text-right tabular-nums"
                        >
                          {cell ? (
                            <>
                              <span
                                className={cn(
                                  cell.available === 0 && "text-destructive",
                                )}
                              >
                                {cell.available}
                              </span>
                              {cell.held > 0 && (
                                <span className="text-xs text-muted-foreground">
                                  {" "}
                                  +{cell.held} held
                                </span>
                              )}
                              {cell.expiring > 0 && (
                                <span className="block text-xs text-destructive">
                                  {cell.expiring} expiring
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Every unit</CardTitle>
          <CardDescription>
            Ordered by expiry — the oldest compatible unit goes first, the same
            rule the pharmacy uses and for the same reason.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Unit</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead>Component</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Held for</TableHead>
                  <TableHead className="text-right">Expires</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {units.map((unit) => (
                  <TableRow
                    key={unit.uuid}
                    className="cursor-pointer"
                    onClick={() => setOpen(unit)}
                  >
                    <TableCell className="font-mono text-xs">
                      {unit.unit_number}
                    </TableCell>
                    <TableCell className="font-mono font-medium">
                      {unit.blood_group}
                    </TableCell>
                    <TableCell>
                      {COMPONENT_LABELS[unit.component] ?? unit.component}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          unit.status === "available"
                            ? "secondary"
                            : unit.status === "quarantined"
                              ? "outline"
                              : "default"
                        }
                      >
                        {humanise(unit.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">
                      {unit.reserved_for_name || "—"}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right text-xs tabular-nums",
                        unit.days_to_expiry <= 7 && "text-destructive",
                      )}
                    >
                      {day(unit.expires_on)}
                      <span className="block">{unit.days_to_expiry}d</span>
                    </TableCell>
                  </TableRow>
                ))}
                {units.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-10 text-center text-sm text-muted-foreground"
                    >
                      Nothing on the shelf.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {open && (
        <UnitDialog
          unit={open}
          onClose={() => setOpen(null)}
          onChanged={() => {
            setOpen(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

function UnitDialog({
  unit,
  onClose,
  onChanged,
}: {
  unit: BloodUnit;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const [emergency, setEmergency] = useState(false);
  const [authorisedBy, setAuthorisedBy] = useState("");
  const [reason, setReason] = useState("");

  const act = async (path: string, body: unknown = {}) => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/blood/units/${unit.unit_number}/${path}/`, body);
      onChanged();
    } catch (err) {
      if (err instanceof ApiError) {
        setProblem(err.message);
        // The service puts its refusal reasons in `detail.blockers`, and they
        // are the whole value of the refusal: "cannot be issued" is not
        // actionable, "there is no cross-match against this patient" is.
        const listed = err.detail?.blockers;
        if (Array.isArray(listed)) setBlockers(listed as string[]);
      } else {
        setProblem("That did not work.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <Card className="my-8 w-full max-w-lg">
        <CardHeader>
          <CardTitle>
            {unit.unit_number}
            <span className="ml-2 font-mono">{unit.blood_group}</span>
          </CardTitle>
          <CardDescription>
            {COMPONENT_LABELS[unit.component] ?? unit.component} ·{" "}
            {unit.volume_ml} ml · from {unit.donation_number} · stored{" "}
            {unit.storage_min_c} to {unit.storage_max_c} °C · expires{" "}
            {day(unit.expires_on)}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {problem && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                {problem}
                {blockers && (
                  <ul className="mt-1 space-y-0.5">
                    {blockers.map((line) => (
                      <li key={line}>· {line}</li>
                    ))}
                  </ul>
                )}
              </AlertDescription>
            </Alert>
          )}

          <div className="space-y-1 text-sm">
            <Field label="Status" value={humanise(unit.status)} />
            {unit.reserved_for_name && (
              <Field label="Held for" value={unit.reserved_for_name} />
            )}
            {unit.issued_to_name && (
              <Field label="Issued to" value={unit.issued_to_name} />
            )}
            {unit.left_storage_at && (
              <Field
                label="Out of storage since"
                value={new Date(unit.left_storage_at).toLocaleString()}
              />
            )}
          </div>

          {unit.status === "issued" && (
            <div className="space-y-2 rounded-md border p-3">
              <p className="text-sm">
                A unit out of controlled storage for more than thirty minutes
                cannot go back, however fine it looks. Returning it past that
                window discards it and says so.
              </p>
              <Button
                variant="outline"
                className="w-full"
                disabled={busy}
                onClick={() => void act("return", { reason: "Not needed" })}
              >
                Return to the bank
              </Button>
            </div>
          )}

          {/* Visually separate, and deliberately unattractive. Offered only
              on a unit already held for somebody: the record has to name who
              received it, and traceability is the whole reason this module
              exists. */}
          {["available", "reserved"].includes(unit.status) &&
            !unit.reserved_for && (
              <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
                To issue this uncross-matched in an emergency, reserve it for
                the patient first. A unit issued to nobody cannot be traced
                back, and traceability is the whole reason this record exists.
              </p>
            )}
          {["available", "reserved"].includes(unit.status) &&
            unit.reserved_for && (
            <div
              className={cn(
                "space-y-2 rounded-md border p-3",
                emergency
                  ? "border-destructive bg-destructive/5"
                  : "border-dashed",
              )}
            >
              {!emergency ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full text-muted-foreground"
                  onClick={() => setEmergency(true)}
                >
                  <Siren className="h-4 w-4" />
                  Uncross-matched emergency issue
                </Button>
              ) : (
                <>
                  <Alert variant="destructive">
                    <Siren className="h-4 w-4" />
                    <AlertTitle>Blood without a cross-match</AlertTitle>
                    <AlertDescription>
                      This is a risk the hospital is accepting, not a step
                      being skipped. Only O negative red cells and AB plasma
                      are allowed, and the authoriser is named in the record.
                    </AlertDescription>
                  </Alert>
                  <div className="space-y-1">
                    <Label htmlFor="e-auth">Authorised by</Label>
                    <Input
                      id="e-auth"
                      value={authorisedBy}
                      onChange={(event) => setAuthorisedBy(event.target.value)}
                      placeholder="Dr Sunita Karki"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="e-reason">Why there is no time</Label>
                    <Textarea
                      id="e-reason"
                      rows={2}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="Massive obstetric haemorrhage; group unknown."
                    />
                  </div>
                  <Button
                    variant="destructive"
                    className="w-full"
                    disabled={
                      busy ||
                      authorisedBy.trim().length < 3 ||
                      reason.trim().length < 10
                    }
                    onClick={() =>
                      void act("issue-emergency", {
                        patient: unit.reserved_for,
                        authorised_by: authorisedBy,
                        reason,
                      })
                    }
                  >
                    Issue uncross-matched to {unit.reserved_for_name}
                  </Button>
                </>
              )}
            </div>
          )}

          <Button variant="outline" className="w-full" onClick={onClose}>
            Close
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* In process                                                                  */
/* -------------------------------------------------------------------------- */

function Processing() {
  const [donations, setDonations] = useState<Donation[]>([]);

  useEffect(() => {
    void api
      .get<Paginated<Donation>>("/blood/donations/")
      .then((page) =>
        setDonations(
          page.results.filter(
            (row) => row.blockers.length > 0 || row.status === "collected",
          ),
        ),
      )
      .catch(() => setDonations([]));
  }, []);

  return (
    <div className="space-y-3">
      <Alert>
        <FlaskConical className="h-4 w-4" />
        <AlertTitle>Nothing here is on the shelf yet</AlertTitle>
        <AlertDescription>
          Every blocker is listed at once rather than one at a time, because a
          laboratory told only the first problem fixes it and comes back.
          Untested is shown separately from reactive: one is a laboratory that
          lost a sample, the other is a donor who must be told.
        </AlertDescription>
      </Alert>

      {donations.map((donation) => (
        <Card
          key={donation.uuid}
          className={cn(
            donation.status === "discarded" && "border-destructive/50",
            donation.screening?.reactive.length && "border-destructive/50",
          )}
        >
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-base">
                {donation.donation_number}
                {donation.group && (
                  <span className="ml-2 font-mono">{donation.group}</span>
                )}
              </CardTitle>
              <CardDescription>
                {donation.donor_name} ({donation.donor_number}) ·{" "}
                {donation.volume_ml} ml · collected {day(donation.collected_at)}
                {donation.is_mobile_drive && " · mobile drive"}
              </CardDescription>
            </div>
            <Badge
              variant={
                donation.status === "discarded"
                  ? "destructive"
                  : donation.status === "processed"
                    ? "secondary"
                    : "outline"
              }
            >
              {humanise(donation.status)}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                  Grouping ({donation.groupings.length} of 2)
                </p>
                {donation.groupings.map((row) => (
                  <p key={row.uuid} className="text-sm">
                    <span className="font-mono">{row.blood_group}</span> by{" "}
                    {row.performed_by_name}
                  </p>
                ))}
                {donation.groupings.length === 0 && (
                  <p className="text-sm text-muted-foreground">Not grouped.</p>
                )}
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                  Screening
                </p>
                {donation.screening ? (
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(donation.screening.results).map(
                      ([key, value]) => (
                        <Badge
                          key={key}
                          variant={
                            value === "reactive" || value === "indeterminate"
                              ? "destructive"
                              : value === "non_reactive"
                                ? "outline"
                                : "secondary"
                          }
                        >
                          {key}: {humanise(value)}
                        </Badge>
                      ),
                    )}
                    {donation.screening.untested.map((key) => (
                      <Badge key={key} variant="secondary" className="opacity-70">
                        {key}: not tested
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Not screened.
                  </p>
                )}
              </div>
            </div>

            {donation.blockers.length > 0 && (
              <div className="rounded-md border border-amber-500/50 bg-amber-50/60 p-2 dark:bg-amber-950/10">
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
                  Cannot be released
                </p>
                <ul className="space-y-0.5 text-sm">
                  {donation.blockers.map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                </ul>
              </div>
            )}

            {donation.discard_reason && (
              <p className="text-sm text-destructive">
                {donation.discard_reason}
              </p>
            )}
          </CardContent>
        </Card>
      ))}

      {donations.length === 0 && (
        <Card>
          <CardContent className="py-16 text-center text-sm text-muted-foreground">
            Nothing waiting to be released.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Requests                                                                    */
/* -------------------------------------------------------------------------- */

function Requests({ facility }: { facility: string }) {
  const [requests, setRequests] = useState<BloodRequest[]>([]);
  const [transfusions, setTransfusions] = useState<Transfusion[]>([]);

  useEffect(() => {
    if (!facility) return;
    void Promise.all([
      api.get<Paginated<BloodRequest>>(`/blood/requests/?facility=${facility}`),
      api.get<Paginated<Transfusion>>("/blood/transfusions/"),
    ])
      .then(([a, b]) => {
        setRequests(a.results);
        setTransfusions(b.results.slice(0, 20));
      })
      .catch(() => undefined);
  }, [facility]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Requests</CardTitle>
          <CardDescription>
            The indication is required on every one, because over-transfusion
            is the commonest quality finding in a blood bank and is invisible
            without it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Request</TableHead>
                <TableHead>Patient</TableHead>
                <TableHead>Wants</TableHead>
                <TableHead>Urgency</TableHead>
                <TableHead>Indication</TableHead>
                <TableHead className="text-right">Hb</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {requests.map((row) => (
                <TableRow key={row.uuid}>
                  <TableCell className="font-mono text-xs">
                    {row.reference}
                  </TableCell>
                  <TableCell>
                    {row.patient_name}
                    <span className="block text-xs text-muted-foreground">
                      {row.patient_mrn}
                      {row.stated_group && ` · ${row.stated_group}`}
                    </span>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {row.units_given}/{row.units_requested}{" "}
                    <span className="text-xs text-muted-foreground">
                      {COMPONENT_LABELS[row.component] ?? row.component}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        row.urgency === "emergency"
                          ? "destructive"
                          : row.urgency === "urgent"
                            ? "default"
                            : "outline"
                      }
                    >
                      {row.urgency}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-[16rem] truncate text-xs">
                    {row.indication}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.haemoglobin ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        row.status === "filled" ? "secondary" : "outline"
                      }
                    >
                      {humanise(row.status)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {requests.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-10 text-center text-sm text-muted-foreground"
                  >
                    No requests.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent transfusions</CardTitle>
          <CardDescription>
            Two names on every bedside check. One person checking alone is not
            the check, and the database refuses the two being the same.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {transfusions.map((row) => (
            <div
              key={row.uuid}
              className={cn(
                "flex flex-wrap items-baseline justify-between gap-2 rounded-md border px-3 py-2 text-sm",
                row.reactions.length > 0 && "border-destructive/50 bg-destructive/5",
              )}
            >
              <span>
                <span className="font-mono text-xs">{row.unit_number}</span>{" "}
                <span className="font-mono">{row.unit_group}</span>{" "}
                {COMPONENT_LABELS[row.component] ?? row.component} →{" "}
                {row.patient_name}
              </span>
              <span className="text-xs text-muted-foreground">
                {row.checked_by_first} + {row.checked_by_second} ·{" "}
                {day(row.started_at)} · {humanise(row.outcome)}
                {row.volume_given_ml !== null && ` · ${row.volume_given_ml} ml`}
              </span>
              {row.reactions.map((reaction) => (
                <span
                  key={reaction.uuid}
                  className="w-full text-xs text-destructive"
                >
                  {humanise(reaction.reaction_type)} ({reaction.severity})
                  {reaction.minutes_into_transfusion !== null &&
                    ` at ${reaction.minutes_into_transfusion} minutes`}
                  {reaction.minutes_into_transfusion !== null &&
                    reaction.minutes_into_transfusion <= 15 &&
                    " — within fifteen minutes; haemolytic until proved otherwise"}
                </span>
              ))}
            </div>
          ))}
          {transfusions.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Nothing transfused yet.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Donors                                                                      */
/* -------------------------------------------------------------------------- */

function Donors({ facility }: { facility: string }) {
  const [donors, setDonors] = useState<Donor[]>([]);
  const [group, setGroup] = useState("O-");
  const [callList, setCallList] = useState<DonorCallRow[]>([]);
  const [lookback, setLookback] = useState<LookBack | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<Donor>>("/blood/donors/")
      .then((page) => setDonors(page.results))
      .catch(() => setDonors([]));
  }, []);

  useEffect(() => {
    if (!facility) return;
    void api
      .get<DonorCallRow[]>(
        `/blood/donors/call-list/?facility=${facility}&group=${encodeURIComponent(group)}`,
      )
      .then(setCallList)
      .catch(() => setCallList([]));
  }, [facility, group]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <PhoneCall className="h-4 w-4" />
              Who to call
            </CardTitle>
            <CardDescription>
              Ordered by when each becomes eligible, not by name: a donor
              eligible next week is not the same as one eligible today.
            </CardDescription>
          </div>
          <Select
            className="h-9 w-auto"
            aria-label="Group"
            value={group}
            onChange={(event) => setGroup(event.target.value)}
          >
            {GROUPS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </CardHeader>
        <CardContent className="space-y-1">
          {callList.map((row) => (
            <div
              key={row.donor_number}
              className={cn(
                "flex flex-wrap items-baseline justify-between gap-2 rounded-md border px-3 py-2 text-sm",
                row.eligible_now && "border-emerald-500/50",
              )}
            >
              <span>
                <span className="font-mono text-xs text-muted-foreground">
                  {row.donor_number}
                </span>{" "}
                {row.name} · {row.phone}
              </span>
              <span
                className={cn(
                  "text-xs",
                  row.eligible_now
                    ? "text-emerald-600"
                    : "text-muted-foreground",
                )}
              >
                {row.eligible_now
                  ? `eligible now · ${row.donations} donations`
                  : row.problems[0]}
              </span>
            </div>
          ))}
          {callList.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No contactable donors of that group.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">The registry</CardTitle>
          <CardDescription>
            A donor is not a patient: different record, different consent,
            different privacy. Click one to see everybody who received their
            blood.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Donor</TableHead>
                <TableHead>Group</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead className="text-right">Donations</TableHead>
                <TableHead>Last gave</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {donors.map((donor) => (
                <TableRow
                  key={donor.uuid}
                  className="cursor-pointer"
                  onClick={() =>
                    void api
                      .get<LookBack>(
                        `/blood/donors/${donor.donor_number}/look-back/`,
                      )
                      .then(setLookback)
                      .catch(() => undefined)
                  }
                >
                  <TableCell>
                    {donor.full_name}
                    <span className="block font-mono text-xs text-muted-foreground">
                      {donor.donor_number}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono">
                    {donor.blood_group || "—"}
                  </TableCell>
                  <TableCell className="tabular-nums">{donor.phone}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {donor.donation_count}
                  </TableCell>
                  <TableCell>{day(donor.last_donated_on)}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        donor.status === "permanent"
                          ? "destructive"
                          : donor.status === "active"
                            ? "outline"
                            : "secondary"
                      }
                      title={donor.deferral_reason}
                    >
                      {donor.status === "permanent"
                        ? "deferred for good"
                        : humanise(donor.status)}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {lookback && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
          <Card className="my-8 w-full max-w-2xl">
            <CardHeader>
              <CardTitle>Look-back: {lookback.donor}</CardTitle>
              <CardDescription>
                {lookback.donations} donations, {lookback.units} units,{" "}
                {lookback.recipients} recipients. The question asked when a
                donor seroconverts — without the link the answer is that nobody
                knows, and the hospital has to contact everybody or nobody.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Unit</TableHead>
                    <TableHead>Component</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Recipient</TableHead>
                    <TableHead>Contact</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lookback.rows.map((row) => (
                    <TableRow
                      key={row.unit}
                      className={cn(row.patient && "bg-amber-50/60 dark:bg-amber-950/10")}
                    >
                      <TableCell className="font-mono text-xs">
                        {row.unit}
                      </TableCell>
                      <TableCell>
                        {COMPONENT_LABELS[row.component] ?? row.component}
                      </TableCell>
                      <TableCell>{humanise(row.status)}</TableCell>
                      <TableCell>
                        {row.patient ?? "—"}
                        {row.mrn && (
                          <span className="block text-xs text-muted-foreground">
                            {row.mrn} · {day(row.transfused_on)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {row.phone || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => setLookback(null)}
              >
                Close
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Safety                                                                      */
/* -------------------------------------------------------------------------- */

function Safety({ facility }: { facility: string }) {
  const [wastage, setWastage] = useState<BloodWastage | null>(null);
  const [vigilance, setVigilance] = useState<Haemovigilance | null>(null);

  useEffect(() => {
    if (!facility) return;
    void Promise.all([
      api.get<BloodWastage>(
        `/blood/reports/?report=wastage&facility=${facility}`,
      ),
      api.get<Haemovigilance>(
        `/blood/reports/?report=haemovigilance&facility=${facility}`,
      ),
    ])
      .then(([a, b]) => {
        setWastage(a);
        setVigilance(b);
      })
      .catch(() => undefined);
  }, [facility]);

  if (!wastage || !vigilance) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Card
        className={cn(
          vigilance.clerical_errors > 0 && "border-destructive/60",
        )}
      >
        <CardHeader>
          <CardTitle className="text-base">Haemovigilance</CardTitle>
          <CardDescription>
            Since {day(vigilance.since)}. The clerical-error count sits beside
            the rest because it is the one category that is entirely
            preventable, and the one a blood bank is judged on.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-4">
            <Fact label="Transfusions" value={String(vigilance.transfusions)} />
            <Fact label="Reactions" value={String(vigilance.reactions)} />
            <Fact
              label="Rate"
              value={
                vigilance.reaction_rate_percent === null
                  ? "—"
                  : `${vigilance.reaction_rate_percent}%`
              }
            />
            <Fact
              label="Clerical errors"
              value={String(vigilance.clerical_errors)}
              tone={
                vigilance.clerical_errors > 0 ? "text-destructive" : undefined
              }
            />
          </div>

          {vigilance.not_reported_to_authority > 0 && (
            <Alert variant="destructive">
              <ShieldAlert className="h-4 w-4" />
              <AlertTitle>
                {vigilance.not_reported_to_authority} severe reaction
                {vigilance.not_reported_to_authority === 1 ? "" : "s"} not yet
                reported
              </AlertTitle>
              <AlertDescription>
                Severe, life-threatening and fatal reactions are reportable to
                the national haemovigilance system.
              </AlertDescription>
            </Alert>
          )}

          <div className="flex flex-wrap gap-2">
            {Object.entries(vigilance.by_type).map(([type, count]) => (
              <Badge key={type} variant="outline">
                {humanise(type)}: {count}
              </Badge>
            ))}
            {Object.entries(vigilance.by_severity).map(([severity, count]) => (
              <Badge
                key={severity}
                variant={
                  ["severe", "life_threatening", "fatal"].includes(severity)
                    ? "destructive"
                    : "secondary"
                }
              >
                {humanise(severity)}: {count}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Wastage</CardTitle>
          <CardDescription>
            {wastage.discarded} discarded against {wastage.issued} issued —{" "}
            {wastage.wastage_percent ?? "—"}%. The reasons matter more than the
            total: expiry is a stock problem, a broken cold chain is a process
            problem, and a reactive screen is the system working.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {Object.entries(wastage.by_reason).map(([reason, count]) => (
            <div key={reason} className="flex items-center gap-2 text-sm">
              <span className="flex h-3 flex-1 items-center">
                <span
                  className={cn(
                    "h-3 rounded-sm",
                    reason === "expired" ? "bg-amber-500/70" : "bg-destructive/60",
                  )}
                  style={{
                    width: `${
                      (count /
                        Math.max(1, ...Object.values(wastage.by_reason))) *
                      100
                    }%`,
                  }}
                />
              </span>
              <span className="w-10 shrink-0 text-right tabular-nums">
                {count}
              </span>
              <span className="w-64 shrink-0 truncate text-xs text-muted-foreground">
                {reason}
              </span>
            </div>
          ))}
          {Object.keys(wastage.by_reason).length === 0 && (
            <p className="flex items-center gap-2 py-4 text-sm text-emerald-600">
              <CheckCircle2 className="h-4 w-4" />
              Nothing has been thrown away.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Bits                                                                        */
/* -------------------------------------------------------------------------- */

function Fact({
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
    <div className="rounded-md border p-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={cn("text-lg font-semibold tabular-nums", tone)}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
