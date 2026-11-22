import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHero, Section, Stat } from "@/components/layout/Page";
import { Skeleton } from "@/components/ui/skeleton";
import { useDailyDigest, useIsRanked } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { QUIET_LINK, cn } from "@/lib/utils";
import type { DigestEnvelope, DigestInput, DigestStory } from "@/types/api";

const ET = "America/New_York";

/** The digest warns when the session went this long without an article. */
const GAP_WARN_MINUTES = 120;

const INPUTS: { key: DigestInput; label: string }[] = [
  { key: "coverage", label: "Coverage" },
  { key: "reaction", label: "Stock move" },
  { key: "category", label: "Story type" },
  { key: "on_site", label: "On the site" },
];

const CATEGORY_LABELS: Record<string, string> = { deal: "Deal", earnings: "Earnings", macro: "Macro" };

/** "Tuesday, Sep 8" for a digest date. */
function longDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** "Tue, Sep 8" for a digest date. */
function shortDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** "Mon 4:25 PM" in New York time for a UTC timestamp. */
function etTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone: ET,
  });
}

const signedPct = (v: number, digits = 1) =>
  `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}%`;

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;

function hoursMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h${m ? ` ${m}m` : ""}` : `${m}m`;
}

/** The plain-words reading of one score input for one story. */
function inputReading(key: DigestInput, s: DigestStory, ranked: (t: string) => boolean): string {
  switch (key) {
    case "coverage":
      return plural(s.n_outlets, "outlet");
    case "reaction":
      return s.move_ticker && s.move_return != null
        ? `${s.move_ticker} ${signedPct(s.move_return)} on the day`
        : "No price for the stock it leads with";
    case "category":
      return s.categories.length
        ? s.categories.map((c) => CATEGORY_LABELS[c] ?? c).join(", ")
        : "Not a deal, earnings or macro story";
    case "on_site": {
      const named = s.tickers.filter(ranked);
      return s.components.on_site > 0
        ? `${named.length ? named.join(", ") : "A named stock"} is in a site ranking`
        : "Names no stock the site ranks";
    }
  }
}

function TickerLinks({ tickers, ranked }: { tickers: string[]; ranked: (t: string) => boolean }) {
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

function StoryRow({
  story: s,
  weights,
  ranked,
}: {
  story: DigestStory;
  weights: DigestEnvelope["weights"];
  ranked: (t: string) => boolean;
}) {
  const more = s.also_covered.length;
  return (
    <li className="grid grid-cols-[2rem_1fr] gap-x-4 py-7 sm:grid-cols-[3rem_1fr_9rem] sm:gap-x-8">
      <span className="num pt-1 text-sm text-accent">{String(s.rank).padStart(2, "0")}</span>

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
          <p className="mt-2 line-clamp-3 max-w-3xl text-sm leading-relaxed text-ink-secondary">{s.summary}</p>
        )}
        <p className="num mt-3 flex flex-wrap gap-x-2 text-xs text-ink-muted">
          <span>{s.source}</span>
          <span>·</span>
          <span>{etTime(s.published_at)} ET</span>
          <span>·</span>
          <span>
            {plural(s.n_articles, "article")} from {plural(s.n_outlets, "outlet")}
          </span>
          {s.tickers.length > 0 && (
            <>
              <span>·</span>
              <TickerLinks tickers={s.tickers} ranked={ranked} />
            </>
          )}
          {s.categories.map((c) => (
            <span key={c} className="text-[11px] text-accent/70">
              {CATEGORY_LABELS[c] ?? c}
            </span>
          ))}
        </p>

        <details className="group mt-4">
          <summary className="cursor-pointer list-none text-sm text-ink-secondary transition-colors hover:text-accent [&::-webkit-details-marker]:hidden">
            <span className="inline-block w-3 transition-transform group-open:rotate-90">›</span>
            Why it ranks here{more > 0 && ` · ${plural(more, "more article")}`}
          </summary>
          <dl className="mt-4 max-w-2xl text-sm">
            {INPUTS.map(({ key, label }) => (
              <div key={key} className="grid grid-cols-[6.5rem_1fr_auto] gap-x-4 border-t border-line py-2">
                <dt className="text-ink-muted">{label}</dt>
                <dd className="text-ink-secondary">{inputReading(key, s, ranked)}</dd>
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
            <p className={cn("num text-2xl", s.move_return >= 0 ? "text-gain" : "text-loss")}>
              {signedPct(s.move_return)}
            </p>
            <p className="mt-0.5 text-xs text-ink-muted">{s.move_ticker} on the day</p>
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

function HowItsPicked({ d }: { d: DigestEnvelope }) {
  const help: Record<DigestInput, string> = {
    coverage: `How many outlets ran the story. One outlet scores nothing; each doubling adds the same, up to full marks at ${d.full_marks.coverage_outlets}.`,
    reaction: `The one-day move of the stock the story leads with, in that day's session. Full marks at ${signedPct(d.full_marks.move, 0).replace("+", "±")}.`,
    category: "Full marks for a deal, earnings or macro story, nothing otherwise.",
    on_site: "Full marks when the story names a stock in this week's or this quarter's ranking.",
  };
  const top = Math.max(...Object.values(d.weights));
  return (
    <Section
      title="How stories are picked"
      intro="By rule, not by a model. Each input scores a story from 0 to 1, and the weights below turn that into one score. The weights are a first pass set by hand, not fitted to anything, and may change."
    >
      <div className="grid gap-x-10 sm:grid-cols-2">
        {INPUTS.map(({ key, label }) => (
          <div key={key} className="bar-target border-t border-line py-3.5">
            <div className="flex items-baseline justify-between gap-4">
              <span className="text-[15px]">{label}</span>
              <span className="num text-ink-secondary">{Math.round(d.weights[key] * 100)}%</span>
            </div>
            <div className="mt-2 h-[6px] bg-white/[0.06]">
              <div className="bar h-full" style={{ width: `${(d.weights[key] / top) * 100}%` }} />
            </div>
            <p className="mt-2 text-xs leading-relaxed text-ink-muted">{help[key]}</p>
          </div>
        ))}
      </div>
      <div className="mt-10 grid max-w-4xl gap-6 text-sm leading-relaxed text-ink-secondary md:grid-cols-2">
        <p>
          Before scoring, routine items are dropped: fund filings reporting a stake change, insider and
          congressional trades, price-target notes, templated price recaps, law-firm calls for shareholders, and
          conference, dividend and results-date announcements. So are opinion pieces: headlines that ask a
          question or pitch stocks to buy.
        </p>
        <p>
          Articles become one story when their headlines share enough distinctive words within 36 hours, or lead
          with the same stock on the same kind of news. The story shows the article that shares the most with
          the rest. The feed returns only its latest ~100 articles per pull, so a busy stretch can be missed;
          the page says when the session went two hours or more without an article.
        </p>
      </div>
    </Section>
  );
}

