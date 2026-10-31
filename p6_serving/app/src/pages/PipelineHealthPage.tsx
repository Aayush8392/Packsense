import { ChartCard } from '../charts/ChartCard';
import type { LineSeries, MarkerKind } from '../charts/LineChart';
import { Headline, LoadState, PageTitle, Panels, TextPanel, pageSections } from '../components/pageParts';
import { JOBS } from '../data/derive';
import {
  VERDICTS, checkDay, describeCron, formatAge, formatDuration, jobStatuses, runtimeSeries, serviceStatuses, verdictCounts, type JobStatus, type ServiceStatus,
} from '../data/health';
import { useResource } from '../data/resource';
import { productsHeld } from '../data/series';
import { pipelineHealth, qualityDaily, type HealthRow } from '../data/siteData';
import { formatCount, formatDay } from '../format';

/** Lines differ by marker and dash as well as colour. */
const LOOKS: { marker: MarkerKind; dash?: string; color: string }[] = [
  { marker: 'circle', color: 'var(--series-1)' },
  { marker: 'triangle', dash: '6 4', color: 'var(--series-2)' },
  { marker: 'diamond', dash: '2 4', color: 'var(--series-3)' },
  { marker: 'square', dash: '10 3 2 3', color: 'var(--series-4)' },
  { marker: 'circle', dash: '4 2', color: 'var(--series-5)' },
];

const minutes = (value: number) => `${Number(value.toFixed(1))} min`;

