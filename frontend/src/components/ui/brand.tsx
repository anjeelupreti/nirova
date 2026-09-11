/**
 * The Nirova mark, and the slot a customer's own mark goes into.
 *
 * **What this replaces:** `<Activity />` from lucide — a stock icon, shipped
 * for nine months as the product's identity, in a rounded square, beside the
 * word "Nirova" in the body font. Three separate signals that nobody had
 * decided what this product looks like, in the one place every user looks
 * first.
 *
 * The mark is an **N drawn as a trace**: two uprights joined by a diagonal
 * that deflects on the way down, the way a rhythm strip does. It is a monogram
 * at a glance and a vital sign on a second look, which is the right order —
 * a logo whose cleverness has to be explained is not working. No cross: the
 * red cross is a protected emblem under the Geneva Conventions, and the
 * generic medical cross is what every template uses.
 *
 * It is drawn on a 24-unit grid with a 2.75-unit stroke so it stays legible at
 * 16px in a browser tab, which is the size that actually decides whether a
 * mark is any good.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* The mark                                                                    */
/* -------------------------------------------------------------------------- */

export function NirovaMark({
  className,
  title = "Nirova",
  ...props
}: React.SVGProps<SVGSVGElement> & { title?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      role="img"
      aria-label={title}
      className={cn("h-6 w-6", className)}
      {...props}
    >
      <title>{title}</title>
      {/*
        Left upright, full height. Drawn as its own path rather than as part of
        one polyline so the joins stay square at the ends and round at the
        corners — a single stroked polyline forces one linecap for all six ends.
      */}
      <path
        d="M4.5 19.5V4.5"
        stroke="currentColor"
        strokeWidth="2.75"
        strokeLinecap="round"
      />
      {/*
        The diagonal, with the deflection. It runs top-left to bottom-right but
        steps up at 12 and down at 14 — a QRS complex, compressed into the
        width of a letterform. At 16px the step reads as a thickening rather
        than as detail, which is the intent: it should never look like noise.
      */}
      <path
        d="M4.5 4.5 L10.2 13.1 L12 9.4 L13.8 15.2 L15.6 12.1 L19.5 19.5"
        stroke="currentColor"
        strokeWidth="2.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Right upright. */}
      <path
        d="M19.5 4.5V19.5"
        stroke="currentColor"
        strokeWidth="2.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * The mark in its container — the form it takes in the header and on the
 * sign-in screen.
 *
 * The container is a squircle in the brand colour, not a circle: a circle
 * reads as an avatar, and this sits two centimetres from one.
 */
export function NirovaLogo({
  size = "md",
  className,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const box = {
    sm: "h-7 w-7 rounded-md",
    md: "h-9 w-9 rounded-lg",
    lg: "h-12 w-12 rounded-xl",
  }[size];
  const glyph = { sm: "h-4 w-4", md: "h-5 w-5", lg: "h-7 w-7" }[size];

  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center bg-primary text-primary-foreground",
        box,
        className,
      )}
    >
      <NirovaMark className={glyph} />
    </div>
  );
}

/**
 * Mark plus wordmark.
 *
 * The wordmark is the display face at a tightened tracking rather than the
 * body font at default — the same letters, but set. `font-medium` and not
 * `font-semibold`: a product name shouted at every screen is a product name
 * people stop seeing.
 */
export function NirovaWordmark({
  size = "md",
  className,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const text = {
    sm: "text-sm",
    md: "text-base",
    lg: "text-xl",
  }[size];

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <NirovaLogo size={size} />
      <span
        className={cn(
          "font-display font-medium tracking-[-0.03em] text-foreground",
          text,
        )}
      >
        Nirova
      </span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* The customer's mark                                                         */
/* -------------------------------------------------------------------------- */

/**
 * The organization's own identity in the shell.
 *
 * **This is the difference between a demo and their system.** A hospital that
 * signs in and sees our name and our teal is looking at software somebody
 * sold them; one that sees its own crest and its own name at the top left is
 * looking at its own. The cost of that feeling is this component and a logo
 * field, and it is the single cheapest thing in this whole plan.
 *
 * Falls back to initials on the brand colour when no logo has been uploaded —
 * never to a broken image, and never to ours. Showing the vendor's mark where
 * the customer's belongs is worse than showing a monogram.
 */
export function OrgBrand({
  name,
  logoUrl,
  facility,
  size = "md",
  className,
}: {
  name: string;
  logoUrl?: string | null;
  /** The building, under the organization. A three-hospital customer needs it. */
  facility?: string | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const [broken, setBroken] = React.useState(false);
  const box = size === "sm" ? "h-7 w-7 rounded-md" : "h-8 w-8 rounded-md";

  const initials = React.useMemo(
    () =>
      name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((word) => word[0]?.toUpperCase() ?? "")
        .join(""),
    [name],
  );

  return (
    <div className={cn("flex min-w-0 items-center gap-2.5", className)}>
      {logoUrl && !broken ? (
        <img
          src={logoUrl}
          alt=""
          onError={() => setBroken(true)}
          className={cn("shrink-0 object-contain", box)}
        />
      ) : (
        <div
          className={cn(
            "flex shrink-0 items-center justify-center bg-primary/10 text-[0.6875rem] font-semibold text-primary",
            box,
          )}
          aria-hidden
        >
          {initials || "—"}
        </div>
      )}
      <div className="min-w-0 leading-tight">
        <p className="truncate text-sm font-medium text-foreground">{name}</p>
        {facility ? (
          <p className="truncate text-xs text-muted-foreground">{facility}</p>
        ) : null}
      </div>
    </div>
  );
}
