/**
 * The navigation model.
 *
 * Lifted out of `App.tsx`, where it sat as a 180-line literal in the middle of
 * the router. It is data, three components consume it — the rail, the narrow
 * strip and the command palette — and having it inline meant the palette could
 * not exist without duplicating it.
 *
 * **The permission and scope on every item are derived from the endpoints its
 * screen actually calls, not guessed.** That work is preserved verbatim from
 * the original, comments included, because it was measured rather than assumed
 * and re-deriving it by eye would undo it. Guessing here is the wrong kind of
 * confident: hiding a menu item somebody can use is worse than showing one
 * they cannot.
 *
 * **This is a courtesy, not a control.** The API refuses on its own and that
 * refusal is the guard; this only stops people being offered doors that do not
 * open for them.
 */

import type { IconName } from "@/components/ui/icon";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** The permission code the screen's endpoints require. */
  needs?: string;
  /** The scope those endpoints ask for. */
  scope?: string;
  /**
   * The module this screen is sold as. Absent means core — every tenant has
   * it whatever they bought. A tenant without the module does not see the
   * item, and the route says so plainly rather than 403-ing (`NotInPlan`).
   */
  module?: string;
  /**
   * A second permission the screen also requires, at the same scope. For a
   * screen that sits where two jobs meet: the sales report needs both sight of
   * the counter and the right to read reports, so a doctor (reports, no
   * counter) and a cashier (counter, no reports) are both not offered it.
   */
  alsoNeeds?: string;
  /**
   * Words somebody might type looking for this screen that are not in its
   * label. The command palette searches these too — "roster" finds Attendance,
   * "MRN" finds Patients — because the label is what we call it and the
   * synonym is what they call it.
   */
  keywords?: string[];
  /** A live count, resolved by the shell: unread, pending, waiting. */
  badge?: "notifications" | "workspace";
}

export interface NavGroup {
  label: string;
  icon: IconName;
  platformOnly?: boolean;
  /** Collapsed by default. For groups that are visited rarely. */
  defaultCollapsed?: boolean;
  items: NavItem[];
}

/**
 * Whether this person may open the screen an item points at.
 *
 * Three questions, and all three have to be yes: does the organization have
 * the module (what they bought), does this person hold the permission (what
 * they may do), and at a wide enough scope. The first was missing entirely
 * until §142 — `hasModule` existed on the session hook and was called
 * nowhere, so a pharmacy that had bought the counter was shown ICU, theatre
 * and the blood bank, and concluded the product was not for them.
 */
export function mayOpen(
  item: Pick<NavItem, "needs" | "alsoNeeds" | "scope" | "module">,
  can: (permission: string, scope?: string) => boolean,
  hasModule: (module: string) => boolean = () => true,
): boolean {
  if (item.module && !hasModule(item.module)) return false;
  if (item.needs && !can(item.needs, item.scope)) return false;
  if (item.alsoNeeds && !can(item.alsoNeeds, item.scope)) return false;
  return true;
}

/** The module a route is sold as, or "" when it is core. */
export function moduleForRoute(path: string): string {
  const item = ALL_NAV_ITEMS.find((entry) => entry.to === path);
  return item?.module ?? "";
}

