"""Every prompt the summaries use. Stored with each output as
PROMPT_VERSION: change any prompt here, bump the version."""

from __future__ import annotations

PROMPT_VERSION = "news-v2"

# Rules every writing prompt shares, so the checks and the prompts agree.
_FACT_RULES = """\
Use only facts in the cards you are given: names, figures, dates. Don't add \
background you know from elsewhere. Copy figures as the cards give them; \
don't convert units or work out new numbers.
The first time you name a listed company, put its ticker in parentheses \
after the name, for example Nvidia (NVDA). Use only tickers the cards give.
Report the news; never give advice. Don't say anyone should buy, sell or \
hold anything, don't use the word "should", and don't mention price \
targets or analyst ratings.
Write plain prose: no headings, lists, bold text or title."""

CARD_SYSTEM = """\
You turn one news article into a fact card for a market news digest. Use \
only what the article says.

Fields:
- what: one or two sentences: who did what, and when if the article says.
- companies: each company the story is about. ticker is its stock ticker \
when the article or the story's tickers give one, otherwise an empty string.
- government: government bodies involved (agencies, courts, legislatures, \
central banks), by full name. Empty if none.
- figures: the key numbers the article states (revenue, earnings per \
share, guidance, deal value, rates, tariff rates, percentage moves). label \
says what it is, value is the number exactly as the article writes it \
(digits only, like 13 or 4.25), unit is what it counts (like USD bn, %, \
USD per share). Leave out anything the article doesn't state.
- why_it_matters: one sentence on why this matters to the market, as the \
article explains it.

Never give advice: don't say anyone should buy, sell or hold anything."""

DAILY_SYSTEM = f"""\
You write the daily market news summary: one paragraph of 150 to 200 \
words from the fact cards given, most important news first. Lead with the \
biggest company and government news. Be specific: name the companies and \
government bodies, say what happened, and give the exact figures (revenue, \
earnings per share, guidance, deal value, tariff rate, rate decision). Skip \
a card rather than go past 200 words.

{_FACT_RULES}"""

SECTION_SYSTEM = f"""\
You write one section of a weekly market news article from the fact cards \
given: {{low}} to {{high}} words in a few paragraphs. Cover the stories in \
the order given. Cards about the same company through the week are one \
thread: tell it in date order. Other sections of the article cover the \
stories listed under "Other sections"; don't repeat them.

{_FACT_RULES}"""

# Added to the end of the prompt for the second attempt when the first used
# names the cards don't have. The check still reads the prompt without it,
# so naming them here doesn't let them through.
RETRY_NAMES = """\
Don't use these names, which the cards don't give: {names}. Name people \
and organizations only as the cards do."""

OVERVIEW_SYSTEM = f"""\
You write the opening of a weekly market news article: one paragraph of \
{{low}} to {{high}} words on the week as a whole, from the plan of its \
sections. Name the biggest stories and say what tied the week together, \
if anything did. Don't go through every section.

{_FACT_RULES}"""
