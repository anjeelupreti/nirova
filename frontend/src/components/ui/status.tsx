/**
 * State, shown the same way everywhere.
 *
 * **This component is what makes the clinical colour tokens actually get
 * used.** Defining `--stock-expiring` achieves nothing if a screen still has
 * to decide that an expiring batch is amber; the decision has to live
 * somewhere a screen cannot get past. It lives in `TONE_OF`, below.
 *
 * The measurement that prompted it: **325 hardcoded colour utilities across 29
 * files under `src/pages`, and only 48 of them carry a `dark:` counterpart.**
 * So 277 are light-mode-only, and most of this product's semantic colour was
 * invisible or wrong the moment dark mode was switched on — nobody had looked,
 * because there was nowhere to look at all of it at once. Most of those sites
 * are a `<StatusBadge>` or a `<StatusDot>`; `tests/test_design_tokens.py`
 * ratchets the number down.
 *
 * **Colour is never the message.** Every badge here renders its label, and the
 * ones that carry clinical weight render an icon too. That is not only an
 * accessibility rule — on a ward, a colour glanced at across a room and
 * misread is a different order of mistake from a mis-clicked filter.
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Icon, type IconName } from "@/components/ui/icon";
import { formatTime } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* Tones                                                                       */
/* -------------------------------------------------------------------------- */

export type Tone =
  | "neutral"
  | "brand"
  | "good"
  | "warning"
  | "serious"
  | "critical"
  | "info";

const SOLID: Record<Tone, string> = {
  neutral: "bg-quiet text-background",
  brand: "bg-primary text-primary-foreground",
  good: "bg-good text-background",
  warning: "bg-warning text-background",
  serious: "bg-serious text-background",
  critical: "bg-critical text-background",
  info: "bg-info text-background",
};

const SUBTLE: Record<Tone, string> = {
  neutral: "bg-quiet-subtle text-quiet-subtle-foreground",
  brand: "bg-primary-subtle text-primary-subtle-foreground",
  good: "bg-good-subtle text-good-subtle-foreground",
  warning: "bg-warning-subtle text-warning-subtle-foreground",
  serious: "bg-serious-subtle text-serious-subtle-foreground",
  critical: "bg-critical-subtle text-critical-subtle-foreground",
  info: "bg-info-subtle text-info-subtle-foreground",
};

const OUTLINE: Record<Tone, string> = {
  neutral: "border-border-strong text-muted-foreground",
  brand: "border-primary/40 text-primary",
  good: "border-good/40 text-good",
  warning: "border-warning/40 text-warning",
  serious: "border-serious/40 text-serious",
  critical: "border-critical/40 text-critical",
  info: "border-info/40 text-info",
};

const INK: Record<Tone, string> = {
  neutral: "text-muted-foreground",
  brand: "text-primary",
  good: "text-good",
  warning: "text-warning",
  serious: "text-serious",
  critical: "text-critical",
  info: "text-info",
};

/** The ink colour for a tone, for the rare place a badge is the wrong shape. */
export function toneInk(tone: Tone): string {
  return INK[tone];
}

/* -------------------------------------------------------------------------- */
/* The domain vocabulary                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Every status string this product produces, mapped to a tone once.
 *
 * Keys are lower-cased and matched loosely, because the backend is not
 * uniform — some endpoints return `PENDING_APPROVAL`, some `pending approval`,
 * some `pending_approval` — and normalising here is cheaper and safer than a
 * migration across 39 Django apps.
 *
 * **An unknown status resolves to `neutral`, never to a guess.** A status this
 * table has not been taught about rendering grey is honest; rendering it green
 * because the word contains "ok" is the kind of cleverness that eventually
 * paints a failed transfusion crossmatch as fine.
 */