/**
 * Grouped by the job, not by the module.
 *
 * "Clinical" used to hold eleven items spanning outpatients, inpatients,
 * theatre, the laboratory and the patient portal — and a list of eleven is a
 * list nobody scans. Each group is two to five items, named for the work
 * rather than the codebase: somebody on a ward opens Inpatient, somebody at a
 * counter opens Pharmacy & supply, and neither walks past the other's screens.
 *
 * A group whose every item is hidden does not render its heading either. An
 * empty section with a title is worse than no section: it looks like something
 * failed to load.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    icon: "home",
    items: [
      // **My day first, the organization's second.** They were the other way
      // round while both screens claimed to be "your day" (§143): a nurse and
      // a counter assistant open the product to do their own work, and an
      // organization dashboard is the first thing only for whoever runs the
      // place.
      {
        to: "/workspace",
        label: "My day",
        icon: "workspace",
        badge: "workspace",
        keywords: [
          "workspace", "approvals", "inbox", "pending", "tasks", "my patients",
          "my clinic", "what needs you", "for you",
        ],
      },
      {
        // `analytics.read` rather than nothing: the dashboard is now the
        // organization's day — occupancy, takings, what is stuck — and that is
        // a manager's screen. A nurse was being shown it first and it told her
        // nothing about her shift.
        to: "/dashboard",
        label: "Dashboard",
        icon: "dashboard",
        needs: "analytics.read",
        scope: "facility",
        keywords: ["home", "overview", "kpi", "figures", "today", "occupancy"],
      },
      // Notifications are the bell in the top bar, as in every product people
      // already use; the full page is reached from its "View all".
      // Moved out of People, which is where somebody looks for *other* people.
      {
        to: "/self-service",
        module: "hrms",
        label: "Self service",
        icon: "verifiedPerson",
        keywords: ["payslip", "my leave", "my attendance", "ess"],
      },
    ],
  },
  {
    label: "Patients",
    icon: "patient",
    items: [
      {
        to: "/patients",
        label: "Patients",
        icon: "patient",
        needs: "patient.read",
        scope: "own",
        keywords: ["mrn", "register", "demographics", "search patient"],
      },
      // Beside the queue on purpose: a receptionist moves between "who is
      // booked" and "who is waiting" all morning, and they were a click apart
      // in different groups.
      {
        to: "/appointments",
        module: "clinic",
        label: "Appointments",
        icon: "appointment",
        needs: "encounter.read",
        scope: "own",
        keywords: ["booking", "diary", "schedule", "slot"],
      },
      {
        to: "/queue",
        module: "clinic",
        label: "Queue",
        icon: "queue",
        needs: "encounter.read",
        scope: "own",
        keywords: ["waiting", "token", "walk-in"],
      },
      {
        to: "/portal",
        module: "patient_portal",
        label: "Portal accounts",
        icon: "access",
        needs: "patient.read",
        scope: "facility",
        keywords: ["patient login", "app access"],
      },
    ],
  },
  {
    label: "Inpatient",
    icon: "ward",
    // **`patient.clinical.read` on the four clinical boards below, not
    // `encounter.read`.** The coarse permission is held by the receptionist --
    // correctly, for the outpatient queue and the appointment diary -- and it
    // was putting the critical-care record, the operating list, the
    // transfusion history and the nurse's bedside console in the front desk's
    // sidebar. The tier already existed (`docs/ACCESS_DESIGN.md`); the screens
    // had never moved onto it.
    //
    // Emergency and Wards deliberately stay on `encounter.read`: registering an
    // arrival and knowing which bed somebody is in are front-desk work.
    items: [
      {
        to: "/emergency",
        module: "hospital",
        label: "Emergency",
        icon: "emergency",
        needs: "encounter.read",
        scope: "own",
        keywords: ["ed", "casualty", "triage", "resus"],
      },
      {
        to: "/wards",
        module: "hospital",
        label: "Wards",
        icon: "ward",
        needs: "encounter.read",
        scope: "own",
        keywords: ["beds", "admission", "occupancy", "ipd"],
      },
      {
        to: "/nurse-workspace",
        module: "hospital",
        label: "Nurse workspace",
        icon: "nurse",
        needs: "patient.clinical.read",
        scope: "facility",
        keywords: ["rounds", "medication due", "observations", "handover"],
      },
      {
        to: "/icu",
        module: "hospital",
        label: "ICU",
        icon: "icu",
        needs: "patient.clinical.read",
        scope: "facility",
        keywords: ["critical care", "ventilator", "sofa", "flowsheet"],
      },
      {
        to: "/theatre",
        module: "hospital",
        label: "Theatre",
        icon: "theatre",
        needs: "patient.clinical.read",
        scope: "facility",
        keywords: ["ot", "surgery", "operating list", "anaesthesia"],
      },
    ],
  },
  {
    label: "Diagnostics",
    icon: "laboratory",
    items: [
      {
        to: "/diagnostics",
        module: "laboratory",
        label: "Laboratory",
        icon: "laboratory",
        needs: "encounter.read",
        scope: "own",
        keywords: ["lab", "lis", "radiology", "results", "specimen", "x-ray", "imaging", "radiology", "lab"],
      },
      {
        to: "/blood",
        module: "blood_bank",
        label: "Blood bank",
        icon: "bloodBank",
        needs: "patient.clinical.read",
        scope: "facility",
        keywords: ["transfusion", "crossmatch", "donor", "units"],
      },
      {
        to: "/referrals",
        label: "Referrals",
        icon: "referral",
        needs: "encounter.read",
        scope: "facility",
        keywords: ["refer out", "refer in", "transfer"],
      },
    ],
  },
  {
    label: "Supply",
    icon: "pharmacy",
    items: [
      {
        to: "/pharmacy",
        module: "pharmacy",
        label: "Pharmacy",
        icon: "pharmacy",
        needs: "stock.read",
        scope: "facility",
        keywords: ["dispense", "stock", "batch", "expiry", "fefo", "pharmacy", "stock"],
      },
      {
        to: "/counter",
        module: "pharmacy",
        label: "Counter",
        icon: "counter",
        needs: "sale.read",
        scope: "facility",
        keywords: ["pos", "till", "sale", "retail"],
      },
      {
        to: "/procurement",
        module: "procurement",
        label: "Procurement",
        icon: "procurement",
        needs: "purchase.read",
        scope: "facility",
        keywords: ["purchase order", "supplier", "grn", "receipt"],
      },
    ],
  },
  {
    label: "Money",
    icon: "finance",
    items: [
      {
        to: "/billing",
        label: "Billing",
        icon: "billing",
        needs: "invoice.read",
        scope: "facility",
        keywords: ["invoice", "charge", "receipt", "payment"],
      },
      {
        to: "/sales",
        module: "pharmacy",
        label: "Sales",
        icon: "trendUp",
        needs: "sale.read",
        alsoNeeds: "report.read",
        scope: "facility",
        keywords: ["revenue", "takings", "margin", "counter report", "top products", "esewa", "khalti"],
      },
      {
        to: "/claims",
        module: "insurance",
        label: "Claims",
        icon: "claim",
        needs: "invoice.read",
        scope: "facility",
        keywords: ["tpa", "payer", "denial", "pre-authorisation", "insurance"],
      },
      // `finance.read`, not `report.read`: every doctor holds the latter for
      // laboratory turnaround and theatre utilisation, and it used to put the
      // general ledger and the bank statements in their sidebar.
      {
        to: "/finance",
        module: "finance",
        label: "Finance",
        icon: "finance",
        needs: "finance.read",
        scope: "facility",
        keywords: ["ledger", "trial balance", "p&l", "bank", "vat"],
      },
      // What things cost, beside the screens that charge for them. Reading is
      // `invoice.read` because anybody raising an invoice needs to see prices;
      // changing them is a different permission the screen checks itself.
      {
        to: "/services",
        label: "Price list",
        icon: "price",
        needs: "invoice.read",
        scope: "facility",
        keywords: ["tariff", "price list", "charge master", "services", "prices", "tariff"],
      },
    ],
  },
  {
    label: "People",
    icon: "staff",
    items: [
      {
        to: "/people",
        module: "hrms",
        label: "Directory",
        icon: "directory",
        needs: "employee.read",
        scope: "own",
        keywords: ["employee", "hr", "staff list", "contract"],
      },
      // No `needs`: attendance and leave are self-service. The screen shows
      // you your own days and the facility's only if you hold
      // `attendance.read`, so gating the *link* on that permission hid the
      // screen from exactly the people with most reason to open it -- a
      // doctor, a counter assistant and a pharmacist all held none of it, and
      // all three had to request leave through somebody else.
      {
        to: "/time",
        module: "hrms",
        label: "Attendance",
        icon: "attendance",
        keywords: ["roster", "shift", "holiday", "clock in", "absence", "leave", "roster"],
      },
      {
        to: "/payroll",
        module: "payroll",
        label: "Payroll",
        icon: "payroll",
        needs: "salary.read",
        scope: "facility",
        keywords: ["salary", "payslip", "tax", "pf", "ssf"],
      },
    ],
  },
  {
    label: "Oversight",
    icon: "report",
    items: [
      {
        to: "/reports",
        label: "Reports",
        icon: "report",
        needs: "report.read",
        scope: "own",
        keywords: ["export", "analytics", "statement"],
      },
      {
        to: "/privacy",
        label: "Privacy",
        icon: "privacy",
        needs: "privacy.review",
        scope: "facility",
        keywords: ["break glass", "access review", "audit"],
      },
    ],
  },
  /*
   * **This group used to be eight items and is now two.**
   *
   * Configuration, Staff access, Roles, Plan and usage, Import records and
   * Change requests all moved behind the avatar (`UserMenu.tsx`, `/settings`).
   * They are things somebody opens twice a year, and they were sitting in the
   * rail at the same weight as the queue somebody opens forty times a day —
   * which is most of why a list of forty could not be scanned.
   *
   * What stayed is what a clinician or a manager genuinely reaches for during
   * the working day: which buildings exist, and which departments are in them.
   * The rest is administration, and administration is not the work.
   *
   * They are still routed and still in the command palette, so anybody who
   * knows the name reaches them in one keystroke from anywhere.
   */
  {
    label: "Organization",
    icon: "organization",
    items: [
      {
        to: "/facilities",
        label: "Facilities",
        icon: "facility",
        needs: "facility.read",
        scope: "facility",
        keywords: ["hospital", "clinic", "branch", "department"],
      },
    ],
  },
  {
    label: "Platform",
    icon: "platform",
    platformOnly: true,
    items: [
      {
        to: "/platform",
        label: "Console",
        icon: "platform",
        keywords: ["saas", "tenants", "customers", "mrr", "subscriptions"],
      },
    ],
  },
];

