/**
 * Plan and usage — what this organization bought, and how much is left.
 *
 * The console gates on modules now (`ModuleGate`, `nav.ts`), and a product
 * that hides screens owes the customer a page saying *which* and *why*. Three
 * questions, in the order somebody asks them:
 *
 *  1. **What are we on, and when does it renew?**
 *  2. **What is included — and what else exists?** A module we do not have is
 *     shown, greyed, with what it does. Hiding it does not make anybody buy;
 *     it makes them assume the product cannot do it and look elsewhere.
 *  3. **How close are we to a limit?** Before they fill in the form that
 *     would be refused, not after.
 *
 * Read-only. Changing a plan is the platform's act, taken with the
 * consequences shown first — a customer cannot silently drop the module their
 * ward admits patients with.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, Check, Lock } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/dates";
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
import { Page, PageHeader, Section } from "@/components/ui/layout";

interface PlanSummary {
  plan: {
    code: string;
    name: string;
    tagline: string;
    base_price: string;
    currency: string;
    billing_interval: string;
    status: string;
    is_entitled: boolean;
    trial_ends_at: string | null;
    renews_at: string | null;
  };
  modules: {
    code: string;
    name: string;
    description: string;
    is_core: boolean;
    included: boolean;
    price_to_add: string | null;
  }[];
  limits: {
    key: string;
    value: number | null;
    unlimited: boolean;
    used: number;
    remaining: number | null;
    enforcement: string;
    near_limit: boolean;
  }[];
  features: string[];
}

/** Limit keys as a person would say them. */
const LIMIT_LABELS: Record<string, string> = {
  max_facilities: "Facilities",
  max_users: "User accounts",
  max_employees: "Employees",
  max_patients: "Patient records",
  max_storage_gb: "Storage (GB)",
  max_departments_per_facility: "Departments per facility",
  max_api_calls_per_month: "API calls a month",
  max_sms_per_month: "Messages a month",
  max_monthly_transactions: "Transactions a month",
};

function limitLabel(key: string): string {
  if (LIMIT_LABELS[key]) return LIMIT_LABELS[key];
  if (key.startsWith("max_facilities.")) {
    const type = key.slice("max_facilities.".length).replace(/_/g, " ");
    return `${type.charAt(0).toUpperCase()}${type.slice(1)} facilities`;
  }
  return key.replace(/_/g, " ");
}

export default function PlanPage() {
  const [data, setData] = useState<PlanSummary | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PlanSummary>("/org/plan/")
      .then(setData)
      .catch((err) =>
        setProblem(err instanceof ApiError ? err.message : "The plan could not be read."),
      );
  }, []);

  if (problem) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Could not load the plan</AlertTitle>
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    );
  }
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const included = data.modules.filter((module) => module.included);
  const available = data.modules.filter((module) => !module.included);
  const money = (amount: string) =>
    `${data.plan.currency} ${Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

  return (
    <Page>
      <PageHeader
        title="Plan & usage"
        description="What your organization has, what else Nirova does, and how much of your allowance is left."
      />

      {!data.plan.is_entitled && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>The subscription is {data.plan.status}</AlertTitle>
          <AlertDescription>
            Work already recorded stays readable. Anything that adds to the system
            is refused until this is settled.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="flex flex-wrap items-end justify-between gap-4 py-5">
          <div>
            <p className="type-label text-muted-foreground">Current plan</p>
            <p className="mt-0.5 font-display text-2xl font-semibold tracking-tight">
              {data.plan.name || data.plan.code}
            </p>
            {data.plan.tagline ? (
              <p className="mt-1 max-w-lg text-sm text-muted-foreground">{data.plan.tagline}</p>
            ) : null}
          </div>
          <div className="text-right">
            <p className="text-2xl font-semibold tabular-nums">{money(data.plan.base_price)}</p>
            <p className="text-sm text-muted-foreground">
              per {data.plan.billing_interval === "monthly" ? "month" : data.plan.billing_interval}
            </p>
            {data.plan.renews_at ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Renews {formatDate(data.plan.renews_at)}
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Section
        title="What you have"
        description={`${included.length} of ${data.modules.length} modules.`}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {included.map((module) => (
            <Card key={module.code}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Check className="h-4 w-4 text-good" />
                  {module.name}
                  {module.is_core ? <Badge variant="secondary">Core</Badge> : null}
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <p className="text-sm text-muted-foreground">{module.description || "—"}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </Section>

      {available.length > 0 && (
        <Section
          title="What else Nirova does"
          description="Not in your plan. Your account manager can add any of these."
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {available.map((module) => (
              <Card key={module.code} className="border-dashed bg-muted/30">
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-base text-muted-foreground">
                    <Lock className="h-4 w-4" />
                    {module.name}
                  </CardTitle>
                  {module.price_to_add ? (
                    <CardDescription>{money(module.price_to_add)} a month to add</CardDescription>
                  ) : null}
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-sm text-muted-foreground">{module.description || "—"}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </Section>
      )}

      <Section title="Allowances" description="What the plan permits, and what is used.">
        <Card>
          <CardContent className="divide-y py-2">
            {data.limits.map((limit) => {
              const proportion =
                limit.unlimited || !limit.value
                  ? 0
                  : Math.min(100, (limit.used / limit.value) * 100);
              return (
                <div key={limit.key} className="flex items-center gap-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{limitLabel(limit.key)}</p>
                    <p className="text-xs text-muted-foreground">
                      {limit.used.toLocaleString()} used
                      {limit.unlimited
                        ? " · unlimited"
                        : ` of ${(limit.value ?? 0).toLocaleString()}`}
                      {limit.enforcement !== "hard" ? ` · ${limit.enforcement}` : ""}
                    </p>
                  </div>
                  <div className="w-40 shrink-0">
                    {limit.unlimited ? (
                      <span className="text-xs text-muted-foreground">No ceiling</span>
                    ) : (
                      <Progress
                        value={proportion}
                        className={cn(limit.near_limit && "[&>div]:bg-warning")}
                      />
                    )}
                  </div>
                </div>
              );
            })}
            {data.limits.length === 0 && (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No ceilings on this plan.
              </p>
            )}
          </CardContent>
        </Card>
      </Section>
    </Page>
  );
}
