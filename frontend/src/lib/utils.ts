import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

/**
 * `tailwind-merge`, told about this product's own shadow scale.
 *
 * **It resolves conflicts by recognising class names, and it did not recognise
 * ours.** The elevation tokens are `shadow-flat`, `shadow-raised`,
 * `shadow-floating` and `shadow-modal`; out of the box the library only knows
 * `shadow-sm`, `shadow-lg` and friends. So `cn("shadow-raised", "shadow-none")`
 * kept *both*, and which one applied was decided by stylesheet order — the
 * caller's override silently lost.
 *
 * Found by screenshot, not by reading: stat tiles nested inside a dashboard
 * panel were passed `shadow-none` to flatten them and still drew as cards
 * inside a card. Probed directly afterwards — colours, radii and spacing all
 * merge correctly (their theme groups accept any value), and the shadow group
 * was the only one that did not.
 *
 * If another custom scale is added to `tailwind.config.js` whose names are not
 * Tailwind's own, it belongs in this list too, or every override of it will
 * fail the same quiet way.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      shadow: [{ shadow: ["flat", "raised", "floating", "modal"] }],
    },
  },
})

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
