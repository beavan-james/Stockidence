# News Summaries

The News page gives a short daily summary of the important news and a long
weekly article on everything that happened that week. Both are written by a
small local model from the full text of the articles, and both list their
sources. This file is the governing spec for that pipeline: the article
scraper, the model harness, and where the jobs run.

Status (2026-11-23): the scraper (steps 2–3), the model harness (steps
4–7) and the News page showing the summaries are built and tested, the
harness against a scripted model; none has run on the server yet. Still to
build: the selection changes (step 1).

## What the reader gets

- **Daily summary** (weekdays, by ~07:50 ET): one paragraph of 150–200
  words. Concise but specific: which companies and government bodies, what
  happened, and the exact figures (revenue, EPS, guidance, deal value, tariff
  rate, rate decision).
- **Weekly article** (Saturdays, by ~08:15 ET): 2,500–4,000 words in
  sections (policy and the economy, earnings, deals, then sectors), opening
  with a short overview of the week.
- **Sources** under every summary and every weekly section: headline,
  outlet, link. Article text is never shown on the site, only what the
  model wrote and the links.

The digest ranking (`mart/news_digest.py`) stays in the pipeline as the step
that chooses which stories get read. Its scores aren't shown on the page.

As built: `GET /api/summary/{daily,weekly}` (`service/news_summary.py`)
serves the latest written summary on or before `?date=` (the latest of
all without one), each part with its sources. A summary counts as written
when at least one part has text, so a daily whose paragraph failed its
checks falls back to the article before it. Previous and next step through
written summaries; from the first one, previous goes on to the digest
before it. A source is the page its story's card was read from
(`mart.news_story_cards.source_url`), named by that article in
`staging.stg_news_articles`; a story with no card falls back to its own
article. On the News page (`components/news/Summary.tsx`) each digest
section shows that article: the daily paragraph, or the weekly overview
and then each section under its heading, with that part's sources beside
it on wide screens and under it on phones. The overview has no list of its
own, since every one of its stories is listed under a section. A
`sources_only` weekly section shows its heading and sources. A date with
no article on or before it (every digest before the first run) shows the
digest's top 10 stories as headline links, without scores.

## Principles

- Code chooses, fetches, plans and checks; the model only turns facts it is
  given into sentences. Same rule as AGENTS.md: the model sits on top of the
  deterministic core and never replaces it.
- Every number and ticker the model writes must appear in what it was
  given, or the output is rejected.
- No advice. The summaries report news; they never say to buy, sell or
  hold.
- Every model output is stored with the model name and prompt version, so
  any sentence on the site traces back to its sources.

## Pipeline

| Step | Who | Writes | Notes |
|---|---|---|---|
| 1. Select | rules | `mart.news_digest_*` (exists) | Daily top 10, weekly top 15 |
| 2. Fetch | scraper | `raw.news_article_pages` | Picked stories only |
| 3. Extract | trafilatura | `staging.stg_news_article_text` | Main text, capped |
| 4. Read | model | `mart.news_story_cards` | One card per story, reused by the weekly |
| 5. Plan | rules | (in memory) | Weekly sections only |
| 6. Write | model | `mart.news_summaries` | Daily paragraph, weekly sections |
| 7. Check | rules | (rejects or retries) | Numbers, tickers, length, no advice |

### 1. Selection changes

- **Policy category.** The `macro` category catches the Fed, rates,
  inflation, jobs data and tariffs. A new `policy` category catches
  government action: SEC, FTC, DOJ/antitrust, Congress (bills, hearings),
  executive orders, the White House, sanctions and export controls.
- **Reserved slots.** Each daily digest keeps up to 2 of its 10 places for
  `policy` or `macro` stories when the day has any.
- **Weekly coverage.** The weekly article reads every story from that week's
  daily digests plus the weekly top 15, merged by story.

Like the other digest thresholds, these are provisional.

### 2–3. Article fetch (new source)

The linked publisher pages, not a provider API.

| | |
|---|---|
| Cadence | Event-driven: inside the digest jobs, right after selection. The weekly job also reads any of the week's daily stories still unread. |
| Watermark | `url` |
| Cache TTL | A success is never fetched again, and neither is a refusal (403 or another 4xx), a robots.txt block or a page under 150 words. A timeout, a 429, a 5xx or an unreadable robots.txt is retried after 6 hours, at most 3 attempts. robots.txt is read once per domain per run. |
| Volume | ~10 stories a day, at most 3 page requests per story and 60 per run (`max_requests`, raised for a backfill) |

