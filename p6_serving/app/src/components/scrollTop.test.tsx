import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ScrollTopButton, pastShare } from './ScrollTopButton';

describe('pastShare', () => {
  it('is true from a twentieth of the way down the part that can be scrolled', () => {
    expect(pastShare(0, 5000, 800)).toBe(false);
    expect(pastShare(209, 5000, 800)).toBe(false); // 5% of 4,200 is 210
    expect(pastShare(210, 5000, 800)).toBe(true);
    expect(pastShare(4200, 5000, 800)).toBe(true);
  });

  it('is never true for a page that fits the window', () => {
    expect(pastShare(0, 700, 800)).toBe(false);
    expect(pastShare(50, 800, 800)).toBe(false);
  });
});

describe('ScrollTopButton', () => {
  const scrollTo = vi.fn();

  const scrollTopTo = (y: number) => {
    Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
    act(() => {
      fireEvent.scroll(window);
    });
  };

  beforeEach(() => {
    Object.defineProperty(document.documentElement, 'scrollHeight', { value: 5000, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
    window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    scrollTo.mockClear();
  });
  afterEach(cleanup);

  it('is not there at the top, appears 5% of the way down and goes again at the top', () => {
    render(<ScrollTopButton />);
    expect(screen.queryByRole('button', { name: 'Back to the top of the page' })).toBeNull();
    scrollTopTo(300);
    expect(screen.getByRole('button', { name: 'Back to the top of the page' })).toBeTruthy();
    scrollTopTo(0);
    expect(screen.queryByRole('button', { name: 'Back to the top of the page' })).toBeNull();
  });

  it('scrolls smoothly to the top and puts the focus on the page', () => {
    document.body.innerHTML = '';
    const main = document.createElement('main');
    main.id = 'main';
    main.tabIndex = -1;
    document.body.append(main);
    render(<ScrollTopButton />, { container: document.body.appendChild(document.createElement('div')) });
    scrollTopTo(1000);
    fireEvent.click(screen.getByRole('button', { name: 'Back to the top of the page' }));
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    expect(document.activeElement).toBe(main);
  });

  it('jumps at once for a visitor who asked for less motion', () => {
    window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined })) as unknown as typeof window.matchMedia;
    render(<ScrollTopButton />);
    scrollTopTo(1000);
    fireEvent.click(screen.getByRole('button', { name: 'Back to the top of the page' }));
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'auto' });
  });
});
