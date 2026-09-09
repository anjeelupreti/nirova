/**
 * The display primitives this console was missing or re-inventing per screen.
 *
 * Counted rather than guessed, because the first version of this comment said
 * "six dashboards" from memory and the real number is worse:
 *
 * * **A figure with a label is hand-built markup on 16 of the 34 screens.**
 *   Counter, Diagnostics, Emergency, Notifications, Payroll, People, Pharmacy,
 *   Platform, Privacy, Procurement, Queue, Reports, Staff, Time, Wards and
 *   Workspace each write their own, and they do not agree on size, spacing or
 *   what a good and a bad movement look like.
 * * **There are no avatars anywhere.** Not duplicated -- absent. Every list of
 *   people in this console is a column of names, which is why they all read as
 *   rows of text rather than as colleagues and patients.
 * * **Day/Week/Month is three buttons and a conditional class**, wherever a
 *   screen needed it.
 *
 * These are here so the seventeenth screen looks like the first without its
 * author having to go and read the sixteenth.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Avatar                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Twelve hues at a fixed lightness, so any two are equally readable.
 *
 * Not random per render and not stored on the person: derived from their name,
 * so the same colleague is the same colour on every screen and after every
 * reload. That consistency is the whole value — an avatar colour that moves is
 * worse than no colour, because the eye learns it and is then misled.
 *
 * Deliberately not the semantic palette. A person is not a status, and
 * borrowing `destructive` for somebody whose surname happens to hash there
 * would say something the design did not mean.
 */
const AVATAR_HUES = [
  "bg-rose-500", "bg-orange-500", "bg-amber-500", "bg-lime-600",
  "bg-emerald-500", "bg-teal-500", "bg-cyan-600", "bg-sky-500",
  "bg-indigo-500", "bg-violet-500", "bg-fuchsia-500", "bg-pink-500",
];

function hueFor(seed: string): string {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    // A plain rolling hash. It does not need to be good, it needs to be the
    // same every time, which `Math.random` and object identity are not.
    hash = (hash * 31 + seed.charCodeAt(index)) | 0;
  }
  return AVATAR_HUES[Math.abs(hash) % AVATAR_HUES.length];
}

/** First letters of the first and last words: "Sabina Rana" -> "SR". */
function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

const AVATAR_SIZES = {
  xs: "h-6 w-6 text-[10px]",
  sm: "h-8 w-8 text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-14 w-14 text-base",
} as const;

export function Avatar({
  name,
  src,
  size = "md",
  className,
  title,
}: {
  name: string;
  src?: string | null;
  size?: keyof typeof AVATAR_SIZES;
  className?: string;
  title?: string;
}) {
  const [failed, setFailed] = React.useState(false);
  const showImage = Boolean(src) && !failed;

  return (
    <span
      title={title ?? name}
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center",
        "rounded-full font-semibold text-white",
        AVATAR_SIZES[size],
        showImage ? "bg-muted" : hueFor(name),
        className,
      )}
    >
      {showImage ? (
        <img
          src={src as string}
          alt=""
          // Falls back to initials rather than showing a broken image. A
          // photo that 404s is common -- an avatar host goes down, a signed
          // URL expires -- and the initials are always right.
          onError={() => setFailed(true)}
          className="h-full w-full rounded-full object-cover"
        />
      ) : (
        <span aria-hidden>{initialsFor(name)}</span>
      )}
      <span className="sr-only">{name}</span>
    </span>
  );
}

/**
 * Overlapping avatars with a "+3" when there are more than fit.
 *
 * The overflow count is not decoration: a strip that silently stopped at four
 * would tell a ward sister there are four people on shift when there are nine.
 */