function JobsTable({ statuses, day }: { statuses: JobStatus[]; day: string }) {
  return (
    <div className="table-card table-card--figures table-card--jobs">
      <table>
        <caption className="visually-hidden">The scheduled jobs and how each did, judged against its own schedule, at the check of {formatDay(day)}</caption>
        <thead>
          <tr>
            <th scope="col">Job</th>
            <th scope="col">What it is for</th>
            <th scope="col">When it runs</th>
            <th scope="col">Status</th>
            <th scope="col">Last success</th>
            <th scope="col">Runs that did not succeed, last 14 days</th>
            <th scope="col">Longest run, last 14 days</th>
          </tr>
        </thead>
        <tbody>
          {statuses.map((status) => {
            const verdict = VERDICTS[status.verdict];
            return (
              <tr key={status.job.name}>
                <th scope="row">{status.job.name.replace('packsense-', '')}</th>
                <td data-label="What it is for">{status.job.purpose}</td>
                <td data-label="When it runs">{status.when}</td>
                <td data-label="Status">
                  <span className={`verdict verdict--${status.verdict}`}>
                    <span aria-hidden="true">{verdict.glyph}</span> {verdict.label}
                  </span>
                </td>
                <td data-label="Last success">{status.hours === null ? 'none in 30 days' : `${formatAge(status.hours)} before the check`}</td>
                <td data-label="Runs that did not succeed, last 14 days">{`${status.notSucceeded} of ${status.runs}`}</td>
                <td data-label="Longest run, last 14 days">{status.longestSeconds === null ? 'not recorded' : formatDuration(status.longestSeconds)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ServicesTable({ services }: { services: ServiceStatus[] }) {
  return (
    <div className="table-card table-card--figures table-card--services">
      <table>
        <caption className="visually-hidden">The outside services the pipeline depends on, from the newest check</caption>
        <thead>
          <tr>
            <th scope="col">Service</th>
            <th scope="col">What it is for</th>
            <th scope="col">Newest answer</th>
            <th scope="col">Time to answer</th>
            <th scope="col">Days without an answer</th>
          </tr>
        </thead>
        <tbody>
          {services.map((service) => (
            <tr key={service.name}>
              <th scope="row">{service.name}</th>
              <td data-label="What it is for">{service.purpose}</td>
              <td data-label="Newest answer">
                {service.answered ? 'Answered' : 'No answer'} ({service.detail})
                {service.detail === 'HTTP 403' && <small className="code"> Expected: this address is up but wants a key, so a refusal is its normal answer.</small>}
              </td>
              <td data-label="Time to answer">{service.seconds === null ? 'not recorded' : `${service.seconds} seconds`}</td>
              <td data-label="Days without an answer">{`${service.daysWithoutAnswer} of ${service.daysChecked}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Board({ rows }: { rows: HealthRow[] }) {
  const day = checkDay(rows);
  const statuses = jobStatuses(rows);
  const quality = useResource(qualityDaily);
  if (day === null || statuses.length === 0) return <p className="data-problem" role="status">There are no health figures yet.</p>;

  const counts = verdictCounts(statuses);
  const services = serviceStatuses(rows);
  const answering = services.filter((service) => service.answered).length;
  const checkTime = describeCron(JOBS.find((job) => job.name === 'packsense-health')?.cron ?? '0 40 8 * * ?');
  const runtime: LineSeries[] = runtimeSeries(rows).map((series, i) => ({
    id: series.name,
    label: series.name.replace('packsense-', ''),
    points: series.points,
    ...LOOKS[i % LOOKS.length],
  }));
  const held = quality.phase === 'ready' ? productsHeld(quality.data, 'all') : [];

  return (
    <>
      <Headline
        range={`Checked once a day. ${checkTime}. Newest check: ${formatDay(day)}`}
        facts={[
          { label: 'Jobs on time', value: `${counts['on-time']} of ${statuses.length}` },
          { label: 'Late, missed or not known', value: String(counts.late + counts.missed + counts.unknown) },
          { label: 'Outside services answering', value: `${answering} of ${services.length}` },
        ]}
      />

      <section className="chart-section" aria-labelledby="jobs-title">
        <h2 id="jobs-title">The scheduled jobs</h2>
        <p className="chart-section__note">
          Each job is judged against its own schedule. A daily job is on time for 30 hours after its last success, a weekly job for 8 days and a monthly job for 33 days. The age is measured at the daily check, not when you read this page.
        </p>
        <JobsTable statuses={statuses} day={day} />
        <ul className="verdict-key">
          {(['on-time', 'late', 'missed', 'unknown'] as const).map((id) => (
            <li key={id}>
              <span className={`verdict verdict--${id}`}><span aria-hidden="true">{VERDICTS[id].glyph}</span> {VERDICTS[id].label}</span> {VERDICTS[id].meaning}
            </li>
          ))}
        </ul>
      </section>

      <section className="chart-section" aria-labelledby="history-title">
        <h2 id="history-title">Run times and products held, day by day</h2>
        <div className="chart-grid chart-grid--two">
          {runtime.length > 0 && (
            <ChartCard
              title="Longest run of each job"
              note="The longest single run of the day, in minutes, for the five daily jobs whose runs are longest. A day with no recorded run is a gap. The table above shows every job."
              series={runtime}
              format={minutes}
              unknownText="no run recorded"
            />
          )}
          {held.length > 0 && (
            <ChartCard
              title="Products held"
              note="How many products PackSense holds each day."
              series={[{ id: 'held', label: 'Products held', points: held, marker: 'square', color: 'var(--secondary)' }]}
              format={formatCount}
              unknownText="not known"
            />
          )}
        </div>
      </section>

      <section className="chart-section" aria-labelledby="services-title">
        <h2 id="services-title">The outside services</h2>
        <p className="chart-section__note">The pipeline depends on these. A service counts as answering when anything comes back, even a refusal.</p>
        <ServicesTable services={services} />
      </section>
    </>
  );
}

export function PipelineHealthPage() {
  const loaded = useResource(pipelineHealth);
  const { intro, sections } = pageSections('pipeline-health');
  return (
    <div className="data-page">
      <PageTitle slug="pipeline-health" />
      <div className="prose" dangerouslySetInnerHTML={{ __html: intro }} />
      {loaded.phase === 'ready' ? <Board rows={loaded.data} /> : <LoadState loaded={[loaded]} />}
      <Panels>
        {sections.map((section, i) => (
          <TextPanel key={section.title} id={`health-panel-${i}`} title={section.title} html={section.html} />
        ))}
      </Panels>
    </div>
  );
}
