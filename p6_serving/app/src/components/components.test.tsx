import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { openExternalInNewTab } from '../content/parse';
import { ExternalLink } from './ExternalLink';

describe('links that leave the site', () => {
  it('open in a new tab and say so', () => {
    render(<ExternalLink href="https://huggingface.co/datasets/PackSense/packsense-india">Data card</ExternalLink>);
    const link = screen.getByRole('link', { name: /Data card/ });
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link.textContent).toContain('(opens in a new tab)');
  });

  it('are marked in page texts, but links inside the site are not', () => {
    const html = openExternalInNewTab('<p><a href="https://openfoodfacts.org">OFF</a> and <a href="/about">About</a></p>');
    expect(html).toContain('<a href="https://openfoodfacts.org" target="_blank" rel="noopener noreferrer">');
    expect(html).toContain('<a href="/about">');
  });
});
