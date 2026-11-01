import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import plainNames from './flag-names.json';
import { flagLines, flagName } from './flagNames';

const names = plainNames as Record<string, string>;

/** Every value written under the key `flag` anywhere in the showcase file: the flags of the four real products. */
function showcaseFlags(node: unknown, found = new Set<string>()): Set<string> {
  if (Array.isArray(node)) node.forEach((n) => showcaseFlags(n, found));
  else if (node && typeof node === 'object') {
    for (const [key, value] of Object.entries(node)) {
      if (key === 'flag' && typeof value === 'string') found.add(value);
      else showcaseFlags(value, found);
    }
  }
  return found;
}

describe('plain flag names', () => {
  it('has a written sentence for every tag, each a full sentence on its own', () => {
    const tags = Object.keys(names);
    expect(tags).toHaveLength(22);
    for (const tag of tags) {
      expect(tag).toMatch(/^en:[a-z0-9-]+$/);
      expect(names[tag]).toMatch(/^[A-Z].*[.)]$/);
    }
    expect(new Set(Object.values(names)).size).toBe(tags.length);
  });

  it('explains every flag the four showcase products carry', () => {
    const text = readFileSync(join(import.meta.dirname, '..', '..', '..', 'showcase', 'showcase.json'), 'utf-8');
    const flags = [...showcaseFlags(JSON.parse(text))];
    expect(flags.length).toBeGreaterThan(0);
    expect(flags.filter((f) => !(f in names))).toEqual([]);
  });

  it('shows the sentence with the tag small underneath, and a notice when a tag has no sentence yet', () => {
    const tag = 'en:no-packaging-data';
    expect(flagName(tag)).toEqual({ name: 'No packaging details were entered at all.', plain: true });
    expect(flagLines(tag)).toEqual({ name: 'No packaging details were entered at all.', small: tag });
    expect(flagLines('en:food-groups-warnings')).toEqual({ name: 'Food groups warnings', small: 'Open Food Facts label, not yet explained' });
    expect(flagLines('unmapped').small).toBeNull();
  });
});
