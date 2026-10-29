/** WCAG 2.x contrast helpers and a reader for the colour tokens in tokens.css. */

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) throw new Error(`not a 6-digit hex colour: ${hex}`);
  const n = parseInt(m[1], 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function readVars(block: string): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const m of block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) vars[m[1]] = m[2];
  return vars;
}

const SYSTEM_DARK = '@media (prefers-color-scheme: dark)';
const CHOSEN_DARK = ":root[data-theme='dark']";

/**
 * The colour tokens of the light theme, of the dark theme that follows the system setting, and of the dark theme the visitor chose.
 * The two dark sets are laid over the light one, so a token missing from a dark block shows up as the light value.
 */
export function readThemes(css: string): {
  light: Record<string, string>;
  dark: Record<string, string>;
  chosenDark: Record<string, string>;
} {
  const system = css.indexOf(SYSTEM_DARK);
  const chosen = css.indexOf(CHOSEN_DARK);
  if (system < 0 || chosen < 0 || chosen < system) throw new Error('tokens.css needs a system dark block, then a chosen dark block');
  const light = readVars(css.slice(0, system));
  return {
    light,
    dark: { ...light, ...readVars(css.slice(system, chosen)) },
    chosenDark: { ...light, ...readVars(css.slice(chosen)) },
  };
}
