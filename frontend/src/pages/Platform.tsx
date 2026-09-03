/**
 * The platform console: the owner's view of their own business.
 *
 * Everything here reads the control plane, never a tenant database. That is
 * the point of the control plane existing: a platform owner can see how many
 * hospitals their customers run and what each is worth, without a single
 * query touching a patient record.
 *
 * Three things the screen insists on.
 *
 * **MRR is shown split into plan and expansion.** For a modular product most
 * growth is add-ons, and a single MRR figure hides the fact. This customer is
 * 82% expansion revenue — which is either the best news in the business or a
 * concentration risk, and neither is visible from one number.
 *
 * **A trial is not revenue.** Trial value is reported beside MRR and never
 * inside it. Counting hope as income is how a SaaS dashboard tells its owner
 * the business is bigger than it is.
 *
 * **Concentration is a first-class figure.** A business where one customer is
 * 40% of MRR is a different business from one where the largest is 4%, and
 * the headline number is identical in both.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Database,
  Layers,
  Loader2,
  PieChart,
  Server,
  ShieldQuestion,
  TrendingUp,
  Users,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  Paginated,
  PlatformDashboard,
  PlatformOrganization,
  PlatformPlan,
  PlatformSubscription,
} from "@/types";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";

type Tab = "overview" | "customers" | "subscriptions" | "plans";

const TABS: { id: Tab; label: string; icon: typeof Building2 }[] = [
  { id: "overview", label: "Overview", icon: TrendingUp },
  { id: "customers", label: "Customers", icon: Building2 },
  { id: "subscriptions", label: "Subscriptions", icon: Layers },
  { id: "plans", label: "Plans", icon: PieChart },
];

const rupees = (value: string | number) =>
  `Rs ${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;

const humanise = (value: string) => value.replace(/_/g, " ");

const STATUS_TONE: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "secondary",
  trial: "default",
  trialing: "default",
  past_due: "destructive",
  suspended: "destructive",
  cancelled: "destructive",
  pending: "outline",
};

export default function PlatformPage() {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Platform</h1>
        <p className="text-sm text-muted-foreground">
          Every customer, every subscription, without opening a tenant
          database.
        </p>
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

      {tab === "overview" && <Overview />}
      {tab === "customers" && <Customers />}
      {tab === "subscriptions" && <Subscriptions />}
      {tab === "plans" && <Plans />}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Overview                                                                    */
/* -------------------------------------------------------------------------- */

