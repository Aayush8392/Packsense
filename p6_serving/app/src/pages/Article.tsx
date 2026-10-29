import { useEffect } from 'react';
import { pageBySlug } from '../content';

/**
 * One hand-written page of text, framed like the page-02 design: a title block (the heading, then the question the page answers in
 * italics, then a rule) above the text. The text comes from content/, written by the owner, never from visitors.
 */
export function Article({ slug }: { slug: string }) {
  const page = pageBySlug(slug);
  const title = page?.meta.title;

  useEffect(() => {
    if (title) document.title = `${title} — PackSense`;
  }, [title]);

  if (!page) throw new Error(`No page text for '${slug}'`);
  return (
    <article className="article">
      <div className="article__header">
        <h1>{page.heading}</h1>
        {page.meta.question && <p className="article__question">{page.meta.question}</p>}
      </div>
      <div className="prose" dangerouslySetInnerHTML={{ __html: page.html }} />
    </article>
  );
}
