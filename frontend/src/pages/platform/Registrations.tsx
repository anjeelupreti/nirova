/**
 * Registrations — organizations asking to use the product.
 *
 * The platform team's queue. Each request is read, called, and then either
 * onboarded — which hands its own answers to the same onboarding the
 * Customers tab uses, so nobody retypes a hospital's name — or declined with
 * a reason. The two things asked here that the request cannot answer itself
 * are the ones only the platform decides: the customer's address in the
 * product (its slug) and its plan.
 */

import { useCallback, useEffect, useState } from "react";
import { Building2, CheckCircle2, Mail, Phone, XCircle } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Paginated } from "@/types";
import { Alert, AlertDescription, Badge, Button, Card, Input, Label, Select } from "@/components/ui/primitives";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { formatDayMonth } from "@/lib/dates";

interface Registration {
  uuid: string;
  reference: string;
  organization_name: string;
  business_type: string;
  pan_number: string;
  province: string;
  district: string;
  facility_count: number;
  bed_count: number;
  modules: string[];
  current_system: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  contact_role: string;
  message: string;
  status: "new" | "contacted" | "onboarded" | "declined";
  created_at: string;
  reviewed_by_email: string;
  review_notes: string;
  organization_slug: string;
}

interface Plan {
  code: string;
  name: string;
}

const STATUS: Record<Registration["status"], { label: string; className: string }> = {
  new: { label: "New", className: "bg-info-subtle text-info-subtle-foreground" },
  contacted: { label: "Contacted", className: "bg-warning-subtle text-warning-subtle-foreground" },
  onboarded: { label: "Onboarded", className: "bg-good-subtle text-good-subtle-foreground" },
  declined: { label: "Declined", className: "bg-muted text-muted-foreground" },
};

const slugFor = (name: string) =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