/* -------------------------------------------------------------------------- */
/* The administrative half                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Screens that live behind the avatar rather than in the rail.
 *
 * **They are here rather than nowhere because leaving the rail must not mean
 * leaving the product.** These six moved out of `NAV_GROUPS` so the rail could
 * be the work; if they had simply been deleted from the model, the command
 * palette — which is built from the same data — would have stopped finding
 * them, and "Configuration" would have become a screen you can only reach by
 * remembering it is under an avatar.
 *
 * So the rail renders `NAV_GROUPS`, the palette renders both, and `/settings`
 * is the browsable index of this list. One keystroke from anywhere, a menu for
 * anybody who prefers to point, and a hub for anybody who wants to look
 * around — which is three ways in for screens that previously had one.
 */
export const SYSTEM_ITEMS: NavItem[] = [
  {
    to: "/settings",
    label: "Settings",
    icon: "settings",
    keywords: ["preferences", "appearance", "colour", "theme", "admin", "system"],
  },
  // `subscription.read`, not `facility.read`: this screen is what the
  // hospital's *plan* allows and how much of it is spent — commercial
  // information that once inherited the permission every clinician holds for
  // knowing which facilities exist.
  {
    to: "/capacity",
    label: "Plan",
    icon: "capacity",
    needs: "subscription.read",
    scope: "organization",
    keywords: ["plan", "limit", "usage", "entitlement", "subscription", "billing", "plan", "usage", "billing plan"],
  },
  // `user.read` at `own`, because seeing your colleagues is not an
  // administrative act; inviting one is, and that is checked on POST.
  {
    to: "/staff",
    label: "Staff access",
    icon: "access",
    needs: "user.read",
    scope: "own",
    keywords: ["user", "invite", "sign in", "account", "deactivate"],
  },
  // `role.read`, derived from `RoleListView` rather than guessed. The first
  // version of this line said `user.read` — reasoned from what the screen
  // shows rather than from what it calls — and `tests/test_nav.py` caught it
  // on the first run.
  {
    to: "/access",
    label: "Roles",
    icon: "role",
    needs: "role.read",
    scope: "own",
    keywords: [
      "rbac", "permission", "matrix", "scope", "authority", "who can",
      "security", "segregation", "audit access", "permissions", "access control",
    ],
  },
  // Six rarely-visited lists behind one entry rather than six. Reading needs
  // `config.read`; each list checks its own write permission.
  {
    to: "/configuration",
    label: "Configuration",
    icon: "configuration",
    needs: "config.read",
    scope: "facility",
    keywords: ["settings", "master data", "reference", "setup", "payers", "tests"],
  },
  {
    to: "/facility-requests",
    label: "Change requests",
    icon: "changeRequest",
    needs: "facility.read",
    scope: "facility",
    keywords: ["approval", "amendment", "facility change"],
  },
  // `data.import` at organization scope — registering one patient at the
  // counter is a clerk's job, creating eight thousand from a spreadsheet is
  // not, and the mistake is a different size.
  {
    to: "/import",
    module: "api_access",
    label: "Data import",
    icon: "dataImport",
    needs: "data.import",
    scope: "organization",
    keywords: ["migration", "csv", "upload", "bulk", "spreadsheet", "import", "migrate", "upload"],
  },
];

