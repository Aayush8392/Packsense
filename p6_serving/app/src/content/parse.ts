import { marked } from 'marked';
import { parse as parseYaml } from 'yaml';

export interface PageMeta {
  slug: string;
  title: string;
  section: string;
  order: number;
  question: string;
  built_from: string;
  status?: string;
  headline?: string;
  checked_claims?: string[];
  design_notes?: string[];
}

export interface Page {
  fileName: string;
  meta: PageMeta;
  /** The body as written (markdown), kept for tests. */
  text: string;
  /** The text of the page's one heading (the first `# ` line). */
  heading: string;
  /** The body rendered to HTML, without the heading. It is our own hand-written text, never visitor input. */
  html: string;
}

const FRONT_MATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/;
const HEADING = /^\s*#\s+(.+?)\s*\r?\n/;
const CELL = /<(td|th)([^>]*)>([\s\S]*?)<\/\1>/g;

function plainText(html: string): string {
  return html.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/"/g, '&quot;').trim();
}

function reshapeRow(row: string, inBody: boolean, labels: string[]): string {
  const cells = [...row.matchAll(CELL)];
  return cells
    .map((cell, i) => {
      const isHeader = cell[1] === 'th' && !inBody;
      const isRowHeader = inBody && i === 0;
      const tag = isRowHeader ? 'th' : cell[1];
      const role = isRowHeader ? 'rowheader' : isHeader ? 'columnheader' : 'cell';
      const scope = isRowHeader ? ' scope="row"' : '';
      const label = inBody && !isRowHeader && labels[i] ? ` data-label="${labels[i]}"` : '';
      const emphasis = i === cells.length - 1 && cells.length > 1 ? ' class="col-emph"' : '';
      return `<${tag}${cell[2]} role="${role}"${scope}${label}${emphasis}>${cell[3]}</${tag}>`;
    })
    .join('');
}

/**
 * A table is shown as a framed card. The first cell of each body row is a row header, and the last column (the one that says
 * what PackSense adds) is marked so the style can set it apart. Each body cell carries its column's name (data-label), because on a
 * narrow screen every row becomes a card that shows the names, and explicit roles keep it a table for screen readers when it does.
 */
export function frameTables(html: string): string {
  return html.replace(/<table>([\s\S]*?)<\/table>/g, (_all, inner: string) => {
    const head = /<thead>([\s\S]*?)<\/thead>/.exec(inner);
    const labels = head ? [...head[1].matchAll(CELL)].map((cell) => plainText(cell[3])) : [];
    const shaped = inner.replace(/<(thead|tbody)>([\s\S]*?)<\/\1>/g, (_part, name: string, rows: string) => {
      const body = rows.replace(/<tr>([\s\S]*?)<\/tr>/g, (_row, row: string) => `<tr role="row">${reshapeRow(row, name === 'tbody', labels)}</tr>`);
      return `<${name} role="rowgroup">${body}</${name}>`;
    });
    return `<div class="table-card"><table role="table">${shaped}</table></div>`;
  });
}

/**
 * After the first section heading, a paragraph that opens with a bold lead-in ("**What PackSense does not claim.** ...") becomes a
 * callout: a titled box with a coloured edge. Paragraphs before the first heading stay as running text.
 */
export function frameCallouts(html: string): string {
  const firstHeading = html.indexOf('<h2>');
  if (firstHeading < 0) return html;
  const rest = html.slice(firstHeading).replace(
    /<p><strong>([^<]+?)\.<\/strong>\s*([\s\S]*?)<\/p>/g,
    (_all, title: string, body: string) => `<aside class="callout"><h3>${title}</h3><p>${body}</p></aside>`,
  );
  return html.slice(0, firstHeading) + rest;
}

/** The top-level blocks (paragraphs, lists, headings, framed tables) of rendered HTML, in order. */
export function splitBlocks(html: string): string[] {
  return html.match(/<(p|ul|ol|h2|h3)>[\s\S]*?<\/\1>|<div class="table-card">[\s\S]*?<\/table><\/div>/g) ?? [];
}

export function parsePage(fileName: string, source: string): Page {
  const match = FRONT_MATTER.exec(source);
  if (!match) throw new Error(`${fileName}: front matter missing`);
  const meta = parseYaml(match[1]) as PageMeta;
  for (const key of ['slug', 'title', 'section', 'order'] as const) {
    if (meta[key] === undefined || meta[key] === '') throw new Error(`${fileName}: front matter has no '${key}'`);
  }
  const text = match[2];
  const headingMatch = HEADING.exec(text);
  if (!headingMatch) throw new Error(`${fileName}: the text has no heading line`);
  const body = text.slice(headingMatch[0].length);
  const rendered = frameTables(marked.parse(body, { async: false, gfm: true }) as string);
  // Home lays out its own bold lead-ins (in its own boxes), so only the other pages get callouts.
  const html = meta.slug === 'home' ? rendered : frameCallouts(rendered);
  return { fileName, meta, text, heading: headingMatch[1], html };
}
