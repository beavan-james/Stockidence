import { Link } from "react-router-dom";

import {
  CATEGORY_LABELS,
  INPUTS,
  MOVE_SPAN,
  etTime,
  inputReading,
  plural,
  signedPct,
} from "@/lib/digest";
import { cn } from "@/lib/utils";
import type { DigestEnvelope, DigestPeriod, DigestStory } from "@/types/api";

type Ranked = (ticker: string) => boolean;

const rankLabel = (rank: number) => String(rank).padStart(2, "0");

function TickerLinks({ tickers, ranked }: { tickers: string[]; ranked: Ranked }) {
  return (
    <span className="inline-flex flex-wrap gap-x-2">
      {tickers.map((t) =>
        ranked(t) ? (
          <Link key={t} to={`/stocks/${t}`} className="ticker text-ink-secondary hover:text-accent">
            {t}
          </Link>
        ) : (
          <span key={t} className="ticker">
            {t}
          </span>
        ),
      )}
    </span>
  );
}

/** Source, time, coverage, tickers and story type on one muted line. */
function Meta({ story: s, ranked, categories = true }: { story: DigestStory; ranked: Ranked; categories?: boolean }) {
  return (
    <p className="num flex flex-wrap gap-x-2 text-xs text-ink-muted">
      <span>{s.source}</span>
      <span>·</span>
      <span>{etTime(s.published_at)} ET</span>
      <span>·</span>
      <span>{s.n_outlets > 1 ? plural(s.n_outlets, "outlet") : plural(s.n_articles, "article")}</span>
      {s.tickers.length > 0 && (
        <>
          <span>·</span>
          <TickerLinks tickers={s.tickers} ranked={ranked} />
        </>
      )}
      {categories &&
        s.categories.map((c) => (
          <span key={c} className="text-[11px] text-accent/70">
            {CATEGORY_LABELS[c] ?? c}
          </span>
        ))}
    </p>
  );
}

const moveTone = (v: number) => (v >= 0 ? "text-gain" : "text-loss");

/** One line per story: the day's digest. */
export function BriefRow({ story: s, ranked }: { story: DigestStory; ranked: Ranked }) {
  const move = s.move_ticker && s.move_return != null;
  return (
    <li className="grid grid-cols-[2rem_1fr_auto] gap-x-4 py-4 sm:grid-cols-[3rem_1fr_7rem] sm:gap-x-8">
      <span className="num pt-0.5 text-sm text-accent">{rankLabel(s.rank)}</span>
      <div className="min-w-0">
        <a
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          className="leading-snug transition-colors hover:text-accent sm:text-lg"
        >
          {s.headline}
        </a>
        <div className="mt-1.5">
          <Meta story={s} ranked={ranked} categories={false} />
        </div>
      </div>
      <div className="text-right">
        {move && (
          <>
            <p className={cn("num text-sm sm:text-base", moveTone(s.move_return!))}>{signedPct(s.move_return!)}</p>
            <p className="ticker mt-0.5 text-[11px] text-ink-muted">{s.move_ticker}</p>
          </>
        )}
      </div>
    </li>
  );
}

/** A story in full: summary, score and why it ranks there. The week's digest. */
export function StoryRow({
  story: s,
  period,
  weights,
  ranked,
}: {
  story: DigestStory;
  period: DigestPeriod;
  weights: DigestEnvelope["weights"];
  ranked: Ranked;
}) {
  const more = s.also_covered.length;
  return (
    <li className="grid grid-cols-[2rem_1fr] gap-x-4 py-7 sm:grid-cols-[3rem_1fr_9rem] sm:gap-x-8">
      <span className="num pt-1 text-sm text-accent">{rankLabel(s.rank)}</span>

      <div className="min-w-0">
        <a
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-lg leading-snug transition-colors hover:text-accent sm:text-xl"
        >
          {s.headline}
        </a>
        {s.summary && (
          <p className="mt-2 line-clamp-4 max-w-3xl text-sm leading-relaxed text-ink-secondary">{s.summary}</p>
        )}
        <div className="mt-3">
          <Meta story={s} ranked={ranked} />
        </div>

        <details className="group mt-4">
          <summary className="cursor-pointer list-none text-sm text-ink-secondary transition-colors hover:text-accent [&::-webkit-details-marker]:hidden">
            <span className="inline-block w-3 transition-transform group-open:rotate-90">›</span>
            Why it ranks here{more > 0 && ` · ${plural(more, "more article")}`}
          </summary>
          <dl className="mt-4 max-w-2xl text-sm">
            {INPUTS.map(({ key, label }) => (
              <div key={key} className="grid grid-cols-[6.5rem_1fr_auto] gap-x-4 border-t border-line py-2">
                <dt className="text-ink-muted">{label}</dt>
                <dd className="text-ink-secondary">{inputReading(key, s, period, ranked)}</dd>
                <dd className="num text-right">
                  {(weights[key] * s.components[key]).toFixed(2)}
                  <span className="text-ink-muted"> / {weights[key].toFixed(2)}</span>
                </dd>
              </div>
            ))}
          </dl>
          {more > 0 && (
            <ul className="mt-5 max-w-3xl divide-y divide-line border-t border-line">
              {s.also_covered.map((a) => (
                <li key={a.url} className="py-2.5">
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm leading-snug transition-colors hover:text-accent"
                  >
                    {a.headline}
                  </a>
                  <p className="num mt-0.5 text-xs text-ink-muted">
                    {a.source} · {etTime(a.published_at)} ET
                  </p>
                </li>
              ))}
            </ul>
          )}
        </details>
      </div>

      <div className="col-start-2 mt-5 flex items-end gap-10 sm:col-start-auto sm:mt-0 sm:block sm:text-right">
        {s.move_ticker && s.move_return != null && (
          <div className="sm:mb-5">
            <p className={cn("num text-2xl", moveTone(s.move_return))}>{signedPct(s.move_return)}</p>
            <p className="mt-0.5 text-xs text-ink-muted">
              {s.move_ticker} {MOVE_SPAN[period]}
            </p>
          </div>
        )}
        <div className="w-28 sm:ml-auto sm:w-full sm:max-w-[9rem]">
          <p className="num text-sm">
            <span className="text-xs text-ink-muted">Score </span>
            {s.score.toFixed(2)}
          </p>
          <div className="mt-1.5 h-[6px] bg-white/[0.06]" title="Out of a possible 1.00">
            <div className="bar h-full" style={{ width: `${Math.min(1, s.score) * 100}%` }} />
          </div>
        </div>
      </div>
    </li>
  );
}
