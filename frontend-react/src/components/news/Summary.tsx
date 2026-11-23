import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { SummaryPart, SummarySource } from "@/types/api";

const paragraphs = (body: string) =>
  body
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Prose({ body, lead = false }: { body: string; lead?: boolean }) {
  return (
    <div className={cn("space-y-5", lead ? "text-lg leading-relaxed sm:text-xl" : "text-[17px] leading-[1.7]")}>
      {paragraphs(body).map((p, i) => (
        <p key={i}>{p}</p>
      ))}
    </div>
  );
}

/** Headline links with their outlets, under hairlines. */
export function SourceList({ sources }: { sources: SummarySource[] }) {
  return (
    <ol className="divide-y divide-line border-t border-line">
      {sources.map((s) => (
        <li key={s.url} className="py-2.5 text-sm leading-snug">
          <a
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-ink-secondary transition-colors hover:text-accent"
          >
            {s.headline ?? host(s.url)}
          </a>
          {s.outlet && <span className="text-ink-muted"> · {s.outlet}</span>}
        </li>
      ))}
    </ol>
  );
}

function Sources({ sources }: { sources: SummarySource[] }) {
  return (
    <div className="min-w-0 lg:pt-1.5">
      <p className="mb-2 text-xs text-ink-muted">Sources</p>
      <SourceList sources={sources} />
    </div>
  );
}

/** The text on the left and its sources beside it on wide screens; stacked on narrow ones. */
function Row({ sources, className, children }: { sources: SummarySource[]; className?: string; children: ReactNode }) {
  return (
    <div className={cn("grid gap-y-7 lg:grid-cols-[minmax(0,42rem)_minmax(0,1fr)] lg:gap-x-16", className)}>
      <div className="min-w-0">{children}</div>
      {sources.length > 0 && <Sources sources={sources} />}
    </div>
  );
}

/**
 * A digest's model-written text: the daily paragraph with its sources, or the
 * weekly article, its overview then each section under its heading with that
 * section's sources. A part that failed its checks shows only its sources.
 */
export function Summary({ parts }: { parts: SummaryPart[] }) {
  const lead = parts.find((p) => p.part === 0);
  const sections = parts.filter((p) => p.part > 0);
  return (
    <article>
      {/* The overview's sources are its sections' sources, listed under each. */}
      {lead?.body ? (
        <Row sources={sections.length === 0 ? lead.sources : []}>
          <Prose body={lead.body} lead />
        </Row>
      ) : (
        lead &&
        sections.length === 0 && (
          <div className="max-w-2xl">
            <Sources sources={lead.sources} />
          </div>
        )
      )}
      {sections.map((s, i) => (
        <Row
          key={s.part}
          sources={s.sources}
          className={cn((i > 0 || lead?.body) && "mt-14 border-t border-line pt-7")}
        >
          <h3 className="text-2xl font-medium leading-tight tracking-[-0.015em]">{s.heading}</h3>
          {s.body && (
            <div className="mt-4">
              <Prose body={s.body} />
            </div>
          )}
        </Row>
      ))}
    </article>
  );
}
