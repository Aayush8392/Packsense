export interface TipLine {
  label: string;
  value: string;
  /** A CSS colour for the small swatch before the label, when the line stands for a series. */
  color?: string;
}

export interface TipData {
  /** Where the tip points, in pixels from the top left of the chart. */
  x: number;
  y: number;
  title: string;
  lines: TipLine[];
  note?: string;
}

/**
 * The small box that says what a point, bar, square or region stands for. It follows the pointer or the keyboard cursor, flips to the other side of
 * the point near the right edge, and never takes a click (the figures are also in the readout under the chart and in the table).
 */
export function Tip({ tip, width }: { tip: TipData | null; width: number }) {
  if (tip === null) return null;
  const flip = tip.x > width * 0.55;
  return (
    <div className={`chart-tip${flip ? ' chart-tip--left' : ''}`} style={{ left: tip.x, top: tip.y }} aria-hidden="true">
      <strong className="chart-tip__title">{tip.title}</strong>
      {tip.lines.map((line) => (
        <span className="chart-tip__line" key={line.label}>
          {line.color && <i className="chart-tip__swatch" style={{ background: line.color }} />}
          <span>{line.label}</span>
          <b>{line.value}</b>
        </span>
      ))}
      {tip.note && <span className="chart-tip__note">{tip.note}</span>}
    </div>
  );
}
