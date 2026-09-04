/**
 * Shared markdown renderers matching the dark theme. Used by DocsPage and
 * ModelPage so rendered .md files look consistent across the site.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const mdComponents: Record<string, React.ComponentType<any>> = {
  h1: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className="mb-4 mt-0 text-2xl font-semibold tracking-tight text-ink">{children}</h1>
  ),
  h2: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className="mb-3 mt-10 text-lg font-semibold tracking-tight text-ink">{children}</h2>
  ),
  h3: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className="mb-2 mt-8 text-base font-semibold text-ink">{children}</h3>
  ),
  p: ({ children }: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="mb-4 leading-relaxed text-ink-secondary">{children}</p>
  ),
  a: ({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} className="text-accent underline-offset-2 hover:text-accent-strong hover:underline">
      {children}
    </a>
  ),
  ul: ({ children }: React.HTMLAttributes<HTMLUListElement>) => (
    <ul className="mb-4 list-disc space-y-1 pl-6 text-ink-secondary">{children}</ul>
  ),
  ol: ({ children }: React.HTMLAttributes<HTMLOListElement>) => (
    <ol className="mb-4 list-decimal space-y-1 pl-6 text-ink-secondary">{children}</ol>
  ),
  li: ({ children }: React.HTMLAttributes<HTMLLIElement>) => (
    <li className="leading-relaxed">{children}</li>
  ),
  code: ({ children, className }: React.HTMLAttributes<HTMLElement>) => {
    const isBlock = className?.includes("language-");
    return isBlock ? (
      <code className="mb-4 block overflow-x-auto rounded-lg border border-line bg-surface p-4 text-sm text-accent-strong">
        {children}
      </code>
    ) : (
      <code className="rounded bg-surface px-1.5 py-0.5 text-sm text-accent-strong">{children}</code>
    );
  },
  pre: ({ children }: React.HTMLAttributes<HTMLPreElement>) => (
    <pre className="mb-4 overflow-x-auto">{children}</pre>
  ),
  blockquote: ({ children }: React.HTMLAttributes<HTMLQuoteElement>) => (
    <blockquote className="mb-4 border-l-2 border-accent/30 pl-4 text-ink-muted italic">
      {children}
    </blockquote>
  ),
  table: ({ children }: React.HTMLAttributes<HTMLTableElement>) => (
    <div className="mb-4 overflow-x-auto">
      <table className="w-full text-sm text-ink-secondary">{children}</table>
    </div>
  ),
  thead: ({ children }: React.HTMLAttributes<HTMLTableSectionElement>) => (
    <thead className="border-b border-line text-left text-xs uppercase tracking-wider text-ink-muted">
      {children}
    </thead>
  ),
  th: ({ children }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <th className="px-3 py-2 font-medium">{children}</th>
  ),
  td: ({ children }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <td className="border-b border-line/50 px-3 py-2">{children}</td>
  ),
  hr: () => <hr className="my-8 border-line" />,
  strong: ({ children }: React.HTMLAttributes<HTMLElement>) => (
    <strong className="font-semibold text-ink">{children}</strong>
  ),
};
