/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },

      // ---------------------------------------------------------------
      // Motion
      // ---------------------------------------------------------------
      // `tailwindcss-animate` was installed and wired in here from the
      // beginning and used by nothing. These are the durations and curves
      // this product moves at, named, so that a transition is a choice
      // between three speeds rather than a number somebody picks.
      //
      // The scale is deliberately short. 150ms for a hover or a colour, so
      // it feels immediate; 200ms for something that slides or resizes,
      // which needs long enough to be followed; 300ms only for something
      // entering the screen for the first time. Anything slower reads as
      // the application being slow, which on a ward is worse than plain.
      transitionDuration: {
        instant: "100ms",
        quick: "150ms",
        moderate: "200ms",
        deliberate: "300ms",
      },
      transitionTimingFunction: {
        // Standard easing for things moving within the screen: quick to
        // leave, gentle to arrive, which is how objects with mass behave.
        smooth: "cubic-bezier(0.4, 0, 0.2, 1)",
        // For something appearing: no acceleration in, so it is at full
        // speed the instant it becomes visible and does not seem to hesitate.
        enter: "cubic-bezier(0, 0, 0.2, 1)",
        // And leaving: no deceleration, so it is gone rather than lingering.
        exit: "cubic-bezier(0.4, 0, 1, 1)",
      },
      keyframes: {
        // A skeleton's shimmer, for the few places a sweep beats a pulse --
        // a single wide element, where the pulse reads as flashing.
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
