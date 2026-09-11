/**
 * NEWS2, shown the way a ward reads it.
 *
 * The score is a number with a meaning attached, and the meaning is what the
 * nurse acts on: 0–4 is routine observation, 5–6 is a clinician within the
 * hour, 7 or more is an emergency response (Royal College of Physicians,
 * 2017). So low scores are deliberately quiet — a board where every bed shouts
 * "NEWS 0" in green trains people to stop looking — and the colour arrives
 * only when the score asks for something.
 *
 * The number is always rendered. Colour confirms; it never carries the
 * message alone.
 *
 * **Old observations are not a score.** A "2" from yesterday evening says
 * nothing about the patient now, so a stale reading is drawn dashed with a
 * clock and the time, rather than looking as reassuring as a fresh one.
 */

import { Clock } from "lucide-react";

import { cn } from "@/lib/utils";

export type News2Risk = "low" | "medium" | "high";

export function news2Band(score: number): "routine" | "urgent" | "emergency" {
  if (score >= 7) return "emergency";
  if (score >= 5) return "urgent";
  return "routine";
}

const BAND_LABEL = {
  routine: "Routine observation",
  urgent: "Clinician review within the hour",
  emergency: "Emergency response",
} as const;

export function News2Badge({
  score,
  stale = false,
  recordedAt,
  size = "sm",
  className,
}: {
  score: number;
  stale?: boolean;
  recordedAt?: string | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const band = news2Band(score);
  const time = recordedAt
    ? new Date(recordedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <span
      title={`NEWS2 ${score} — ${BAND_LABEL[band]}${time ? `, observed ${time}` : ""}${stale ? " (out of date)" : ""}`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md font-semibold tabular-nums leading-none",
        size === "sm" ? "h-5 px-1.5 text-[11px]" : "h-7 px-2 text-xs",
        stale
          ? "border border-dashed border-muted-foreground/40 text-muted-foreground"
          : band === "emergency"
            ? "bg-critical text-white shadow-sm"
            : band === "urgent"
              ? "bg-warning-subtle text-warning-subtle-foreground ring-1 ring-inset ring-warning/40"
              : "bg-muted text-muted-foreground",
        className,
      )}
    >
      {stale && <Clock className="h-3 w-3" aria-hidden />}
      <span className="font-medium opacity-70">NEWS</span>
      {score}
    </span>
  );
}
