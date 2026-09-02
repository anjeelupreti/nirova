/**
 * Facility capacity: what the plan allows, what is used, and what is left.
 *
 * This screen exists so limits are never a surprise. A customer should see
 * "2 of 3 pharmacies" before they start filling in a form, not after they
 * submit one — which is the reason the backend returns a decision object
 * rather than a boolean (dev log entry 012).
 */

import { useEffect, useState } from "react";
import { AlertTriangle, Building2, Info, Lock } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { formatLimit } from "@/lib/utils";
import type { CapacityResponse, CapacityRow } from "@/types";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Progress,
} from "@/components/ui/primitives";

const FACILITY_LABELS: Record<string, string> = {
  hospital: "Hospitals",
  clinic: "Clinics",
  pharmacy: "Pharmacies",
  laboratory: "Laboratories",
  diagnostic: "Diagnostic centres",
  warehouse: "Warehouses",
  corporate_office: "Corporate offices",
  other: "Other",
};

/** Colour the bar by how close to the ceiling usage is. */
function toneFor(row: CapacityRow): "default" | "warning" | "danger" {
  if (row.unlimited || row.limit === null || row.limit === 0) return "default";
  const ratio = row.used / row.limit;
  if (ratio >= 1) return "danger";
  if (ratio >= 0.8) return "warning";
  return "default";
}

function CapacityCard({ row }: { row: CapacityRow }) {
  const label = FACILITY_LABELS[row.facility_type] ?? row.facility_type;
  const blocked = !row.module_entitled;

  return (
    <Card className={blocked ? "opacity-70" : undefined}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              {blocked ? (
                <Lock className="h-4 w-4 text-muted-foreground" />
              ) : (
                <Building2 className="h-4 w-4 text-muted-foreground" />
              )}
              {label}
            </CardTitle>
            <CardDescription className="mt-1">
              {blocked
                ? "Not included in this subscription"
                : `${row.used} of ${formatLimit(row.limit, row.unlimited)} used`}
            </CardDescription>
          </div>
          {row.enforcement !== "hard" && !blocked && (
            <Badge variant="secondary" title="How the limit is applied">
              {row.enforcement}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {!blocked && !row.unlimited && row.limit !== null && row.limit > 0 && (
          <Progress value={row.used} max={row.limit} tone={toneFor(row)} />
        )}
        {!blocked && row.unlimited && (
          <p className="text-sm text-muted-foreground">No limit applies.</p>
        )}

        {/*
          Provenance. Support's first question when a customer disputes a
          limit is "where did that number come from?" — so the answer is on
          the screen rather than in a database somewhere.
        */}
        {row.sources.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {row.sources.map((source) => (
              <span
                key={source}
                className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
              >
                {source}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function CapacityPage() {
  const [data, setData] = useState<CapacityResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<CapacityResponse>("/org/facilities/capacity/")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err : null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading capacity…</p>;
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Could not load capacity</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  // Types whose module is not entitled sort last: they are context, not the
  // thing the user came to look at.
  const rows = Object.values(data.by_type).sort((a, b) => {
    if (a.module_entitled !== b.module_entitled) return a.module_entitled ? -1 : 1;
    return (FACILITY_LABELS[a.facility_type] ?? a.facility_type).localeCompare(
      FACILITY_LABELS[b.facility_type] ?? b.facility_type,
    );
  });

  const overall = data.overall;
  const nearOverall =
    !overall.unlimited &&
    overall.limit !== null &&
    overall.limit > 0 &&
    overall.used / overall.limit >= 0.8;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Facility capacity</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          What the <span className="font-medium">{data.plan}</span> plan allows,
          and how much of it is in use.
        </p>
      </div>

      {!data.is_entitled && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Subscription is not active</AlertTitle>
          <AlertDescription>
            No new capacity can be used while the subscription is{" "}
            {data.subscription_status}.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>All facilities</CardTitle>
          <CardDescription>
            {overall.used} of {formatLimit(overall.limit, overall.unlimited)} used
            {" — "}this ceiling applies across every type, on top of the per-type
            limits below.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!overall.unlimited && overall.limit !== null && overall.limit > 0 && (
            <Progress
              value={overall.used}
              max={overall.limit}
              tone={nearOverall ? "warning" : "default"}
            />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => (
          <CapacityCard key={row.facility_type} row={row} />
        ))}
      </div>

      <Alert variant="info">
        <Info className="h-4 w-4" />
        <AlertTitle>How limits are applied</AlertTitle>
        <AlertDescription>
          Closing a facility frees its slot; suspending one does not. Opening a
          facility that exceeds a limit is not blocked outright — it becomes a
          request for the platform to decide, which can be approved together
          with the extra capacity.
        </AlertDescription>
      </Alert>
    </div>
  );
}
