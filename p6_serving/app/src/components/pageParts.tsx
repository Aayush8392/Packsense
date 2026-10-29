import { useEffect, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { pageBySlug } from '../content';
import { splitSections } from '../content/parse';
import type { Loaded } from '../data/resource';
import type { Scope } from '../data/series';

/** One choice kept in the address (?name=value), so a link and the back button keep it. The first allowed value is the default and is left out of the address. */
export function useChoice<T extends string>(name: string, allowed: readonly T[]): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const value = allowed.find((option) => option === raw) ?? allowed[0];
  const set = (next: T) => {
    const copy = new URLSearchParams(params);
    if (next === allowed[0]) copy.delete(name);
    else copy.set(name, next);
    // keepScroll: changing a choice on the page is not going to another page, so the page must stay where it is.
    setParams(copy, { replace: true, state: { keepScroll: true } });
  };
  return [value, set];
}

/** The market the page shows. */
export function useMarket(): [Scope, (next: Scope) => void] {
  return useChoice<Scope>('market', ['all', 'india']);
}

/** A small set of exclusive choices drawn as one control (a radio group). */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button key={option.id} type="button" role="radio" aria-checked={value === option.id} className="segmented__option" onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function MarketSwitch({ market, onChange }: { market: Scope; onChange: (next: Scope) => void }) {
  return (
    <Segmented
      label="Which products to count"
      value={market}
      onChange={onChange}
      options={[
        { id: 'all', label: 'All markets' },
        { id: 'india', label: 'India' },
      ]}
    />
  );
}

/** The title block of a page: its heading, the question it answers and a rule, as on every page. */
export function PageTitle({ slug }: { slug: string }) {
  const page = pageBySlug(slug);
  const title = page?.meta.title;
  useEffect(() => {
    if (title) document.title = `${title} — PackSense`;
  }, [title]);
  if (!page) throw new Error(`No page text for '${slug}'`);
  return (
    <div className="article__header">
      <h1>{page.heading}</h1>
      {page.meta.question && <p className="article__question">{page.meta.question}</p>}
    </div>
  );
}

/** The text of a page cut into its introduction and its sections, which pages lay out as panels. */
export function pageSections(slug: string) {
  const page = pageBySlug(slug);
  if (!page) throw new Error(`No page text for '${slug}'`);
  return splitSections(page.html);
}

/** A section of the page text as a panel. Inside a block that already has its own heading it is not a landmark of its own (two would share a name). */
export function TextPanel({ title, html, id, landmark = true }: { title: string; html: string; id?: string; landmark?: boolean }) {
  const Box = landmark ? 'section' : 'div';
  return (
    <Box className="text-panel" aria-labelledby={landmark ? id : undefined}>
      <h2 id={id}>{title}</h2>
      <div className="prose" dangerouslySetInnerHTML={{ __html: html }} />
    </Box>
  );
}

/** Headline facts computed from the data, in one box with the date range. */
export function Headline({ range, facts }: { range: string; facts: { label: string; value: string }[] }) {
  return (
    <section className="headline" aria-label="Headline">
      <p className="headline__range">{range}</p>
      <dl>
        {facts.map((fact) => (
          <div key={fact.label}>
            <dt>{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** What a page shows while its files load or when they could not be loaded. */
export function LoadState({ loaded }: { loaded: Loaded<unknown>[] }) {
  if (loaded.some((l) => l.phase === 'error')) {
    return (
      <p className="data-problem" role="status">
        The figures on this page could not be loaded just now. Please try again in a little while.
      </p>
    );
  }
  return (
    <p className="data-loading" role="status">
      Loading the figures…
    </p>
  );
}

export function Panels({ children }: { children: ReactNode }) {
  return <div className="panels">{children}</div>;
}
