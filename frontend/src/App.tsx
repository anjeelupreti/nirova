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
import PatientsPage from "@/pages/Patients";
import PeoplePage from "@/pages/People";
import PayrollPage from "@/pages/Payroll";
import TimePage from "@/pages/Time";
import WardsPage from "@/pages/Wards";
import PharmacyPage from "@/pages/Pharmacy";
import ProcurementPage from "@/pages/Procurement";
import QueuePage from "@/pages/Queue";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Select,
} from "@/components/ui/primitives";

const NAV = [
  { to: "/patients", label: "Patients", icon: Users },
  { to: "/queue", label: "Queue", icon: ListOrdered },
  { to: "/diagnostics", label: "Diagnostics", icon: FlaskConical },
  { to: "/wards", label: "Wards", icon: BedDouble },
  { to: "/pharmacy", label: "Pharmacy", icon: Package },
  { to: "/counter", label: "Counter", icon: ShoppingCart },
  { to: "/procurement", label: "Procurement", icon: Truck },
  { to: "/people", label: "People", icon: UserCog },
  { to: "/time", label: "Time", icon: CalendarClock },
  { to: "/payroll", label: "Payroll", icon: Coins },
  { to: "/billing", label: "Billing", icon: Receipt },
  { to: "/facilities", label: "Facilities", icon: Building2 },
  { to: "/capacity", label: "Capacity", icon: GaugeCircle },
  { to: "/facility-requests", label: "Change requests", icon: ScrollText },
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
            organization && (
              <span className="text-sm font-medium">
                {organization.display_name}
              </span>
            )
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

        <nav className="mx-auto flex max-w-7xl gap-1 px-4">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "border-primary font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {/*
          A tenant that cannot be reached is a normal state during onboarding,
          not a crash — so it is explained rather than thrown.
        */}
        {data?.tenant_error && (
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
          <Route path="/" element={<Navigate to="/patients" replace />} />
          <Route path="/patients" element={<PatientsPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/consultation/:uuid" element={<ConsultationPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
          <Route path="/wards" element={<WardsPage />} />
          <Route path="/pharmacy" element={<PharmacyPage />} />
          <Route path="/counter" element={<CounterPage />} />
          <Route path="/procurement" element={<ProcurementPage />} />
          <Route path="/people" element={<PeoplePage />} />
          <Route path="/time" element={<TimePage />} />
          <Route path="/payroll" element={<PayrollPage />} />
          <Route path="/facilities" element={<FacilitiesPage />} />
          <Route path="/capacity" element={<CapacityPage />} />
          <Route path="/facility-requests" element={<FacilityRequestsPage />} />
          <Route path="*" element={<Navigate to="/patients" replace />} />
        </Routes>
      </main>
    </div>
  );
}
