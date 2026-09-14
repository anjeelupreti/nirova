/**
 * The account menu at the far right of the header.
 *
 * **This is now the door to the whole administrative half of the product**, not
 * just to your own account — which is the correction to "everything starts
 * from sidebar menus".
 *
 * The rail carried forty entries because everything lived in it, including six
 * things a person opens twice a year: Configuration, Change requests, Import
 * records, Plan and usage, Staff access, Roles. They sat at the same weight as
 * the queue somebody opens forty times a day, and the result was a list nobody
 * could scan.
 *
 * Every mature product of this shape splits the two, and splits them the same
 * way: the rail is **the work**, the identity control is **the system**. Gmail,
 * Stripe, Linear, Slack, GitHub, Notion — account and workspace administration
 * all live behind the avatar, because the two are used on completely different
 * rhythms and mixing them costs the frequent one its legibility.
 *
 * Radix's dropdown rather than a hand-rolled popover, because the parts that
 * are tedious to get right are the parts people notice when they are wrong:
 * focus returns to the trigger on close, Escape and outside clicks dismiss,
 * arrow keys move between items, and the menu is announced as a menu.
 */

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Link } from "react-router-dom";

import { Avatar } from "@/components/ui/data";
import { Icon, type IconName } from "@/components/ui/icon";
import { useCan } from "@/components/ui/can";
import { usePreferences, type Theme } from "@/hooks/usePreferences";
import { useSession } from "@/hooks/useSession";
import { visibleSettingsGroups } from "@/components/shell/settingsMap";
import { cn } from "@/lib/utils";

const THEMES: { value: Theme; label: string; icon: IconName }[] = [
  { value: "system", label: "Match my device", icon: "meter" },
  { value: "light", label: "Light", icon: "themeLight" },
  { value: "dark", label: "Dark", icon: "themeDark" },
];

/**
 * The administrative destinations, gated by the permission that governs each.
 *
 * A menu item somebody cannot open is worse here than in the rail: the rail at
 * least looked like a directory, whereas a menu of five things where two are
 * refused reads as a broken product.
 */
const SYSTEM_LINKS: {
  to: string;
  label: string;
  icon: IconName;
  needs?: string;
  scope?: string;
}[] = [
  {
    to: "/staff",
    label: "Staff access",
    icon: "access",
    needs: "user.read",
    scope: "own",
  },
  {
    to: "/access",
    label: "Roles",
    icon: "role",
    needs: "role.read",
    scope: "own",
  },
  {
    to: "/configuration",
    label: "Configuration",
    icon: "configuration",
    needs: "config.read",
    scope: "facility",
  },
  {
    to: "/capacity",
    label: "Subscription",
    icon: "capacity",
    needs: "subscription.read",
    scope: "organization",
  },
];

const ITEM = cn(
  "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2 py-1.5",
  "text-sm outline-none transition-colors duration-quick",
  "focus:bg-accent focus:text-accent-foreground",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
);

const LABEL = "px-2 pb-1 pt-1.5 type-eyebrow text-muted-foreground";