export function Registrations() {
  const [rows, setRows] = useState<Registration[] | null>(null);
  const [filter, setFilter] = useState<"open" | "all">("open");
  const [open, setOpen] = useState<Registration | null>(null);

  const load = useCallback(async () => {
    const page = await api.get<Paginated<Registration>>("/platform/registrations/?page_size=100");
    setRows(page.results);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const shown = (rows ?? []).filter(
    (row) => filter === "all" || row.status === "new" || row.status === "contacted",
  );

  if (!rows) return <Skeleton className="h-64 rounded-xl" />;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <p className="text-sm font-medium">
            {shown.length} {filter === "open" ? "waiting" : "in total"}
          </p>
          <div className="inline-flex rounded-md border bg-muted/40 p-0.5 text-sm">
            {(["open", "all"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                className={cn("rounded px-2.5 py-1", filter === value ? "bg-background font-medium shadow-sm" : "text-muted-foreground")}
              >
                {value === "open" ? "Waiting" : "All"}
              </button>
            ))}
          </div>
        </div>
        {shown.length === 0 ? (
          <EmptyState
            illustration="people"
            title="Nobody waiting"
            description="Registrations from the sign-up page arrive here."
          />
        ) : (
          <ul className="divide-y">
            {shown.map((row) => (
              <li key={row.uuid}>
                <button
                  type="button"
                  onClick={() => setOpen(row)}
                  className={cn(
                    "flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-accent/40",
                    open?.uuid === row.uuid && "bg-accent/60",
                  )}
                >
                  <Building2 className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{row.organization_name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {row.business_type} · {[row.district, row.province].filter(Boolean).join(", ")}
                      {row.bed_count ? ` · ${row.bed_count} beds` : ""} · {row.contact_name}
                    </p>
                  </div>
                  <div className="text-right">
                    <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium", STATUS[row.status].className)}>
                      {STATUS[row.status].label}
                    </span>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {formatDayMonth(row.created_at)}
                    </p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {open ? (
        <RegistrationDetail
          key={open.uuid}
          row={open}
          onChanged={(next) => {
            setOpen(next);
            void load();
          }}
        />
      ) : (
        <Card className="hidden p-6 text-sm text-muted-foreground lg:block">
          Choose a registration to read it, call, and onboard or decline.
        </Card>
      )}
    </div>
  );
}

function RegistrationDetail({ row, onChanged }: { row: Registration; onChanged: (row: Registration) => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [slug, setSlug] = useState(slugFor(row.organization_name));
  const [plan, setPlan] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<Plan>>("/platform/plans/?page_size=50")
      .then((page) => {
        setPlans(page.results);
        setPlan(page.results.find((row) => row.code === "professional")?.code ?? page.results[0]?.code ?? "");
      })
      .catch(() => setPlans([]));
  }, []);

  async function act(path: string, body: object, done?: (data: Registration & { owner_email?: string }) => void) {
    setBusy(true);
    setProblem(null);
    try {
      const data = await api.post<Registration & { owner_email?: string }>(
        `/platform/registrations/${row.reference}/${path}/`,
        body,
      );
      done?.(data);
      onChanged(data);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  const closed = row.status === "onboarded" || row.status === "declined";

  return (
    <Card className="space-y-4 p-4">
      <div>
        <p className="text-xs text-muted-foreground">{row.reference}</p>
        <h3 className="text-lg font-semibold">{row.organization_name}</h3>
        <p className="text-sm text-muted-foreground">
          {row.business_type} · {row.facility_count} site{row.facility_count === 1 ? "" : "s"}
          {row.bed_count ? ` · ${row.bed_count} beds` : ""} · {[row.district, row.province].filter(Boolean).join(", ")}
        </p>
      </div>

      <div className="space-y-1.5 rounded-lg border p-3 text-sm">
        <p className="font-medium">
          {row.contact_name}
          {row.contact_role && <span className="font-normal text-muted-foreground"> · {row.contact_role}</span>}
        </p>
        <a href={`mailto:${row.contact_email}`} className="flex items-center gap-1.5 text-primary hover:underline">
          <Mail className="h-3.5 w-3.5" />
          {row.contact_email}
        </a>
        {row.contact_phone && (
          <a href={`tel:${row.contact_phone}`} className="flex items-center gap-1.5 text-primary hover:underline">
            <Phone className="h-3.5 w-3.5" />
            {row.contact_phone}
          </a>
        )}
      </div>

      <div className="flex flex-wrap gap-1">
        {row.modules.map((code) => (
          <Badge key={code} variant="secondary">{code.replace(/_/g, " ")}</Badge>
        ))}
      </div>
      {row.current_system && <p className="text-sm"><span className="text-muted-foreground">Uses today:</span> {row.current_system}</p>}
      {row.pan_number && <p className="text-sm"><span className="text-muted-foreground">PAN:</span> {row.pan_number}</p>}
      {row.message && <p className="rounded-lg bg-muted/40 p-3 text-sm">{row.message}</p>}

      {problem && (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}
      {result && (
        <Alert>
          <CheckCircle2 className="h-4 w-4" />
          <AlertDescription>{result}</AlertDescription>
        </Alert>
      )}

      {closed ? (
        <p className="text-sm text-muted-foreground">
          {row.status === "onboarded" ? `Onboarded as ${row.organization_slug}` : "Declined"}
          {row.reviewed_by_email && ` by ${row.reviewed_by_email}`}
          {row.review_notes && ` — ${row.review_notes}`}
        </p>
      ) : (
        <div className="space-y-4 border-t pt-4">
          {row.status === "new" && (
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void act("contacted", {})}>
              <Phone className="h-4 w-4" />
              Mark as contacted
            </Button>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="reg-slug">Workspace address</Label>
              <Input id="reg-slug" value={slug} onChange={(event) => setSlug(slugFor(event.target.value))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reg-plan">Plan</Label>
              <Select id="reg-plan" value={plan} onChange={(event) => setPlan(event.target.value)}>
                {plans.map((row) => (
                  <option key={row.code} value={row.code}>{row.name}</option>
                ))}
              </Select>
            </div>
          </div>
          <Button
            className="w-full"
            disabled={busy || !slug || !plan}
            onClick={() =>
              void act("onboard", { slug, plan_code: plan }, (data) =>
                setResult(`Provisioned. ${data.owner_email} is the owner — issue them a temporary password from Staff.`),
              )
            }
          >
            <CheckCircle2 className="h-4 w-4" />
            Onboard {row.organization_name}
          </Button>
          <div className="flex gap-2">
            <Input value={reason} placeholder="Reason for declining" onChange={(event) => setReason(event.target.value)} />
            <Button variant="ghost" disabled={busy || !reason.trim()} onClick={() => void act("decline", { reason })}>
              <XCircle className="h-4 w-4" />
              Decline
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
