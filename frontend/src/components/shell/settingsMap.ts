/**
 * The organization's settings, as a map: what exists and who may open each.
 *
 * Out of `pages/Settings.tsx` so the account menu can ask the same question
 * the hub does -- "is there anything here for this person?" -- instead of
 * offering a Settings link that opens onto an empty page.
 *
 * **Nothing about you is in here.** Profile, password, appearance, leave and
 * payslips are one place, `/me`. The hub used to list them as a "You" group
 * as well, which made two roads to the same room and a reader wondering
 * whether they led to the same one.
 */

import type { IconName } from "@/components/ui/icon";

export interface SettingsLink {
  to: string;
  label: string;
  description: string;
  icon: IconName;
  needs?: string;
  scope?: string;
}

export interface SettingsGroup {
  label: string;
  description: string;
  items: SettingsLink[];
}

export const SETTINGS_GROUPS: SettingsGroup[] = [
  {
    label: "People and access",
    description:
      "Who can sign in, what each role carries, and how far it reaches.",
    items: [
      {
        to: "/staff",
        label: "Staff access",
        description:
          "Invite a colleague, change their details, grant or revoke a role.",
        icon: "access",
        needs: "user.read",
        scope: "own",
      },
      {
        to: "/access",
        label: "Roles and permissions",
        description:
          "What each role carries, who holds it, and the scope it reaches. The permission matrix lives here.",
        icon: "role",
        needs: "role.read",
        scope: "own",
      },
      {
        to: "/people",
        label: "Employee directory",
        description:
          "The workforce, their positions, credentials and history. Distinct from who can sign in.",
        icon: "directory",
        needs: "employee.read",
        scope: "own",
      },
      {
        to: "/privacy",
        label: "Privacy and break-glass",
        description:
          "Emergency access that was taken, and the queue of it waiting to be reviewed.",
        icon: "privacy",
        needs: "privacy.review",
        scope: "facility",
      },
    ],
  },
  {
    label: "Organization",
    description: "The shape of the business: buildings, departments, reference data.",
    items: [
      {
        to: "/facilities",
        label: "Facilities and departments",
        description:
          "Buildings, their licences, operating hours and departments.",
        icon: "facility",
        needs: "facility.read",
        scope: "facility",
      },
      {
        to: "/configuration",
        label: "Configuration",
        description:
          "Payers, scheme packages, stock locations, theatres, diagnostic tests, referral providers.",
        icon: "configuration",
        needs: "config.read",
        scope: "facility",
      },
      {
        to: "/services",
        label: "Services and prices",
        description: "What things cost, and the price lists that override the default.",
        icon: "price",
        needs: "invoice.read",
        scope: "facility",
      },
      {
        to: "/facility-requests",
        label: "Change requests",
        description: "Amendments to a facility, and the queue approving them.",
        icon: "changeRequest",
        needs: "facility.read",
        scope: "facility",
      },
    ],
  },
  {
    label: "Plan and data",
    description: "What the subscription allows, and getting records in and out.",
    items: [
      {
        to: "/capacity",
        label: "Plan and usage",
        description:
          "What the subscription includes, the limits on it, and how much of each is spent.",
        icon: "capacity",
        needs: "subscription.read",
        scope: "organization",
      },
      {
        to: "/import",
        label: "Import records",
        description:
          "Bring patients, staff or stock in from a spreadsheet. Rare, administrative, done once.",
        icon: "dataImport",
        needs: "data.import",
        scope: "organization",
      },
      {
        to: "/reports",
        label: "Reports",
        description: "The report library, and everything exportable from it.",
        icon: "report",
        needs: "report.read",
        scope: "own",
      },
    ],
  },
];

/** The groups this person can open at least one item of. */
export function visibleSettingsGroups(
  can: (permission: string, scope?: string) => boolean,
): SettingsGroup[] {
  return SETTINGS_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.needs || can(item.needs, item.scope)),
  })).filter((group) => group.items.length > 0);
}
