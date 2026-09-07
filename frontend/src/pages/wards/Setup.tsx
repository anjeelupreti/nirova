/**
 * Wards and beds: creating them, which nothing in the console could do.
 *
 * The admissions half of this screen is deep — admit, move, discharge, the
 * whole stay. **What it had no way to do was set a ward up.** No form created
 * a ward or added a bed, so a new facility's ward list could only be loaded
 * with an HTTP client, and opening a new bay meant asking an engineer.
 *
 * (Until yesterday it could not be done at all: `Ward.facility` and `Bed.ward`
 * were declared read-only on serializers whose columns are not nullable, so
 * every create violated a not-null constraint. See development log 218.)
 *
 * **Beds are added in a run, not one at a time.** A ward opens with twelve
 * beds, not with one; making somebody fill the same form twelve times is how a
 * setup screen goes unused and the data ends up loaded from a spreadsheet by
 * somebody else.
 *
 * **`bed.manage` to change anything, `encounter.read` to look.** A ward sister
 * should see the layout of her ward; changing it is the facility manager's.
 */

import { useCallback, useEffect, useState } from "react";
import { BedDouble, Loader2, Plus, TriangleAlert } from "lucide-react";

import { useSession } from "@/hooks/useSession";
import api, { ApiError } from "@/lib/api";
import type { Bed, Facility, Paginated, Ward } from "@/types";
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DetailPanel,
  DetailRow,
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

const WARD_TYPES = ["general", "private", "semi_private", "deluxe", "icu",
                    "nicu", "picu", "hdu", "maternity", "isolation", "burn",
                    "psychiatric", "day_care", "emergency"];

function label(value: string): string {
  return value ? value.replace(/_/g, " ") : "";
}

