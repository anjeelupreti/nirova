/**
 * A person's interface preferences, applied to the document.
 *
 * **Dark mode has never worked.** `darkMode: ["class"]` is set in the Tailwind
 * config, `dark:` variants are written throughout the console, and nothing has
 * ever added the class to `<html>`. Every one of those variants has been dead
 * code. Density and reduced motion were not expressed at all.
 *
 * So this is not a settings screen's helper — it is the thing that makes those
 * three preferences mean anything, and it lives above the router because a
 * theme that only applied on the screen where you chose it would be a joke.
 *
 * **Two sources, deliberately.** The server is the record: preferences follow
 * you to another machine, which is the point of storing them per user.
 * `localStorage` is a cache read *synchronously on the first paint*, because
 * the server's answer arrives one round trip after the page renders and
 * without it every load would flash white before turning dark. The cache is
 * never the authority — it is overwritten by the server's answer the moment it
 * lands.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import api from "@/lib/api";

export type Theme = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

/**
 * The five identities in `styles/tokens/palettes.css`.
 *
 * Light/dark is a *mode*; this is the palette, and the two are independent —
 * every one of these has a validated dark form. Conflating them is the
 * commonest way a theme picker ends up with eight options and four of them
 * unreadable.
 */
export type Palette = "vital" | "meridian" | "command" | "verdant" | "ember";

export const PALETTES: { value: Palette; label: string; blurb: string }[] = [
  { value: "vital", label: "Vital", blurb: "Luminous teal, coral counterpoint" },
  { value: "meridian", label: "Meridian", blurb: "Deep indigo and amber" },
  { value: "command", label: "Command", blurb: "Navy chrome, electric cyan" },
  { value: "verdant", label: "Verdant", blurb: "Fresh green with a violet lift" },
  { value: "ember", label: "Ember", blurb: "Warm rose and teal" },
];

export interface Preferences {
  theme: Theme;
  palette: Palette;
  density: Density;
  landing: string;
  reduced_motion: boolean;
  notify_critical_results: boolean;
  notify_approvals: boolean;
}

/**
 * Mirrors `apps/identity/preferences.py::DEFAULTS`.
 *
 * A second copy, and an unavoidable one: this has to be applied before any
 * request completes. It is only ever a *starting* value — everything the
 * server sends replaces it — so the two drifting shows up as a wrong first
 * paint rather than as wrong behaviour.
 */
const FALLBACK: Preferences = {
  theme: "system",
  palette: "vital",
  density: "comfortable",
  landing: "auto",
  reduced_motion: false,
  notify_critical_results: true,
  notify_approvals: true,
};

const CACHE_KEY = "nirova.preferences";

function cached(): Preferences {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    return raw ? { ...FALLBACK, ...JSON.parse(raw) } : FALLBACK;
  } catch {
    // A private window, cleared site data, or storage blocked entirely. The
    // defaults are always a valid answer, so this must never throw upward:
    // failing here would take the whole application down over a colour.
    return FALLBACK;
  }
}

function remember(preferences: Preferences) {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(preferences));
  } catch {
    /* See `cached`. A preference that cannot be cached still works. */
  }
}

/* -------------------------------------------------------------------------- */
/* Applying                                                                    */
/* -------------------------------------------------------------------------- */

function applyToDocument(preferences: Preferences, systemIsDark: boolean) {
  const root = document.documentElement;

  const dark =
    preferences.theme === "dark" ||
    (preferences.theme === "system" && systemIsDark);
  root.classList.toggle("dark", dark);

  // Data attributes rather than classes for these two, because they are
  // states rather than styles: CSS reads them through `[data-density]`, and
  // anything that needs to branch in JavaScript can read them too without
  // parsing a class list.
  // The palette. `palettes.css` also declares Vital on bare `:root`, so a
  // page rendered before this runs is already complete rather than unstyled —
  // this only switches it.
  root.dataset.palette = preferences.palette;

  root.dataset.density = preferences.density;
  root.dataset.reducedMotion = preferences.reduced_motion ? "true" : "false";

  // Tells the browser which scrollbars and form controls to draw. Without it
  // a dark page keeps light native widgets, which is the detail that makes a
  // dark theme look half-finished.
  root.style.colorScheme = dark ? "dark" : "light";
}

/* -------------------------------------------------------------------------- */
/* Context                                                                     */
/* -------------------------------------------------------------------------- */

interface PreferencesContext {
  preferences: Preferences;
  /** Applied immediately, saved in the background. */
  update: (patch: Partial<Preferences>) => void;
  /** True once the server's answer has replaced the cached guess. */
  loaded: boolean;
}

const Context = createContext<PreferencesContext | null>(null);

export function PreferencesProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [preferences, setPreferences] = useState<Preferences>(cached);
  const [loaded, setLoaded] = useState(false);
  const [systemIsDark, setSystemIsDark] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches,
  );

  // Follow the device while the theme is "system". Somebody whose laptop
  // switches at sunset expects this to switch with it, without a reload.
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    const onChange = (event: MediaQueryListEvent) =>
      setSystemIsDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  // Applied on every change, including the very first render, so the cached
  // guess is on the document before anything is fetched.
  useEffect(() => {
    applyToDocument(preferences, systemIsDark);
    remember(preferences);
  }, [preferences, systemIsDark]);

  // The server's answer, once. Failure is silent on purpose: a signed-out
  // visitor gets a 401 here and should still see a themed login screen rather
  // than an error about preferences.
  useEffect(() => {
    let current = true;
    api
      .get<{ preferences: Preferences }>("/auth/me/")
      .then((body) => {
        if (!current) return;
        setPreferences((existing) => ({ ...existing, ...body.preferences }));
      })
      .catch(() => undefined)
      .finally(() => {
        if (current) setLoaded(true);
      });
    return () => {
      current = false;
    };
  }, []);

  // Saves are debounced and last-write-wins. Dragging a control through three
  // values should send one request, not three -- and if two do overlap, the
  // one that started later is the one whose answer the user is looking at.
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<Partial<Preferences>>({});

  const update = useCallback((patch: Partial<Preferences>) => {
    // Optimistic: the interface changes under the pointer. A theme toggle
    // that waits for a round trip feels broken even when it is fast.
    setPreferences((existing) => ({ ...existing, ...patch }));
    pending.current = { ...pending.current, ...patch };

    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const body = pending.current;
      pending.current = {};
      // Nothing is rolled back on failure. The value is already cached
      // locally and applied; a preference that reverted itself a second
      // after being set would be worse than one that quietly did not sync.
      void api.patch("/auth/me/preferences/", body).catch(() => undefined);
    }, 400);
  }, []);

  const value = useMemo(
    () => ({ preferences, update, loaded }),
    [preferences, update, loaded],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePreferences(): PreferencesContext {
  const context = useContext(Context);
  if (context === null) {
    throw new Error("usePreferences must be used inside PreferencesProvider");
  }
  return context;
}