/** Every item the product has, rail and system alike. */
export const ALL_NAV_ITEMS: NavItem[] = [
  ...NAV_GROUPS.flatMap((group) => group.items),
  ...SYSTEM_ITEMS,
];

/**
 * The groups this person can actually use.
 *
 * Filtered once and shared by the rail, the narrow strip and the palette, so
 * the three can never disagree about what exists. A group with nothing left in
 * it is dropped entirely.
 */
export function visibleGroups(
  can: (permission: string, scope?: string) => boolean,
  isPlatformStaff: boolean,
  {
    includeSystem = false,
    hasModule = () => true,
    isPlatformOnly = false,
  }: {
    includeSystem?: boolean;
    hasModule?: (module: string) => boolean;
    /** Platform staff who belong to no hospital. Their rail is the console
     *  and nothing else: a dashboard, a workspace and a self-service screen
     *  all read a tenant database they have no tenant in. */
    isPlatformOnly?: boolean;
  } = {},
): NavGroup[] {
  const groups = NAV_GROUPS.filter(
    (group) => (!group.platformOnly || isPlatformStaff)
      && (!isPlatformOnly || group.platformOnly),
  )
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => mayOpen(item, can, hasModule)),
    }))
    .filter((group) => group.items.length > 0);

  if (!includeSystem) return groups;

  // The palette passes `includeSystem` and the rail does not, which is the
  // whole split: one list, two audiences. Appended rather than merged into an
  // existing group so the palette can label them "System" and a reader can see
  // that these are not rail destinations.
  const system = isPlatformOnly
    ? []
    : SYSTEM_ITEMS.filter((item) => mayOpen(item, can, hasModule));
  return system.length > 0
    ? [...groups, { label: "System", icon: "settings" as const, items: system }]
    : groups;
}

