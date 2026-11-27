"""The market beside a digest's stories, for the daily paragraph and the
weekly overview: the S&P 500's move and the VIX (mart.news_digests), and
the news feed's most covered market headlines (mart.news_digest_context).

The headlines are background, never stories: the prompts allow the market
one or two sentences, with any reason for a move credited to the outlet
that reported it. A summary keeps the headlines' article ids after its
cards' keys, so its sources can list them apart (service.news_summary).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..mart.news_digest import previous_weekday
from .cards import first_sentences

# A feed summary can run a whole paragraph; the prompt needs its opening.
HEADLINE_SENTENCES = 2
HEADLINE_CHARS = 300


@dataclass(frozen=True)
class Headline:
    key: str  # the article id, kept with the summary for its sources
    headline: str
    summary: str | None
    outlet: str | None
    url: str


@dataclass(frozen=True)
class Market:
    sp500_return: float | None  # the session's (daily) or the week's (weekly)
    vix: float | None  # the latest close in that span
    headlines: tuple[Headline, ...] = ()

    @property
    def keys(self) -> list[str]:
        return [h.key for h in self.headlines]

    @property
    def empty(self) -> bool:
        return self.sp500_return is None and self.vix is None and not self.headlines


def percent(r: float) -> str:
    """A return as the prompts write it: "up 0.8%", "down 1.2%", one decimal
    (two when one would read 0.0), so a figure the model copies stays one
    the number check finds."""
    pct = abs(r) * 100
    if round(pct, 2) == 0:
        return "unchanged"
    figure = f"{pct:.1f}" if round(pct, 1) else f"{pct:.2f}"
    return f"{'up' if r > 0 else 'down'} {figure}%"


def market_block(market: Market | None, period: str, day: date) -> str | None:
    """The Market block at the end of a prompt, or None when there is
    nothing to say (digests built before the market context)."""
    if market is None or market.empty:
        return None
    if period == "daily":
        span, close = f"in {previous_weekday(day):%A}'s session", "at the close"
    else:
        span, close = "over the week", "at the week's last close"
    figures = []
    if market.sp500_return is not None:
        figures.append(f"S&P 500 {span}: {percent(market.sp500_return)}.")
    if market.vix is not None:
        figures.append(f"VIX {close}: {market.vix:.1f}.")
    lines = ["Market:"]
    if figures:
        lines.append(" ".join(figures))
    if market.headlines:
        lines.append("Most covered market headlines:")
        for h in market.headlines:
            text = f"- {h.outlet}: {h.headline}" if h.outlet else f"- {h.headline}"
            if h.summary:
                text += f" — {first_sentences(h.summary, HEADLINE_SENTENCES, HEADLINE_CHARS)}"
            lines.append(text)
    return "\n".join(lines)