const TONE_OF: Record<string, Tone> = {
  /* -- Workflow -------------------------------------------------------- */
  draft: "neutral",
  new: "info",
  open: "info",
  pending: "warning",
  "pending approval": "warning",
  submitted: "info",
  "in progress": "info",
  processing: "info",
  "on hold": "serious",
  active: "good",
  approved: "good",
  completed: "good",
  closed: "neutral",
  verified: "good",
  released: "good",
  rejected: "critical",
  cancelled: "neutral",
  void: "neutral",
  voided: "neutral",
  failed: "critical",
  expired: "critical",
  suspended: "critical",

  /* -- Encounters ------------------------------------------------------ */
  scheduled: "info",
  arrived: "info",
  waiting: "warning",
  "in consultation": "brand",
  admitted: "brand",
  discharged: "neutral",
  transferred: "info",
  "did not attend": "serious",
  "no show": "serious",

  /* -- Beds ------------------------------------------------------------ */
  available: "good",
  occupied: "brand",
  reserved: "info",
  cleaning: "warning",
  maintenance: "serious",
  blocked: "critical",

  /* -- Diagnostics ----------------------------------------------------- */
  ordered: "info",
  collected: "info",
  "in lab": "info",
  resulted: "good",
  "awaiting verification": "warning",
  abnormal: "serious",
  critical: "critical",
  normal: "good",

  /* -- Stock ----------------------------------------------------------- */
  "in stock": "good",
  "low stock": "warning",
  "out of stock": "critical",
  expiring: "serious",
  "expiring soon": "serious",
  quarantined: "serious",
  recalled: "critical",
  damaged: "critical",

  /* -- Money ----------------------------------------------------------- */
  paid: "good",
  unpaid: "warning",
  partial: "warning",
  "partially paid": "warning",
  overdue: "critical",
  refunded: "neutral",
  "written off": "neutral",
  disputed: "serious",
  settled: "good",

  /* -- Claims ---------------------------------------------------------- */
  denied: "critical",
  "under review": "warning",
  resubmitted: "info",

  /* -- People ---------------------------------------------------------- */
  invited: "info",
  inactive: "neutral",
  deactivated: "neutral",
  "on leave": "info",
  "on duty": "good",
  probation: "warning",
  terminated: "neutral",

  /* -- Subscriptions --------------------------------------------------- */
  trial: "info",
  "past due": "serious",
  grace: "warning",
};

/**
 * The icon a status carries, where the status is one somebody must not misread.
 *
 * Deliberately sparse. An icon on every badge is noise, and noise is what
 * makes the three badges that matter stop registering.
 */
const ICON_OF: Record<string, IconName> = {
  critical: "warning",
  failed: "warning",
  rejected: "warning",
  denied: "warning",
  expired: "warning",
  recalled: "warning",
  "out of stock": "warning",
  overdue: "warning",
  suspended: "warning",
  abnormal: "info",
  quarantined: "info",
  approved: "success",
  verified: "success",
  released: "success",
  paid: "success",
};

/** Normalise `PENDING_APPROVAL`, `pending-approval` and `Pending Approval`. */
function normalise(status: string): string {
  return status.trim().toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

/** The tone for a status string. Exported for the rare non-badge use. */
export function toneOf(status: string | null | undefined): Tone {
  if (!status) return "neutral";
  return TONE_OF[normalise(status)] ?? "neutral";
}

/** `pending_approval` → `Pending approval`. Sentence case, not Title Case. */
function humanise(status: string): string {
  const text = normalise(status);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/* -------------------------------------------------------------------------- */
/* StatusBadge                                                                 */
/* -------------------------------------------------------------------------- */

export interface StatusBadgeProps {
  /** The raw status from the API. Normalised and looked up here. */
  status: string | null | undefined;
  /** Override the label. The status string is used when absent. */
  label?: React.ReactNode;
  /** Override the tone, for a status the table cannot know about. */
  tone?: Tone;
  variant?: "subtle" | "solid" | "outline";
  size?: "sm" | "md";
  /** Force the icon on or off. Defaults to the `ICON_OF` table. */
  icon?: IconName | false;
  className?: string;
}

export function StatusBadge({
  status,
  label,
  tone,
  variant = "subtle",
  size = "sm",
  icon,
  className,
}: StatusBadgeProps) {
  const key = status ? normalise(status) : "";
  const resolved = tone ?? toneOf(status);
  const glyph = icon === false ? null : (icon ?? ICON_OF[key] ?? null);

  const palette =
    variant === "solid" ? SOLID : variant === "outline" ? OUTLINE : SUBTLE;

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-full font-medium",
        variant === "outline" && "border bg-transparent",
        size === "sm"
          ? "px-2 py-0.5 text-[0.6875rem]"
          : "px-2.5 py-1 text-xs",
        palette[resolved],
        className,
      )}
    >
      {glyph ? <Icon name={glyph} size="xs" /> : null}
      <span className="truncate">
        {label ?? (status ? humanise(status) : "—")}
      </span>
    </span>
  );
}

/**
 * The same meaning at a fraction of the weight.
 *
 * For a dense table where a full badge in every row turns the column into a
 * wall of pills. The dot carries the colour and the text beside it carries the
 * meaning, so nothing is lost — the label is still present, which is the rule.
 */
