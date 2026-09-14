/**
 * How the console looks, in one place.
 *
 * **It was in three.** The palette picker sat on Settings, the same choices
 * were repeated as drop-downs on My account, and the account menu offered the
 * mode a third time. Three controls for one preference is three places to
 * wonder which one wins. This is the one; the account menu keeps only the
 * light switch, because mode is the preference people change *because of the
 * room they are in*.
 *
 * Each swatch previews the real thing: the actual `--brand-*` and `--accent-*`
 * values of that palette, read straight from the stylesheet. A picker that
 * shows approximations is a picker that lies.
 */

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { isHexColour } from "@/lib/brandRamp";
import { Icon, type IconName } from "@/components/ui/icon";
import { Section } from "@/components/ui/layout";
import { PALETTES, usePreferences, type Palette } from "@/hooks/usePreferences";

/** The preference keys this card owns, so the generic list does not repeat them. */
export const APPEARANCE_KEYS = ["theme", "palette", "brand_color", "density"] as const;

export function AppearanceCard() {
  const { preferences, update } = usePreferences();

  return (
    <Section
      title="Appearance"
      description="Applies immediately, and follows you to any machine you sign in on. Every palette is contrast-checked in light and dark."
    >
      <div className="rounded-lg border bg-card p-4 shadow-raised">
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {PALETTES.map((palette) => (
            <PaletteSwatch
              key={palette.value}
              palette={palette}
              selected={preferences.palette === palette.value}
              onSelect={() => update({ palette: palette.value })}
            />
          ))}
          <CustomSwatch />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 border-t pt-4">
          <ModeToggle />
          <DensityToggle />
        </div>
      </div>
    </Section>
  );
}

function PaletteSwatch({
  palette,
  selected,
  onSelect,
}: {
  palette: { value: Palette; label: string; blurb: string };
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      // `data-palette` on the button itself, so the swatch resolves the tokens
      // of the palette it *represents* rather than the one currently applied.
      data-palette={palette.value}
      className={cn(
        "group flex flex-col gap-2.5 rounded-lg border p-3 text-left transition-all duration-quick ease-smooth",
        selected
          ? "border-primary ring-2 ring-primary/30"
          : "border-border hover:border-border-strong",
      )}
    >
      <span className="flex h-10 overflow-hidden rounded-md">
        <span className="flex-[2]" style={{ background: "hsl(var(--brand-primary))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--brand-300))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--brand-700))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--accent-500))" }} />
        <span className="flex-1" style={{ background: "hsl(var(--neutral-200))" }} />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          {palette.label}
          {selected ? <Icon name="confirm" size="xs" className="text-primary" /> : null}
        </span>
        <span className="mt-0.5 block truncate type-caption">{palette.blurb}</span>
      </span>
    </button>
  );
}

export function ModeToggle() {
  const { preferences, update } = usePreferences();
  const options = [
    { value: "system", label: "Match device", icon: "meter" as IconName },
    { value: "light", label: "Light", icon: "themeLight" as IconName },
    { value: "dark", label: "Dark", icon: "themeDark" as IconName },
  ] as const;

  return (
    <div className="flex items-center gap-2.5">
      <span className="type-label text-muted-foreground">Mode</span>
      <div className="inline-flex rounded-lg bg-muted p-1">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => update({ theme: option.value })}
            aria-pressed={preferences.theme === option.value}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-quick",
              preferences.theme === option.value
                ? "bg-card text-foreground shadow-raised"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon name={option.icon} size="xs" />
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function DensityToggle() {
  const { preferences, update } = usePreferences();

  return (
    <div className="flex items-center gap-2.5">
      <span className="type-label text-muted-foreground">Row height</span>
      <div className="inline-flex rounded-lg bg-muted p-1">
        {(["comfortable", "compact"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => update({ density: value })}
            aria-pressed={preferences.density === value}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors duration-quick",
              preferences.density === value
                ? "bg-card text-foreground shadow-raised"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {value}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Your own colour. The picker fires on every movement of the cursor, so the
 * preview updates live but the preference is saved once the hand stops.
 */
function CustomSwatch() {
  const { preferences, update } = usePreferences();
  const selected = preferences.palette === "custom";
  const saved = isHexColour(preferences.brand_color) ? preferences.brand_color : "#2563EB";
  const [colour, setColour] = useState(saved);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => setColour(saved), [saved]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const choose = (next: string) => {
    setColour(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(
      () => update({ palette: "custom", brand_color: next.toUpperCase() }),
      350,
    );
  };

  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 rounded-lg border p-3 text-left transition-all duration-quick ease-smooth",
        selected ? "border-primary ring-2 ring-primary/30" : "border-border hover:border-border-strong",
      )}
    >
      <label className="relative block h-10 cursor-pointer overflow-hidden rounded-md">
        <span className="absolute inset-0" style={{ background: colour }} />
        <input
          type="color"
          aria-label="Choose your colour"
          value={colour}
          onChange={(event) => choose(event.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
      </label>
      <button
        type="button"
        onClick={() => update({ palette: "custom", brand_color: colour.toUpperCase() })}
        aria-pressed={selected}
        className="min-w-0 text-left"
      >
        <span className="flex items-center gap-1.5 text-sm font-medium">
          Custom
          {selected ? <Icon name="confirm" size="xs" className="text-primary" /> : null}
        </span>
        <span className="mt-0.5 block truncate type-caption">
          {selected ? colour.toUpperCase() : "Your organization's colour"}
        </span>
      </button>
    </div>
  );
}
