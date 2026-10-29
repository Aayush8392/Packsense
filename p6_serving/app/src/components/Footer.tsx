import { Link } from 'react-router';

function formatBuildTime(iso: string): string {
  const date = new Date(iso);
  const day = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
  return `${day}, ${time} UTC`;
}

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <div className="site-footer__credit">
          <p className="brand brand--small">PackSense</p>
          <p>
            Contains data from <a href="https://world.openfoodfacts.org/">Open Food Facts</a>, available under the{' '}
            <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>.
          </p>
          <p>
            Site built <time dateTime={__BUILD_TIME__}>{formatBuildTime(__BUILD_TIME__)}</time>.
          </p>
        </div>
        <nav aria-label="Footer">
          <ul>
            <li><Link to="/about">About</Link></li>
            <li><a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a></li>
            <li><a href="https://world.openfoodfacts.org/">Open Food Facts</a></li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
