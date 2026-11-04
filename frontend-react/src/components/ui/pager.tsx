const BUTTON =
  "rounded-lg border border-line px-3 py-1 text-ink-secondary transition-colors enabled:hover:text-accent disabled:opacity-40";

/** Previous/next for a paged list; `page` counts from 1. */
export function Pager({
  page,
  pageCount,
  onPage,
}: {
  page: number;
  pageCount: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-between pt-4 text-sm">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className={BUTTON}>
        ← Prev
      </button>
      <span className="num text-xs text-ink-muted">
        Page {page} of {pageCount}
      </span>
      <button type="button" disabled={page >= pageCount} onClick={() => onPage(page + 1)} className={BUTTON}>
        Next →
      </button>
    </div>
  );
}