export default function UserMenu({
  name,
  email,
  role,
  onSignOut,
}: {
  name: string;
  email: string;
  /** What this person is here, shown under their name. */
  role?: string | null;
  onSignOut: () => void;
}) {
  const { preferences, update } = usePreferences();
  const can = useCan();

  const { hasModule } = useSession();
  // Settings is offered only when it holds something this person may open.
  // Everything about *you* moved to /me, so for most clinical roles the
  // organization hub would be an empty page behind a menu item.
  const settings =
    visibleSettingsGroups(can).length > 0
      ? [{ to: "/settings", label: "Settings", icon: "settings" as IconName }]
      : [];
  const links = [
    ...settings,
    ...SYSTEM_LINKS.filter((link) => !link.needs || can(link.needs, link.scope)),
  ];

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label="Account and settings"
        className={cn(
          "flex items-center gap-2 rounded-full p-0.5",
          "outline-none transition-shadow",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          "data-[state=open]:ring-2 data-[state=open]:ring-ring",
        )}
      >
        <Avatar name={name || email || "?"} size="sm" />
        <span className="hidden max-w-[10rem] truncate text-sm sm:inline">
          {name}
        </span>
        <Icon
          name="chevronDown"
          size="xs"
          className="hidden text-muted-foreground sm:block"
        />
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className={cn(
            "z-50 w-64 rounded-lg border bg-popover p-1.5 shadow-floating",
            "animate-in fade-in-0 zoom-in-95 duration-quick",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
            "data-[side=bottom]:slide-in-from-top-1",
          )}
        >
          {/* The identity block is itself the way to the profile: it is
              what people click first, in every product they already use. */}
          <DropdownMenu.Item asChild>
            <Link
              to="/me"
              className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 outline-none focus:bg-accent"
            >
              <Avatar name={name || email || "?"} size="md" />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{name}</p>
                <p className="truncate text-xs text-muted-foreground">{email}</p>
                {role ? (
                  <p className="mt-0.5 truncate text-xs text-primary-ink">{role}</p>
                ) : null}
              </div>
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          <DropdownMenu.Item asChild>
            <Link to="/me" className={ITEM}>
              <Icon name="patientSingle" size="md" className="text-muted-foreground" />
              My profile
            </Link>
          </DropdownMenu.Item>
          {hasModule("hrms") ? (
            <DropdownMenu.Item asChild>
              <Link to="/me?tab=leave" className={ITEM}>
                <Icon name="appointment" size="md" className="text-muted-foreground" />
                Leave &amp; payslips
              </Link>
            </DropdownMenu.Item>
          ) : null}
          <DropdownMenu.Item asChild>
            <Link to="/me?tab=security" className={ITEM}>
              <Icon name="access" size="md" className="text-muted-foreground" />
              Password &amp; sign-in
            </Link>
          </DropdownMenu.Item>

          {links.length > 0 ? (
            <>
              <DropdownMenu.Separator className="my-1.5 h-px bg-border" />
              <DropdownMenu.Label className={LABEL}>System</DropdownMenu.Label>
              {links.map((link) => (
                <DropdownMenu.Item key={link.to} asChild>
                  <Link to={link.to} className={ITEM}>
                    <Icon
                      name={link.icon}
                      size="md"
                      className="text-muted-foreground"
                    />
                    {link.label}
                  </Link>
                </DropdownMenu.Item>
              ))}
            </>
          ) : null}

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          {/* The mode is here as well as in Settings, deliberately. It is the
              one preference people change *because of the room they are in*,
              and making them navigate to a page to do it means they will not.
              The full palette picker stays on Settings — it is a decision
              somebody makes once, not a light switch. */}
          <DropdownMenu.Label className={LABEL}>Appearance</DropdownMenu.Label>

          {THEMES.map((theme) => (
            <DropdownMenu.Item
              key={theme.value}
              className={ITEM}
              onSelect={(event) => {
                // Kept open, so somebody comparing light against dark can try
                // both without reopening the menu between them.
                event.preventDefault();
                update({ theme: theme.value });
              }}
            >
              <Icon name={theme.icon} size="md" className="text-muted-foreground" />
              <span className="flex-1">{theme.label}</span>
              {preferences.theme === theme.value && (
                <Icon name="confirm" size="sm" className="text-primary" />
              )}
            </DropdownMenu.Item>
          ))}

          <DropdownMenu.Item asChild>
            <Link to="/me?tab=preferences" className={cn(ITEM, "text-muted-foreground")}>
              <Icon name="spark" size="md" />
              Colours and preferences…
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          <DropdownMenu.Item
            className={cn(ITEM, "text-destructive focus:bg-destructive/10")}
            onSelect={onSignOut}
          >
            <Icon name="signOut" size="md" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