Rules:

- Honest user agent `StockidenceBot/0.1`. Obey robots.txt: a 401 or 403
  on robots.txt means keep out, another 4xx means no rules, and a 5xx or
  no answer means try again later.
- Skip any domain whose robots.txt disallows the named AI crawlers
  (ClaudeBot, anthropic-ai, GPTBot, CCBot, Google-Extended). Today that is
  Yahoo Finance, Reuters and The Globe and Mail.
- Never work around a 403, a paywall or a bot check.
- A redirect to another domain is held to that domain's robots.txt.
- One request at a time, 2 seconds between requests to the same domain,
  15-second timeout, HTML only, 5 MB at most.
- Per story, try the lead article first, then the others earliest first,
  and stop at the first that gives at least 150 words. At most 3 pages are
  requested per story; links skipped by robots.txt don't count.
- Remove forms and pop-up dialogs, then extract the main text with
  trafilatura. Without that step, one test page came back as its sign-in
  form. Sections next to the article, such as a company profile, can still
  come through.
- Keep the first 1,500 words. Some pages are full earnings-call
  transcripts (one test page was 4,900 words).

Test on 16 domains, one recent digest link each (2026-11-22): 11 gave
full text. Reuters is disallowed by robots.txt, and Morningstar,
AlphaStreet and The Globe and Mail returned 403. Skipping those and the AI
opt-outs, 183 of 193 daily stories and 59 of 60 weekly stories in the test
warehouse still had a readable article (domains outside the 16 tested were
counted as readable).

First run of the built scraper (2026-11-22, on the test warehouse's
Sep 8 digest): 6 of 10 stories read, with 7 page requests in 21 seconds.
The other 4 had links only on Yahoo Finance and intellectia.ai (AI
opt-outs) and Investing.com (disallowed by robots.txt on one domain, 403 on
the other).

Tables:

- `raw.news_article_pages`: `url` (key), `first_tried_at`, `last_tried_at`,
  `attempts`, `domain`, `http_status`, `final_url`, `robots` (`allowed` /
  `disallowed` / `ai_optout` / `unreachable`), `html` (null on failure),
  `error`.
- `staging.stg_news_article_text`: `url` (key), `text`, `words`,
  `truncated`, `extractor` (library, version and cleaning; a change
  re-extracts every page), `extracted_at`.

Code: `ingest/articles.py` (plan, fetch, land) and
`staging/article_text.py`. Registry entries: `news_article.page` and
`news_article.text`.

### 4. Story cards

One model call per story, on the day it is picked. The output must match a
JSON schema, which the model server enforces while it writes:

```json
{
  "what": "one or two sentences",
  "companies": [{"ticker": "NVDA", "name": "Nvidia"}],
  "government": ["Federal Trade Commission"],
  "figures": [{"label": "deal value", "value": "13", "unit": "USD bn"}],
  "why_it_matters": "one sentence"
}
```

Checks: every figure appears in the article text, and every ticker is one
of the story's tickers or appears in the text. On a failure, retry once at
temperature 0. If that fails too, build the card from the news feed's own
summary and mark it `fallback`.

As built:

- The number check covers the whole card, not just `figures`: every
  number in it must be in the prompt (the article, headline, feed summary
  and date). Rules for numbers are under step 7.
- A story with no readable article gets its fallback card straight away,
  with no model call.
- A fallback card is the feed summary's opening sentences (two at most,
  400 characters, never less than the first), the story's tickers, and no
  figures. Some feed summaries run a whole paragraph.
- Stories that share an article are one event (Tuesday's story picked
  again for the week), so they share cards: a story needs a card only when
  no card is keyed by any of its articles or those of a story it shares an
  article with.
- A fallback card is read again when a readable page has arrived since it
  was made (a fetch the weekly job retried). Otherwise a card is made once;
  a prompt change doesn't redo old cards (`redo` in the op config does).