export function AvatarGroup({
  people,
  max = 4,
  size = "sm",
  className,
}: {
  people: { name: string; src?: string | null }[];
  max?: number;
  size?: keyof typeof AVATAR_SIZES;
  className?: string;
}) {
  const shown = people.slice(0, max);
  const extra = people.length - shown.length;

  return (
    <div className={cn("flex items-center -space-x-2", className)}>
      {shown.map((person, index) => (
        <Avatar
          key={`${person.name}-${index}`}
          name={person.name}
          src={person.src}
          size={size}
          className="ring-2 ring-background"
        />
      ))}
      {extra > 0 && (
        <span
          title={people.slice(max).map((person) => person.name).join(", ")}
          className={cn(
            "inline-flex items-center justify-center rounded-full",
            "bg-muted font-medium text-muted-foreground ring-2 ring-background",
            AVATAR_SIZES[size],
          )}
        >
          +{extra}
        </span>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Stat tile                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * One figure, what it is, and which way it is going.
 *
 * **The delta carries a direction and a meaning, and they are not the same
 * thing.** Waiting time falling is good; revenue falling is not. `intent`
 * says which, so the colour is a judgement the caller makes rather than one
 * this component guesses from the sign — a dashboard that paints every
 * decrease red would tell a triage nurse that a shorter queue is a problem.
 */
export function StatTile({
  label,
  value,
  hint,
  delta,
  intent = "neutral",
  icon,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  /** Rendered verbatim: "+12%", "3 fewer", "unchanged". */
  delta?: string;
  /** What the delta *means*, not which way it points. */
  intent?: "good" | "bad" | "neutral";
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card p-4",
        // A restrained lift on hover. These are often clickable; when they are
        // not, the movement still tells the eye they are one unit rather than
        // four numbers sharing a row.
        "transition-shadow duration-200 hover:shadow-sm",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        {icon && <span className="text-muted-foreground/60">{icon}</span>}
      </div>

      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">
        {value}
      </p>

      {(delta || hint) && (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 text-xs">
          {delta && (
            <span
              className={cn(
                "font-medium",
                intent === "good" && "text-emerald-600 dark:text-emerald-400",
                intent === "bad" && "text-destructive",
                intent === "neutral" && "text-muted-foreground",
              )}
            >
              {delta}
            </span>
          )}
          {hint && <span className="text-muted-foreground">{hint}</span>}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Segmented control                                                           */
/* -------------------------------------------------------------------------- */

/**
 * Day / Week / Month, and every other small exclusive choice.
 *
 * A `role="tablist"` of buttons rather than a `<select>`, because with three
 * or four options the whole choice should be visible: a select hides the
 * alternatives behind a click and makes "what else could I see?" a question.
 *
 * The moving highlight is one absolutely-positioned element rather than a
 * background on the active button, so it slides between options instead of
 * blinking from one to the next. That is the difference people describe as
 * "feels finished".
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = "default",
  className,
  "aria-label": ariaLabel,
}: {
  options: { value: T; label: React.ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "default";
  className?: string;
  "aria-label"?: string;
}) {
  const index = Math.max(0, options.findIndex((option) => option.value === value));

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "relative inline-flex rounded-lg bg-muted p-1",
        className,
      )}
    >
      <span
        aria-hidden
        className="absolute inset-y-1 rounded-md bg-background shadow-sm transition-transform duration-200 ease-out"
        style={{
          width: `calc((100% - 0.5rem) / ${options.length})`,
          transform: `translateX(calc(${index} * 100%))`,
        }}
      />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          onClick={() => onChange(option.value)}
          className={cn(
            "relative z-10 flex-1 whitespace-nowrap rounded-md font-medium transition-colors",
            size === "sm" ? "px-3 py-1 text-xs" : "px-4 py-1.5 text-sm",
            option.value === value
              ? "text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Timeline                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Things that happened, in the order they happened.
 *
 * A patient's care, an invoice's life, a change request's decisions — all of
 * these were rendered as tables of rows sorted by date, which is a list of
 * facts rather than a story. The rail and the markers are what make a reader
 * see duration and sequence rather than seven rows.
 */
export function Timeline({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <ol className={cn("relative space-y-0", className)}>{children}</ol>
  );
}

export function TimelineItem({
  time,
  title,
  description,
  icon,
  intent = "neutral",
  last = false,
  onClick,
}: {
  time?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  intent?: "neutral" | "good" | "bad" | "active";
  /** Suppresses the rail below the marker on the final entry. */
  last?: boolean;
  onClick?: () => void;
}) {
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      {/* The rail, drawn behind the marker and stopped on the last item so
          the sequence does not appear to continue past its end. */}
      {!last && (
        <span
          aria-hidden
          className="absolute left-[11px] top-6 h-full w-px bg-border"
        />
      )}

      <span
        aria-hidden
        className={cn(
          "relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-4 ring-background",
          intent === "neutral" && "bg-muted text-muted-foreground",
          intent === "good" && "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
          intent === "bad" && "bg-destructive/15 text-destructive",
          intent === "active" && "bg-primary text-primary-foreground",
        )}
      >
        {icon ?? <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      </span>

      <div
        className={cn(
          "min-w-0 flex-1 pb-1",
          onClick && "cursor-pointer rounded-md -mx-2 px-2 hover:bg-muted/60 transition-colors",
        )}
        onClick={onClick}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-sm font-medium">{title}</p>
          {time && (
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {time}
            </span>
          )}
        </div>
        {description && (
          <div className="mt-0.5 text-sm text-muted-foreground">
            {description}
          </div>
        )}
      </div>
    </li>
  );
}
