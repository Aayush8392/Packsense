import type { ReactNode } from 'react';

/** A link to another site. It always opens in a new tab (without handing that site a reference to this one), and a screen reader is told so. */
export function ExternalLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return (
    <a className={className} href={href} target="_blank" rel="noopener noreferrer">
      {children}{' '}
      <span className="visually-hidden">(opens in a new tab)</span>
    </a>
  );
}
