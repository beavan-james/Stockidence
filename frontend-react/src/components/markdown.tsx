/**
 * Shared markdown renderers matching the dark theme, using the site's heading
 * scale and table style so rendered .md files read like the other pages.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const mdComponents: Record<string, React.ComponentType<any>> = {
  h1: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className="mb-6 mt-0 font-medium text-4xl tracking-tight text-ink">{children}</h1>
  ),
  h2: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className="mb-3 mt-10 font-medium text-2xl tracking-tight text-ink">{children}</h2>
  ),
  h3: ({ children }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className="mb-2 mt-8 font-medium text-lg text-ink">{children}</h3>
  ),
  p: ({ children }: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="mb-4 leading-relaxed text-ink-secondary">{children}</p>
  ),
  a: ({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
    const external = /^https?:/.test(href ?? "");
    return (
      <a
        href={href}
        target={external ? "_blank" : undefined}
        rel={external ? "noopener noreferrer" : undefined}
        className="text-accent underline-offset-2 hover:text-accent-strong hover:underline"
      >
        {children}
      </a>
    );
  },
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
      <table className="data-table text-ink-secondary">{children}</table>
    </div>
  ),
  hr: () => <hr className="my-8 border-line" />,
  strong: ({ children }: React.HTMLAttributes<HTMLElement>) => (
    <strong className="font-semibold text-ink">{children}</strong>
  ),
};
