import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { LIMITS, checkDay, describeCron, formatAge, formatDuration, jobStatuses, runtimeSeries, serviceStatuses, verdictCounts, verdictFor } from './health';
import { parsePipelineHealth } from './siteData';

// The real health file as published on 30 Oct 2026: 12 days of checks (19 to 30 Oct), taken at 08:40 UTC each day.
const rows = parsePipelineHealth(readFileSync(join(import.meta.dirname, 'fixtures', 'pipeline_health.real.csv'), 'utf-8'));

describe('describeCron', () => {
  it('says a schedule in plain words', () => {
    expect(describeCron('0 45 6 * * ?')).toBe('Every day, 06:45 UTC');
    expect(describeCron('0 0 12 ? * MON')).toBe('Mondays, 12:00 UTC');
    expect(describeCron('0 0 7 ? * THU')).toBe('Thursdays, 07:00 UTC');
    expect(describeCron('0 0 5 1 * ?')).toBe('The 1st of each month, 05:00 UTC');
    expect(describeCron('0 30 10 3 * ?')).toBe('The 3rd of each month, 10:30 UTC');
    expect(describeCron('0 0 5 22 * ?')).toBe('The 22nd of each month, 05:00 UTC');
    expect(describeCron('0 0 5 11 * ?')).toBe('The 11th of each month, 05:00 UTC');
  });
});

describe('verdicts against a job\'s own rhythm', () => {
  it('is on time up to the limit, late up to the next one, then missed', () => {
    expect(verdictFor('daily', 23.7)).toBe('on-time');
    expect(verdictFor('daily', LIMITS.daily.late)).toBe('on-time');
    expect(verdictFor('daily', 31)).toBe('late');
    expect(verdictFor('daily', 72)).toBe('missed');
    expect(verdictFor('weekly', 6 * 24)).toBe('on-time');
    expect(verdictFor('weekly', 9 * 24)).toBe('late');
    expect(verdictFor('weekly', 11 * 24)).toBe('missed');
    expect(verdictFor('monthly', 31 * 24)).toBe('on-time');
    expect(verdictFor('monthly', 36 * 24)).toBe('late');
    expect(verdictFor('monthly', 45 * 24)).toBe('missed');
  });

  it('is not red for a weekly job a few days after its run: a slot is missed only when a whole period and a margin pass', () => {
    expect(verdictFor('weekly', 5 * 24)).toBe('on-time');
    expect(verdictFor('weekly', 7 * 24 + 6)).toBe('on-time');
  });

  it('treats no success in the 30 days the board looks back as missed, except for a monthly job, where it cannot tell', () => {
    expect(verdictFor('daily', null)).toBe('missed');
    expect(verdictFor('weekly', null)).toBe('missed');
    expect(verdictFor('monthly', null)).toBe('unknown');
  });
});

describe('the real board of 30 Oct 2026', () => {
  const statuses = jobStatuses(rows);
  const byName = (name: string) => statuses.find((s) => s.job.name === name)!;

  it('is the check of the newest day, one row for each of the twelve jobs', () => {
    expect(checkDay(rows)).toBe('2026-10-30');
    expect(statuses).toHaveLength(12);
  });

  it('judges each job by its own rhythm: weekly and monthly jobs a few days after a run are on time', () => {
    expect(byName('packsense-snapshots').verdict).toBe('on-time'); // 58 hours, weekly
    expect(byName('packsense-reconcile-candidates').verdict).toBe('on-time');
    expect(byName('packsense-egress-check').verdict).toBe('on-time'); // 214 hours, monthly
    expect(byName('packsense-release').verdict).toBe('on-time');
    expect(byName('packsense-gold-build').verdict).toBe('on-time');
  });

  it('shows what really happened: the three daily jobs that did not run on 28 and 29 Oct are missed, and the weekly load whose Thursday slot fell in those days is late', () => {
    expect(byName('packsense-health').verdict).toBe('missed'); // 72 hours
    expect(byName('packsense-publish').verdict).toBe('missed');
    expect(byName('packsense-reconcile-lookup').verdict).toBe('missed');
    expect(byName('packsense-reconcile-load').verdict).toBe('late'); // 193.7 hours against a weekly limit of 192
    expect(verdictCounts(statuses)).toEqual({ 'on-time': 8, late: 1, missed: 3, unknown: 0 });
  });

  it('counts runs, runs that did not succeed and the longest run over the last 14 days (all twelve days of the file)', () => {
    expect(byName('packsense-bronze-load')).toMatchObject({ runs: 11, notSucceeded: 1, longestSeconds: 1246, when: 'Every day, 06:45 UTC' });
    expect(byName('packsense-gold-build')).toMatchObject({ runs: 20, notSucceeded: 2, longestSeconds: 382 });
    expect(byName('packsense-snapshots')).toMatchObject({ runs: 21, notSucceeded: 14, longestSeconds: 10376 });
    expect(byName('packsense-policy').notSucceeded).toBe(0);
  });

  it('says a time as it reads best', () => {
    expect(formatAge(16.62)).toBe('16.6 hours');
    expect(formatAge(193.66)).toBe('8.1 days');
    expect(formatDuration(78)).toBe('78 seconds');
    expect(formatDuration(1246)).toBe('20.8 minutes');
  });
});

describe('run times', () => {
  it('draws the five daily jobs with the longest runs, longest first, in minutes, with a gap where a day has no run', () => {
    const series = runtimeSeries(rows);
    expect(series.map((s) => s.name)).toEqual(['packsense-bronze-load', 'packsense-publish', 'packsense-gold-build', 'packsense-policy', 'packsense-archive']);
    const bronze = series[0].points;
    expect(Math.max(...bronze.map((p) => p.value ?? 0))).toBeCloseTo(1246 / 60);
    expect(bronze[0].day).toBe('2026-10-19');
    expect(bronze[bronze.length - 1].day).toBe('2026-10-30');
    expect(bronze.some((p) => p.value === null)).toBe(true);
  });
});

describe('outside services', () => {
  it('lists the seven services with the newest answer, the time and the days without an answer', () => {
    const services = serviceStatuses(rows);
    expect(services).toHaveLength(7);
    expect(services.every((s) => s.answered && s.daysWithoutAnswer === 0)).toBe(true);
    const b2 = services.find((s) => s.name.startsWith('Backblaze'))!;
    expect(b2.detail).toBe('HTTP 403');
    expect(services.filter((s) => s.detail === 'HTTP 200')).toHaveLength(6);
    expect(b2.daysChecked).toBe(8);
  });

  it('says what each of the seven real services is for, and every job too', () => {
    for (const service of serviceStatuses(rows)) expect(service.purpose.length, service.name).toBeGreaterThan(20);
    for (const status of jobStatuses(rows)) expect(status.job.purpose.length, status.job.name).toBeGreaterThan(20);
  });

  it('counts a service that did not answer', () => {
    const down = parsePipelineHealth(
      'metric_date,subject,metric,value,unit,detail\n2026-10-29,Svc,reachable,0.0,flag,no answer\n2026-10-30,Svc,reachable,1.0,flag,HTTP 200\n2026-10-30,Svc,response_seconds,0.3,seconds,\n',
    );
    expect(serviceStatuses(down)).toEqual([{ name: 'Svc', purpose: '', detail: 'HTTP 200', answered: true, seconds: 0.3, daysChecked: 2, daysWithoutAnswer: 1 }]);
  });
});
