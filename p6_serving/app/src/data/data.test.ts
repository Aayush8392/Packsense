import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseCsv } from './csv';
import { dailyJobsVerdict, editsOnDay, JOBS, nextUpdateDue, rightNow } from './derive';
import { DataError, fetchText, parseChangeDaily, parsePipelineHealth, parseSiteStatus, type HealthRow } from './siteData';
import { addDays, describeMoment, formatCount, formatDay, formatPerProduct } from '../format';

// Real rows of the published files: the change file from the gold fixture (1 to 15 Oct 2026) and the health file from the collector's real output.
const fixture = (name: string) => readFileSync(join(import.meta.dirname, 'fixtures', name), 'utf-8');

describe('parseCsv', () => {
  it('reads a header and rows', () => {
    expect(parseCsv('a,b\n1,2\n3,4\n')).toEqual([{ a: '1', b: '2' }, { a: '3', b: '4' }]);
  });

  it('reads quoted fields with commas, doubled quotes and line breaks, and Windows line ends', () => {
    expect(parseCsv('a,b\r\n"x, y","say ""hi"""\r\n"two\nlines",z\r\n')).toEqual([
      { a: 'x, y', b: 'say "hi"' },
      { a: 'two\nlines', b: 'z' },
    ]);
  });

  it('keeps an empty cell as an empty string and ignores blank lines', () => {
    expect(parseCsv('a,b,c\n1,,3\n\n')).toEqual([{ a: '1', b: '', c: '3' }]);
  });

  it('returns no rows for no text', () => {
    expect(parseCsv('')).toEqual([]);
  });
});

describe('the published files', () => {
  it('reads the status file', () => {
    const status = parseSiteStatus(
      'built_at_utc,first_complete_day,last_complete_day,products_held_all,products_held_india\n2026-10-28T09:01:00,2026-10-01,2026-10-27,155134,24932\n',
    );
    expect(status).toEqual({
      builtAt: '2026-10-28T09:01:00',
      firstCompleteDay: '2026-10-01',
      lastCompleteDay: '2026-10-27',
      productsAll: 155134,
      productsIndia: 24932,
    });
  });

  it('names the file and the column when one is missing, and refuses an empty file', () => {
    expect(() => parseSiteStatus('built_at_utc\nx\n')).toThrow(/site_status.csv is missing the column/);
    expect(() => parseChangeDaily('')).toThrow(/change_daily.csv has no rows/);
  });

  it('reads the real change file: 145 rows, the "any" group present, counts as numbers', () => {
    const rows = parseChangeDaily(fixture('change_daily.sample.csv'));
    expect(rows).toHaveLength(145);
    expect(rows.some((r) => r.group === 'any')).toBe(true);
    expect(rows.every((r) => r.products === null || Number.isInteger(r.products))).toBe(true);
  });

  it('treats a blank count as hidden (a count of 1 to 4), not as zero', () => {
    const rows = parseChangeDaily('change_date,scope,change_group,opened_by_seed,n_products,n_periods,unseen_edits\n2026-10-01,all,any,0,,,0\n');
    expect(rows[0].products).toBeNull();
  });

  it('reads the real health file: 81 rows with the three right-now times', () => {
    const rows = parsePipelineHealth(fixture('pipeline_health.sample.csv'));
    expect(rows).toHaveLength(81);
    expect(rows.filter((r) => r.subject === 'pipeline')).toHaveLength(3);
  });

  it('refuses text that is not a number where a number belongs', () => {
    expect(() => parsePipelineHealth('metric_date,subject,metric,value,unit,detail\n2026-10-01,a,b,not-a-number,u,\n')).toThrow(DataError);
  });
});

describe('fetchText', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('refuses a page that is not data (a server that answers every address with its home page)', async () => {
    vi.stubGlobal('fetch', async () => new Response('<!doctype html><html></html>', { status: 200 }));
    await expect(fetchText('site_status.csv')).rejects.toThrow(/is not a data file/);
  });

  it('names the file and the status when the file is missing', async () => {
    vi.stubGlobal('fetch', async () => new Response('', { status: 404 }));
    await expect(fetchText('site_status.csv')).rejects.toThrow(/could not be loaded \(404\)/);
  });

  it('says so when the network fails', async () => {
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('network');
    });
    await expect(fetchText('site_status.csv')).rejects.toThrow(/could not be reached/);
  });
});

