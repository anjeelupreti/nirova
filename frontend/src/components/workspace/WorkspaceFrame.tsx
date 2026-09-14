/**
 * The frame every persona's home sits in.
 *
 * **Distinct, but not different products.** The brief was that a doctor's
 * workspace, a nurse's and a patient's portal should not be the same screen
 * with different rows in it — and they should not. But five unrelated designs
 * is the other failure: a hospital buys one system, and an interface that
 * changes its rules between desks is one people have to re-learn at every
 * transfer.
 *
 * So the shape is constant and three things shift:
 *
 *  1. **The hero.** Each persona names the day in its own words — "My ward",
 *     "Front desk", "Cash position" — over a band tinted with that persona's
 *     accent. That is the strongest signal and it costs one gradient.
 *  2. **The accent.** Drawn from the validated eight-slot series ramp rather
 *     than from a new hue, so the colour-vision guarantees survive and the
 *     personas still read as one family.
 *  3. **What is on it.** A ward board is beds; a clinic is a list of people;
 *     a cash position is money moving. The composition differs because the
 *     work differs, which is the only honest reason for it to.
 *
 * What does *not* shift: the rail, the header, the palette, the type scale,
 * the status colours. A nurse who covers a shift at the front desk should find
 * the furniture where she left it.
 */

import * as React from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import { Icon, type IconName } from "@/components/ui/icon";
import { HeroArt } from "@/components/ui/HeroArt";
import { Spinner } from "@/components/ui/loader";
import { Freshness } from "@/components/ui/status";
import { personaAccent, type Persona } from "@/components/shell/personas";

/* -------------------------------------------------------------------------- */
/* The hero                                                                    */
/* -------------------------------------------------------------------------- */