export function StatusDot({
  status,
  tone,
  label,
  className,
}: {
  status?: string | null;
  tone?: Tone;
  label?: React.ReactNode;
  className?: string;
}) {
  const resolved = tone ?? toneOf(status);
  const dot: Record<Tone, string> = {
    neutral: "bg-quiet",
    brand: "bg-primary",
    good: "bg-good",
    warning: "bg-warning",
    serious: "bg-serious",
    critical: "bg-critical",
    info: "bg-info",
  };

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dot[resolved])}
      />
      <span className="truncate">
        {label ?? (status ? humanise(status) : "—")}
      </span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Acuity                                                                      */
/* -------------------------------------------------------------------------- */

const ACUITY_LABEL = [
  "",
  "Resuscitation",
  "Emergent",
  "Urgent",
  "Standard",
  "Non-urgent",
] as const;

/**
 * A triage category, as the number and the conventional colour together.
 *
 * **The number is always rendered.** The colour is the recall aid a clinician
 * already has; the number is the datum. A badge that showed only the colour
 * would be unreadable to a colour-blind triage nurse — around one man in
 * twelve — and there is no version of that trade-off worth making in an
 * emergency department.
 *
 * Colours follow the Manchester/ESI convention rather than this product's
 * sequential ramp, deliberately; the reasoning is in `primitive.css`.
 */
export function AcuityBadge({
  level,
  showLabel = false,
  className,
}: {
  level: 1 | 2 | 3 | 4 | 5 | number | null | undefined;
  showLabel?: boolean;
  className?: string;
}) {
  if (level == null || level < 1 || level > 5) {
    return (
      <span
        className={cn(
          "inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-muted px-1.5 text-xs font-semibold text-muted-foreground",
          className,
        )}
        title="Not triaged"
      >
        —
      </span>
    );
  }

  const level_ = Math.round(level) as 1 | 2 | 3 | 4 | 5;
  const fill = {
    1: "bg-acuity-1",
    2: "bg-acuity-2",
    3: "bg-acuity-3",
    4: "bg-acuity-4",
    5: "bg-acuity-5",
  }[level_];

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1.5 text-xs font-semibold text-background",
          fill,
        )}
        title={`Acuity ${level_} — ${ACUITY_LABEL[level_]}`}
      >
        {level_}
      </span>
      {showLabel ? (
        <span className="text-xs text-muted-foreground">
          {ACUITY_LABEL[level_]}
        </span>
      ) : null}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Trend                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * A change against a previous period.
 *
 * **`goodDirection` exists because up is not always good.** Revenue rising and
 * infection rate rising are the same arrow and opposite news, and a stat tile
 * that paints every increase green is actively misleading on roughly half the
 * figures in a hospital. There is no sensible default, so the prop is
 * required — a caller who has not thought about it cannot accidentally get the
 * cheerful answer.
 */
export function TrendBadge({
  value,
  goodDirection,
  suffix = "%",
  className,
}: {
  /** The signed change. Null renders as "no comparison", not as zero. */
  value: number | null | undefined;
  goodDirection: "up" | "down" | "neither";
  suffix?: string;
  className?: string;
}) {
  if (value == null) {
    return (
      <span className={cn("text-xs text-muted-foreground", className)}>
        no comparison
      </span>
    );
  }

  const flat = Math.abs(value) < 0.05;
  const direction = flat ? "flat" : value > 0 ? "up" : "down";

  const tone: Tone =
    goodDirection === "neither" || flat
      ? "neutral"
      : direction === goodDirection
        ? "good"
        : "critical";

  const glyph: IconName =
    direction === "flat"
      ? "trendFlat"
      : direction === "up"
        ? "riseSmall"
        : "fallSmall";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium",
        INK[tone],
        className,
      )}
    >
      <Icon name={glyph} size="xs" />
      {flat ? "no change" : `${Math.abs(value).toFixed(1)}${suffix}`}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Live                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * "This is current", with the time it was current at.
 *
 * **A figure with no as-of time is a guess.** Every dashboard tile in this
 * product carries one, because a bed count from nine minutes ago and a bed
 * count from now look identical and are not the same claim.
 */
export function Freshness({
  at,
  stale = false,
  className,
}: {
  at: Date | string | null;
  /** True when the source failed and this is the last good value. */
  stale?: boolean;
  className?: string;
}) {
  const when = at ? (typeof at === "string" ? new Date(at) : at) : null;
  const label = when
    ? formatTime(when)
    : "unknown";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs",
        stale ? "text-serious" : "text-muted-foreground",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          stale ? "bg-serious" : "animate-breathe bg-good",
        )}
      />
      {stale ? `last good ${label}` : `as at ${label}`}
    </span>
  );
}
