/**
 * Who is this person, and therefore what should their day look like?
 *
 * **"The system itself is confused whom to show what" was the brief, and it
 * was exact.** Every one of the seventeen seeded roles opened onto the same
 * screen showing the same panels, with the only difference being which of them
 * 403'd. A pharmacist and a financial controller saw an identical product.
 *
 * A persona is *not* a role. Roles are customer-editable data — a hospital can
 * write "Ward Sister", rename `nurse` to `sister`, or invent a role nobody
 * anticipated — so keying the interface to role codes would break the moment
 * somebody used the role editor. A persona is inferred from **what a person can
 * actually do**, which is stable across renaming and correct for roles that do
 * not exist yet.
 *
 * That is also the honest test. Somebody who can chart observations and
 * administer medication *is* working as a nurse, whatever their role is called,
 * and the ward board is the right home for them.
 *
 * The ladder is ordered most-specific first: a medical director who also holds
 * clinical permissions gets the leadership view, because that is the more
 * distinctive of their two jobs and the clinic day is one click away.
 */

import type { IconName } from "@/components/ui/icon";

export type PersonaId =
  | "leadership"
  | "doctor"
  | "nurse"
  | "frontdesk"
  | "pharmacy"
  | "finance"
  | "people"
  | "platform"
  | "general";

export interface Persona {
  id: PersonaId;
  /** What this person's day is called, in their words. */
  label: string;
  /** The greeting line under it — the job, not the product. */
  blurb: string;
  icon: IconName;
  /**
   * Which of the eight chart series slots this persona's accents draw from.
   *
   * **This is how the workspaces are made visually distinct without inventing
   * five palettes.** The whole product re-themes from one selectable palette;
   * a persona shifts *within* it by taking a different validated series slot
   * for its hero and its emphasis. A doctor's day and a pharmacist's day look
   * like different rooms in the same building, which is the intent — five
   * unrelated colour schemes would look like five products.
   */
  accent: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
}

/**
 * The test for each persona: a permission and the scope it must be held at.
 *
 * Every one is a *capability*, deliberately. `salary.read` at facility scope is
 * not something a clinician has and is not something a role can be renamed out
 * of.
 */
const LADDER: {
  persona: Persona;
  /** All of these, at the given scope. */
  requires: [permission: string, scope: string][];
}[] = [
  {
    persona: {
      id: "leadership",
      label: "Facility overview",
      blurb: "How the hospital is running today",
      icon: "capacity",
      accent: 1,
    },
    // Somebody who can see the plan *and* the money is running the place, not
    // working a desk in it.
    requires: [
      ["subscription.read", "organization"],
      ["finance.read", "facility"],
    ],
  },
  {
    persona: {
      id: "finance",
      label: "Cash position",
      blurb: "What came in, what is owed, what is due",
      icon: "finance",
      accent: 4,
    },
    requires: [["finance.read", "facility"]],
  },
  {
    persona: {
      id: "nurse",
      label: "My ward",
      blurb: "Beds, medications due, observations outstanding",
      icon: "nurse",
      accent: 3,
    },
    // Charting and administering is the nurse's day. A doctor holds the
    // clinical read but not the bedside write, which is what separates them.
    requires: [["patient.clinical.read", "facility"], ["encounter.create", "own"]],
  },
  {
    persona: {
      id: "doctor",
      label: "My clinic",
      blurb: "Your list, results to acknowledge, scripts to sign",
      icon: "doctor",
      accent: 1,
    },
    requires: [["patient.clinical.read", "facility"]],
  },
  {
    persona: {
      id: "pharmacy",
      label: "Dispensing",
      blurb: "What to dispense, what is short, what is expiring",
      icon: "pharmacy",
      accent: 6,
    },
    requires: [["stock.read", "facility"]],
  },
  {
    persona: {
      id: "people",
      label: "People",
      blurb: "Headcount, credentials, leave and payroll",
      icon: "staff",
      accent: 5,
    },
    requires: [["employee.read", "own"], ["attendance.read", "facility"]],
  },
  {
    persona: {
      id: "frontdesk",
      label: "Front desk",
      blurb: "Who is waiting, who is booked, who has arrived",
      icon: "queue",
      accent: 7,
    },
    requires: [["encounter.read", "own"]],
  },
];

const GENERAL: Persona = {
  id: "general",
  label: "Today",
  blurb: "What needs you",
  icon: "workspace",
  accent: 1,
};

const PLATFORM: Persona = {
  id: "platform",
  label: "Platform",
  blurb: "Customers, subscriptions and the estate",
  icon: "platform",
  accent: 3,
};

/**
 * Work out whose day this is.
 *
 * **Falls back to `general` rather than guessing.** A persona that is wrong is
 * worse than a persona that is generic: somebody shown a ward board who does
 * not work on a ward concludes the product does not understand them, whereas
 * "what needs you" is true for everybody and is never embarrassing.
 */
export function resolvePersona({
  can,
  isPlatformOnly,
  override,
}: {
  can: (permission: string, scope?: string) => boolean;
  isPlatformOnly: boolean;
  /** A person's own choice, from preferences. Beats the inference. */
  override?: PersonaId | "auto";
}): Persona {
  if (isPlatformOnly) return PLATFORM;

  if (override && override !== "auto") {
    const chosen = LADDER.find((entry) => entry.persona.id === override);
    // Only honour a choice they can still satisfy: somebody whose role changed
    // since they set it should not land on a board that 403s every panel.
    if (chosen && chosen.requires.every(([code, scope]) => can(code, scope))) {
      return chosen.persona;
    }
    if (override === "general") return GENERAL;
  }

  for (const entry of LADDER) {
    if (entry.requires.every(([code, scope]) => can(code, scope))) {
      return entry.persona;
    }
  }
  return GENERAL;
}

/** Every persona a given person could legitimately switch to. */
export function availablePersonas(
  can: (permission: string, scope?: string) => boolean,
): Persona[] {
  const reachable = LADDER.filter((entry) =>
    entry.requires.every(([code, scope]) => can(code, scope)),
  ).map((entry) => entry.persona);
  return [...reachable, GENERAL];
}

/**
 * The CSS colour for a persona's accent.
 *
 * A series slot rather than a new hue: the eight were validated as a set for
 * colour-vision deficiency, and inventing a ninth for "the pharmacist's green"
 * would break that guarantee for a decorative reason.
 */
export function personaAccent(persona: Persona): string {
  return `hsl(var(--series-${persona.accent}))`;
}
