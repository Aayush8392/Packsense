import type { MouseEvent, ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { pageForPath } from '../nav';
import { forgetPage, pushStep } from './jumpStore';

/** The page to leave behind, as the Back button will return to it. */
function currentStep(pathname: string, search: string) {
  return { path: `${pathname}${search}`, scroll: window.scrollY, label: pageForPath(pathname)?.label ?? 'the page' };
}

function destinationPath(to: string): string {
  return to.split('?')[0].split('#')[0];
}

/**
 * A link that is a jump: it leaves a step on the trail (so the Back button can return here, scroll and choices included), opens the destination fresh and, when the
 * address carries `?focus=kind:name`, brings that part of the destination into view. A click with a modifier key (a new tab) is an ordinary link.
 */
export function JumpLink({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  const { pathname, search } = useLocation();
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    pushStep(currentStep(pathname, search));
    forgetPage(destinationPath(to));
  };
  return (
    <Link to={to} className={className} state={{ jump: true }} data-jump="" onClick={onClick}>
      {children}
    </Link>
  );
}

/** The same jump, started from code (the barcode box on the home page). */
export function useJump(): (to: string) => void {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  return (to: string) => {
    pushStep(currentStep(pathname, search));
    forgetPage(destinationPath(to));
    navigate(to, { state: { jump: true } });
  };
}
