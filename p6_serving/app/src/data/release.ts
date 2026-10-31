import { parseCsv } from './csv';
import { createResource } from './resource';
import { DataError, dataUrl } from './siteData';
import { JOBS } from './derive';
import { describeCron } from './health';

/** Where the release lives. The download links go straight to the public Hugging Face repository. */
export const RELEASE_REPO = 'https://huggingface.co/datasets/PackSense/packsense-india';
export const RELEASE_FILE_URL = `${RELEASE_REPO}/resolve/main/india_products.csv`;

export interface ChangelogEntry {
  version: string;
  builtAt: string;
  /** The first line the changelog writes under the release. */
  summary: string;
}

export interface ColumnFill {
  column: string;
  rows: number;
  /** Share of the rows that have a value, 0 to 1. */
  share: number;
}

export interface Release {
  version: string;
  builtAt: string;
  products: number;
  sourceDumpDate: string;
  attribution: string;
  changelog: ChangelogEntry[];
  /** The first rows of the data file, as the file writes them. */
  sample: { columns: string[]; rows: Record<string, string>[] };
  fill: ColumnFill[];
}

/** The page's three outcomes besides loading: nothing published yet, or a release. A file that cannot be read is an error, not a state. */
export type ReleaseState = { published: false } | { published: true; release: Release };

export function parseManifest(text: string): { version: string; builtAt: string; products: number; sourceDumpDate: string; attribution: string } {
  let manifest: unknown;
  try {
    manifest = JSON.parse(text);
  } catch {
    throw new DataError('release_manifest.json is not valid JSON');
  }
  const m = manifest as Record<string, unknown>;
  const files = Array.isArray(m?.files) ? (m.files as Record<string, unknown>[]) : [];
  const data = files.find((file) => file.kind === 'data');
  if (typeof m?.release_version !== 'string' || typeof m.built_at_utc !== 'string' || !data || typeof data.rows !== 'number') {
    throw new DataError('release_manifest.json is missing the version, the build time or the data file');
  }
  return {
    version: m.release_version,
    builtAt: m.built_at_utc,
    products: data.rows,
    sourceDumpDate: typeof m.source_dump_date === 'string' ? m.source_dump_date : '',
    attribution: typeof m.attribution === 'string' ? m.attribution : '',
  };
}

/** The changelog is one section for each release, newest first: "## Release 2026-10-22 (2026-10-22T12:30:20 UTC)" and then its text. */
export function parseChangelog(text: string): ChangelogEntry[] {
  const entries: ChangelogEntry[] = [];
  let current: ChangelogEntry | null = null;
  for (const line of text.split(/\r?\n/)) {
    const heading = /^##\s+Release\s+(\S+)\s+\(([^)]*?)(?:\s+UTC)?\)\s*$/.exec(line);
    if (heading) {
      current = { version: heading[1], builtAt: heading[2], summary: '' };
      entries.push(current);
    } else if (current && current.summary === '' && line.trim() !== '' && !line.startsWith('#')) {
      current.summary = line.trim();
    }
  }
  return entries;
}

/** The "columns" table of the data card: how many rows have a value in each column. */
export function parseColumnFill(text: string): ColumnFill[] {
  const fills: ColumnFill[] = [];
  for (const line of text.split(/\r?\n/)) {
    const m = /^\|\s*`([a-z0-9_]+)`\s*\|\s*([\d,]+)\s*\|\s*([\d.]+)%\s*\|\s*$/.exec(line);
    if (m) fills.push({ column: m[1], rows: Number(m[2].replace(/,/g, '')), share: Number(m[3]) / 100 });
  }
  return fills;
}

export function parseSample(text: string): Release['sample'] {
  const rows = parseCsv(text);
  if (rows.length === 0) throw new DataError('india_sample.csv has no rows');
  return { columns: Object.keys(rows[0]), rows };
}

/** The number of products a changelog line mentions ("First release: 24,932 products."), or null. */
export function productsIn(summary: string): number | null {
  const m = /([\d,]+)\s+products/.exec(summary);
  return m ? Number(m[1].replace(/,/g, '')) : null;
}

export interface VersionRow {
  version: string;
  builtAt: string;
  products: number | null;
  status: 'Latest' | 'Earlier';
  summary: string;
}

/** The versions table: the changelog's releases, newest first, with the manifest's count for the latest. */
export function versionRows(release: Release): VersionRow[] {
  return release.changelog.map((entry, i) => ({
    version: entry.version,
    builtAt: entry.builtAt,
    products: i === 0 ? release.products : productsIn(entry.summary),
    status: i === 0 ? 'Latest' : 'Earlier',
    summary: entry.summary,
  }));
}

/** When the next release is built, written from the monthly job's own schedule. */
export function releaseSchedule(): string {
  const job = JOBS.find((entry) => entry.name === 'packsense-release');
  return job ? describeCron(job.cron) : '';
}

/** One published file, or null when the server says it is not there. */
async function fetchOptional(name: string): Promise<string | null> {
  let response: Response;
  try {
    response = await fetch(dataUrl(name));
  } catch {
    throw new DataError(`${name} could not be reached`);
  }
  if (response.status === 404) return null;
  if (!response.ok) throw new DataError(`${name} could not be loaded (${response.status})`);
  const text = await response.text();
  // A server that answers an unknown file with its home page must not be mistaken for a file.
  if (/^\s*<(!doctype|html)/i.test(text)) return null;
  return text;
}

async function fetchRequired(name: string): Promise<string> {
  const text = await fetchOptional(name);
  if (text === null) throw new DataError(`${name} could not be found`);
  return text;
}

export async function loadRelease(): Promise<ReleaseState> {
  const manifestText = await fetchOptional('release/release_manifest.json');
  if (manifestText === null) return { published: false };
  const manifest = parseManifest(manifestText);
  const [changelog, datacard, sample] = await Promise.all([
    fetchRequired('release/CHANGELOG.md'),
    fetchRequired('release/README.md'),
    fetchRequired('release/india_sample.csv'),
  ]);
  const entries = parseChangelog(changelog);
  if (entries.length === 0) throw new DataError('CHANGELOG.md lists no release');
  return {
    published: true,
    release: { ...manifest, changelog: entries, sample: parseSample(sample), fill: parseColumnFill(datacard) },
  };
}

export const release = createResource(loadRelease);
