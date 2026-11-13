import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigationType } from 'react-router';
import { TABS, pageForPath, pagesInTab, tabById, type TabId } from '../nav';
import { ChatWidget } from '../lookup/ChatWidget';
import { getTrail, popStep, startFreshView } from '../nav/jumpStore';
import { AskToggle } from './AskToggle';
import { BackButton } from './BackButton';
import { ScrollTopButton } from './ScrollTopButton';
import { Footer } from './Footer';
import { ThemeToggle } from './ThemeToggle';

function Breadcrumb() {
  const { pathname } = useLocation();
  const page = pageForPath(pathname);
  if (!page || page.tab === 'home') return null;
  const tab = tabById(page.tab);
  const sameAsTab = pagesInTab(page.tab).length === 1;
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        <li><Link to="/">Home</Link></li>
        <li>{sameAsTab ? <span aria-current="page">{tab.label}</span> : <Link to={tab.path}>{tab.label}</Link>}</li>
        {!sameAsTab && <li><span aria-current="page">{page.label}</span></li>}
      </ol>
    </nav>
  );
}

function SubNav({ tab }: { tab: TabId | undefined }) {
  const pages = tab ? pagesInTab(tab) : [];
  if (pages.length < 2) return null;
  return (
    <nav className="subnav" aria-label={`${tabById(tab as TabId).label} pages`}>
      <ul className="container">
        {pages.map((page) => (
          <li key={page.slug}>
            <NavLink to={page.path} end>{page.label}</NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** Scrolls to a height the visitor had reached, waiting (up to three seconds) until the page is long enough, because its data may still be arriving. */
function restoreScroll(target: number): () => void {
  let frame = 0;
  const started = Date.now();
  const step = () => {
    const tall = document.documentElement.scrollHeight >= target + window.innerHeight - 4;
    if (tall || Date.now() - started > 3000) {
      window.scrollTo(0, target);
      return;
    }
    frame = requestAnimationFrame(step);
  };
  step();
  return () => cancelAnimationFrame(frame);
}

/** Scrolls to the part of the page marked `data-focus="<value>"` and flashes it, waiting (up to four seconds) for the page's data to put it there. */
function bringIntoView(value: string): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const started = Date.now();
  const look = () => {
    const found = Array.from(document.querySelectorAll<HTMLElement>('[data-focus]')).find((el) => el.dataset.focus === value);
    if (found) {
      found.scrollIntoView({ block: 'center', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      found.classList.add('focus-flash');
      timer = setTimeout(() => found.classList.remove('focus-flash'), 2600);
      return;
    }
    if (Date.now() - started < 4000) timer = setTimeout(look, 120);
  };
  look();
  return () => clearTimeout(timer);
}

/** A click on a link that stays in the app and is not a jump (the menu, the logo, the breadcrumb, a link in a text) starts a fresh view. */
function freshViewOnLinkClick(event: React.MouseEvent) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = (event.target as HTMLElement).closest('a');
  if (!link || link.hasAttribute('data-jump') || link.target === '_blank') return;
  const href = link.getAttribute('href') ?? '';
  if (href === '' || href.startsWith('#') || /^[a-z]+:/i.test(href)) return;
  startFreshView();
}

export function Shell() {
  const location = useLocation();
  const current = pageForPath(location.pathname);
  const tab = current?.tab;
  // The menu is open for one address only, so going anywhere else closes it without an effect.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const menuOpen = openAt === location.pathname;
  const menuButton = useRef<HTMLButtonElement>(null);
  const main = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  // After a navigation inside the app: go to the very top (or, coming Back, to where the visitor was; or, after a jump, to the part that was clicked), and move
  // focus to the page so a screen reader starts reading it. Focus must not scroll: it would put the top of the page under the sticky header.
  const navigationType = useNavigationType();
  useEffect(() => {
    // The browser's own Back button returning to the page on top of the trail counts as using the trail.
    if (navigationType === 'POP') {
      const trail = getTrail();
      const top = trail[trail.length - 1];
      if (top && top.path === `${location.pathname}${location.search}`) popStep();
    }
    if (firstRender.current) {
      firstRender.current = false;
      const focus = new URLSearchParams(location.search).get('focus');
      if (focus) return bringIntoView(focus);
      return;
    }
    const state = location.state as { keepScroll?: boolean; restoreScroll?: number } | null;
    // A choice made on the page (the market, a chart view) changes the address but not the page: leave the scroll and the focus alone.
    if (state?.keepScroll) return;
    main.current?.focus({ preventScroll: true });
    if (typeof state?.restoreScroll === 'number') return restoreScroll(state.restoreScroll);
    window.scrollTo(0, 0);
    const focus = new URLSearchParams(location.search).get('focus');
    if (focus) return bringIntoView(focus);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenAt(null);
        menuButton.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  return (
    <div className="shell" onClickCapture={freshViewOnLinkClick}>
      <a className="skip-link" href="#main">Skip to the page</a>
      <header className="site-header">
        <div className="container site-header__inner">
          <Link className="brand" to="/">PackSense</Link>
          <div className="site-header__actions">
            <AskToggle />
            <ThemeToggle />
            <Link className="button button--primary lookup-cta" to="/look-up">Look up barcode</Link>
            <button
              ref={menuButton}
              type="button"
              className="menu-button"
              aria-expanded={menuOpen}
              aria-controls="site-menu"
              onClick={() => setOpenAt(menuOpen ? null : location.pathname)}
            >
              Menu
            </button>
          </div>
          <nav id="site-menu" className="tabs" aria-label="Main" data-open={menuOpen}>
            <ul>
              {TABS.map((item) => (
                <li key={item.id}>
                  <Link to={item.path} aria-current={item.id === tab ? 'page' : undefined}>{item.label}</Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <SubNav tab={tab} />
      <main id="main" ref={main} tabIndex={-1}>
        <div className="page">
          <Breadcrumb />
          <Outlet />
        </div>
      </main>
      <Footer />
      <BackButton />
      <ScrollTopButton />
      <ChatWidget />
    </div>
  );
}
