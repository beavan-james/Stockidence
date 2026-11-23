import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { NewsTable } from "@/components/discover/NewsTable";
import { PageHero, Section } from "@/components/layout/Page";
import { BriefRow, StoryRow } from "@/components/news/StoryRows";
import { Skeleton } from "@/components/ui/skeleton";
import { useDigest, useIsRanked } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { GAP_WARN_MINUTES, hoursMinutes, longDay, monthDay, plural, shortDay, weekStart } from "@/lib/digest";
import { QUIET_LINK, cn } from "@/lib/utils";
import type { DigestEnvelope, DigestPeriod } from "@/types/api";

/** The search param that picks each digest's date. */
const PARAM: Record<DigestPeriod, "day" | "week"> = { daily: "day", weekly: "week" };

/** 0 = Sunday, for a YYYY-MM-DD date. */
const weekday = (iso: string) => new Date(`${iso}T00:00:00Z`).getUTCDay();

const TEXT: Record<
  DigestPeriod,
  {
    /** Whether a digest can carry this date at all. */
    dated: (date: string) => boolean;
    title: (date: string) => string;
    step: (date: string) => string;
    missing: (date: string) => string;
    misdated: string;
    first: string;
  }
> = {
  daily: {
    dated: (date) => weekday(date) >= 1 && weekday(date) <= 5,
    title: longDay,
    step: shortDay,
    missing: (date) => `There is no digest for ${longDay(date)}.`,
    misdated: "Daily digests are built on weekdays only.",
    first: "The first daily digest is built at 7:30 ET on the next weekday.",
  },
  weekly: {
    dated: (date) => weekday(date) === 5,
    title: (date) => `Week of ${monthDay(weekStart(date))}`,
    step: (date) => monthDay(weekStart(date)),
    missing: (date) => `There is no digest for the week of ${monthDay(weekStart(date))}.`,
    misdated: "Weekly digests are dated by the week's Friday.",
    first: "The first weekly digest is built at 7:30 ET on Saturday.",
  },
};

function DigestSection({
  period,
  query,
  requested,
}: {
  period: DigestPeriod;
  query: UseQueryResult<DigestEnvelope>;
  requested: string | undefined;
}) {
  const [params] = useSearchParams();
  const ranked = useIsRanked();
  const text = TEXT[period];
  const d = query.data;

  /** This page with one digest's date swapped, the other kept. */
  const at = (date: string | null) => {
    const next = new URLSearchParams(params);
    if (date) next.set(PARAM[period], date);
    else next.delete(PARAM[period]);
    const search = next.toString();
    return { search: search ? `?${search}` : "" };
  };

  const missing = query.error instanceof ApiError && query.error.status === 404;
  const asked = missing && requested && text.dated(requested) ? requested : null;
  const title = d?.digest_date
    ? text.title(d.digest_date)
    : asked
      ? text.title(asked)
      : period === "daily"
        ? "Today"
        : "This week";

  const steps = d?.digest_date && (
    <div className="flex gap-x-6">
      {d.previous_date && (
        <Link to={at(d.previous_date)} className={QUIET_LINK}>
          ← {text.step(d.previous_date)}
        </Link>
      )}
      {d.next_date && (
        <Link to={at(d.next_date)} className={QUIET_LINK}>
          {text.step(d.next_date)} →
        </Link>
      )}
    </div>
  );

  let body;
  if (missing) {
    body = (
      <p className="text-ink-secondary">
        {asked ? text.missing(asked) : requested ? text.misdated : text.first}{" "}
        <Link to={at(null)} className={cn(QUIET_LINK, "ml-1")}>
          Latest →
        </Link>
      </p>
    );
  } else if (query.isError) {
    body = <p className="text-ink-secondary">The digest is unavailable right now.</p>;
  } else if (!d) {
    body = (
      <div className="space-y-3">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className={period === "daily" ? "h-14" : "h-28"} />
        ))}
      </div>
    );
  } else if (!d.digest_date) {
    body = <p className="text-ink-secondary">{text.first}</p>;
  } else if (d.items.length === 0) {
    body = <p className="text-ink-secondary">No stories made it through the filters.</p>;
  } else {
    const gap = d.session_gap_minutes ?? 0;
    body = (
      <div className={cn("transition-opacity", query.isPlaceholderData && "opacity-50")}>
        <p className="num text-[13px] text-ink-muted">
          {plural(d.articles, "article")} from {plural(d.outlets, "outlet")} ·{" "}
          {(d.routine_dropped + d.commentary_dropped).toLocaleString("en-US")} dropped as routine or opinion
        </p>
        {gap >= GAP_WARN_MINUTES && (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-secondary">
            <span className="text-accent">Gap in the feed.</span> A session went {hoursMinutes(gap)} without an
            article, so stories from that stretch may be missing.
          </p>
        )}
        <ol className="mt-5 divide-y divide-line border-t border-line">
          {d.items.map((s) =>
            period === "daily" ? (
              <BriefRow key={s.rank} story={s} ranked={ranked} />
            ) : (
              <StoryRow key={s.rank} story={s} period={period} weights={d.weights} ranked={ranked} />
            ),
          )}
        </ol>
      </div>
    );
  }

  return (
    <Section title={title} aside={steps}>
      {body}
    </Section>
  );
}

export function NewsPage() {
  const [params] = useSearchParams();
  const day = params.get(PARAM.daily) ?? undefined;
  const week = params.get(PARAM.weekly) ?? undefined;
  const daily = useDigest("daily", day);
  const weekly = useDigest("weekly", week);

  useEffect(() => {
    document.title = "News | Stockidence";
  }, []);

  return (
    <div>
      <PageHero
        link={{ to: "/news/method", label: "How stories are picked →" }}
        title="News Digest"
      />
      <DigestSection period="daily" query={daily} requested={day} />
      <DigestSection period="weekly" query={weekly} requested={week} />
      <Section title="All news">
        <NewsTable />
      </Section>
    </div>
  );
}