export function DigestPage() {
  const { date } = useParams<{ date?: string }>();
  const digest = useDailyDigest(date);
  const ranked = useIsRanked();

  useEffect(() => {
    document.title = "Daily digest | Stockidence";
  }, []);

  const d = digest.data;
  const missing = digest.error instanceof ApiError && digest.error.status === 404;
  const filtered = d ? d.routine_dropped + d.commentary_dropped : 0;
  const gap = d?.session_gap_minutes ?? 0;

  const hero = {
    link: { to: "/market", label: "← Market" },
  };

  if (missing || digest.isError || (d && !d.digest_date)) {
    return (
      <div>
        <PageHero
          {...hero}
          title={
            <>
              The morning's news. <span className="text-accent">Ranked by rule.</span>
            </>
          }
          lede={
            missing
              ? `There is no digest for ${date ? longDay(date) : "that day"}. Digests are built on weekdays only.`
              : digest.isError
                ? "The digest is unavailable right now."
                : "The first digest is built at 7:30 ET on the next weekday."
          }
        >
          {missing && date && (
            <p className="mt-6">
              <Link to="/market/digest" className={QUIET_LINK}>
                Latest digest →
              </Link>
            </p>
          )}
        </PageHero>
      </div>
    );
  }

  return (
    <div>
      <PageHero
        {...hero}
        loading={!d}
        title={
          d?.digest_date && (
            <>
              {longDay(d.digest_date)}.{" "}
              <span className="text-accent">
                {d.items.length === 1 ? "The top story." : `The top ${d.items.length} stories.`}
              </span>
            </>
          )
        }
        lede={
          d?.window_start &&
          d.window_end &&
          `News from ${etTime(d.window_start)} to ${etTime(d.window_end)} ET.`
        }
      >
        {d && (
          <>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2">
              {d.previous_date && (
                <Link to={`/market/digest/${d.previous_date}`} className={QUIET_LINK}>
                  ← {shortDay(d.previous_date)}
                </Link>
              )}
              {d.next_date && (
                <Link to={`/market/digest/${d.next_date}`} className={QUIET_LINK}>
                  {shortDay(d.next_date)} →
                </Link>
              )}
            </div>
            <div className="mt-10 grid max-w-3xl grid-cols-2 gap-5 border-t border-line pt-5 sm:grid-cols-4">
              <Stat value={d.articles.toLocaleString("en-US")} label="articles read" />
              <Stat value={filtered.toLocaleString("en-US")} label="dropped as routine or opinion" />
              <Stat value={d.stories.toLocaleString("en-US")} label="stories after grouping" />
              <Stat value={d.outlets.toLocaleString("en-US")} label="outlets" />
            </div>
            {gap >= GAP_WARN_MINUTES && (
              <p className="mt-6 max-w-2xl text-sm leading-relaxed text-ink-secondary">
                <span className="text-accent">Gap in the feed.</span> The session went {hoursMinutes(gap)} without
                an article, so stories from that stretch may be missing.
              </p>
            )}
          </>
        )}
      </PageHero>

      <Section title="Top stories">
        {!d ? (
          <div className="space-y-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : d.items.length === 0 ? (
          <p className="text-ink-secondary">No stories made it through the filters that day.</p>
        ) : (
          <ol className="divide-y divide-line border-t border-line">
            {d.items.map((s) => (
              <StoryRow key={s.rank} story={s} weights={d.weights} ranked={ranked} />
            ))}
          </ol>
        )}
      </Section>

      {d && <HowItsPicked d={d} />}
    </div>
  );
}