export default function WardSetup({ facilityUuid }: { facilityUuid: string }) {
  const { can } = useSession();
  const mayEdit = can("bed.manage", "facility");

  const [wards, setWards] = useState<Ward[]>([]);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<Ward | null>(null);
  const [beds, setBeds] = useState<Bed[]>([]);
  const [newWard, setNewWard] = useState<Record<string, unknown> | null>(null);
  const [bedRun, setBedRun] = useState<{ prefix: string; from: string; to: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.get<Paginated<Ward>>("/ipd/wards/");
      setWards(page.results);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .catch(() => undefined);
  }, [load]);

  async function openWard(ward: Ward) {
    setOpen(ward);
    setBeds([]);
    const page = await api.get<Paginated<Bed>>(
      `/ipd/beds/?ward=${ward.uuid}`,
    );
    setBeds(page.results);
  }

  async function createWard() {
    if (newWard === null) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(newWard)) {
        if (value !== "") body[key] = value;
      }
      await api.post<Ward>("/ipd/wards/", body);
      setNewWard(null);
      await load();
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "The ward could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  /**
   * Add a run of beds: `A-1` through `A-12` in one go.
   *
   * Created one request at a time rather than in a batch, because there is no
   * bulk endpoint and inventing one for a setup screen would be the tail
   * wagging the dog. Failures are collected and reported together — stopping
   * at the first would leave a half-numbered ward and no way to tell how far
   * it got.
   */
  async function createBeds() {
    if (bedRun === null || open === null) return;
    const from = Number(bedRun.from);
    const to = Number(bedRun.to);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) {
      setError("That is not a range.");
      return;
    }
    setBusy(true);
    setError(null);
    const failed: string[] = [];
    for (let number = from; number <= to; number += 1) {
      const code = `${bedRun.prefix}${number}`;
      try {
        await api.post<Bed>("/ipd/beds/", { ward: open.uuid, code });
      } catch (problem) {
        failed.push(
          `${code}: ${problem instanceof ApiError ? problem.message : "failed"}`,
        );
      }
    }
    setBusy(false);
    setBedRun(null);
    if (failed.length) setError(failed.join(" · "));
    await openWard(open);
    await load();
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BedDouble className="h-4 w-4 text-muted-foreground" />
              Wards and beds
            </CardTitle>
            <CardDescription>
              The layout a ward round and an admission both depend on. Bed
              occupancy is on the board; this is what the board is a board of.
            </CardDescription>
          </div>
          {mayEdit ? (
            <Button
              size="sm"
              onClick={() =>
                setNewWard({
                  code: "",
                  name: "",
                  ward_type: "general",
                  facility: facilityUuid || facilities[0]?.uuid || "",
                  floor: "",
                  is_gender_segregated: false,
                  allows_attendant: true,
                  is_active: true,
                })
              }
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Add a ward
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {error && newWard === null && bedRun === null ? (
            <Alert variant="destructive" className="mb-3">
              <TriangleAlert className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {loading ? (
            <p className="py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
              Loading wards…
            </p>
          ) : wards.length === 0 ? (
            <div className="py-10 text-center">
              <p className="text-sm font-medium">No wards yet.</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {mayEdit
                  ? "Add a ward, then the beds in it, before anybody can be admitted."
                  : "Somebody who manages beds needs to set these up."}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Ward</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Beds</TableHead>
                    <TableHead>Floor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {wards.map((ward) => (
                    <TableRow
                      key={ward.uuid}
                      onClick={() => void openWard(ward)}
                      className="cursor-pointer hover:bg-muted/50"
                    >
                      <TableCell className="font-mono text-xs">
                        {ward.code}
                      </TableCell>
                      <TableCell className="font-medium">{ward.name}</TableCell>
                      <TableCell className="text-xs capitalize">
                        {label(ward.ward_type)}
                        {ward.is_critical_care ? (
                          <Badge variant="outline" className="ml-1.5 text-[10px]">
                            critical care
                          </Badge>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {/*
                          A ward with no beds is the state this screen exists to
                          fix, so it says so rather than showing a quiet zero.
                        */}
                        {ward.bed_count === 0 ? (
                          <span className="text-xs text-muted-foreground">
                            none yet
                          </span>
                        ) : (
                          ward.bed_count
                        )}
                      </TableCell>
                      <TableCell className="text-xs">
                        {ward.floor || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* One ward, and the beds in it. */}
      <DetailPanel
        open={open !== null && newWard === null && bedRun === null}
        onClose={() => setOpen(null)}
        title={open?.name ?? ""}
        subtitle={open ? `${open.code} · ${label(open.ward_type)}` : undefined}
        footer={
          mayEdit && open ? (
            <Button
              className="w-full"
              onClick={() => setBedRun({ prefix: `${open.code}-`, from: "1", to: "12" })}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Add beds
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Changing the ward layout needs the bed management permission.
            </p>
          )
        }
      >
        {open ? (
          <div className="space-y-6">
            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                The ward
              </h3>
              <DetailRow label="Type">{label(open.ward_type)}</DetailRow>
              <DetailRow label="Floor">{open.floor}</DetailRow>
              <DetailRow label="Building">{open.building}</DetailRow>
              <DetailRow label="Nurse ratio">
                {open.nurse_to_patient_ratio}
              </DetailRow>
              <DetailRow label="Gender segregated">
                {open.is_gender_segregated ? "Yes" : "No"}
              </DetailRow>
              <DetailRow label="Attendant allowed">
                {open.allows_attendant ? "Yes" : "No"}
              </DetailRow>
              <DetailRow label="Visiting hours">{open.visiting_hours}</DetailRow>
            </section>

            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Beds ({beds.length})
              </h3>
              {beds.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No beds in this ward yet. Nobody can be admitted to it until
                  there are.
                </p>
              ) : (
                <div className="space-y-1">
                  {beds.map((bed) => (
                    <div
                      key={bed.uuid}
                      className="flex items-center justify-between gap-3 border-b py-1.5 last:border-b-0"
                    >
                      <span className="font-mono text-sm">{bed.code}</span>
                      <span className="flex items-center gap-1.5">
                        {bed.has_oxygen ? (
                          <Badge variant="outline" className="text-[10px]">O₂</Badge>
                        ) : null}
                        {bed.has_ventilator ? (
                          <Badge variant="outline" className="text-[10px]">vent</Badge>
                        ) : null}
                        {bed.is_isolation ? (
                          <Badge variant="outline" className="text-[10px]">isolation</Badge>
                        ) : null}
                        <Badge
                          variant={
                            bed.status === "available" ? "secondary" : "outline"
                          }
                          className="text-[10px]"
                        >
                          {label(bed.status)}
                        </Badge>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        ) : null}
      </DetailPanel>

      {/* Creating a ward. */}
      <DetailPanel
        open={newWard !== null}
        onClose={() => setNewWard(null)}
        title="Add a ward"
        subtitle="A code, a name and a facility are all that is required"
        footer={
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={
                busy ||
                !String(newWard?.code ?? "").trim() ||
                !String(newWard?.name ?? "").trim() ||
                !newWard?.facility
              }
              onClick={() => void createWard()}
            >
              {busy ? "Creating…" : "Create ward"}
            </Button>
            <Button variant="outline" onClick={() => setNewWard(null)}>
              Cancel
            </Button>
          </div>
        }
      >
        {newWard ? (
          <div className="space-y-4">
            {error ? (
              <Alert variant="destructive">
                <TriangleAlert className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="ward-code">
                  Code <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="ward-code"
                  value={String(newWard.code ?? "")}
                  onChange={(event) =>
                    setNewWard({ ...newWard, code: event.target.value })
                  }
                  placeholder="MW1"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="ward-name">
                  Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="ward-name"
                  value={String(newWard.name ?? "")}
                  onChange={(event) =>
                    setNewWard({ ...newWard, name: event.target.value })
                  }
                  placeholder="Medical Ward 1"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="ward-facility">
                  Facility <span className="text-destructive">*</span>
                </Label>
                <Select
                  id="ward-facility"
                  value={String(newWard.facility ?? "")}
                  onChange={(event) =>
                    setNewWard({ ...newWard, facility: event.target.value })
                  }
                >
                  <option value="">Choose…</option>
                  {facilities.map((facility) => (
                    <option key={facility.uuid} value={facility.uuid}>
                      {facility.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="ward-type">Type</Label>
                <Select
                  id="ward-type"
                  value={String(newWard.ward_type ?? "general")}
                  onChange={(event) =>
                    setNewWard({ ...newWard, ward_type: event.target.value })
                  }
                >
                  {WARD_TYPES.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="ward-floor">Floor</Label>
                <Input
                  id="ward-floor"
                  value={String(newWard.floor ?? "")}
                  onChange={(event) =>
                    setNewWard({ ...newWard, floor: event.target.value })
                  }
                />
              </div>
            </div>
          </div>
        ) : null}
      </DetailPanel>

      {/* Adding a run of beds. */}
      <DetailPanel
        open={bedRun !== null}
        onClose={() => setBedRun(null)}
        title="Add beds"
        subtitle={open ? `into ${open.name}` : undefined}
        footer={
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={busy}
              onClick={() => void createBeds()}
            >
              {busy ? "Adding…" : "Add these beds"}
            </Button>
            <Button variant="outline" onClick={() => setBedRun(null)}>
              Cancel
            </Button>
          </div>
        }
      >
        {bedRun ? (
          <div className="space-y-4">
            {error ? (
              <Alert variant="destructive">
                <TriangleAlert className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <p className="text-sm text-muted-foreground">
              A ward opens with a dozen beds, not with one. Give the numbering
              and they are created in a run.
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1">
                <Label htmlFor="bed-prefix">Prefix</Label>
                <Input
                  id="bed-prefix"
                  value={bedRun.prefix}
                  onChange={(event) =>
                    setBedRun({ ...bedRun, prefix: event.target.value })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="bed-from">From</Label>
                <Input
                  id="bed-from"
                  type="number"
                  value={bedRun.from}
                  onChange={(event) =>
                    setBedRun({ ...bedRun, from: event.target.value })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="bed-to">To</Label>
                <Input
                  id="bed-to"
                  type="number"
                  value={bedRun.to}
                  onChange={(event) =>
                    setBedRun({ ...bedRun, to: event.target.value })
                  }
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              This will create{" "}
              <span className="font-medium text-foreground">
                {Math.max(0, Number(bedRun.to) - Number(bedRun.from) + 1)}
              </span>{" "}
              beds, {bedRun.prefix}
              {bedRun.from} to {bedRun.prefix}
              {bedRun.to}.
            </p>
          </div>
        ) : null}
      </DetailPanel>
    </div>
  );
}
