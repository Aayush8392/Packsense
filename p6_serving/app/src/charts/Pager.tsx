export const PAGE_SIZE = 10;

export interface PageWindow {
  /** Index of the first row on the page, 0-based, and one past the last. */
  start: number;
  end: number;
  pages: number;
}

/** Which rows a page shows. A page number past the end is pulled back to the last page. */
export function pageWindow(total: number, page: number, size = PAGE_SIZE): PageWindow {
  const pages = Math.max(1, Math.ceil(total / size));
  const clamped = Math.min(Math.max(page, 0), pages - 1);
  return { start: clamped * size, end: Math.min(total, clamped * size + size), pages };
}

/** Previous and Next, and a line saying which rows are shown. Nothing is drawn when everything fits on one page. */
export function Pager({ total, page, onPage, noun, size = PAGE_SIZE }: {
  total: number;
  page: number;
  onPage: (next: number) => void;
  /** What a row is, in the plural, for the status line ("days"). */
  noun: string;
  size?: number;
}) {
  const { start, end, pages } = pageWindow(total, page, size);
  if (pages <= 1) return null;
  const current = start / size;
  return (
    <div className="pager">
      <button type="button" className="button button--quiet" disabled={current === 0} onClick={() => onPage(current - 1)}>
        Previous 10
      </button>
      <p className="pager__status" role="status">
        {noun[0].toUpperCase() + noun.slice(1)} {start + 1} to {end} of {total}
      </p>
      <button type="button" className="button button--quiet" disabled={current >= pages - 1} onClick={() => onPage(current + 1)}>
        Next 10
      </button>
    </div>
  );
}