/* -------------------------------------------------------------------------- */
/* Role homes                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Where "/" goes, when the user has expressed no preference.
 *
 * **Seventeen roles existed and every one of them landed on `/patients`.** A
 * pharmacist opening a patient list every morning, and a controller doing the
 * same, is the clearest possible statement that the product has no idea who
 * anybody is.
 *
 * Ordered by specificity — the first role a person holds that appears here
 * wins — so somebody who is both a doctor and a medical director lands on the
 * director's overview, which is the more distinctive of their two jobs.
 */
const ROLE_HOME: [role: string, path: string][] = [
  ["platform_staff", "/platform"],
  ["organization_admin", "/dashboard"],
  ["medical_director", "/dashboard"],
  ["operations_manager", "/dashboard"],
  ["facility_manager", "/dashboard"],
  ["financial_controller", "/finance"],
  ["accountant", "/billing"],
  ["hr_manager", "/people"],
  ["pharmacy_manager", "/pharmacy"],
  ["pharmacist", "/pharmacy"],
  ["pharmacy_counter", "/counter"],
  ["store_keeper", "/procurement"],
  ["lab_technician", "/diagnostics"],
  ["nurse", "/nurse-workspace"],
  // Their own day, not the organization's: a doctor's dashboard was a board
  // about the hospital when what they wanted was their clinic list.
  ["doctor", "/workspace"],
  ["receptionist", "/queue"],
  ["auditor", "/reports"],
];

