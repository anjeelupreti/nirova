/**
 * The application shell: navigation, the organization switcher, and routing.
 *
 * The switcher is the visible half of the multi-tenancy design. Changing the
 * selected organization changes one HTTP header, and every screen re-renders
 * against a different database — no screen contains tenant-specific code.
 */

import { Suspense, lazy } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  Activity,
  Building2,
  ChevronDown,
  GaugeCircle,
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
  Send,
  KeyRound,
  Users,
  UserCheck,
  ClipboardCheck,
  BarChart3,
  Tags,
  SlidersHorizontal,
  ShieldAlert,
  Inbox,
  Bell,
  Loader2,
} from "lucide-react";

import GlobalSearch from "@/components/GlobalSearch";
import UserMenu from "@/components/UserMenu";
import { useSession } from "@/hooks/useSession";
import { cn } from "@/lib/utils";

/*
  Route-level code splitting.

  Every page used to be a static import, which produced one 943 kB bundle that
  a receptionist downloaded in full to open the queue -- including the payroll
  engine, the theatre scheduler and the platform console, none of which they
  can even see. `lazy()` turns each page into its own chunk fetched on first
  navigation.

  Login stays eager on purpose: it is the first thing a logged-out visitor
  renders, and putting a spinner in front of the login form to save a few
  kilobytes is a bad trade.
*/
const BillingPage = lazy(() => import("@/pages/Billing"));
const BloodPage = lazy(() => import("@/pages/Blood"));
const CapacityPage = lazy(() => import("@/pages/Capacity"));
const ClaimsPage = lazy(() => import("@/pages/Claims"));
const ConfigurationPage = lazy(() => import("@/pages/Configuration"));
const ConsultationPage = lazy(() => import("@/pages/Consultation"));
const CounterPage = lazy(() => import("@/pages/Counter"));
const DiagnosticsPage = lazy(() => import("@/pages/Diagnostics"));
const EmergencyPage = lazy(() => import("@/pages/Emergency"));
const FacilitiesPage = lazy(() => import("@/pages/Facilities"));
const FacilityRequestsPage = lazy(() => import("@/pages/FacilityRequests"));
const FinancePage = lazy(() => import("@/pages/Finance"));
const IcuPage = lazy(() => import("@/pages/Icu"));
const NotificationsPage = lazy(() => import("@/pages/Notifications"));
const NurseWorkspacePage = lazy(() => import("@/pages/NurseWorkspace"));
const PatientsPage = lazy(() => import("@/pages/Patients"));
const PayrollPage = lazy(() => import("@/pages/Payroll"));
const PeoplePage = lazy(() => import("@/pages/People"));
const PharmacyPage = lazy(() => import("@/pages/Pharmacy"));
const PlatformPage = lazy(() => import("@/pages/Platform"));
const PortalPage = lazy(() => import("@/pages/Portal"));
const PrivacyPage = lazy(() => import("@/pages/Privacy"));
const ProcurementPage = lazy(() => import("@/pages/Procurement"));
const QueuePage = lazy(() => import("@/pages/Queue"));
const ReferralsPage = lazy(() => import("@/pages/Referrals"));
const ReportsPage = lazy(() => import("@/pages/Reports"));
const SelfServicePage = lazy(() => import("@/pages/SelfService"));
const AccountPage = lazy(() => import("@/pages/Account"));
const StaffPage = lazy(() => import("@/pages/Staff"));
const ServicesPage = lazy(() => import("@/pages/Services"));
const TheatrePage = lazy(() => import("@/pages/Theatre"));
const TimePage = lazy(() => import("@/pages/Time"));
const WardsPage = lazy(() => import("@/pages/Wards"));
const WorkspacePage = lazy(() => import("@/pages/Workspace"));

import LoginPage from "@/pages/Login";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Select,
} from "@/components/ui/primitives";

