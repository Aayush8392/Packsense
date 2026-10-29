import plainNames from './flag-names.json';

/**
 * Plain-language names for kinds of flag, written by the owner in flag-names.json (tag -> name). Until a name is written, the Open Food Facts
 * tag is made readable ("en:food-groups-warnings" becomes "Food groups warnings") and the page says these are OFF's own names.
 */
export function readableTag(tag: string): string {
  const bare = tag.replace(/^[a-z]{2}:/, '').replace(/-/g, ' ').trim();
  return bare.charAt(0).toUpperCase() + bare.slice(1);
}

export interface FlagName {
  name: string;
  /** True when the owner wrote the name; false when it is OFF's tag made readable. */
  plain: boolean;
}

export function flagName(tag: string): FlagName {
  if (tag === 'unmapped') return { name: "Flags that Open Food Facts does not list by name", plain: true };
  const written = (plainNames as Record<string, string>)[tag];
  return written ? { name: written, plain: true } : { name: readableTag(tag), plain: false };
}
