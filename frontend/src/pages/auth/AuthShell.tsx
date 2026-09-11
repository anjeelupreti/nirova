/**
 * The frame both signed-out screens share: the form on the left, the product
 * on the right.
 *
 * **The third version of this screen, and the first one planned rather than
 * decorated.** The first was a card on a grey field. The second put a teal
 * block beside the form with a small ward diagram in it — at 45% opacity, on
 * a gradient, with its labels at eleven pixels, so the one thing meant to
 * show a buyer the product was the one thing on the page they could not read.
 *
 * What the right-hand side has to do in the seconds it is looked at:
 *
 *  - **Say what this is, in one line a hospital director would repeat.** Not
 *    a feature list. The headline is the product's claim.
 *  - **Show it, legibly.** A composed view of three real screens — the bed
 *    board, a patient deteriorating, today's figures — at a size where the
 *    names and numbers can be read, in the same visual language as the
 *    screens behind the sign-in. Illustrative figures, and labelled so.
 *  - **Answer the objection before it is raised.** For a Nepali buyer that is
 *    "was this built for us?" — so Bikram Sambat, PAN/VAT and SSF are named.
 *
 * The left side stays narrow on purpose: a field stretched across a 27-inch
 * monitor is harder to use, not easier.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import { NirovaWordmark } from "@/components/ui/brand";

export function AuthShell({
  children,
  aside,
  corner,
}: {
  children: React.ReactNode;
  aside: React.ReactNode;
  /** Top-right of the form column: the way to the other screen. */
  corner?: React.ReactNode;
}) {
  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-[minmax(30rem,46%)_1fr]">
      <div className="flex min-h-screen flex-col px-6 py-6 sm:px-10">
        <header className="flex items-center justify-between gap-4">
          <Link to="/" aria-label="Nirova">
            <NirovaWordmark size="md" />
          </Link>
          <div className="text-sm">{corner}</div>
        </header>
        <main className="flex flex-1 items-center justify-center py-10">{children}</main>
        <footer className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>© {new Date().getFullYear()} Nirova Health Systems</span>
          <SystemStatus />
        </footer>
      </div>
      <aside className="relative hidden overflow-hidden bg-hero text-hero-foreground lg:block">
        <HeroBackdrop />
        <div className="relative flex h-full flex-col p-10 xl:p-14">{aside}</div>
      </aside>
    </div>
  );
}

/**
 * Whether the service is up, said on the one screen where it matters most.
 *
 * When sign-in fails at seven in the morning, the first question is whether
 * it is you or the system. The health endpoint answers it without anyone
 * ringing IT.
 */

function SystemStatus() {
  const [state, setState] = useState<"checking" | "up" | "down">("checking");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/health/")
      .then((response) => !cancelled && setState(response.ok ? "up" : "down"))
      .catch(() => !cancelled && setState("down"));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <span className="flex items-center gap-1.5" role="status">
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          state === "up" ? "bg-good" : state === "down" ? "bg-critical" : "bg-muted-foreground/40",
        )}
      />
      {state === "up"
        ? "All systems normal"
        : state === "down"
          ? "The service is not responding — try again shortly"
          : "Checking service…"}
    </span>
  );
}

function HeroBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0">
      {/* Light from the upper right, so the panel has a direction rather than
          a flat fill — and the composition sits in the light. */}
      <div className="absolute -right-40 -top-40 h-[40rem] w-[40rem] rounded-full bg-hero-2 opacity-70 blur-3xl" />
      <div className="absolute -bottom-48 -left-24 h-[28rem] w-[28rem] rounded-full bg-hero-2 opacity-30 blur-3xl" />
      <svg className="absolute inset-0 h-full w-full opacity-[0.07]">
        <defs>
          <pattern id="auth-grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M32 0H0V32" fill="none" stroke="currentColor" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#auth-grid)" />
      </svg>
    </div>
  );
}
