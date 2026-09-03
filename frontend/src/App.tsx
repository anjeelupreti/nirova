/**
 * The application shell: navigation, the organization switcher, and routing.
 *
 * The switcher is the visible half of the multi-tenancy design. Changing the
 * selected organization changes one HTTP header, and every screen re-renders
 * against a different database — no screen contains tenant-specific code.
 */

import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  Activity,
  Building2,
  ChevronDown,
  GaugeCircle,
  LogOut,
  FlaskConical,
  ListOrdered,
  Package,
  Receipt,
  ScrollText,
  ShoppingCart,
  Truck,
  UserCog,
  CalendarClock,
  Coins,
  BedDouble,
  Globe,
  Siren,
  Scissors,
  HeartPulse,
  Scale,
  ShieldCheck,
  Droplet,
  Users,
} from "lucide-react";

import { useSession } from "@/hooks/useSession";
import { cn } from "@/lib/utils";
import CapacityPage from "@/pages/Capacity";
import FacilitiesPage from "@/pages/Facilities";
import FacilityRequestsPage from "@/pages/FacilityRequests";
import LoginPage from "@/pages/Login";
import BillingPage from "@/pages/Billing";
import ConsultationPage from "@/pages/Consultation";
import CounterPage from "@/pages/Counter";
import DiagnosticsPage from "@/pages/Diagnostics";
import EmergencyPage from "@/pages/Emergency";
import PatientsPage from "@/pages/Patients";
import PlatformPage from "@/pages/Platform";
import PeoplePage from "@/pages/People";
import PayrollPage from "@/pages/Payroll";
import TimePage from "@/pages/Time";
import WardsPage from "@/pages/Wards";
import PharmacyPage from "@/pages/Pharmacy";
import ProcurementPage from "@/pages/Procurement";
import QueuePage from "@/pages/Queue";
import BloodPage from "@/pages/Blood";
import ClaimsPage from "@/pages/Claims";
import FinancePage from "@/pages/Finance";
import IcuPage from "@/pages/Icu";
import TheatrePage from "@/pages/Theatre";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Select,
} from "@/components/ui/primitives";

/**
 * Navigation, grouped.
 *
 * A flat row of fourteen tabs is a row nobody scans — and the product is
 * still growing. Grouping by *who uses it* rather than by module keeps each
 * list short enough to read: a receptionist lives in Clinical, a storekeeper
 * in Supply, and neither has to walk past the other's screens to find their
 * own.
 *
 * `platformOnly` marks the console that reads the control plane rather than a
 * tenant. It is hidden from customers entirely, not merely refused on click:
 * a menu item that always errors teaches people to ignore errors.
 */
const NAV_GROUPS: {
  label: string;
  platformOnly?: boolean;
  items: { to: string; label: string; icon: typeof Users }[];
}[] = [
  {
    label: "Clinical",
    items: [
      { to: "/patients", label: "Patients", icon: Users },
      { to: "/queue", label: "Queue", icon: ListOrdered },
      { to: "/emergency", label: "Emergency", icon: Siren },
      { to: "/wards", label: "Wards", icon: BedDouble },
      { to: "/theatre", label: "Theatre", icon: Scissors },
      { to: "/icu", label: "ICU", icon: HeartPulse },
      { to: "/diagnostics", label: "Diagnostics", icon: FlaskConical },
      { to: "/blood", label: "Blood bank", icon: Droplet },
    ],
  },
  {
    label: "Supply",
    items: [
      { to: "/pharmacy", label: "Pharmacy", icon: Package },
      { to: "/counter", label: "Counter", icon: ShoppingCart },
      { to: "/procurement", label: "Procurement", icon: Truck },
    ],
  },
  {
    label: "Money",
    items: [
      { to: "/billing", label: "Billing", icon: Receipt },
      { to: "/finance", label: "Finance", icon: Scale },
      { to: "/claims", label: "Claims", icon: ShieldCheck },
      { to: "/payroll", label: "Payroll", icon: Coins },
    ],
  },
  {
    label: "People",
    items: [
      { to: "/people", label: "Directory", icon: UserCog },
      { to: "/time", label: "Time", icon: CalendarClock },
    ],
  },
  {
    label: "Organization",
    items: [
      { to: "/facilities", label: "Facilities", icon: Building2 },
      { to: "/capacity", label: "Capacity", icon: GaugeCircle },
      { to: "/facility-requests", label: "Change requests", icon: ScrollText },
    ],
  },
  {
    label: "Platform",
    platformOnly: true,
    items: [{ to: "/platform", label: "Console", icon: Globe }],
  },
];

