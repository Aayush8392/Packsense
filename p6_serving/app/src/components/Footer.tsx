import { Link } from 'react-router';
import { ExternalLink } from './ExternalLink';

function formatBuildTime(iso: string): string {
  const date = new Date(iso);
  const day = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' });
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' });
  return `${day}, ${time} IST`;
}

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <div className="site-footer__credit">
          <p className="brand brand--small">PackSense</p>
          <p>
            Contains data from <ExternalLink href="https://world.openfoodfacts.org/">Open Food Facts</ExternalLink>, available under the{' '}
            <ExternalLink href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</ExternalLink>.
          </p>
          <p>
            Site built <time dateTime={__BUILD_TIME__}>{formatBuildTime(__BUILD_TIME__)}</time>.
          </p>
        </div>
        <nav aria-label="Footer">
          <ul>
            <li><Link to="/about">About</Link></li>
            <li><ExternalLink href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</ExternalLink></li>
            <li><ExternalLink href="https://world.openfoodfacts.org/">Open Food Facts</ExternalLink></li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
