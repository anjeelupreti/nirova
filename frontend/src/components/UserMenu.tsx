/**
 * The account menu at the far right of the header.
 *
 * Where every product of this kind puts it, and this one had nothing: a name
 * in grey text and a Sign out button, with no route to your own settings at
 * all. An avatar that opens onto the things about *you* — as distinct from the
 * organization switcher a few centimetres to its left, which is about your
 * employer.
 *
 * Radix's dropdown rather than a hand-rolled popover, because the parts that
 * are tedious to get right are the parts people notice when they are wrong:
 * focus returns to the trigger on close, Escape and outside clicks dismiss,
 * arrow keys move between items, and the menu is announced to a screen reader
 * as a menu. `@radix-ui/react-dropdown-menu` was already a dependency and had
 * never been used.
 */

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, LogOut, Monitor, Moon, Sun, UserCog } from "lucide-react";
import { Link } from "react-router-dom";

import { Avatar } from "@/components/ui/data";
import { usePreferences, type Theme } from "@/hooks/usePreferences";
import { cn } from "@/lib/utils";

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "Match my device", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

const ITEM = cn(
  "flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5",
  "text-sm outline-none transition-colors",
  "focus:bg-accent focus:text-accent-foreground",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
);

export default function UserMenu({
  name,
  email,
  onSignOut,
}: {
  name: string;
  email: string;
  onSignOut: () => void;
}) {
  const { preferences, update } = usePreferences();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label="Account"
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
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className={cn(
            "z-50 w-60 rounded-lg border bg-card p-1.5 shadow-lg",
            // Radix sets data-state and data-side; these are the animations
            // tailwindcss-animate exists for and which nothing in this
            // console was using.
            "animate-in fade-in-0 zoom-in-95 duration-150",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
            "data-[side=bottom]:slide-in-from-top-1",
          )}
        >
          <div className="px-2 py-1.5">
            <p className="truncate text-sm font-medium">{name}</p>
            <p className="truncate text-xs text-muted-foreground">{email}</p>
          </div>

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          <DropdownMenu.Item asChild>
            <Link to="/account" className={ITEM}>
              <UserCog className="h-4 w-4 text-muted-foreground" />
              My account
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          {/* The theme is here as well as on the account screen, deliberately.
              It is the one preference people change often and change *because
              of the room they are in*, so making them navigate to a settings
              page to do it would mean they simply would not. */}
          <DropdownMenu.Label className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Appearance
          </DropdownMenu.Label>

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
              <theme.icon className="h-4 w-4 text-muted-foreground" />
              <span className="flex-1">{theme.label}</span>
              {preferences.theme === theme.value && (
                <Check className="h-4 w-4 text-primary" />
              )}
            </DropdownMenu.Item>
          ))}

          <DropdownMenu.Separator className="my-1.5 h-px bg-border" />

          <DropdownMenu.Item
            className={cn(ITEM, "text-destructive focus:bg-destructive/10")}
            onSelect={onSignOut}
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