/**
 * Navigation: grouped by the job, and filtered by what this person may open.
 *
 * **Grouped by the job, not by the module.** "Clinical" used to hold eleven
 * items spanning outpatients, inpatients, theatre, the laboratory and the
 * patient portal — and a list of eleven is a list nobody scans. Each group is
 * now two to five items, named for the work rather than the codebase: somebody
 * on a ward opens Inpatient, somebody at a counter opens Pharmacy & supply,
 * and neither walks past the other's screens.
 *
 * **`needs` hides what this person cannot open.** Every item's permission is
 * *derived* from the endpoints its screen actually calls, not guessed —
 * guessing would be the wrong kind of confident, because hiding a menu item
 * somebody can use is worse than showing one they cannot. Items with no
 * `needs` are open to everybody who is signed in.
 *
 * A group whose every item is hidden does not render its heading either. An
 * empty section with a title is worse than no section: it looks like something
 * failed to load.
 *
 * **This is a courtesy, not a control.** The API refuses on its own and that
 * refusal is the guard; this only stops people being offered doors that do not
 * open for them.
 *
 * `platformOnly` marks the console that reads the control plane rather than a
 * tenant. Hidden from customers entirely, for the same reason: a menu item
 * that always errors teaches people to ignore errors.
 */
const NAV_GROUPS: {
  label: string;
  platformOnly?: boolean;
  items: {
    to: string;
    label: string;
    icon: typeof Users;
    needs?: string;
    /** The scope the screen's own endpoints ask for. */
    scope?: string;
  }[];
}[] = [
  {
    label: "Mine",
    items: [
      { to: "/workspace", label: "What needs you", icon: Inbox },
      { to: "/notifications", label: "Notifications", icon: Bell },
      // Moved out of People, which is where somebody looks for *other* people.
      { to: "/self-service", label: "Self service", icon: UserCheck },
    ],
  },
  {
    label: "Patients",
    items: [
      { to: "/patients", label: "Patients", icon: Users, needs: "patient.read", scope: "own" },
      { to: "/queue", label: "Queue", icon: ListOrdered, needs: "encounter.read", scope: "own" },
      { to: "/portal", label: "Portal accounts", icon: KeyRound, needs: "patient.read", scope: "facility" },
    ],
  },
  {
    label: "Inpatient",
    items: [
      { to: "/emergency", label: "Emergency", icon: Siren, needs: "encounter.read", scope: "own" },
      { to: "/wards", label: "Wards", icon: BedDouble, needs: "encounter.read", scope: "own" },
      { to: "/nurse-workspace", label: "Nurse workspace", icon: ClipboardCheck, needs: "encounter.read", scope: "facility" },
      { to: "/icu", label: "ICU", icon: HeartPulse, needs: "encounter.read", scope: "facility" },
      { to: "/theatre", label: "Theatre", icon: Scissors, needs: "encounter.read", scope: "facility" },
    ],
  },
  {
    label: "Diagnostics",
    items: [
      { to: "/diagnostics", label: "Laboratory & imaging", icon: FlaskConical, needs: "encounter.read", scope: "own" },
      { to: "/blood", label: "Blood bank", icon: Droplet, needs: "encounter.read", scope: "facility" },
      { to: "/referrals", label: "Referrals", icon: Send, needs: "encounter.read", scope: "facility" },
    ],
  },
  {
    label: "Pharmacy & supply",
    items: [
      { to: "/pharmacy", label: "Pharmacy", icon: Package, needs: "stock.read", scope: "facility" },
      { to: "/counter", label: "Counter", icon: ShoppingCart, needs: "sale.read", scope: "facility" },
      { to: "/procurement", label: "Procurement", icon: Truck, needs: "purchase.read", scope: "facility" },
    ],
  },
  {
    label: "Money",
    items: [
      { to: "/billing", label: "Billing", icon: Receipt, needs: "invoice.read", scope: "facility" },
      { to: "/claims", label: "Insurance claims", icon: ShieldCheck, needs: "invoice.read", scope: "facility" },
      { to: "/finance", label: "Finance", icon: Scale, needs: "report.read", scope: "facility" },
      // What things cost, beside the screens that charge for them. Reading is
      // `invoice.read` because anybody raising an invoice needs to see prices;
      // changing them is a different permission the screen checks itself.
      { to: "/services", label: "Services & prices", icon: Tags, needs: "invoice.read", scope: "facility" },
    ],
  },
  {
    label: "People",
    items: [
      { to: "/people", label: "Directory", icon: UserCog, needs: "employee.read", scope: "own" },
      { to: "/time", label: "Attendance & leave", icon: CalendarClock, needs: "attendance.read", scope: "own" },
      { to: "/payroll", label: "Payroll", icon: Coins, needs: "salary.read", scope: "facility" },
    ],
  },
  {
    label: "Oversight",
    items: [
      { to: "/reports", label: "Reports", icon: BarChart3, needs: "report.read", scope: "own" },
      { to: "/privacy", label: "Privacy", icon: ShieldAlert, needs: "privacy.review", scope: "facility" },
    ],
  },
  {
    label: "Organization",
    items: [
      { to: "/facilities", label: "Facilities", icon: Building2, needs: "facility.read", scope: "facility" },
      { to: "/capacity", label: "Capacity", icon: GaugeCircle, needs: "facility.read", scope: "facility" },
      { to: "/facility-requests", label: "Change requests", icon: ScrollText, needs: "facility.read", scope: "facility" },
      // Under Organization rather than People on purpose: /people is the
      // employee directory -- hiring, transfers, credentials -- and says
      // nothing about who can sign in. Those are different questions asked by
      // different people, and putting them side by side taught nobody which
      // was which. `user.read` at `own`, because seeing your colleagues is not
      // an administrative act; inviting one is, and that is checked on POST.
      { to: "/staff", label: "Staff access", icon: KeyRound, needs: "user.read", scope: "own" },
      // Six rarely-visited lists behind one entry rather than six. Reading
      // needs `config.read`; each list checks its own write permission.
      { to: "/configuration", label: "Configuration", icon: SlidersHorizontal, needs: "config.read", scope: "facility" },
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

  const { session: data, can } = session;
  const organization = data?.organization;
  //: Where "/" goes. A platform operator with no membership has nothing to
  //: see on a clinical screen, and a customer has no business on the console.
  const isPlatformOnly =
    Boolean(data?.user.is_platform_staff) &&
    (data?.memberships.length ?? 0) === 0;
  const home = isPlatformOnly ? "/platform" : "/patients";
  const memberships = data?.memberships ?? [];

  /**
   * The groups this person can actually use.
   *
   * Filtered once here rather than inside both navigations, so the sidebar and
   * the narrow-screen strip can never disagree about what exists. A group with
   * nothing left in it is dropped entirely: an empty section under a heading
   * looks like something failed to load.
   */
  const visibleGroups = NAV_GROUPS.filter(
    (group) => !group.platformOnly || data?.user.is_platform_staff,
  )
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.needs || can(item.needs, item.scope)),
    }))
    .filter((group) => group.items.length > 0);

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
            The omnibox, in the header rather than on a page: a search you have
            to navigate to is a search nobody uses. Hidden from a platform
            operator with no membership, who has no tenant to search.
          */}
          {isPlatformOnly ? null : <GlobalSearch />}

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

          {/*
            The account menu, where every product of this kind puts it: an
            avatar at the far right that opens onto the things about *you*
            rather than about the organization. Before this the header had a
            name in grey text and a Sign out button, and there was nowhere at
            all to reach your own settings.
          */}
          <div className="ml-auto flex items-center gap-2">
            <UserMenu
              name={data?.user.display_name ?? ""}
              email={data?.user.email ?? ""}
              onSignOut={session.logout}
            />
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
          {visibleGroups.map((group) => (
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
          {visibleGroups
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

        <Suspense
          fallback={
            <p className="py-16 text-center text-sm text-muted-foreground">
              <Loader2 className="inline h-4 w-4 animate-spin" />
            </p>
          }
        >
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
          <Route path="/referrals" element={<ReferralsPage />} />
          <Route path="/portal" element={<PortalPage />} />
          <Route path="/emergency" element={<EmergencyPage />} />
          <Route path="/wards" element={<WardsPage />} />
          <Route path="/nurse-workspace" element={<NurseWorkspacePage />} />
          <Route path="/theatre" element={<TheatrePage />} />
          <Route path="/icu" element={<IcuPage />} />
          <Route path="/pharmacy" element={<PharmacyPage />} />
          <Route path="/counter" element={<CounterPage />} />
          <Route path="/procurement" element={<ProcurementPage />} />
          <Route path="/self-service" element={<SelfServicePage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/services" element={<ServicesPage />} />
          <Route path="/configuration" element={<ConfigurationPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/people" element={<PeoplePage />} />
          <Route path="/staff" element={<StaffPage />} />
          {/* Reached from the account menu rather than the sidebar: it is
              about you, not about the work. */}
          <Route path="/account" element={<AccountPage />} />
          <Route path="/time" element={<TimePage />} />
          <Route path="/payroll" element={<PayrollPage />} />
          <Route path="/facilities" element={<FacilitiesPage />} />
          <Route path="/capacity" element={<CapacityPage />} />
          <Route path="/facility-requests" element={<FacilityRequestsPage />} />
          <Route path="/platform" element={<PlatformPage />} />
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
        </Suspense>
      </main>
      </div>
    </div>
  );
}
