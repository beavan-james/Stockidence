import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { NewsTable } from "@/components/discover/NewsTable";
import { PageHero, Section } from "@/components/layout/Page";
import { SourceList, Summary } from "@/components/news/Summary";
import { Skeleton } from "@/components/ui/skeleton";
import { useDigest, useSummary } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { GAP_WARN_MINUTES, hoursMinutes, longDay, monthDay, shortDay, weekStart } from "@/lib/digest";
import { QUIET_LINK, cn } from "@/lib/utils";
import type { DigestEnvelope, DigestPeriod, SummaryEnvelope } from "@/types/api";

/** How many of a digest's stories are listed when it has no article. */
const TOP_STORIES = 10;

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
    // A daily digest covers the 24 hours to 7:00 ET, so it is that morning's premarket news.
    title: (date) => `${longDay(date)} premarket`,
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

/** Shown when a session went long enough without an article that stories may be missing. */
function GapNote({ minutes }: { minutes: number | null }) {
  if ((minutes ?? 0) < GAP_WARN_MINUTES) return null;
  return (
    <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-secondary">
      <span className="text-accent">Gap in the feed.</span> A session went {hoursMinutes(minutes!)} without an
      article, so stories from that stretch may be missing.
    </p>
  );
}

/**
 * One day's or one week's news: the latest article written on or before the
 * asked date, stepping from article to article. With no article yet, the
 * digest's top 10 stories, stepping from digest to digest.
 */
function DigestSection({
  period,
  query,
  summary,
  requested,
}: {
  period: DigestPeriod;
  query: UseQueryResult<DigestEnvelope>;
  summary: UseQueryResult<SummaryEnvelope>;
  requested: string | undefined;
}) {
  const [params] = useSearchParams();
  const text = TEXT[period];
  const d = query.data;
  const written = summary.data?.digest_date && summary.data.parts.length > 0 ? summary.data : null;
  // No answer yet on whether there is an article: hold the section rather than flash the list.
  const deciding = !written && summary.isPending;

  /** This page with one digest's date swapped, the other kept. */
  const at = (date: string | null) => {
    const next = new URLSearchParams(params);
    if (date) next.set(PARAM[period], date);
    else next.delete(PARAM[period]);
    const search = next.toString();
    return { search: search ? `?${search}` : "" };
  };

  const missing = !written && query.error instanceof ApiError && query.error.status === 404;
  const asked = missing && requested && text.dated(requested) ? requested : null;
  const shown = written ?? (deciding ? undefined : d);
  const title = shown?.digest_date
    ? text.title(shown.digest_date)
    : asked
      ? text.title(asked)
      : period === "daily"
        ? "Today"
        : "This week";

  const steps = shown?.digest_date && (
    <div className="flex gap-x-6">
      {shown.previous_date && (
        <Link to={at(shown.previous_date)} className={QUIET_LINK}>
          ← {text.step(shown.previous_date)}
        </Link>
      )}
      {shown.next_date && (
        <Link to={at(shown.next_date)} className={QUIET_LINK}>
          {text.step(shown.next_date)} →
        </Link>
      )}
    </div>
  );

  const loading = (
    <div className="max-w-2xl space-y-3">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-5" />
      ))}
    </div>
  );

  let body;
  if (written) {
    body = (
      <div className={cn("transition-opacity", summary.isPlaceholderData && "opacity-50")}>
        {written.model && <p className="text-[13px] text-ink-muted">Written by {written.model}</p>}
        <GapNote minutes={written.session_gap_minutes} />
        <div className="mt-6">
          <Summary parts={written.parts} />
        </div>
      </div>
    );
  } else if (deciding) {
    body = loading;
  } else if (missing) {
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
    body = loading;
  } else if (!d.digest_date) {
    body = <p className="text-ink-secondary">{text.first}</p>;
  } else if (d.items.length === 0) {
    body = <p className="text-ink-secondary">No stories made it through the filters.</p>;
  } else {
    body = (
      <div className={cn("transition-opacity", query.isPlaceholderData && "opacity-50")}>
        <GapNote minutes={d.session_gap_minutes} />
        <div className="mt-5 max-w-2xl first:mt-0">
          <SourceList
            sources={d.items.slice(0, TOP_STORIES).map((s) => ({ headline: s.headline, outlet: s.source, url: s.url }))}
          />
        </div>
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
  const dailySummary = useSummary("daily", day);
  const weeklySummary = useSummary("weekly", week);

  useEffect(() => {
    document.title = "News | Stockidence";
  }, []);

  return (
    <div>
      <PageHero
        link={{ to: "/news/method", label: "How stories are picked →" }}
        title="News Digest"
      />
      <DigestSection period="daily" query={daily} summary={dailySummary} requested={day} />
      <DigestSection period="weekly" query={weekly} summary={weeklySummary} requested={week} />
      <Section title="All news">
        <NewsTable />
      </Section>
    </div>
  );
}