/**
 * Resolve the landing screen.
 *
 * The stored preference wins over the role default, and the role default wins
 * over the old hardcoded `/patients`.
 *
 * **`landing` has been declared in `apps/identity/preferences.py`, offered as a
 * control on My account, saved to the user row, and read by nothing.** The
 * whole path existed except the last step: `App.tsx` computed its home as
 * `isPlatformOnly ? "/platform" : "/patients"` and never consulted it. So
 * anybody who set it watched their choice be stored and ignored, which is worse
 * than the preference not existing. This is the missing step.
 */
export function resolveHome({
  landing,
  roles,
  isPlatformOnly,
  can,
  hasModule = () => true,
}: {
  landing?: string;
  roles: string[];
  isPlatformOnly: boolean;
  can: (permission: string, scope?: string) => boolean;
  /** What the organization bought. Landing somebody on a screen their plan
   *  does not include would greet them with "not in your plan" every day. */
  hasModule?: (module: string) => boolean;
}): string {
  if (isPlatformOnly) return "/platform";

  if (landing && landing !== "auto") {
    const item = ALL_NAV_ITEMS.find((entry) => entry.to === landing);
    // A preference pointing at a screen this person can no longer open — their
    // role changed since they set it — falls through to the role default
    // rather than landing them on a permission error every morning.
    if (item && mayOpen(item, can, hasModule)) return landing;
  }

  for (const [role, path] of ROLE_HOME) {
    if (!roles.includes(role)) continue;
    const item = ALL_NAV_ITEMS.find((entry) => entry.to === path);
    if (!item || mayOpen(item, can, hasModule)) return path;
  }

  /*
    The fallback ladder, by permission rather than by role name.

    `/auth/me/` returns `authorization.permissions` and **not** the list of
    roles the person holds, so `ROLE_HOME` above only fires where a caller can
    supply names. Rather than leave everyone else on a generic screen, the same
    question is asked of the permissions themselves — which is in any case the
    more honest test, since a customer who has renamed `nurse` to `sister` or
    built a role of their own still lands somewhere useful.

    Ordered narrowest-job-first: the permissions that identify one desk come
    before the ones half the hospital holds.
  */
  const LADDER: [permission: string, scope: string | undefined, path: string][] = [
    ["sale.read", "facility", "/counter"],
    ["stock.read", "facility", "/pharmacy"],
    ["salary.read", "facility", "/payroll"],
    ["finance.read", "facility", "/finance"],
    ["patient.clinical.read", "facility", "/dashboard"],
    ["invoice.read", "facility", "/billing"],
    ["employee.read", "own", "/people"],
    ["encounter.read", "own", "/queue"],
    ["patient.read", "own", "/patients"],
  ];

  for (const [permission, scope, path] of LADDER) {
    if (can(permission, scope)) return path;
  }

  return "/dashboard";
}
