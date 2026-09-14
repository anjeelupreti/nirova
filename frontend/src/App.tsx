/**
 * The application shell: frame, navigation, routing.
 *
 * **What moved out of here, and why.** This file used to be 566 lines, of
 * which about 320 were a navigation literal and two hand-built `<nav>`s. The
 * navigation is data — `components/shell/nav.ts` — because three things now
 * consume it: the rail, the narrow strip, and the command palette. Keeping it
 * inline meant the palette could not exist without a second copy, and a second
 * copy is a rail and a palette that disagree about what the product contains.
 *
 * What is left is the shell's own job: decide who is signed in, work out where
 * "/" goes for *this* person, hold the frame together, and route.
 */

import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { Header } from "@/components/shell/Header";
import { NarrowNav, Sidebar, useRailState } from "@/components/shell/Sidebar";
import {
  CommandPalette,
  usePaletteShortcut,
  type PaletteAction,
} from "@/components/shell/CommandPalette";
import { moduleForRoute, resolveHome, visibleGroups } from "@/components/shell/nav";
import { RouteProgress, ShellSkeleton } from "@/components/ui/loader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/primitives";
import { useSession } from "@/hooks/useSession";
import { usePreferences } from "@/hooks/usePreferences";
import api from "@/lib/api";
import type { MyWorkspace } from "@/types";

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
const AccessPage = lazy(() => import("@/pages/Access"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const AccountPage = lazy(() => import("@/pages/Account"));
const AppointmentsPage = lazy(() => import("@/pages/Appointments"));
const BillingPage = lazy(() => import("@/pages/Billing"));
const BloodPage = lazy(() => import("@/pages/Blood"));
const PlanPage = lazy(() => import("@/pages/Plan"));
const ClaimsPage = lazy(() => import("@/pages/Claims"));
const ConfigurationPage = lazy(() => import("@/pages/Configuration"));
const ConsultationPage = lazy(() => import("@/pages/Consultation"));
const CounterPage = lazy(() => import("@/pages/Counter"));
const SalesPage = lazy(() => import("@/pages/Sales"));
const OnlineReturnPage = lazy(() => import("@/pages/billing/OnlineReturn"));
const DashboardPage = lazy(() => import("@/pages/Dashboard"));
const DataImportPage = lazy(() => import("@/pages/DataImport"));
const DiagnosticsPage = lazy(() => import("@/pages/Diagnostics"));
const EmergencyPage = lazy(() => import("@/pages/Emergency"));
const FacilitiesPage = lazy(() => import("@/pages/Facilities"));
const FacilityRequestsPage = lazy(() => import("@/pages/FacilityRequests"));
const FinancePage = lazy(() => import("@/pages/Finance"));
const IcuPage = lazy(() => import("@/pages/Icu"));
const KitchenPage = lazy(() => import("@/pages/Kitchen"));
const NotificationsPage = lazy(() => import("@/pages/Notifications"));
const NurseWorkspacePage = lazy(() => import("@/pages/NurseWorkspace"));
const PatientsPage = lazy(() => import("@/pages/Patients"));
const PatientRecordPage = lazy(() => import("@/pages/PatientRecord"));
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
const ServicesPage = lazy(() => import("@/pages/Services"));
const StaffPage = lazy(() => import("@/pages/Staff"));
const TheatrePage = lazy(() => import("@/pages/Theatre"));
const TimePage = lazy(() => import("@/pages/Time"));
const WardsPage = lazy(() => import("@/pages/Wards"));
const WorkspacePage = lazy(() => import("@/pages/Workspace"));

import LoginPage from "@/pages/Login";
import SignupPage from "@/pages/auth/Signup";
import { ForgotPasswordPage, ResetPasswordPage } from "@/pages/auth/PasswordReset";
import NotInPlan from "@/components/shell/NotInPlan";
import { ChoosePassword } from "@/pages/auth/ChoosePassword";
import { EnrolSecondFactor } from "@/pages/auth/EnrolSecondFactor";

export default function App() {
  const session = useSession();
  const { preferences } = usePreferences();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [counts, setCounts] = useState<{ notifications?: number; workspace?: number }>({});

  const navigate = useNavigate();
  const location = useLocation();

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  usePaletteShortcut(openPalette);

  const { session: data, can } = session;
  const isAuthenticated = session.isAuthenticated;

  const isPlatformOnly =
    Boolean(data?.user.is_platform_staff) && (data?.memberships.length ?? 0) === 0;

  /*
    The two numbers on the rail.

    One request, on sign-in and then never polled. A badge that reloads every
    thirty seconds is a request per user per thirty seconds for a number that
    changes a few times a day, and on a tenant with two hundred staff that is
    the busiest endpoint in the product for no clinical reason. The screens
    themselves are authoritative and refresh when opened.
  */
  useEffect(() => {
    // Platform staff have no hospital to have a workspace in; asking anyway
    // is a request whose only possible answer is "nothing".
    if (!isAuthenticated || isPlatformOnly) return;
    let cancelled = false;
    void api
      .get<MyWorkspace>("/me/workspace/")
      .then((workspace) => {
        if (cancelled) return;
        setCounts({
          workspace: workspace.approvals_total,
          // `unread` is `number | null` — null when the notification source
          // itself could not be read. Undefined here means "no badge", which is
          // the honest rendering; a zero would claim there is nothing unread.
          notifications: workspace.notifications?.unread ?? undefined,
        });
      })
      .catch(() => {
        // A count that cannot be read is shown as no count. Rendering a zero
        // would be a claim that nothing is waiting, which is the one thing it
        // must not say when the source failed.
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, isPlatformOnly]);

  /*
    Two lists from one model.

    The rail gets the work; the palette gets the work **and** the
    administrative screens that now live behind the avatar. Deleting those from
    the model instead would have made "Configuration" a screen you can only
    reach by remembering it is under an avatar, which is worse than the
    forty-item rail it replaced.
  */
  const groups = visibleGroups(can, Boolean(data?.user.is_platform_staff), {
    hasModule: session.hasModule,
    isPlatformOnly,
  });
  const paletteGroups = visibleGroups(can, Boolean(data?.user.is_platform_staff), {
    includeSystem: true,
    hasModule: session.hasModule,
    isPlatformOnly,
  });
  const railState = useRailState(groups);

  // A reset link opened in a browser that is already signed in is still a
  // reset link: somebody may be setting a password for an account other than
  // the one on screen, or recovering this one on a shared ward computer.
  if (location.pathname === "/reset-password") return <ResetPasswordPage />;
  if (session.loading) return <ShellSkeleton />;
  // Signed out, the only other place anyone can be is the registration form.
  // Every other path — a bookmarked ward, a link from a notification — lands
  // on sign-in, and the router takes them on to it afterwards.
  if (!session.isAuthenticated) {
    return (
      <Routes>
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="*" element={<LoginPage session={session} />} />
      </Routes>
    );
  }
  // A temporary password is for signing in once. Nothing else opens until it
  // has been replaced with one only this person knows.
  if (data?.user.must_change_password) {
    return <ChoosePassword session={session} name={data.user.full_name} />;
  }
  // The organization requires a second factor and this person has none yet.
  // The API refuses everything but enrolment, so the application would be a
  // screen of refusals; this is the one thing that can be done.
  if (data?.mfa_enrolment_required) {
    return (
      <EnrolSecondFactor
        session={session}
        organization={data.organization?.display_name ?? "Your organization"}
      />
    );
  }

  const organization = data?.organization;
  const memberships = data?.memberships ?? [];

  /*
    Where "/" goes, for this person.

    Previously one line: `isPlatformOnly ? "/platform" : "/patients"`. Every one
    of the seventeen seeded roles landed on the patient list — a pharmacist, a
    controller and a payroll officer included. `resolveHome` consults the
    `landing` preference first — which was offered on My account, saved, and
    then read by nothing — then the person's role, then their permissions.
  */
  const home = resolveHome({
    landing: preferences.landing,
    roles: [],
    isPlatformOnly,
    can,
    hasModule: session.hasModule,
  });

  const actions: PaletteAction[] = [
    {
      id: "appearance",
      label: "Change the colour scheme",
      icon: "spark",
      keywords: ["theme", "palette", "colour", "color", "dark", "light", "appearance"],
      run: () => navigate("/settings"),
    },
    {
      id: "sign-out",
      label: "Sign out",
      icon: "signOut",
      run: session.logout,
    },
  ];

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar
        groups={groups}
        organizationName={organization?.display_name ?? "Nirova"}
        facilityName={data?.entitlements?.plan_code ? null : null}
        planCode={data?.entitlements?.plan_code ?? null}
        counts={counts}
        state={railState}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          organization={organization ?? null}
          memberships={memberships}
          onSwitchOrganization={(slug) => void session.switchOrganization(slug)}
          onOpenPalette={openPalette}
          user={{
            name: data?.user.display_name ?? "",
            email: data?.user.email ?? "",
          }}
          onSignOut={session.logout}
          isPlatformOnly={isPlatformOnly}
          readOnly={organization?.is_read_only}
        />

        <div className="min-w-0 px-4 lg:px-6">
          <NarrowNav groups={groups} pinned={railState.pinned} counts={counts} />
        </div>

        <main className="mx-auto w-full min-w-0 max-w-content flex-1 px-4 py-6 lg:px-6">
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

          {/*
            A progress bar at the top of the window rather than a centred
            spinner. The spinner pushed the whole page down while a chunk
            downloaded and let it snap back on arrival, which on a slow
            connection looked like the page loading twice.
          */}
          {/*
            One gate for every route, rather than a check inside each screen.
            A module the organization has not bought is answered with what it
            is and who can add it (`NotInPlan`) — at the route, so a bookmark
            and a link from a colleague get the same answer as the sidebar.
          */}
          <ModuleGate hasModule={session.hasModule}>
          <Suspense fallback={<RouteProgress />}>
            <Routes>
              <Route path="/" element={<Navigate to={home} replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/patients" element={<PatientsPage />} />
              {/* One patient, on one page. Reached from the patient list, the
                  command palette and every worklist row. */}
              <Route path="/patients/:uuid" element={<PatientRecordPage />} />
              <Route path="/queue" element={<QueuePage />} />
              <Route path="/appointments" element={<AppointmentsPage />} />
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
              <Route path="/sales" element={<SalesPage />} />
              <Route path="/billing/online-return" element={<OnlineReturnPage />} />
              <Route path="/procurement" element={<ProcurementPage />} />
              <Route path="/self-service" element={<SelfServicePage />} />
              <Route path="/notifications" element={<NotificationsPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/configuration" element={<ConfigurationPage />} />
              <Route path="/import" element={<DataImportPage />} />
              <Route path="/workspace" element={<WorkspacePage />} />
              <Route path="/people" element={<PeoplePage />} />
              <Route path="/staff" element={<StaffPage />} />
              <Route path="/access" element={<AccessPage />} />
              {/* The administrative hub, reached from the avatar. */}
              <Route path="/settings" element={<SettingsPage />} />
              {/* Reached from the account menu rather than the sidebar: it is
                  about you, not about the work. */}
              <Route path="/account" element={<AccountPage />} />
              <Route path="/time" element={<TimePage />} />
              <Route path="/payroll" element={<PayrollPage />} />
              <Route path="/facilities" element={<FacilitiesPage />} />
              <Route path="/capacity" element={<PlanPage />} />
              <Route path="/facility-requests" element={<FacilityRequestsPage />} />
              <Route path="/platform" element={<PlatformPage />} />
              {/* The design system, rendered. Not in the sidebar: it is for
                  whoever is building the product, and the route is the door. */}
              <Route path="/design" element={<KitchenPage />} />
              <Route path="*" element={<Navigate to={home} replace />} />
            </Routes>
          </Suspense>
          </ModuleGate>
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        groups={paletteGroups}
        actions={actions}
        canSearchRecords={!isPlatformOnly}
      />
    </div>
  );
}

/**
 * Refuses a route whose module the organization has not bought.
 *
 * Reads the module from the navigation table (`moduleForRoute`), which is the
 * same table the sidebar filters on — one declaration, so the rail and the
 * router cannot disagree about what is included.
 */
function ModuleGate({
  hasModule,
  children,
}: {
  hasModule: (module: string) => boolean;
  children: React.ReactNode;
}) {
  const location = useLocation();
  const module = moduleForRoute(location.pathname);
  if (module && !hasModule(module)) return <NotInPlan module={module} />;
  return <>{children}</>;
}
