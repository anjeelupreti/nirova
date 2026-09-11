/** @type {import('tailwindcss').Config} */

/*
 * Every colour here resolves to a semantic token from
 * `src/styles/tokens/semantic.css`, never to a primitive and never to a hex.
 *
 * That is what makes the guard in `backend/tests/test_design_tokens.py`
 * enforceable rather than merely aspirational: if a screen needs "the colour
 * for an expiring batch" it has `text-serious` and `<StatusBadge>` available,
 * so reaching for `text-amber-600` is a choice to bypass the system rather than
 * the only thing on offer. There were 325 of those across 29 files, and 277 of
 * them had no `dark:` counterpart at all. The guard is a ratchet: the count may
 * fall and may not rise.
 */
const token = (name) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    extend: {
      fontFamily: {
        sans: "var(--font-sans)",
        display: "var(--font-display)",
        mono: "var(--font-mono)",
      },

      colors: {
        border: token("border"),
        "border-strong": token("border-strong"),
        input: token("input"),
        ring: token("ring"),
        background: token("background"),
        foreground: token("foreground"),

        primary: {
          DEFAULT: token("primary"),
          foreground: token("primary-foreground"),
          subtle: token("primary-subtle"),
          "subtle-foreground": token("primary-subtle-foreground"),
          // The deep step, for brand-coloured *ink* on a light ground — a
          // link, a selected label. Distinct from DEFAULT, which is a fill
          // and is deliberately bright enough that text on it would fail.
          ink: token("primary-ink"),
        },

        /*
         * A deep brand surface for the one banner at the top of a portal or a
         * workspace. Replaces the hand-rolled literal gradients, which ignored
         * the palette and were unreadable in dark mode.
         */
        hero: {
          DEFAULT: token("hero"),
          2: token("hero-2"),
          foreground: token("hero-foreground"),
          muted: token("hero-muted"),
        },

        /*
         * The second voice.
         *
         * One accent used sparingly on grey is not a colour scheme, it is a
         * monochrome with a highlight — which is most of what "boring and dim"
         * described. Each palette carries a complementary hue for the places
         * the brand would be wrong: a secondary series, a highlight that is
         * not an action, the ring on a live indicator.
         *
         * Named `brandaccent` because shadcn's `accent` already means "hover
         * fill" throughout the component layer and renaming that would touch
         * every screen.
         */
        brandaccent: {
          DEFAULT: token("accent-solid"),
          foreground: token("accent-solid-foreground"),
          subtle: token("accent-subtle"),
          "subtle-foreground": token("accent-subtle-foreground"),
          ink: token("accent-ink"),
        },
        secondary: {
          DEFAULT: token("secondary"),
          foreground: token("secondary-foreground"),
        },
        destructive: {
          DEFAULT: token("destructive"),
          foreground: token("destructive-foreground"),
        },
        muted: {
          DEFAULT: token("muted"),
          foreground: token("muted-foreground"),
        },
        accent: {
          DEFAULT: token("accent"),
          foreground: token("accent-foreground"),
        },
        card: {
          DEFAULT: token("card"),
          foreground: token("card-foreground"),
        },
        popover: {
          DEFAULT: token("popover"),
          foreground: token("popover-foreground"),
        },

        /* The application frame: header, sidebar, and the rail's own states. */
        shell: {
          DEFAULT: token("shell"),
          foreground: token("shell-foreground"),
          border: token("shell-border"),
          hover: token("shell-item-hover"),
          active: token("shell-item-active"),
          "active-foreground": token("shell-item-active-foreground"),
          heading: token("shell-heading"),
          // The selected item's tint and ink — brand, not grey. The one place
          // in the chrome where the identity should be unmistakable.
          selected: token("shell-item-selected"),
          "selected-foreground": token("shell-item-selected-foreground"),
        },

        /*
         * Status, each as ink + tint + ink-on-tint. A badge needs all three and
         * every screen that only had the ink invented the other two.
         */
        good: {
          DEFAULT: token("good"),
          subtle: token("good-subtle"),
          "subtle-foreground": token("good-subtle-foreground"),
        },
        warning: {
          DEFAULT: token("warning"),
          subtle: token("warning-subtle"),
          "subtle-foreground": token("warning-subtle-foreground"),
        },
        serious: {
          DEFAULT: token("serious"),
          subtle: token("serious-subtle"),
          "subtle-foreground": token("serious-subtle-foreground"),
        },
        critical: {
          DEFAULT: token("critical"),
          subtle: token("critical-subtle"),
          "subtle-foreground": token("critical-subtle-foreground"),
        },
        info: {
          DEFAULT: token("info"),
          subtle: token("info-subtle"),
          "subtle-foreground": token("info-subtle-foreground"),
        },
        quiet: {
          DEFAULT: token("neutral-signal"),
          subtle: token("neutral-subtle"),
          "subtle-foreground": token("neutral-subtle-foreground"),
        },

        /* Triage acuity. Always rendered beside its number — see primitive.css. */
        acuity: {
          1: token("acuity-1"),
          2: token("acuity-2"),
          3: token("acuity-3"),
          4: token("acuity-4"),
          5: token("acuity-5"),
        },

        /* Chart series, in fixed slot order. Never cycled past 8. */
        series: {
          1: token("series-1"),
          2: token("series-2"),
          3: token("series-3"),
          4: token("series-4"),
          5: token("series-5"),
          6: token("series-6"),
          7: token("series-7"),
          8: token("series-8"),
        },

        /* Sequential magnitude ramp: heatmaps, occupancy, calendar density. */
        scale: {
          1: token("scale-1"),
          2: token("scale-2"),
          3: token("scale-3"),
          4: token("scale-4"),
          5: token("scale-5"),
          6: token("scale-6"),
          7: token("scale-7"),
          8: token("scale-8"),
        },

        chart: {
          grid: token("chart-grid"),
          axis: token("chart-axis"),
          label: token("chart-label"),
          surface: token("chart-surface"),
          emphasis: token("chart-emphasis"),
          recede: token("chart-recede"),
        },
      },

      /*
       * A nesting scale rather than one radius. The outer shape is always
       * larger than the inner one, which is the difference between a card that
       * contains buttons and a rectangle with rectangles on it.
       */
      borderRadius: {
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },

      /*
       * Elevation as four named levels. In dark mode these resolve to hairlines
       * and lighter surfaces rather than shadows — see `semantic.css` — so a
       * component asks for "raised" and gets the right answer in both themes
       * without knowing which theme it is in.
       */
      boxShadow: {
        flat: "var(--elevation-flat)",
        raised: "var(--elevation-raised)",
        floating: "var(--elevation-floating)",
        modal: "var(--elevation-modal)",
      },

      spacing: {
        header: "var(--header-height)",
        sidebar: "var(--sidebar-width)",
        "sidebar-collapsed": "var(--sidebar-width-collapsed)",
      },

      maxWidth: {
        content: "var(--content-max)",
      },

      // ---------------------------------------------------------------
      // Motion
      // ---------------------------------------------------------------
      // The durations and curves this product moves at, named, so that a
      // transition is a choice between three speeds rather than a number
      // somebody picks.
      //
      // The scale is deliberately short. 150ms for a hover or a colour, so it
      // feels immediate; 200ms for something that slides or resizes, which
      // needs long enough to be followed; 300ms only for something entering the
      // screen for the first time. Anything slower reads as the application
      // being slow, which on a ward is worse than plain.
      transitionDuration: {
        instant: "100ms",
        quick: "150ms",
        moderate: "200ms",
        deliberate: "300ms",
      },
      transitionTimingFunction: {
        // Standard easing for things moving within the screen: quick to leave,
        // gentle to arrive, which is how objects with mass behave.
        smooth: "cubic-bezier(0.4, 0, 0.2, 1)",
        // For something appearing: no acceleration in, so it is at full speed
        // the instant it becomes visible and does not seem to hesitate.
        enter: "cubic-bezier(0, 0, 0.2, 1)",
        // And leaving: no deceleration, so it is gone rather than lingering.
        exit: "cubic-bezier(0.4, 0, 1, 1)",
      },
      keyframes: {
        // A skeleton's sweep, for the few places it beats a pulse — a single
        // wide element, where the pulse reads as flashing.
        shimmer: { "100%": { transform: "translateX(100%)" } },
        // The route progress bar: it must never reach the end on its own,
        // because arriving at 100% and then waiting is worse than not knowing.
        // It decelerates towards 90% and the real completion snaps it home.
        creep: {
          "0%": { transform: "scaleX(0.02)" },
          "60%": { transform: "scaleX(0.6)" },
          "100%": { transform: "scaleX(0.9)" },
        },
        // A figure that has just changed, acknowledged rather than animated.
        tick: {
          "0%": { transform: "translateY(0.15em)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        // For a live indicator: a slow breath, not a blink.
        breathe: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        creep: "creep 8s cubic-bezier(0.1, 0.6, 0.2, 1) forwards",
        tick: "tick 200ms cubic-bezier(0, 0, 0.2, 1)",
        breathe: "breathe 2.4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
