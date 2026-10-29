import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';
import { TABS, pageForPath, pagesInTab, tabById, type TabId } from '../nav';
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

  // After a navigation inside the app: go to the very top, and move focus to the page so a screen reader starts reading it. Focus must not
  // scroll: it would put the top of the page under the sticky header.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    main.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
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
    <div className="shell">
      <a className="skip-link" href="#main">Skip to the page</a>
      <header className="site-header">
        <div className="container site-header__inner">
          <Link className="brand" to="/">PackSense</Link>
          <div className="site-header__actions">
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
    </div>
  );
}
