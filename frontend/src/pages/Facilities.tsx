/**
 * The facility list.
 *
 * Read-only, and not because the screen is unfinished: facilities come into
 * existence only by executing an approved change request, so an edit button
 * here would be a second, unchecked door into the same state. The action
 * offered instead is "Request a change".
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, Plus } from "lucide-react";

import api from "@/lib/api";
import type { Facility, Paginated } from "@/types";
import {
  Badge,
  Button,
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

const STATUS_VARIANT: Record<string, "success" | "warning" | "secondary"> = {
  active: "success",
  pending: "warning",
  suspended: "warning",
  closed: "secondary",
};

export default function FacilitiesPage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => setFacilities(page.results))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Facilities</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every business unit in this organization.
          </p>
        </div>
        <Button asChild>
          <Link to="/facility-requests">
            <Plus className="h-4 w-4" />
            Request a change
          </Link>
        </Button>
      </div>

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
                </TableRow>
              </TableHeader>
              <TableBody>
                {facilities.map((facility) => (
                  <TableRow key={facility.uuid}>
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
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
