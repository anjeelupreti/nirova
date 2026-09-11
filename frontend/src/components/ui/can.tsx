/**
 * "May this person do this?", asked the same way everywhere.
 *
 * **`useSession` has exposed `can(permission, scope)` since it was written and
 * six of forty-four screens call it.** Every other screen offers every control
 * to everybody and leaves the API to refuse — so a receptionist sees "Approve
 * payroll", presses it, and gets a 403 dialog. The permission was always
 * enforced; what was missing was any reason for the button to be there.
 *
 * This is deliberately a *courtesy*, not a control. The API refuses on its own
 * and that refusal is the guard. Hiding a control here only stops people being
 * offered doors that do not open for them.
 *
 * **The failure mode to fear is the opposite one.** Hiding a control from
 * somebody who *is* permitted is worse than showing one that 403s: the 403 is
 * annoying and legible, whereas a missing button is invisible and gets
 * reported as "the system cannot do that". So the default when a permission
 * cannot be resolved is to **show**, and `mode="disable"` exists for the cases
 * where the control's absence would itself be confusing.
 */

import * as React from "react";

import { useSession } from "@/hooks/useSession";
import { cn } from "@/lib/utils";

export interface CanProps {
  /** A permission code, e.g. `invoice.write`. */
  permission: string;
  /**
   * The scope the action needs. Defaults to `own` — "do they hold it at all" —
   * which matches `useSession.can` and is the right question for most
   * screen-level controls.
   */
  scope?: string;
  /**
   * `hide` removes the control. `disable` renders it greyed with a reason on
   * hover — right when its absence would read as a missing feature rather than
   * as a permission, such as the only action on an otherwise empty panel.
   */
  mode?: "hide" | "disable";
  /** Shown instead, when hiding. Usually nothing. */
  fallback?: React.ReactNode;
  /** Explains the disabled state. Ignored when hiding. */
  reason?: string;
  children: React.ReactNode;
}

export function Can({
  permission,
  scope,
  mode = "hide",
  fallback = null,
  reason,
  children,
}: CanProps) {
  const { can } = useSession();
  const allowed = can(permission, scope);

  if (allowed) return <>{children}</>;
  if (mode === "hide") return <>{fallback}</>;

  return (
    <span
      // `aria-disabled` on the wrapper and `pointer-events-none` inside: the
      // control keeps its place in the tab order so a screen-reader user is
      // told it exists and is unavailable, rather than it silently not being
      // there. `title` carries the reason to a mouse.
      aria-disabled
      title={reason ?? "You do not have permission for this"}
      className="inline-flex cursor-not-allowed opacity-50"
    >
      <span className="pointer-events-none contents">{children}</span>
    </span>
  );
}

/**
 * The same question, as a value.
 *
 * For the cases a wrapper cannot express — a column that should not exist, a
 * form field that must not be submitted, a tab to leave out of the array.
 */
export function useCan() {
  const { can } = useSession();
  return can;
}

/**
 * A whole screen behind a permission.
 *
 * The sidebar already hides links somebody cannot use, but a bookmark, a
 * pasted URL and the back button all reach a route directly. Without this the
 * screen mounts, fires its requests, collects a fistful of 403s and renders a
 * page of error alerts — which looks like an outage rather than like a closed
 * door.
 */
export function RequirePermission({
  permission,
  scope,
  children,
  title = "You do not have access to this screen",
  description = "Ask an administrator if you need it. Nothing is broken — this screen is simply not part of your role.",
}: {
  permission: string;
  scope?: string;
  children: React.ReactNode;
  title?: string;
  description?: string;
}) {
  const { can } = useSession();

  if (can(permission, scope)) return <>{children}</>;

  return (
    <div
      className={cn(
        "mx-auto flex max-w-md flex-col items-center gap-2 rounded-xl border border-dashed bg-card px-6 py-16 text-center",
      )}
    >
      <p className="type-heading">{title}</p>
      <p className="type-caption">{description}</p>
    </div>
  );
}
