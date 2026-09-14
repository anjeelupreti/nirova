/**
 * An organization's own colour, turned into a complete brand ramp at runtime.
 *
 * The five built-in palettes are solved offline (`styles/tokens/palettes.css`);
 * a colour somebody picks cannot be, so the same arithmetic runs here. Each
 * step that has a job is **solved against the surface it sits on**, never
 * guessed: the 600 step is found by bisection until it clears 4.6:1 on white,
 * and the 400 step until it clears 6.5:1 on the dark card. HSL lightness is not
 * perceived brightness, which is why a fixed ladder cannot do this.
 *
 * **The colour picked is the colour shown.** If text can sit on it -- white or
 * near-black at 4.5:1 -- it is the button exactly as chosen. Only a colour that
 * carries neither (a mid-grey-blue, a pale yellow) falls back to the solved
 * 600 step with white, because an unreadable button is not a brand.
 *
 * Accent, neutrals and status colours are untouched: they come from the
 * `custom` palette block, and chart series never follow the brand at all.
 */

type Rgb = [number, number, number];

/** Every variable this sets, so switching away can remove exactly these. */
export const BRAND_VARIABLES = [
  "--brand-primary",
  "--brand-primary-ink",
  ...[50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((step) => `--brand-${step}`),
] as const;

const WHITE: Rgb = [1, 1, 1];
/** `--neutral-1000` and `--neutral-950` of the custom palette block. */
const NEAR_BLACK: Rgb = [9 / 255, 9 / 255, 10 / 255];
const DARK_CARD: Rgb = [19 / 255, 19 / 255, 21 / 255];
const CHROMA_CEILING = 84;

export function isHexColour(value: string | null | undefined): value is string {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
}

function hexToRgb(hex: string): Rgb {
  const clean = hex.replace("#", "");
  return [0, 2, 4].map((index) => parseInt(clean.slice(index, index + 2), 16) / 255) as Rgb;
}

function rgbToHsl([r, g, b]: Rgb): [number, number, number] {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let s = 0;
  let h = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [h, s * 100, l * 100];
}

function hslToRgb(h: number, s: number, l: number): Rgb {
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const f = (n: number) => light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)];
}

function luminance(rgb: Rgb): number {
  const linear = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const [r, g, b] = rgb.map(linear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: Rgb, b: Rgb): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** The lightness at which this hue first clears `target` against `against`. */
function solveLightness(hue: number, saturation: number, against: Rgb, target: number, darker: boolean): number {
  let low = darker ? 0 : 50;
  let high = darker ? 60 : 100;
  let best = darker ? low : high;
  for (let i = 0; i < 24; i += 1) {
    const mid = (low + high) / 2;
    if (contrast(hslToRgb(hue, saturation, mid), against) >= target) {
      best = mid;
      if (darker) low = mid;
      else high = mid;
    } else if (darker) high = mid;
    else low = mid;
  }
  return best;
}

const triple = (rgb: Rgb): string => {
  const [h, s, l] = rgbToHsl(rgb);
  return `${h.toFixed(0)} ${s.toFixed(1)}% ${l.toFixed(1)}%`;
};

/** CSS variable → `H S% L%`, for `style.setProperty`. `null` for a bad colour. */
export function brandRamp(hex: string): Record<(typeof BRAND_VARIABLES)[number], string> | null {
  if (!isHexColour(hex)) return null;

  const picked = hexToRgb(hex);
  const [hue, rawSaturation] = rgbToHsl(picked);
  const saturation = Math.min(rawSaturation, CHROMA_CEILING);

  const l600 = solveLightness(hue, saturation, WHITE, 4.6, true);
  const l400 = solveLightness(hue, saturation, DARK_CARD, 6.5, false);
  const lightness: Record<number, number> = {
    50: 96.5, 100: 93, 200: 86, 300: Math.max(l400 + 14, 70), 400: l400,
    500: (l400 + l600) / 2, 600: l600, 700: l600 * 0.82, 800: l600 * 0.66,
    900: l600 * 0.53, 950: l600 * 0.36,
  };
  const chroma: Record<number, number> = {
    50: 0.6, 100: 0.72, 200: 0.85, 300: 0.9, 400: 1, 500: 1, 600: 1,
    700: 0.97, 800: 0.92, 900: 0.86, 950: 0.78,
  };
  const neonGuard = (l: number) => 1 - (Math.max(0, l - 55) / 45) * 0.45;

  const steps = {} as Record<number, Rgb>;
  for (const [step, l] of Object.entries(lightness)) {
    steps[Number(step)] = hslToRgb(hue, Math.min(100, saturation * chroma[Number(step)] * neonGuard(l)), l);
  }

  let fill: Rgb = steps[600];
  let ink: Rgb = WHITE;
  if (contrast(WHITE, picked) >= 4.5) {
    fill = picked;
  } else if (contrast(NEAR_BLACK, picked) >= 4.5) {
    fill = picked;
    ink = NEAR_BLACK;
  }

  const out = {
    "--brand-primary": triple(fill),
    "--brand-primary-ink": triple(ink),
  } as Record<(typeof BRAND_VARIABLES)[number], string>;
  for (const [step, rgb] of Object.entries(steps)) {
    out[`--brand-${step}` as (typeof BRAND_VARIABLES)[number]] = triple(rgb);
  }
  return out;
}
