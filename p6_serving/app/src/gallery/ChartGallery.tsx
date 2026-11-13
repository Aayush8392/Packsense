import { useMemo, useState } from 'react';
import { BarCard } from '../charts/BarCard';
import { ChartCard } from '../charts/ChartCard';
import { DumbbellCard } from '../charts/DumbbellCard';
import { HeatmapCard } from '../charts/HeatmapCard';
import { WaterfallCard } from '../charts/WaterfallCard';
import type { Scope } from '../data/series';
import { buildGallery, startIndex, type GalleryChart, type GalleryData } from './charts';

const UNKNOWN = 'fewer than 5';

function Slide({ chart }: { chart: GalleryChart }) {
  if (chart.kind === 'line') {
    return <ChartCard title={chart.title} note={chart.note} caption={chart.caption} series={chart.series} format={chart.format} form={chart.form} unknownText={UNKNOWN} headingLevel={3} />;
  }
  if (chart.kind === 'dumbbell') {
    return <DumbbellCard title={chart.title} note={chart.note} caption={chart.caption} rows={chart.rows} fromLabel={chart.fromLabel} toLabel={chart.toLabel} valueHeading={chart.valueHeading} format={chart.format} unknownText={UNKNOWN} headingLevel={3} />;
  }
  if (chart.kind === 'heatmap') {
    return <HeatmapCard title={chart.title} note={chart.note} caption={chart.caption} points={chart.points} label={chart.label} format={chart.format} unknownText={UNKNOWN} headingLevel={3} />;
  }
  if (chart.kind === 'waterfall') {
    return <WaterfallCard title={chart.title} note={chart.note} caption={chart.caption} steps={chart.steps} format={chart.format} short={chart.short} valueHeading={chart.valueHeading} headingLevel={3} />;
  }
  return <BarCard title={chart.title} note={chart.note} caption={chart.caption} rows={chart.rows} valueHeading={chart.valueHeading} unknownText={UNKNOWN} headingLevel={3} />;
}

/**
 * The chart gallery as a carousel: one chart at a time, with Previous and Next buttons and a catalogue of every chart by name. It opens on a
 * chart chosen by the day number, so each day starts on a different one and every chart comes round in turn. Every chart is built from the
 * published files by code; the captions are code too.
 */
export function ChartGallery({ data, market, now = new Date() }: { data: GalleryData; market: Scope; now?: Date }) {
  const charts = useMemo(() => buildGallery(data, market), [data, market]);
  const [chosen, setChosen] = useState<number | null>(null);
  if (charts.length === 0) return null;
  const index = Math.min(chosen ?? startIndex(now, charts.length), charts.length - 1);
  const go = (next: number) => setChosen((next + charts.length) % charts.length);
  const chart = charts[index];

  return (
    <section className="gallery" aria-roledescription="carousel" aria-labelledby="gallery-heading">
      <div className="gallery__head">
        <h2 id="gallery-heading" data-focus="section:gallery">More charts</h2>
        <p className="gallery__position" aria-live="polite">
          Chart {index + 1} of {charts.length}
        </p>
      </div>
      <p className="gallery__intro">
        Every chart here is drawn from the published files and described by a program, not written by hand. Each day the gallery opens on a different one.
      </p>
      <div className="gallery__controls">
        <button type="button" className="button button--quiet" onClick={() => go(index - 1)}>
          <span aria-hidden="true">←</span> Previous chart
        </button>
        <button type="button" className="button button--quiet" onClick={() => go(index + 1)}>
          Next chart <span aria-hidden="true">→</span>
        </button>
      </div>
      <ol className="gallery__catalogue" aria-label="All the charts">
        {charts.map((c, i) => (
          <li key={c.id}>
            <button type="button" className="gallery__tab" aria-current={i === index ? 'true' : undefined} onClick={() => go(i)}>
              {c.title}
            </button>
          </li>
        ))}
      </ol>
      <div className="gallery__slide" role="group" aria-roledescription="slide" aria-label={`${index + 1} of ${charts.length}: ${chart.title}`}>
        <Slide key={`${market}-${chart.id}`} chart={chart} />
      </div>
    </section>
  );
}
