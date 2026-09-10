/**
 * The facility list.
 *
 * Read-only, and not because the screen is unfinished: facilities come into
 * existence only by executing an approved change request, so an edit button
 * here would be a second, unchecked door into the same state. The action
 * offered instead is "Request a change".
 *
 * **Read-only is not the same as shallow, and this screen used to confuse the
 * two.** Six columns and no way into a row, while `/org/facilities/{uuid}/`
 * has always returned the address, the licence, the operating hours and every
 * department -- and no screen had ever called it. Opening a row now shows what
 * was already there.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, Plus } from "lucide-react";

import api from "@/lib/api";
import type { Facility, FacilityDetail, Paginated } from "@/types";
import {
  Badge,
  Button,
  DetailPanel,
  DetailRow,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/layout";

const STATUS_VARIANT: Record<string, "success" | "warning" | "secondary"> = {
  active: "success",
  pending: "warning",
  suspended: "warning",
  closed: "secondary",
};

export default function FacilitiesPage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<FacilityDetail | null>(null);
  const [opening, setOpening] = useState<string | null>(null);

  // Fetched when a row is opened rather than eagerly with the list: the detail
  // carries every department, and loading all of them to show one is work
  // nobody asked for.
  async function openFacility(facility: Facility) {
    setOpening(facility.uuid);
    try {
      setOpen(
        await api.get<FacilityDetail>(`/org/facilities/${facility.uuid}/`),
      );
    } finally {
      setOpening(null);
    }
  }

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Facilities"
        description="Every business unit in this organization."
        actions={
          <>
            <Button asChild>
              <Link to="/facility-requests">
                <Plus className="h-4 w-4" />
                Request a change
              </Link>
            </Button>
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-muted-foreground" />
            {facilities.length} {facilities.length === 1 ? "facility" : "facilities"}
          </CardTitle>
          <CardDescription>
            Facilities are opened and closed through the approval workflow, so
            each one carries the reference of the request that created it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : facilities.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No facilities yet. Request one to get started.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Departments</TableHead>
                  <TableHead>Opened via</TableHead>
                  <TableHead className="w-16"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {facilities.map((facility) => (
                  <TableRow
                    key={facility.uuid}
                    onClick={() => void openFacility(facility)}
                    className="cursor-pointer hover:bg-muted/50"
                  >
                    <TableCell className="font-mono text-xs">
                      {facility.code}
                    </TableCell>
                    <TableCell className="font-medium">{facility.name}</TableCell>
                    <TableCell className="capitalize">
                      {facility.facility_type.replace(/_/g, " ")}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[facility.status] ?? "secondary"}>
                        {facility.status}
                      </Badge>
                    </TableCell>
                    <TableCell>{facility.department_count}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {facility.origin_reference || "—"}
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {opening === facility.uuid ? "Opening…" : "View"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DetailPanel
        open={open !== null}
        onClose={() => setOpen(null)}
        title={open?.name ?? ""}
        subtitle={
          open
            ? `${open.code} · ${open.facility_type.replace(/_/g, " ")}`
            : undefined
        }
        footer={
          <Button asChild variant="outline" className="w-full">
            <Link to="/facility-requests">
              Request a change to this facility
            </Link>
          </Button>
        }
      >
        {open ? (
          <div className="space-y-6">
            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Where it is
              </h3>
              <DetailRow label="Address">{open.street_address}</DetailRow>
              <DetailRow label="Ward">{open.ward}</DetailRow>
              <DetailRow label="Municipality">{open.municipality}</DetailRow>
              <DetailRow label="District">{open.district}</DetailRow>
              <DetailRow label="Province">{open.province}</DetailRow>
            </section>

            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Getting hold of it
              </h3>
              <DetailRow label="Phone">{open.phone}</DetailRow>
              <DetailRow label="Email">{open.email}</DetailRow>
              <DetailRow label="Hours">
                {open.is_24x7 ? "Open 24 hours" : open.operating_hours}
              </DetailRow>
            </section>

            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Registration
              </h3>
              <DetailRow label="Licence">{open.license_number}</DetailRow>
              {/*
                Red once the date is past. A lapsed operating licence is not a
                paperwork problem, and a date sitting quietly in a list is not a
                warning.
              */}
              <DetailRow label="Licence expires">
                {open.license_expires_on ? (
                  <span
                    className={
                      new Date(open.license_expires_on) < new Date()
                        ? "font-medium text-destructive"
                        : undefined
                    }
                  >
                    {open.license_expires_on}
                    {new Date(open.license_expires_on) < new Date()
                      ? " · expired"
                      : ""}
                  </span>
                ) : null}
              </DetailRow>
              <DetailRow label="PAN">{open.pan_number}</DetailRow>
              <DetailRow label="Opened">{open.opened_on}</DetailRow>
              <DetailRow label="Created by">{open.origin_reference}</DetailRow>
            </section>

            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Departments ({open.departments?.length ?? 0})
              </h3>
              {open.departments?.length ? (
                <div className="space-y-1">
                  {open.departments.map((department) => (
                    <div
                      key={department.uuid}
                      className="flex items-center justify-between gap-3 border-b py-1.5 last:border-b-0"
                    >
                      <span className="truncate text-sm">
                        {department.name}
                      </span>
                      <span className="shrink-0 font-mono text-xs text-muted-foreground">
                        {department.code}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No departments yet.
                </p>
              )}
            </section>
          </div>
        ) : null}
      </DetailPanel>
    </div>
  );
}