function Overview() {
  const [data, setData] = useState<PlatformDashboard | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(
        await api.get<PlatformDashboard>("/platform/dashboard/", {
          withoutOrganization: true,
        }),
      );
      setProblem(null);
    } catch (err) {
      setProblem(
        err instanceof ApiError
          ? err.message
          : "Could not load the platform dashboard.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (problem) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Not available</AlertTitle>
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    );
  }
  if (!data) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        <Loader2 className="inline h-4 w-4 animate-spin" />
      </p>
    );
  }

  const { revenue, organizations, facilities, infrastructure } = data;

  return (
    <div className="space-y-4">
      {infrastructure.failed > 0 && (
        <Alert variant="destructive">
          <Database className="h-4 w-4" />
          <AlertTitle>
            {infrastructure.failed} tenant{" "}
            {infrastructure.failed === 1 ? "database" : "databases"} failed to
            provision
          </AlertTitle>
          <AlertDescription>
            Those customers can sign in and see nothing. It is inert and
            obvious, which is why provisioning writes in that order — but it
            still needs fixing.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="MRR"
          value={rupees(revenue.mrr)}
          hint={`${rupees(revenue.arr)} annualised`}
        />
        <Stat
          label="Expansion"
          value={rupees(revenue.expansion_mrr)}
          hint={`${revenue.expansion_share_percent}% of MRR`}
          tone={
            revenue.expansion_share_percent > 50 ? "text-emerald-600" : undefined
          }
        />
        <Stat
          label="Paying customers"
          value={String(revenue.paying_customers)}
          hint={`${rupees(revenue.arpu)} average`}
        />
        <Stat
          label="On trial"
          value={String(revenue.trial_customers)}
          hint={`${rupees(revenue.trial_potential_mrr)} potential`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Where the revenue comes from
            </CardTitle>
            <CardDescription>
              Plan against expansion. For a modular product most growth is
              add-ons, and a single MRR figure hides that entirely.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Plan</span>
                <span className="tabular-nums">
                  {rupees(revenue.base_mrr)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">
                  Expansion (add-ons)
                </span>
                <span className="tabular-nums">
                  {rupees(revenue.expansion_mrr)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary"
                  style={{
                    width: `${Math.min(
                      100 - revenue.expansion_share_percent,
                      100,
                    )}%`,
                  }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {revenue.expansion_share_percent}% of revenue is above the plan
                the customer originally bought.
              </p>
            </div>

            <div className="border-t pt-3">
              <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                By plan
              </p>
              {Object.entries(revenue.by_plan).map(([plan, value]) => (
                <div key={plan} className="flex justify-between text-sm">
                  <span className="capitalize">{plan || "—"}</span>
                  <span className="tabular-nums">{rupees(value)}</span>
                </div>
              ))}
            </div>

            <div className="border-t pt-3">
              <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                By billing interval
              </p>
              {Object.entries(revenue.by_billing_interval).map(
                ([interval, value]) => (
                  <div key={interval} className="flex justify-between text-sm">
                    <span className="capitalize">{humanise(interval)}</span>
                    <span className="tabular-nums">{rupees(value)}</span>
                  </div>
                ),
              )}
              <p className="mt-1 text-xs text-muted-foreground">
                Annual contracts are divided down to a month — summing
                contracted prices would report an annual customer as twelve
                times their size.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Concentration</CardTitle>
            <CardDescription>
              A business where one customer is 40% of MRR is a different
              business from one where the largest is 4% — and the headline
              number is identical in both.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer</TableHead>
                  <TableHead className="text-right">MRR</TableHead>
                  <TableHead className="text-right">Share</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.concentration.map((row) => (
                  <TableRow key={row.organization}>
                    <TableCell>
                      <span className="font-medium">{row.organization}</span>
                      <span className="block text-xs text-muted-foreground">
                        {row.plan}
                        {Number(row.expansion_mrr) > 0 &&
                          ` · ${rupees(row.expansion_mrr)} expansion`}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.mrr)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        row.share_percent > 25 && "font-medium text-amber-600",
                      )}
                    >
                      {row.share_percent}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {data.entitled_but_unbilled.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Using the product, not paying for it
            </CardTitle>
            <CardDescription>
              Trials, grace periods and past-due accounts. Every one is a
              deliberate state — but the reason it happened is rarely still
              remembered a month later.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Ends</TableHead>
                  <TableHead className="text-right">Would be</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.entitled_but_unbilled.map((row) => (
                  <TableRow key={row.organization}>
                    <TableCell className="font-medium">
                      {row.organization_name}
                    </TableCell>
                    <TableCell>{row.plan}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                        {humanise(row.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.trial_ends_at
                        ? new Date(row.trial_ends_at).toLocaleDateString()
                        : row.grace_ends_at
                          ? new Date(row.grace_ends_at).toLocaleDateString()
                          : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.contracted_price)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Customers</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Row label="Total" value={organizations.total} />
            <Row label="Active" value={organizations.active} />
            <Row label="On trial" value={organizations.trial} />
            <Row
              label="Past due"
              value={organizations.past_due}
              tone={organizations.past_due > 0 ? "text-destructive" : undefined}
            />
            <Row
              label="Suspended"
              value={organizations.suspended}
              tone={
                organizations.suspended > 0 ? "text-destructive" : undefined
              }
            />
            <Row label="Cancelled" value={organizations.cancelled} />
            {organizations.pending_provisioning > 0 && (
              <Row
                label="Awaiting provisioning"
                value={organizations.pending_provisioning}
                tone="text-amber-600"
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Facilities</CardTitle>
            <CardDescription>
              Across every customer, without opening a tenant database.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Row label="Total" value={facilities.total} />
            {Object.entries(facilities.by_type).map(([type, count]) => (
              <Row key={type} label={humanise(type)} value={count} />
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="h-4 w-4" />
              Infrastructure
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Row
              label="Tenant databases"
              value={infrastructure.tenant_databases}
            />
            <Row label="Ready" value={infrastructure.ready} />
            <Row
              label="Failed"
              value={infrastructure.failed}
              tone={infrastructure.failed > 0 ? "text-destructive" : undefined}
            />
            <div className="border-t pt-2">
              <Row
                label="Change requests open"
                value={data.change_requests.open}
              />
              <Row
                label="Waiting on us"
                value={data.change_requests.awaiting_platform}
                tone={
                  data.change_requests.awaiting_platform > 0
                    ? "text-amber-600"
                    : undefined
                }
              />
              <Row
                label="Waiting on the customer"
                value={data.change_requests.awaiting_organization}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-muted-foreground">
        Generated {new Date(data.generated_at).toLocaleString()} — one endpoint,
        one moment in time. A dashboard assembled from a dozen calls shows a
        dozen different moments, which is how "our numbers don't tie up"
        starts.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Customers                                                                   */
/* -------------------------------------------------------------------------- */

function Customers() {
  const [rows, setRows] = useState<PlatformOrganization[]>([]);

  useEffect(() => {
    void api
      .get<Paginated<PlatformOrganization>>("/platform/organizations/", {
        withoutOrganization: true,
      })
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Customers</CardTitle>
        <CardDescription>
          Every organization, with its estate and its tenant database — read
          from the control plane, never from a patient record.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Organization</TableHead>
              <TableHead>Where</TableHead>
              <TableHead className="text-right">Facilities</TableHead>
              <TableHead className="text-right">Users</TableHead>
              <TableHead>Database</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.uuid}>
                <TableCell>
                  <span className="font-medium">{row.display_name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {row.slug} · {humanise(row.business_type)}
                    {row.pan_number && ` · PAN ${row.pan_number}`}
                  </span>
                </TableCell>
                <TableCell className="text-xs">
                  {[row.municipality, row.district, row.province]
                    .filter(Boolean)
                    .join(", ") || "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.facility_count}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.member_count}
                </TableCell>
                <TableCell>
                  {row.database_status === "ready" ? (
                    <span className="flex items-center gap-1 text-xs text-emerald-600">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      {row.database_alias}
                    </span>
                  ) : (
                    <Badge variant="destructive">
                      {row.database_status ?? "none"}
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
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
                  No customers yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Subscriptions                                                               */
/* -------------------------------------------------------------------------- */

function Subscriptions() {
  const [rows, setRows] = useState<PlatformSubscription[]>([]);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Paginated<PlatformSubscription>>("/platform/subscriptions/", {
        withoutOrganization: true,
      })
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, []);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Subscriptions</CardTitle>
          <CardDescription>
            The contract, its add-ons, and where each add-on came from — a
            facility change request, usually.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead className="text-right">Contract</TableHead>
                <TableHead className="text-right">Add-ons</TableHead>
                <TableHead>Period ends</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const addonTotal = row.addons
                  .filter((addon) => addon.is_active)
                  .reduce(
                    (sum, addon) =>
                      sum + Number(addon.unit_price) * addon.quantity,
                    0,
                  );
                return (
                  <TableRow
                    key={row.uuid}
                    className="cursor-pointer"
                    onClick={() =>
                      setOpen(open === row.uuid ? null : row.uuid)
                    }
                  >
                    <TableCell>
                      <span className="font-medium">
                        {row.organization_name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {row.organization_slug} · {humanise(row.billing_interval)}
                      </span>
                    </TableCell>
                    <TableCell>{row.plan_name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {rupees(row.contracted_price)}
                      {Number(row.discount_percent) > 0 && (
                        <span className="block text-xs text-emerald-600">
                          −{row.discount_percent}%
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {addonTotal > 0 ? rupees(addonTotal) : "—"}
                      {row.addons.length > 0 && (
                        <span className="block text-xs text-muted-foreground">
                          {row.addons.filter((a) => a.is_active).length} active
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.current_period_end
                        ? new Date(row.current_period_end).toLocaleDateString()
                        : "—"}
                      {row.cancel_at_period_end && (
                        <span className="block text-destructive">
                          cancels then
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_TONE[row.status] ?? "outline"}>
                        {humanise(row.status)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {rows
        .filter((row) => row.uuid === open)
        .map((row) => (
          <Card key={row.uuid}>
            <CardHeader>
              <CardTitle className="text-base">
                {row.organization_name} — add-ons
              </CardTitle>
              <CardDescription>
                Each carries the reference of whatever bought it, so a price
                rise traces back to the request that caused it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Add-on</TableHead>
                    <TableHead>Grants</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead>From</TableHead>
                    <TableHead>Because of</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {row.addons.map((addon) => (
                    <TableRow
                      key={addon.uuid}
                      className={cn(!addon.is_active && "opacity-50")}
                    >
                      <TableCell className="font-medium">
                        {addon.addon_name}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {addon.target_key}
                        {addon.increment > 0 && ` +${addon.increment}`}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {addon.quantity}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {rupees(addon.unit_price)}
                      </TableCell>
                      <TableCell className="text-xs">
                        {new Date(addon.effective_from).toLocaleDateString()}
                        {addon.effective_to && (
                          <span className="block text-muted-foreground">
                            to {new Date(addon.effective_to).toLocaleDateString()}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {addon.source_reference || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Plans                                                                       */
/* -------------------------------------------------------------------------- */

function Plans() {
  const [rows, setRows] = useState<PlatformPlan[]>([]);

  useEffect(() => {
    void api
      .get<Paginated<PlatformPlan>>("/platform/plans/", {
        withoutOrganization: true,
      })
      .then((page) => setRows(page.results))
      .catch(() => setRows([]));
  }, []);

  return (
    <div className="space-y-4">
      <Alert>
        <ShieldQuestion className="h-4 w-4" />
        <AlertTitle>A limit not on the plan resolves to zero</AlertTitle>
        <AlertDescription>
          The entitlement engine fails closed: an unknown limit key is nothing,
          never unlimited. A plan that forgot to mention a limit sells nothing
          rather than everything.
        </AlertDescription>
      </Alert>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {rows.map((plan) => (
          <Card key={plan.uuid} className={cn(!plan.is_active && "opacity-60")}>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <CardTitle className="text-base">{plan.name}</CardTitle>
                  <CardDescription>{plan.tagline}</CardDescription>
                </div>
                {!plan.is_public && <Badge variant="outline">private</Badge>}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <p className="text-2xl font-semibold tabular-nums">
                  {rupees(plan.base_price)}
                  <span className="text-sm font-normal text-muted-foreground">
                    {" "}
                    / {humanise(plan.billing_interval)}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">
                  {plan.trial_days} days' trial · {plan.grace_days} days' grace
                  {Number(plan.setup_fee) > 0 &&
                    ` · ${rupees(plan.setup_fee)} setup`}
                </p>
              </div>

              {plan.modules.length > 0 && (
                <div>
                  <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                    Modules
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {plan.modules.map((module) => (
                      <Badge key={module} variant="secondary">
                        {humanise(module)}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {plan.limits.length > 0 && (
                <div>
                  <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                    Limits
                  </p>
                  <ul className="space-y-0.5 text-sm">
                    {plan.limits.map((limit) => (
                      <li
                        key={limit.key}
                        className="flex justify-between gap-2"
                      >
                        <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                          {limit.key}
                        </span>
                        <span className="shrink-0 tabular-nums">
                          {limit.is_unlimited ? "∞" : limit.value}
                          {limit.enforcement !== "hard" && (
                            <span className="ml-1 text-xs text-muted-foreground">
                              {limit.enforcement}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {rows.length === 0 && (
          <Card className="md:col-span-2 lg:col-span-3">
            <CardContent className="py-16 text-center text-sm text-muted-foreground">
              <Users className="mx-auto mb-2 h-8 w-8 opacity-40" />
              No plans defined.
            </CardContent>
          </Card>
        )}
      </div>
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
        <p className={cn("mt-1 text-2xl font-semibold tabular-nums", tone)}>
          {value}
        </p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: string;
}) {
  return (
    <div className="flex justify-between gap-2">
      <span className="capitalize text-muted-foreground">{label}</span>
      <span className={cn("tabular-nums", tone)}>{value}</span>
    </div>
  );
}