describe('derived figures', () => {
  const changes = parseChangeDaily(fixture('change_daily.sample.csv'));
  const health = parsePipelineHealth(fixture('pipeline_health.sample.csv'));

  it('takes the products edited on a day from the "any" row, per scope (real values for 15 Oct)', () => {
    expect(editsOnDay(changes, '2026-10-15')).toBe(13);
    expect(editsOnDay(changes, '2026-10-15', 'india')).toBe(8);
  });

  it('returns null for a day that is not there, and for a hidden count', () => {
    expect(editsOnDay(changes, '2030-01-01')).toBeNull();
    const hidden = parseChangeDaily('change_date,scope,change_group,opened_by_seed,n_products,n_periods,unseen_edits\n2026-10-01,all,any,0,,,0\n');
    expect(editsOnDay(hidden, '2026-10-01')).toBeNull();
  });

  it('reads the right-now times of the real first run (23 Oct 2026, UTC)', () => {
    const moments = rightNow(health);
    expect(moments.offFilePublished?.toISOString()).toBe('2026-10-23T06:31:15.000Z');
    expect(moments.ourCopyReceived?.toISOString()).toBe('2026-10-23T06:45:34.000Z');
  });

  it('has no right-now times when the table has none', () => {
    expect(rightNow([])).toEqual({ offFilePublished: null, ourCopyReceived: null });
  });

  it('keeps the daily jobs list in step with the collector (checked in p6_serving/tests too)', () => {
    expect(JOBS.filter((job) => job.cadence === 'daily')).toHaveLength(7);
    expect(JOBS).toHaveLength(12);
  });

  describe('daily jobs verdict', () => {
    const daily = JOBS.filter((job) => job.cadence === 'daily').map((job) => job.name);
    const rows = (day: string, ran: Record<string, [number, number]>): HealthRow[] =>
      daily.flatMap((name) => {
        const [runs, failed] = ran[name] ?? [1, 0];
        return [
          { day, subject: name, metric: 'runs', value: runs, unit: 'runs', detail: '' },
          { day, subject: name, metric: 'failed_runs', value: failed, unit: 'runs', detail: '' },
        ];
      });

    it('judges the newest COMPLETE day, not the day still in progress', () => {
      const table = [...rows('2026-10-26', {}), ...rows('2026-10-27', { 'packsense-publish': [0, 0] })];
      const verdict = dailyJobsVerdict(table);
      expect(verdict?.day).toBe('2026-10-26');
      expect(verdict?.missing).toEqual([]);
      expect(verdict?.failed).toEqual([]);
    });

    it('lists jobs that did not run and jobs that ran and failed', () => {
      const table = [
        ...rows('2026-10-26', { 'packsense-publish': [0, 0], 'packsense-archive': [2, 1] }),
        ...rows('2026-10-27', {}),
      ];
      const verdict = dailyJobsVerdict(table);
      expect(verdict?.missing).toEqual(['packsense-publish']);
      expect(verdict?.failed).toEqual(['packsense-archive']);
      expect(verdict?.expected).toBe(7);
    });

    it('says nothing when the table has no earlier complete day', () => {
      expect(dailyJobsVerdict(rows('2026-10-27', {}))).toBeNull();
      expect(dailyJobsVerdict([])).toBeNull();
    });
  });

  it('says when the next update is due, in plain words', () => {
    expect(nextUpdateDue(new Date('2026-10-28T05:00:00Z'))).toBe('today, about 06:45 UTC');
    expect(nextUpdateDue(new Date('2026-10-28T06:45:00Z'))).toBe('tomorrow, about 06:45 UTC');
    expect(nextUpdateDue(new Date('2026-10-28T17:00:00Z'))).toBe('tomorrow, about 06:45 UTC');
  });
});

describe('formats', () => {
  it('writes counts, days and moments in plain words', () => {
    expect(formatCount(155134)).toBe('155,134');
    expect(formatDay('2026-10-27')).toBe('27 Oct 2026');
    const now = new Date('2026-10-28T12:00:00Z');
    expect(describeMoment(new Date('2026-10-28T06:31:15Z'), now)).toBe('today, 06:31 UTC');
    expect(describeMoment(new Date('2026-10-27T06:31:15Z'), now)).toBe('yesterday, 06:31 UTC');
    expect(describeMoment(new Date('2026-10-23T06:31:15Z'), now)).toBe('23 Oct, 06:31 UTC');
  });

  it('keeps small flags-per-product values apart on an axis (0.05 is not 0.1)', () => {
    expect([0, 0.05, 0.1, 0.15].map(formatPerProduct)).toEqual(['0.00', '0.05', '0.10', '0.15']);
    expect([1, 2, 9.43, 10].map(formatPerProduct)).toEqual(['1', '2', '9.4', '10']);
  });

  it('steps a day across a month end', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
  });
});
