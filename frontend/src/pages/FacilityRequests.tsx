/**
 * Facility change requests: raise one, and see where existing ones stand.
 *
 * The form previews before it submits. The user learns that a hospital is
 * outside their plan while they are still filling the form — and is told
 * exactly who will have to approve it — rather than discovering it from a
 * rejection afterwards.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Info,
  Send,
  ShieldQuestion,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import type {
  ChangePreview,
  FacilityChangeRequest,
  Paginated,
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

const FACILITY_TYPES = [
  ["clinic", "Clinic"],
  ["hospital", "Hospital"],
  ["pharmacy", "Pharmacy"],
  ["laboratory", "Laboratory"],
  ["diagnostic", "Diagnostic centre"],
  ["warehouse", "Warehouse"],
  ["corporate_office", "Corporate office"],
] as const;

/** Minimum justification length the backend enforces by default. */
const MIN_JUSTIFICATION = 40;

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "destructive" | "warning" | "success"
> = {
  executed: "success",
  approved: "success",
  rejected: "destructive",
  failed: "destructive",
  org_review: "warning",
  platform_review: "warning",
  info_requested: "warning",
  expired: "secondary",
  withdrawn: "secondary",
};

const APPROVAL_EXPLANATION: Record<string, string> = {
  automatic: "Within your plan — this will take effect immediately.",
  organization: "Your own administrator will approve this.",
  platform:
    "The platform team will decide this, because it goes beyond your plan.",
  both: "Your administrator approves first, then the platform team — because this goes beyond your current subscription.",
};

function PreviewPanel({ preview }: { preview: ChangePreview }) {
  const fits = preview.within_entitlement;

  return (
    <Alert variant={fits ? "info" : "warning"} className="mt-4">
      {fits ? (
        <Info className="h-4 w-4" />
      ) : (
        <ShieldQuestion className="h-4 w-4" />
      )}
      <AlertTitle>
        {fits ? "This fits within your plan" : "This goes beyond your plan"}
      </AlertTitle>
      <AlertDescription className="space-y-2">
        <p>{APPROVAL_EXPLANATION[preview.approval_level]}</p>

        {preview.escalation_reasons.length > 0 && (
          <ul className="ml-4 list-disc space-y-1">
            {preview.escalation_reasons.map((reason, index) => (
              <li key={`${reason.code}-${index}`}>{reason.message}</li>
            ))}
          </ul>
        )}

        {/*
          Usage figures, so an over-quota message is a number the customer can
          act on rather than a flat refusal.
        */}
        {preview.quota_decisions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {preview.quota_decisions
              .filter((decision) => !decision.unlimited)
              .map((decision) => (
                <span
                  key={decision.key}
                  className="rounded bg-background/60 px-2 py-0.5 text-xs"
                >
                  {decision.key}: {decision.current_usage}/{decision.limit}
                </span>
              ))}
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
}

export default function FacilityRequestsPage() {
  const [requests, setRequests] = useState<FacilityChangeRequest[]>([]);
  const [facilityType, setFacilityType] = useState("clinic");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [justification, setJustification] = useState("");
  const [preview, setPreview] = useState<ChangePreview | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadRequests = useCallback(async () => {
    const page = await api.get<Paginated<FacilityChangeRequest>>(
      "/org/facility-requests/",
    );
    setRequests(page.results);
  }, []);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  // Re-preview whenever the facility type changes. Cheap, read-only, and it
  // is the answer the user most wants before they commit to typing.
  useEffect(() => {
    let cancelled = false;
    api
      .post<ChangePreview>("/org/facility-requests/preview/", {
        request_type: "open_facility",
        facility_type: facilityType,
      })
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch(() => {
        if (!cancelled) setPreview(null);
      });
    return () => {
      cancelled = true;
    };
  }, [facilityType]);

  const justificationShort = justification.trim().length < MIN_JUSTIFICATION;
  const canSubmit =
    name.trim().length > 0 && code.trim().length > 0 && !justificationShort;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const created = await api.post<FacilityChangeRequest>(
        "/org/facility-requests/",
        {
          request_type: "open_facility",
          facility_type: facilityType,
          justification,
          payload: { name, code: code.toUpperCase() },
        },
      );
      setNotice(
        `${created.reference} submitted — ${
          APPROVAL_EXPLANATION[created.approval_level] ?? created.status
        }`,
      );
      setName("");
      setCode("");
      setJustification("");
      await loadRequests();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not submit the request.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          Facility changes
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Opening or closing a facility is reviewed before it takes effect, so
          the estate stays deliberate and every change has a reason attached.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Request a new facility</CardTitle>
            <CardDescription>
              You will see what this needs before you submit it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="facility-type">Facility type</Label>
                <Select
                  id="facility-type"
                  value={facilityType}
                  onChange={(event) => setFacilityType(event.target.value)}
                >
                  {FACILITY_TYPES.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="facility-name">Name</Label>
                  <Input
                    id="facility-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Manakamana Clinic, Pokhara"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="facility-code">Code</Label>
                  <Input
                    id="facility-code"
                    value={code}
                    onChange={(event) => setCode(event.target.value.toUpperCase())}
                    placeholder="MKC-PKR"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="justification">Justification</Label>
                <Textarea
                  id="justification"
                  value={justification}
                  onChange={(event) => setJustification(event.target.value)}
                  placeholder="Why this facility is needed — the approver reads this."
                />
                <p
                  className={
                    justificationShort
                      ? "text-xs text-amber-600"
                      : "text-xs text-muted-foreground"
                  }
                >
                  {justification.trim().length}/{MIN_JUSTIFICATION} characters
                  minimum
                </p>
              </div>

              {preview && <PreviewPanel preview={preview} />}

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

              <Button type="submit" disabled={!canSubmit || submitting}>
                <Send className="h-4 w-4" />
                {submitting ? "Submitting…" : "Submit request"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Requests</CardTitle>
            <CardDescription>
              Every facility change, decided or pending.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {requests.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No facility changes have been requested yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Reference</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Facility</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Raised by</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {requests.map((request) => (
                    <TableRow key={request.uuid}>
                      <TableCell className="font-mono text-xs">
                        {request.reference}
                      </TableCell>
                      <TableCell className="capitalize">
                        {request.facility_type}
                      </TableCell>
                      <TableCell>
                        {request.proposed_name || "—"}
                        {request.proposed_code && (
                          <span className="ml-1 text-xs text-muted-foreground">
                            ({request.proposed_code})
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={STATUS_VARIANT[request.status] ?? "secondary"}
                        >
                          {request.status.replace(/_/g, " ")}
                        </Badge>
                        {request.is_open && (
                          <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
                            <Clock className="h-3 w-3" />
                            {request.age_in_days}d
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {request.requested_by_email}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