export function WorkspaceHero({
  persona,
  name,
  context,
  asOf,
  actions,
  stats,
}: {
  persona: Persona;
  /** The person, not the product. "Good morning, Anjeela." */
  name?: string;
  /** Where they are: the ward, the facility, the shift. */
  context?: React.ReactNode;
  asOf?: Date | null;
  actions?: React.ReactNode;
  /** Two to four figures that belong to the *day*, not to a panel. */
  stats?: {
    label: string;
    value: React.ReactNode;
    tone?: "good" | "warning" | "critical";
    /** The list behind the figure. A number you cannot open is a poster. */
    to?: string;
    /** Shown in a tinted tile beside the figure. */
    icon?: IconName;
  }[];
}) {
  const accent = personaAccent(persona);

  return (
    <header
      className="relative overflow-hidden rounded-xl border bg-card shadow-raised"
      // The accent as a CSS variable on the element, so the band, the icon
      // tile and the rule beneath all read from one value rather than three
      // copies that can drift.
      style={{ ["--persona" as string]: accent }}
    >
      {/* A wash rather than a solid fill. A saturated band at the top of every
          screen is a 2011 dashboard; a 6% wash reads as a surface with a
          temperature, which is what distinguishes the personas without
          shouting. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(120deg, color-mix(in srgb, var(--persona) 10%, transparent), transparent 55%)",
        }}
      />
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-0.5"
        style={{ background: "var(--persona)" }}
      />

      <div className="relative flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="flex min-w-0 items-start gap-3.5">
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg"
            style={{
              background: "color-mix(in srgb, var(--persona) 16%, transparent)",
              color: "var(--persona)",
            }}
          >
            <Icon name={persona.icon} size="lg" />
          </span>
          <div className="min-w-0">
            <p className="type-eyebrow" style={{ color: "var(--persona)" }}>
              {persona.label}
            </p>
            <h1 className="mt-1 type-title">
              {name ? `${greeting()}, ${name}` : persona.blurb}
            </h1>
            <p className="mt-0.5 type-caption">
              {context ?? persona.blurb}
            </p>
          </div>
        </div>

        <HeroArt className="hidden shrink-0 self-center lg:block" />

        <div className="flex shrink-0 flex-col items-end gap-2">
          {actions ? (
            <div className="flex flex-wrap items-center gap-2">{actions}</div>
          ) : null}
          {asOf !== undefined ? <Freshness at={asOf ?? null} /> : null}
        </div>
      </div>

      {stats && stats.length > 0 ? (
        <div className="relative grid divide-x divide-border border-t sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => {
            const body = (
              <div className="flex items-center gap-3">
                {stat.icon ? (
                  <span
                    className={cn(
                      "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
                      stat.tone === "critical"
                        ? "bg-critical-subtle text-critical-subtle-foreground"
                        : stat.tone === "warning"
                          ? "bg-warning-subtle text-warning-subtle-foreground"
                          : stat.tone === "good"
                            ? "bg-good-subtle text-good-subtle-foreground"
                            : "bg-primary-subtle text-primary-subtle-foreground",
                    )}
                  >
                    <Icon name={stat.icon} size="md" />
                  </span>
                ) : null}
                <div className="min-w-0">
                  <p className="flex items-center gap-1 type-label text-muted-foreground">
                    {stat.label}
                    {stat.to ? <Icon name="chevronRight" size="xs" className="opacity-60" /> : null}
                  </p>
                  <p
                    className={cn(
                      "mt-0.5 text-xl font-semibold tabular-nums",
                      stat.tone === "good" && "text-good",
                      stat.tone === "warning" && "text-warning",
                      stat.tone === "critical" && "text-critical",
                    )}
                  >
                    {stat.value}
                  </p>
                </div>
              </div>
            );
            return stat.to ? (
              <Link
                key={stat.label}
                to={stat.to}
                className="block px-5 py-3 transition-colors duration-quick hover:bg-accent/40"
              >
                {body}
              </Link>
            ) : (
              <div key={stat.label} className="px-5 py-3">
                {body}
              </div>
            );
          })}
        </div>
      ) : null}
    </header>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 5) return "Still here";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/* -------------------------------------------------------------------------- */
/* Panels                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * One panel on a workspace.
 *
 * Every one declares where it goes when pressed. **A figure you cannot act on
 * is a poster**, and a workspace made entirely of posters is what the previous
 * dashboard was.
 */
export function WorkspacePanel({
  title,
  description,
  icon,
  to,
  toLabel,
  span = 1,
  actions,
  children,
}: {
  title: string;
  description?: string;
  icon?: IconName;
  to?: string;
  toLabel?: string;
  span?: 1 | 2 | 3;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col rounded-xl border border-border/60 bg-card shadow-raised",
        span === 2 && "lg:col-span-2",
        span === 3 && "lg:col-span-3",
      )}
    >
      <div className="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {icon ? <Icon name={icon} size="md" className="text-muted-foreground" /> : null}
          <div className="min-w-0">
            <h2 className="type-heading">{title}</h2>
            {description ? <p className="type-caption">{description}</p> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {actions}
          {to ? (
            <Link
              to={to}
              className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-muted-foreground transition-colors duration-quick hover:bg-accent hover:text-foreground"
            >
              {toLabel ?? "Open"}
              <Icon name="chevronRight" size="xs" />
            </Link>
          ) : null}
        </div>
      </div>
      <div className="flex-1 p-4">{children}</div>
    </section>
  );
}

/**
 * A panel that could not read its source.
 *
 * **Never a zero.** The most dangerous thing a clinical dashboard can do is
 * render an empty state after a failed request: "0 medications due" and "we
 * could not ask" look identical and are not remotely the same claim.
 */
export function PanelProblem({ error }: { error: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-dashed border-serious/40 bg-serious-subtle/40 p-3">
      <Icon name="warning" size="md" className="mt-px text-serious" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-serious-subtle-foreground">
          Not read — this is not a zero
        </p>
        <p className="mt-0.5 type-caption">{error}</p>
      </div>
    </div>
  );
}

export function PanelLoading({ height = 130 }: { height?: number }) {
  return (
    <div
      className="flex items-center justify-center gap-2 type-caption"
      style={{ height }}
    >
      <Spinner size="xs" /> Reading…
    </div>
  );
}

export function PanelEmpty({
  message,
  icon = "success",
}: {
  message: string;
  icon?: IconName;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      <Icon name={icon} size="lg" className="text-muted-foreground/50" />
      <p className="max-w-xs type-caption">{message}</p>
    </div>
  );
}

/**
 * A row in a worklist: something waiting, with how long it has waited.
 *
 * The unit every clinical workspace is built from — a patient to see, a result
 * to acknowledge, a medication due. **How long it has been waiting, not when
 * it arrived**: "waiting 40 minutes" is the number somebody acts on, and a
 * timestamp is one they have to do arithmetic on first.
 */
export function WorklistRow({
  leading,
  title,
  detail,
  meta,
  trailing,
  tone,
  to,
}: {
  leading?: React.ReactNode;
  title: React.ReactNode;
  detail?: React.ReactNode;
  meta?: React.ReactNode;
  trailing?: React.ReactNode;
  tone?: "critical" | "warning" | "good";
  to?: string;
}) {
  const body = (
    <>
      {/* A spine rather than a tinted row. Twelve tinted rows is a stained
          glass window and the names stop being readable on top of it. */}
      {tone ? (
        <span
          aria-hidden
          className={cn(
            "absolute inset-y-1 left-0 w-[3px] rounded-full",
            tone === "critical" && "bg-critical",
            tone === "warning" && "bg-warning",
            tone === "good" && "bg-good",
          )}
        />
      ) : null}
      {leading}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{title}</span>
        {detail ? (
          <span className="block truncate type-caption">{detail}</span>
        ) : null}
      </span>
      {meta ? (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {meta}
        </span>
      ) : null}
      {trailing}
    </>
  );

  const className = cn(
    "relative flex items-center gap-2.5 rounded-md py-2 pl-3 pr-2 text-left",
    to && "transition-colors duration-quick hover:bg-accent/50",
  );

  return to ? (
    <Link to={to} className={className}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

/** How long something has been waiting, in the units a person thinks in. */
export function waitedFor(since: string | Date | null | undefined): string {
  if (!since) return "—";
  const started = typeof since === "string" ? new Date(since) : since;
  const minutes = Math.floor((Date.now() - started.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours}h ${minutes % 60}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}
