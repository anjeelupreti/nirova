/**
 * The account menu at the far right of the header: you, and nothing else.
 *
 * **It had grown into a second sidebar.** Profile, leave, password, five
 * administrative links, three appearance switches and a colour-scheme link
 * -- fourteen rows, most of them also somewhere else. People open this menu
 * for three reasons, the same three as in every product they already use:
 * to see who they are signed in as, to reach their profile or settings, and
 * to sign out. So that is what it holds. Everything that configures lives on
 * the Settings page, one section at a time.
 *
 * Radix's dropdown rather than a hand-rolled popover: focus returns to the
 * trigger on close, Escape and outside clicks dismiss, arrow keys move between
 * items, and the menu is announced as a menu.
 */

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Link } from "react-router-dom";

import { Avatar } from "@/components/ui/data";
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

const ITEM = cn(
  "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2 py-1.5",
  "text-sm outline-none transition-colors duration-quick",
  "focus:bg-accent focus:text-accent-foreground",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
);

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
        <span className="hidden max-w-[10rem] truncate text-sm sm:inline">{name}</span>
        <Icon name="chevronDown" size="xs" className="hidden text-muted-foreground sm:block" />
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
          <div className="flex items-center gap-2.5 px-2 py-2">
            <Avatar name={name || email || "?"} size="md" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{name}</p>
              <p className="truncate text-xs text-muted-foreground">{email}</p>
              {role ? <p className="mt-0.5 truncate text-xs text-primary-ink">{role}</p> : null}
            </div>
          </div>

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          <DropdownMenu.Item asChild>
            <Link to="/me" className={ITEM}>
              <Icon name="patientSingle" size="md" className="text-muted-foreground" />
              My profile
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link to="/settings" className={ITEM}>
              <Icon name="settings" size="md" className="text-muted-foreground" />
              Settings
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
