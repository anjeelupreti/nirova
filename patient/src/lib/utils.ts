import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * Merge Tailwind classes with later ones winning.
 *
 * `clsx` handles conditionals; `twMerge` resolves conflicts, so a component's
 * default `px-4` is genuinely overridden by a caller's `px-6` instead of both
 * landing in the class list and the outcome depending on stylesheet order.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Nepali rupee formatting: NPR 16,000 rather than $16,000.00. */
export function formatNpr(amount: number): string {
  return new Intl.NumberFormat("en-NP", {
    style: "currency",
    currency: "NPR",
    maximumFractionDigits: 0,
  }).format(amount)
}

/** Renders a limit for humans: null means unlimited, not "null". */
export function formatLimit(value: number | null, unlimited: boolean): string {
  return unlimited || value === null ? "unlimited" : String(value)
}
