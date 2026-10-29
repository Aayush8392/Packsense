import { useEffect } from 'react';
import { Link } from 'react-router';

export function NotFound() {
  useEffect(() => {
    document.title = 'Page not found — PackSense';
  }, []);
  return (
    <article className="prose">
      <h1>This page does not exist</h1>
      <p>
        The address may be old or mistyped. Start from the <Link to="/">home page</Link>.
      </p>
    </article>
  );
}
