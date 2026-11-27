import { useEffect } from "react";

import { PageHero, Section } from "@/components/layout/Page";
import { Skeleton } from "@/components/ui/skeleton";
import { useDigest } from "@/hooks/queries";
import { INPUTS, signedPct } from "@/lib/digest";
import type { DigestEnvelope, DigestInput } from "@/types/api";

const range = (v: number) => signedPct(v, 0).replace("+", "±");
const cap = (v: number) => (v >= 1e12 ? `$${v / 1e12}tn` : `$${v / 1e9}bn`);

function Inputs({ daily, weekly }: { daily: DigestEnvelope; weekly: DigestEnvelope }) {
  const day = daily.full_marks;
  const week = weekly.full_marks;
  const help: Record<DigestInput, string> = {
    event: "What happened. For a company, the kind of event its filing reports: a bankruptcy or restatement scores highest, a deal or results high, a director change low. For a government release, its kind: an FOMC statement, CPI or the jobs report scores highest.",
    reaction: `How the stock the story leads with moved: its one-day move in a day's digest, its move over the five sessions in a week's. Full marks at ${range(day.move)} and ${range(week.move)}. For a Fed decision or BLS figure, the S&P 500's move, full marks at ${range(day.market_move)} and ${range(week.market_move)}.`,
    size: `The company's market cap: nothing at ${cap(day.size_from)}, full marks at ${cap(day.size_full_at)}, each tenfold adding the same. A Fed decision or BLS figure gets full marks.`,
    on_site: "Full marks when the story names a stock in this week's or this quarter's ranking.",
  };
  const weights = daily.weights;
  const top = Math.max(...Object.values(weights));
  return (
    <div className="grid gap-x-10 sm:grid-cols-2">
      {INPUTS.map(({ key, label }) => (
        <div key={key} className="bar-target border-t border-line py-3.5">
          <div className="flex items-baseline justify-between gap-4">
            <span className="text-[15px]">{label}</span>
            <span className="num text-ink-secondary">{Math.round(weights[key] * 100)}%</span>
          </div>
          <div className="mt-2 h-[6px] bg-white/[0.06]">
            <div className="bar h-full" style={{ width: `${(weights[key] / top) * 100}%` }} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-muted">{help[key]}</p>
        </div>
      ))}
    </div>
  );
}

export function NewsMethodPage() {
  const daily = useDigest("daily", undefined);
  const weekly = useDigest("weekly", undefined);

  useEffect(() => {
    document.title = "How stories are picked | Stockidence";
  }, []);

  return (
    <div>
      <PageHero
        link={{ to: "/news", label: "← News" }}
        title="How stories are picked"
      />

      <Section
        title="Score inputs"
        intro="Each input scores a story from 0 to 1, and the weights turn that into one score. The weights are a first pass set by hand, not fitted to anything, and may change."
      >
        {daily.data && weekly.data ? (
          <Inputs daily={daily.data} weekly={weekly.data} />
        ) : daily.isError || weekly.isError ? (
          <p className="text-ink-secondary">The weights are unavailable right now.</p>
        ) : (
          <Skeleton className="h-48" />
        )}
      </Section>

      <Section title="Sources">
        <div className="grid max-w-4xl gap-6 text-sm leading-relaxed text-ink-secondary md:grid-cols-2">
          <p>
            Stories come from the source, not from news articles. Company news is the 8-K filings each company in
            the rankings makes with the SEC, read through the press release attached, or the filing itself when
            there is none. Economic and government news is the Federal Reserve's monetary-policy releases, the
            BLS's headline figures, and SEC and FTC press releases.
          </p>
          <p>
            Routine filings are skipped: vote results, bylaw changes, unregistered share sales, credit agreements,
            and filings with no press release that only list exhibits or make a disclosure. Releases by the same
            company on the same kind of news within 36 hours become one story.
          </p>
        </div>
      </Section>

      <Section title="When digests are built">
        <div className="grid max-w-4xl gap-6 text-sm leading-relaxed text-ink-secondary md:grid-cols-2">
          <p>
            A day's digest covers the 24 hours to 7:00 ET and is built at 7:30 ET on weekdays, before the open.
            Monday's covers the weekend too. It keeps the top 10 stories scoring at least 0.20, saving up to two
            places for government and economic news that scores at least 0.30.
          </p>
          <p>
            A week's digest covers the seven days to 7:00 ET on Saturday, so Friday's session and the
            earnings released after it are in, and is built at 7:30 that morning. It keeps the top 15.
          </p>
        </div>
      </Section>
    </div>
  );
}