`mart.news_story_cards`: `story_key` (the lead article's `article_id`),
`source_url`, `card` (JSON), `status` (`ok` / `fallback`), `model`,
`prompt_version`, `input_tokens`, `output_tokens`, `seconds`, `created_at`.

The weekly article reads these cards, never the articles again. A week is
40–50k tokens of article text, 4× the context and ~40 minutes just to read,
but only ~10k tokens of cards.

### 5. Weekly plan (rules, no model)

- Merge stories about the same company across the week, in date order, so a
  story that develops over several days reads as one thread.
- Sections in a fixed order: Policy and the economy, Earnings, Deals, then
  one per sector (from `mart.weekly_rankings` for ranked stocks), ordered by
  their stories' summed scores. Sections with fewer than 2 stories fold into
  "Also this week".
- A section's cards must fit ~3k tokens; a bigger one splits in two.

As built (`summaries/plan.py`):

- A thread goes to the first topic of its highest-scored story, else to its
  company's sector, else to "Also this week". Sectors come from the latest
  weekly rankings, then the quarterly ones for stocks the weekly list
  doesn't have.
- Daily and weekly scores aren't on one scale, so an event picked by both
  takes the higher.
- A split section is headed "Earnings, part 1", "Earnings, part 2", and
  keeps whole threads together where they fit.

### 6. Writing

- **Daily:** the day's cards (~2.5k tokens) in rank order → one paragraph,
  leading with the biggest company and government news.
- **Weekly:** one call per section: that section's cards plus one line on
  what each other section covers, so they don't repeat each other → 300–600
  words. Then one call for a ~150-word overview from the section plan.

### 7. Checks on written text

- Every number and ticker appears in the cards that call was given.
- Length within bounds.
- No advice wording ("buy", "sell", "should", price targets).
- On a failure, retry once at temperature 0. If that fails too, the daily
  shows only its source list that day, and a weekly section is replaced by
  its source list.

As built (`summaries/checks.py`), everything is checked against the
prompt that call was given:

- **Numbers.** A number passes when the prompt has it, written the same
  way or as a word from one to twelve, or when it rounds one in the prompt
  and keeps at least two significant figures (13.48 written as 13.5 or 13
  passes; 2.4 written as 2 doesn't). Labels such as Q3 aren't checked.
- **Tickers.** The prompts ask for tickers in parentheses after the name,
  "Nvidia (NVDA)". Any capitalized code in parentheses or after a `$`
  must be in the prompt, which also catches made-up acronyms.
- **Advice.** Recommendation wording: "should", "ought to", "recommend",
  buy/sell/hold ratings, "is a buy", "time to sell", price targets,
  upgrades and downgrades to a rating, "investors may want". The words
  buy and sell alone aren't banned, since deal news needs them ("agreed to
  buy"). This narrows the list above; flagged for review.
- **Length.** The prompts ask for the spec's counts (daily 150–200 words,
  a section 300–600, the overview 120–180). The check allows 15% either
  side, since a small model doesn't count words exactly.
- **Form.** Headings and lists are rejected; bold markers are removed. The
  daily is joined into one paragraph.
- A reply cut off at its output limit counts as a failure.

`mart.news_summaries`: `period`, `digest_date`, `part` (0 = daily
paragraph or weekly overview, 1..n = weekly sections; together the key),
`heading`, `body`, `story_keys`, `status`, `model`, `prompt_version`,
`created_at`.

## Model and harness

- **Model:** Qwen3.5-4B, Ollama tag `qwen3.5:4b-q4_K_M` (3.3 GB; the
  weights include the image encoder, which the summaries don't use).
  Thinking off (`think: false`).
- **Server:** the `ollama` service in `docker-compose.yml`, reached at
  `OLLAMA_URL` (`http://ollama:11434`). It publishes no port, since Ollama
  has no authentication. The host has 11 GiB of memory (9.7 GiB available
  with the stack running) and 2 Arm cores (Neoverse-N1, one thread each),
  so Ollama already uses both.
- **Context:** 16k (`OLLAMA_CONTEXT_LENGTH`). The model supports 262k, but
  only 8 of its 32 layers keep per-token history (~32 KiB a token), so 16k
  costs ~0.5 GiB. The whole thing needs ~4 GB.
- **Loaded only while a summary job runs:** Ollama loads the model on the
  first call and unloads it two minutes after the last
  (`OLLAMA_KEEP_ALIVE`), so it never holds memory during a retrain.
- **One call at a time** (`OLLAMA_NUM_PARALLEL=1`): two cores don't get
  faster with parallel calls. The model uses both cores, so the site may
  answer slower during a summary run.
- **Sampling** (the model card's settings without thinking): temperature
  0.7, top_p 0.8, top_k 20, presence_penalty 1.5. Story cards pass their
  JSON schema as `format`, so the output always parses.
- **Token budget per call:** context − system prompt − max output − 10%
  margin, counted before each call with Qwen's own tokenizer file from
  Hugging Face (Ollama has no endpoint for counting). If the input doesn't
  fit, the harness splits the work; it never cuts text off silently.
  The Dockerfile bakes `tokenizer.json` (12.8 MB) into the image, pinned to
  a commit of the model repo; `QWEN_TOKENIZER` points elsewhere. Without
  the file (a local checkout) the harness logs a warning and estimates 3
  characters a token, which overcounts. Only weekly sections are split (the
  plan, step 5); a prompt still over budget fails that card or part and is
  logged, never cut.
- **When the server fails:** no connection, an HTTP error (a model not
  pulled, out of memory) or a 20-minute timeout stops the run instead of
  storing fallbacks. The save step after each model step keeps what was
  finished (cards, or whole digests' summaries), then fails the run.
- **Output caps:** 600 tokens for a card, 450 for the daily, 1,100 for a
  section, 400 for the overview.
- **Prompts** live in code with a `PROMPT_VERSION` constant. Changing a
  prompt bumps the version.

Measured on the server (2026-11-22, `qwen3.5:4b-q4_K_M`, 2 cores):
reading 14.7 tokens a second (a 3,772-token prompt took 4 min 16 s) and
writing 4.1 tokens a second. A cold load takes under a minute, once per
job. The MTP build (`qwen3.5:4b-mtp-q4_K_M`) wrote slower, 2.9 tokens a
second, so it isn't used.

| Run | Work | Time |
|---|---|---|
| Daily | 10 cards (~1.4k tokens in, ~200 out: ~2.5 min each) + the paragraph (~2.8k in, ~270 out: ~4 min) | ~30 min; ~40 if every article is long |
| Weekly | ~5 new cards + ~7 sections (~2.5k in, ~600 out: ~5 min each) + the overview | ~55 min |

Reading is most of a card's time, so article length drives the daily run.
A retry after a failed check costs one more call. Both runs still end long
before the next job: the daily by about 08:10 (nothing else until 17:30),
the weekly by about 08:45 on Saturday.

To measure on the server: `--verbose` prints the reading speed ("prompt
eval rate") and the writing speed ("eval rate"). Use a real article as
the prompt for a realistic reading speed.

```bash
docker compose exec ollama ollama run qwen3.5:4b-q4_K_M --think=false --verbose "<article text>"
```

Code: `src/stockidence/summaries/` (`model.py` the client and token
counter, `prompts.py` with `PROMPT_VERSION`, `checks.py`, `stories.py`,
`cards.py`, `plan.py`, `writing.py`, `store.py` for the warehouse reads and
writes, `run.py` for the two model steps). Registry entries:
`news_summary.card` and `news_summary.text`. Tests: `tests/test_summaries.py`
(scripted model, fake HTTP server) and the job tests in
`tests/test_definitions.py`.

Dry run on the test warehouse (2026-11-22, no model; feed-summary cards in
place of model cards). Sep 8 daily: 10 stories, 6 with article text, card
prompts of ~1.2k–4.1k estimated tokens (the estimate overcounts by about a
third), a daily prompt of ~1.4k. Week of Sep 4: 58 stories joined into 43
events (13 picked more than once), planned as Policy and the economy (2),
Earnings (19), Deals (4), Technology (5), Utilities (2) and Also this week
(11), the largest section prompt ~2.8k estimated tokens and the overview's
~4.2k.

## Orchestration

DuckDB allows one writer, and `Warehouse.connect` gives up after ~164
seconds of retries. Both retrains hold the lock for long stretches, so
nothing new may be scheduled on top of them, and nothing should land on
other jobs either.

Current schedule in New York time (the UTC crons move an hour with DST):

| Job | When (ET) | Holds DuckDB |
|---|---|---|
| `news_ingest` | 07:00 and 19:00 (06:00 and 18:00 in winter), daily | Briefly |
| `daily_digest` | 07:30 weekdays | Briefly |
| `weekly_digest` | 07:30 Saturday | Briefly |
| `weekdays_ingest` | 17:30 (16:30 in winter), Mon–Fri | Briefly |
| `weekly_model_refresh` | 17:30 Friday | **For hours** |
| `daily_ingest` | 21:00 (20:00 in winter), daily | Briefly |
| `monthly_ingest` | 22:00 (21:00 in winter), the evening before the 1st | Briefly |
| `quarterly_model_refresh` | 23:00 (22:00 in winter), the evening before the 1st of Jan/Apr/Jul/Oct | **For hours** |
| `refresh_tickers`, `refresh_quotes` | On demand from the site | Briefly |

Placement:

- **The daily summary chains onto `daily_digest`** (07:30 weekdays, ~30
  minutes). Nothing else is scheduled until `weekdays_ingest` at 17:30
  (16:30 in winter).
- **The weekly summary chains onto `weekly_digest`** (07:30 Saturday, ~55
  minutes), 14 hours after the weekly retrain starts.
- **The summary steps never hold a DuckDB connection while the model
  runs:** read inputs, close, call the model, open, write, close. The lock
  is held for seconds, not for the ~30–55 minutes of model work. Keeping
  them apart in time also matters for speed, since the retrain and the
  model both want both cores.
- **The model steps stay out of the pool (below):** a read op and a write
  op take the slot, and the model op between them doesn't. The article
  fetch does keep its slot for the few minutes it runs at most, since passing
  the pages' HTML between ops would mean writing it to disk twice.
  Built as five ops at the end of both digest jobs:
  `read_summary_inputs_op` (pool) → `write_story_cards_op` (model) →
  `save_story_cards_op` (pool) → `write_summaries_op` (model) →
  `save_summaries_op` (pool). Saving the cards before the summaries means a
  failure in the writing step doesn't lose ~25 minutes of cards. A
  summary already written from the same stories is skipped; a rebuilt
  digest with other stories is written again.
  A backfill (`days` above 1 in the digest op's config) writes a summary
  for every digest it builds, ~30 minutes each.

Known overlaps (with the pool below, these jobs wait instead of failing):

- **Quarterly retrain into the morning digest:** if the quarterly retrain is
  still running at 07:30 on the 1st, the digest job (existing, and the
  summary with it) waits for it. Possible on any quarter where the 1st
  is a weekday or a Saturday.
- **Existing Friday collisions:** in summer, `weekdays_ingest` (21:30 UTC =
  17:30 ET) starts the same minute as `weekly_model_refresh`. The evening
  news pull and `daily_ingest` land inside the retrain whenever it runs
  past them (1.5 and 3.5 hours in).
- **Monthly into quarterly:** `monthly_ingest` runs one hour before the
  quarterly retrain on the last evening of Mar/Jun/Sep/Dec.

**Concurrency pool.** Every op of a scheduled or retrain job claims the
Dagster pool `warehouse` (`WAREHOUSE_POOL` in `definitions.py`), which
`dagster.yaml` limits to one op at a time. An op that lands on another job
waits for the slot instead of failing after 164 seconds, so the overlaps
above no longer depend on how long a retrain happens to run. The slot is
taken per op, so a waiting job can get in between a retrain's steps.

- **Left out:** `refresh_tickers` and `refresh_quotes`, so a site visitor
  never waits behind a retrain. They keep relying on the connection
  retries.
- **Cost:** on Fridays the evening news pull and `daily_ingest` now run late,
  when the weekly refresh step ends, instead of failing.
- **Server:** pools need the instance's concurrency tables. If the daemon
  logs that the instance doesn't support them, run
  `dagster instance migrate` once.
- **Test:** `test_scheduled_and_retrain_ops_share_the_warehouse_pool`
  fails if a new op in a scheduled job leaves the pool out.

Still needed: actual run times of `weekly_model_refresh` and
`quarterly_model_refresh` from the server's run history.

## Decisions

Agreed 2026-11-22:

- The scraper spec above, including honoring AI-crawler opt-outs.
- The harness: one card per story, weekly from cards, section-by-section
  writing, number and ticker checks.
- The `policy` category and reserved daily slots (provisional values).
- The new tables: `raw.news_article_pages`,
  `staging.stg_news_article_text`, `mart.news_story_cards`,
  `mart.news_summaries`.
- Summary jobs placed away from the retrains and other jobs.
- Qwen3.5-4B served by Ollama, unloaded between jobs.
- The `warehouse` concurrency pool (built; the user is reviewing it).
- The harness as built above (2026-11-22), pending review: the advice
  phrase list in place of banning "buy" and "sell", the 15% length
  slack, rounding to two significant figures counting as a match.

Open:

- Retrain run times.
- The first real run on the server: card pass rate, fallback rate, and
  actual run times against the estimates above.
