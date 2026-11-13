import { scaleLinear } from 'd3-scale';
import { line } from 'd3-shape';
import type { PointerEvent } from 'react';
import type { LineSeries } from './LineChart';
import { clampStart } from './window';

/**
 * A thin picture of the whole history under a chart, on its own fixed scale, with the part now in view marked. Pressing or dragging on it moves
 * the window. It is a pointer shortcut only: the "earlier" and "later" buttons and the keyboard do the same, so it is hidden from a screen reader.
 */
export function Overview({ series, first, shown, width, unit, onStart }: {
  series: LineSeries[];
  first: number;
  shown: number;
  width: number;
  unit: number;
  onStart: (start: number) => void;
}) {
  const total = series[0]?.points.length ?? 0;
  const height = Math.round(unit * 2);
  const high = Math.max(0, ...series.flatMap((s) => s.points.map((p) => p.value ?? 0)));
  const x = scaleLinear().domain([0, Math.max(total - 1, 1)]).range([0, width]);
  const y = scaleLinear().domain([0, high === 0 ? 1 : high]).range([height - 2, 2]);
  const path = line<{ i: number; value: number | null }>().defined((p) => p.value !== null).x((p) => x(p.i)).y((p) => y(p.value as number));
  const left = x(first);
  const right = x(Math.min(first + shown - 1, total - 1));

  const place = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width === 0) return;
    const centre = Math.round(((event.clientX - box.left) / box.width) * (total - 1));
    onStart(clampStart(centre - Math.floor(shown / 2), total, shown));
  };

  return (
    <svg className="chart__overview" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
      <rect className="chart__overview-window" x={left} y={0} width={Math.max(right - left, 2)} height={height} />
      {series.map((s) => (
        <path key={s.id} d={path(s.points.map((p, i) => ({ i, value: p.value }))) ?? ''} fill="none" stroke={s.color} strokeWidth={1.25} strokeDasharray={s.dash} />
      ))}
      <rect
        className="chart__overview-hit"
        width={width}
        height={height}
        fill="transparent"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          place(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) place(event);
        }}
      />
    </svg>
  );
}
