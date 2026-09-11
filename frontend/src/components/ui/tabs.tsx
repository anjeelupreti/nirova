/**
 * Tabs, once.
 *
 * **`@radix-ui/react-tabs` has been in `package.json` since the first commit
 * and imported by nothing.** Meanwhile seventeen screens each declared their
 * own `type Tab = "overview" | "directory" | …`, their own `const TABS` array,
 * their own `useState`, and their own strip of buttons with their own active
 * styling. Seventeen implementations of a control that was already paid for,
 * and no two of them agreed on the underline.
 *
 * Two things they all also got wrong, fixed here:
 *
 *  1. **Keyboard support.** A row of `<button onClick>` is not a tablist.
 *     Arrow keys did nothing, `Home`/`End` did nothing, and the active tab was
 *     not announced. Radix supplies all of it.
 *
 *  2. **A tab was not a location.** `?tab=` sync means "the claims screen,
 *     denials tab" is a link somebody can send to a colleague, and that going
 *     back returns you to the tab you were on rather than to the first one.
 *     On a screen that people live in all day, losing your tab on every back
 *     navigation is the difference between a tool and a website.
 */

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { useSearchParams } from "react-router-dom";

import { cn } from "@/lib/utils";
import { Icon, type IconName } from "@/components/ui/icon";

/* -------------------------------------------------------------------------- */
/* Primitives                                                                  */
/* -------------------------------------------------------------------------- */

export const Tabs = TabsPrimitive.Root;

export const TabList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      // Scrolls sideways rather than wrapping. A tab row that wraps to two
      // lines pushes the content down by a different amount on every screen
      // width, and the second line is where the tabs nobody finds live.
      "-mb-px flex items-center gap-1 overflow-x-auto border-b border-border",
      // The scrollbar is hidden but the overflow is not: a trackpad and a
      // touch screen both still scroll it, and on a desktop the last tab
      // being clipped is the affordance.
      "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
      className,
    )}
    {...props}
  />
));
TabList.displayName = "TabList";

export const Tab = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> & {
    icon?: IconName;
    /** A count beside the label — pending items, unread, rows. */
    count?: number | null;
  }
>(({ className, children, icon, count, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "group relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 pb-2.5 pt-2 text-sm font-medium",
      "text-muted-foreground transition-colors duration-quick ease-smooth",
      "hover:text-foreground",
      // The indicator is a pseudo-element on the trigger rather than a
      // separate sliding bar: it cannot desynchronise from the tab, and it
      // survives the list being scrolled.
      "after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent after:transition-colors after:duration-quick",
      "data-[state=active]:text-foreground data-[state=active]:after:bg-primary",
      "disabled:pointer-events-none disabled:opacity-50",
      className,
    )}
    {...props}
  >
    {icon ? <Icon name={icon} size="sm" /> : null}
    {children}
    {count != null ? (
      <span
        className={cn(
          "ml-0.5 rounded-full px-1.5 py-px text-[0.6875rem] font-semibold tabular-nums",
          "bg-muted text-muted-foreground",
          "group-data-[state=active]:bg-primary-subtle group-data-[state=active]:text-primary-subtle-foreground",
        )}
      >
        {count}
      </span>
    ) : null}
  </TabsPrimitive.Trigger>
));
Tab.displayName = "Tab";

export const TabPanel = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    // `focus-visible:outline-none` because the panel takes focus when a tab is
    // activated by keyboard, and a ring around the entire page body is noise —
    // the tab itself already shows where focus is.
    className={cn("pt-5 focus-visible:outline-none", className)}
    {...props}
  />
));
TabPanel.displayName = "TabPanel";

/* -------------------------------------------------------------------------- */
/* URL-synced tabs                                                             */
/* -------------------------------------------------------------------------- */

export interface TabSpec {
  id: string;
  label: React.ReactNode;
  icon?: IconName;
  count?: number | null;
  /** Hide the tab entirely — for one the viewer may not open. */
  hidden?: boolean;
  disabled?: boolean;
}

/**
 * The state hook the seventeen screens each wrote by hand, with the URL
 * attached.
 *
 * `param` is namespaced when a screen has two independent tab sets, which
 * three of them do — the alternative is both sets fighting over `?tab=`.
 *
 * **A tab id in the URL that no longer exists falls back to the first visible
 * tab rather than rendering nothing.** Bookmarks outlive tab names, and a
 * blank screen from a stale link is indistinguishable from a broken one.
 */
export function useTabState(
  tabs: TabSpec[],
  { param = "tab" }: { param?: string } = {},
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const visible = tabs.filter((tab) => !tab.hidden);
  const fallback = visible[0]?.id ?? "";

  const requested = searchParams.get(param);
  const value =
    requested && visible.some((tab) => tab.id === requested)
      ? requested
      : fallback;

  const onValueChange = React.useCallback(
    (next: string) => {
      setSearchParams(
        (current) => {
          const params = new URLSearchParams(current);
          // The default tab is left out of the URL. A link to the plain screen
          // should stay a link to the plain screen rather than growing a
          // `?tab=overview` that says nothing.
          if (next === fallback) params.delete(param);
          else params.set(param, next);
          return params;
        },
        // Replace, not push. Clicking through four tabs should not put four
        // entries in the history that the back button has to walk out of.
        { replace: true },
      );
    },
    [fallback, param, setSearchParams],
  );

  return { value, onValueChange, tabs: visible };
}

/**
 * The whole control, for the common case.
 *
 * ```tsx
 * <TabbedSection
 *   tabs={[{ id: "overview", label: "Overview", icon: "dashboard" },
 *          { id: "denials", label: "Denials", count: 12 }]}
 * >
 *   {{ overview: <Overview />, denials: <Denials /> }}
 * </TabbedSection>
 * ```
 *
 * Panels as a record keyed by tab id rather than as children, so a tab and its
 * panel cannot get out of order — which happened twice in the hand-rolled
 * versions and is invisible until somebody clicks the fourth tab.
 */
export function TabbedSection({
  tabs,
  children,
  param,
  className,
  trailing,
}: {
  tabs: TabSpec[];
  children: Record<string, React.ReactNode>;
  param?: string;
  className?: string;
  /** Controls that belong to the tab row itself, pinned to its right. */
  trailing?: React.ReactNode;
}) {
  const { value, onValueChange, tabs: visible } = useTabState(tabs, { param });

  return (
    <Tabs value={value} onValueChange={onValueChange} className={className}>
      <div className="flex items-end justify-between gap-4">
        <TabList className="min-w-0 flex-1">
          {visible.map((tab) => (
            <Tab
              key={tab.id}
              value={tab.id}
              icon={tab.icon}
              count={tab.count}
              disabled={tab.disabled}
            >
              {tab.label}
            </Tab>
          ))}
        </TabList>
        {trailing ? (
          <div className="flex shrink-0 items-center gap-2 pb-2">{trailing}</div>
        ) : null}
      </div>
      {visible.map((tab) => (
        <TabPanel key={tab.id} value={tab.id}>
          {children[tab.id] ?? null}
        </TabPanel>
      ))}
    </Tabs>
  );
}
