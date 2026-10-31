import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { COLUMN_GUIDE, SAMPLE_COLUMNS } from './columnGuide';
import { parseChangelog, parseColumnFill, parseManifest, parseSample, productsIn, versionRows, type Release } from './release';
import { DataError } from './siteData';

const read = (name: string) => readFileSync(join(import.meta.dirname, 'fixtures', name), 'utf-8');
const manifestText = read('release_manifest.fixture.json');
const changelogText = read('release_changelog.fixture.md');
const datacardText = read('release_datacard.fixture.md');
const sampleText = read('release_sample.fixture.csv');

function whole(): Release {
  return { ...parseManifest(manifestText), changelog: parseChangelog(changelogText), sample: parseSample(sampleText), fill: parseColumnFill(datacardText) };
}

describe('the release files, as the first release wrote them', () => {
  it('reads the version, the build time and the product count from the manifest', () => {
    expect(parseManifest(manifestText)).toMatchObject({ version: '2026-10-22', builtAt: '2026-10-22T12:30:20', products: 24932, sourceDumpDate: '2026-10-22' });
  });

  it('refuses a manifest that is not JSON or lacks the data file', () => {
    expect(() => parseManifest('not json')).toThrow(DataError);
    expect(() => parseManifest(JSON.stringify({ release_version: 'x', built_at_utc: 'y', files: [] }))).toThrow(/missing/);
  });

  it('reads the releases of the changelog, newest first, with their first line', () => {
    const entries = parseChangelog(changelogText);
    expect(entries).toEqual([{ version: '2026-10-22', builtAt: '2026-10-22T12:30:20', summary: 'First release: 24,932 products.' }]);
    expect(productsIn(entries[0].summary)).toBe(24932);
    expect(productsIn('Added 12 and removed 3.')).toBeNull();
  });

  it('reads two releases and keeps their order', () => {
    const text = '# Changelog\n\n## Release 2026-11-03 (2026-11-03T10:30:00 UTC)\n\n40 added, 2 removed.\n\n## Release 2026-10-22 (2026-10-22T12:30:20 UTC)\n\nFirst release: 24,932 products.\n';
    expect(parseChangelog(text).map((e) => e.version)).toEqual(['2026-11-03', '2026-10-22']);
  });

  it('reads how many rows fill each of the 36 columns from the data card', () => {
    const fills = parseColumnFill(datacardText);
    expect(fills).toHaveLength(36);
    expect(fills[0]).toEqual({ column: 'code', rows: 24932, share: 1 });
    const fiber = fills.find((fill) => fill.column === 'fiber');
    expect(fiber?.rows).toBe(5669);
    expect(fiber?.share).toBeCloseTo(0.227, 6);
  });

  it('reads the sample rows, and keeps the barcode as the file wrote it, leading zeros included', () => {
    const sample = parseSample(sampleText);
    expect(sample.rows).toHaveLength(10);
    expect(sample.columns).toHaveLength(36);
    expect(sample.rows[1].code).toBe('00000604');
  });

  it('has a plain sentence for every column of the file, and every sample column exists in it', () => {
    const columns = parseSample(sampleText).columns;
    for (const column of columns) expect(COLUMN_GUIDE[column], column).toBeTruthy();
    for (const column of Object.keys(COLUMN_GUIDE)) expect(columns, column).toContain(column);
    for (const sample of SAMPLE_COLUMNS) expect(columns).toContain(sample.key);
  });

  it('builds the versions table with the manifest count for the latest release', () => {
    expect(versionRows(whole())).toEqual([
      { version: '2026-10-22', builtAt: '2026-10-22T12:30:20', products: 24932, status: 'Latest', summary: 'First release: 24,932 products.' },
    ]);
  });
});
