/**
 * The small illustration in a workspace's welcome band.
 *
 * **Drawn from the tokens, never from a file.** A picture pasted in would be
 * one palette's blue on a screen somebody has made rose, and wrong again the
 * moment they switch to dark. Every fill here is a semantic token, so the
 * drawing is the organization's colour, in whichever mode, with no second
 * asset and no request.
 *
 * Decorative: `aria-hidden`, hidden below `lg`, and it never carries a fact.
 */

import { cn } from "@/lib/utils";

export function HeroArt({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 220 120"
      fill="none"
      aria-hidden
      className={cn("h-24 w-auto", className)}
    >
      <ellipse cx="118" cy="72" rx="96" ry="46" fill="hsl(var(--primary-subtle))" />
      <circle cx="30" cy="34" r="7" fill="hsl(var(--accent-subtle))" />
      <circle cx="206" cy="22" r="4" fill="hsl(var(--primary) / 0.35)" />
      <circle cx="16" cy="70" r="3" fill="hsl(var(--primary) / 0.3)" />

      {/* A monitor card with a heartbeat. */}
      <rect x="68" y="24" width="92" height="68" rx="12" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.5" />
      <rect x="80" y="36" width="36" height="6" rx="3" fill="hsl(var(--muted))" />
      <rect x="80" y="46" width="22" height="4" rx="2" fill="hsl(var(--muted))" />
      <path
        d="M80 70h14l6-13 10 24 8-17 6 6h26"
        stroke="hsl(var(--primary))"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* A heart badge in the accent. */}
      <circle cx="160" cy="30" r="16" fill="hsl(var(--accent-solid))" />
      <path
        d="M160 38.5c-6.2-4.1-9.2-7.4-9.2-11.2a4.6 4.6 0 0 1 9.2-.9 4.6 4.6 0 0 1 9.2.9c0 3.8-3 7.1-9.2 11.2Z"
        fill="hsl(var(--accent-solid-foreground))"
      />

      {/* A capsule. */}
      <g transform="rotate(-32 46 92)">
        <rect x="26" y="84" width="42" height="16" rx="8" fill="hsl(var(--card))" stroke="hsl(var(--primary))" strokeWidth="2.5" />
        <path d="M47 85.25h13a6.75 6.75 0 0 1 0 13.5H47Z" fill="hsl(var(--primary))" />
      </g>

      {/* A stethoscope. */}
      <path d="M160 100c18 0 30-9 30-26V58" stroke="hsl(var(--accent-ink))" strokeWidth="3" strokeLinecap="round" />
      <circle cx="190" cy="52" r="7" fill="hsl(var(--card))" stroke="hsl(var(--accent-ink))" strokeWidth="3" />
    </svg>
  );
}