export default function App() {
  const session = useSession();

  if (session.loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (!session.isAuthenticated) {
    return <LoginPage session={session} />;
  }

  const { session: data } = session;
  const organization = data?.organization;
  //: Where "/" goes. A platform operator with no membership has nothing to
  //: see on a clinical screen, and a customer has no business on the console.
  const isPlatformOnly =
    Boolean(data?.user.is_platform_staff) &&
    (data?.memberships.length ?? 0) === 0;
  const home = isPlatformOnly ? "/platform" : "/patients";
  const memberships = data?.memberships ?? [];

  return (
    <div className="min-h-screen bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary">
              <Activity className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-semibold tracking-tight">Nirova</span>
          </div>

          {/*
            The context switcher. Only rendered when there is somewhere to
            switch to — a single-clinic customer should not be shown a control
            that does nothing.
          */}
          {memberships.length > 1 ? (
            <div className="relative flex items-center gap-1">
              <Select
                aria-label="Organization"
                className="h-8 w-auto pr-8 text-sm"
                value={organization?.slug ?? ""}
                onChange={(event) =>
                  void session.switchOrganization(event.target.value)
                }
              >
                {memberships.map((membership) => (
                  <option
                    key={membership.uuid}
                    value={membership.organization_slug}
                  >
                    {membership.organization_name}
                  </option>
                ))}
              </Select>
              <ChevronDown className="pointer-events-none -ml-7 h-4 w-4 text-muted-foreground" />
            </div>
          ) : (
            (organization ? (
              <span className="text-sm font-medium">
                {organization.display_name}
              </span>
            ) : isPlatformOnly ? (
              // No organization name to show, so say what they are instead.
              // A header that reads as blank suggests something failed to
              // load, when in fact nothing was meant to.
              <Badge variant="secondary">Platform operator</Badge>
            ) : null)
          )}

          {data?.entitlements && (
            <Badge variant="secondary" className="hidden sm:inline-flex">
              {data.entitlements.plan_code}
            </Badge>
          )}

          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {data?.user.display_name}
            </span>
            <Button variant="ghost" size="sm" onClick={session.logout}>
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </div>
        </div>

      </header>

      <div className="mx-auto flex max-w-[100rem] gap-6 px-4 py-6">
        {/*
          A sidebar rather than a row of tabs. Fourteen destinations do not fit
          across a header, and the ones that get pushed off the end are the
          ones nobody finds.
        */}
        <nav className="hidden w-52 shrink-0 space-y-5 lg:block">
          {NAV_GROUPS.filter(
            (group) => !group.platformOnly || data?.user.is_platform_staff,
          ).map((group) => (
            <div key={group.label}>
              <p className="mb-1 px-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                        isActive
                          ? "bg-muted font-medium text-foreground"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                      )
                    }
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/*
          On a narrow screen the sidebar collapses to a scrolling strip. A
          hamburger would hide the whole product behind one tap on the device
          a ward round actually uses.
        */}
        <nav className="-mx-4 mb-2 flex gap-1 overflow-x-auto px-4 pb-2 lg:hidden">
          {NAV_GROUPS.filter(
            (group) => !group.platformOnly || data?.user.is_platform_staff,
          )
            .flatMap((group) => group.items)
            .map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm transition-colors",
                    isActive
                      ? "border-primary bg-muted font-medium text-foreground"
                      : "border-transparent text-muted-foreground",
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
        </nav>

      <main className="min-w-0 flex-1">
        {/*
          A tenant that cannot be reached is a normal state during onboarding,
          not a crash — so it is explained rather than thrown.
        */}
        {data?.tenant_error && !isPlatformOnly && (
          <Alert variant="warning" className="mb-6">
            <AlertTitle>This organization is not ready yet</AlertTitle>
            <AlertDescription>{data.tenant_error.message}</AlertDescription>
          </Alert>
        )}

        {organization?.is_read_only && (
          <Alert variant="warning" className="mb-6">
            <AlertTitle>Read-only</AlertTitle>
            <AlertDescription>
              This organization is {organization.status}. Records can be viewed
              but not changed.
            </AlertDescription>
          </Alert>
        )}

        <Routes>
          {/*
            Platform staff have no memberships, so every tenant screen would
            be empty or refused. Landing them on the console is not a
            convenience — it is the only page that means anything to them.
          */}
          <Route path="/" element={<Navigate to={home} replace />} />
          <Route path="/patients" element={<PatientsPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/consultation/:uuid" element={<ConsultationPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/finance" element={<FinancePage />} />
          <Route path="/claims" element={<ClaimsPage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
          <Route path="/blood" element={<BloodPage />} />
          <Route path="/emergency" element={<EmergencyPage />} />
          <Route path="/wards" element={<WardsPage />} />
          <Route path="/theatre" element={<TheatrePage />} />
          <Route path="/icu" element={<IcuPage />} />
          <Route path="/pharmacy" element={<PharmacyPage />} />
          <Route path="/counter" element={<CounterPage />} />
          <Route path="/procurement" element={<ProcurementPage />} />
          <Route path="/people" element={<PeoplePage />} />
          <Route path="/time" element={<TimePage />} />
          <Route path="/payroll" element={<PayrollPage />} />
          <Route path="/facilities" element={<FacilitiesPage />} />
          <Route path="/capacity" element={<CapacityPage />} />
          <Route path="/facility-requests" element={<FacilityRequestsPage />} />
          <Route path="/platform" element={<PlatformPage />} />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </main>
      </div>
    </div>
  );
}
