/**
 * Settings — reached from the avatar, not from the sidebar.
 *
 * **The navigation was wrong and this is the correction.** Everything in this
 * product started from the rail, so the rail carried forty entries and six of
 * them were things a person opens twice a year: Configuration, Change
 * requests, Import records, Capacity, Staff access, Roles. They sat in the
 * same list, at the same weight, as the queue somebody opens forty times a
 * day.
 *
 * Every mature product of this shape splits the two. The rail is **the work**:
 * patients, wards, dispensing, billing. The avatar menu is **the system**:
 * who you are, who else there is, how the organization is configured, what the
 * subscription allows. Gmail, Stripe, Linear, Slack, GitHub — all of them put
 * account and workspace administration behind the identity control, and they
 * do it because the two are used on completely different rhythms.
 *
 * So this is a hub, not a screen. Sections are gated on the permission that
 * governs each destination, and a section nobody in the room can open is not
 * rendered — rather than rendered and refused, which is what the rail used to
 * do.
 */

import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import { useCan } from "@/components/ui/can";
import { Icon, type IconName } from "@/components/ui/icon";
import { Page, PageHeader, Section } from "@/components/ui/layout";
import { useSession } from "@/hooks/useSession";
import { PALETTES, usePreferences, type Palette } from "@/hooks/usePreferences";

/* -------------------------------------------------------------------------- */
/* The map                                                                     */
/* -------------------------------------------------------------------------- */

interface SettingsLink {
  to: string;
  label: string;
  description: string;
  icon: IconName;
  needs?: string;
  scope?: string;
}

interface SettingsGroup {
  label: string;
  description: string;
  items: SettingsLink[];
}

const GROUPS: SettingsGroup[] = [
  {
    label: "You",
    description: "Things that follow you between machines and organizations.",
    items: [
      {
        to: "/account",
        label: "Profile and preferences",
        description:
          "Your name, your password, appearance, density, and which screen you land on.",
        icon: "settings",
      },
      {
        to: "/self-service",
        label: "Self service",
        description: "Your payslips, your leave, your attendance, your documents.",
        icon: "verifiedPerson",
      },
      {
        to: "/notifications",
        label: "Notifications",
        description: "What the system tells you about, and how.",
        icon: "notification",
      },
    ],
  },
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

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function SettingsPage() {
  const can = useCan();
  const { session } = useSession();

  const visible = GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.needs || can(item.needs, item.scope)),
  })).filter((group) => group.items.length > 0);

  return (
    <Page>
      <PageHeader
        title="Settings"
        description={
          session?.organization
            ? `${session.organization.display_name} — everything about the system rather than about the work.`
            : "Everything about the system rather than about the work."
        }
        breadcrumbs={[{ label: "Settings" }]}
      />

      <AppearanceCard />

      {visible.map((group) => (
        <Section
          key={group.label}
          title={group.label}
          description={group.description}
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {group.items.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "group flex gap-3 rounded-lg border bg-card p-4 shadow-raised",
                  "transition-colors duration-quick ease-smooth",
                  "hover:border-border-strong hover:bg-accent/40",
                )}
              >
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-foreground">
                  <Icon name={item.icon} size="md" />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1 text-sm font-medium">
                    {item.label}
                    <Icon
                      name="chevronRight"
                      size="xs"
                      className="text-muted-foreground opacity-0 transition-opacity duration-quick group-hover:opacity-100"
                    />
                  </span>
                  <span className="mt-0.5 block type-caption">
                    {item.description}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </Section>
      ))}
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* Appearance                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The palette picker, on the settings hub rather than buried in Account.
 *
 * **It is here because the answer to "I do not like the colours" should be
 * five seconds, not a release.** The console shipped with one palette I chose,
 * and choosing again would have been the same mistake in a different hue.
 *
 * Each swatch previews the real thing: the actual `--brand-*` and `--accent-*`
 * values of that palette, read straight from the stylesheet. A picker that
 * shows approximations is a picker that lies.
 */
function AppearanceCard() {
  const { preferences, update } = usePreferences();

  return (
    <Section
      title="Appearance"
      description="Applies immediately, and follows you to any machine you sign in on. Every combination in every palette is contrast-checked in both light and dark."
    >
      <div className="rounded-lg border bg-card p-4 shadow-raised">
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {PALETTES.map((palette) => (
            <PaletteSwatch
              key={palette.value}
              palette={palette}
              selected={preferences.palette === palette.value}
              onSelect={() => update({ palette: palette.value })}
            />
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 border-t pt-4">
          <ModeToggle />
          <DensityToggle />
        </div>
      </div>
    </Section>
  );
}

function PaletteSwatch({
  palette,
  selected,
  onSelect,
}: {
  palette: { value: Palette; label: string; blurb: string };
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      // `data-palette` on the button itself, so the swatch resolves the tokens
      // of the palette it *represents* rather than the one currently applied.
      // Without this every swatch previews the active theme and the picker
      // shows five identical cards.
      data-palette={palette.value}
      className={cn(
        "group flex flex-col gap-2.5 rounded-lg border p-3 text-left transition-all duration-quick ease-smooth",
        selected
          ? "border-primary ring-2 ring-primary/30"
          : "border-border hover:border-border-strong",
      )}
    >
      <span className="flex h-10 overflow-hidden rounded-md">
        {/* Brand ramp, then the second hue. Five stops rather than one, because
            a single chip cannot show whether a palette has any range. */}
        <span className="flex-[2]" style={{ background: "hsl(var(--brand-primary))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--brand-300))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--brand-700))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--accent-500))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--neutral-200))" }} />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          {palette.label}
          {selected ? (
            <Icon name="confirm" size="xs" className="text-primary" />
          ) : null}
        </span>
        <span className="mt-0.5 block truncate type-caption">{palette.blurb}</span>
      </span>
    </button>
  );
}

function ModeToggle() {
  const { preferences, update } = usePreferences();
  const options = [
    { value: "system", label: "Match device", icon: "meter" as IconName },
    { value: "light", label: "Light", icon: "themeLight" as IconName },
    { value: "dark", label: "Dark", icon: "themeDark" as IconName },
  ] as const;

  return (
    <div className="flex items-center gap-2.5">
      <span className="type-label text-muted-foreground">Mode</span>
      <div className="inline-flex rounded-lg bg-muted p-1">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => update({ theme: option.value })}
            aria-pressed={preferences.theme === option.value}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-quick",
              preferences.theme === option.value
                ? "bg-card text-foreground shadow-raised"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon name={option.icon} size="xs" />
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function DensityToggle() {
  const { preferences, update } = usePreferences();

  return (
    <div className="flex items-center gap-2.5">
      <span className="type-label text-muted-foreground">Row height</span>
      <div className="inline-flex rounded-lg bg-muted p-1">
        {(["comfortable", "compact"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => update({ density: value })}
            aria-pressed={preferences.density === value}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors duration-quick",
              preferences.density === value
                ? "bg-card text-foreground shadow-raised"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}
