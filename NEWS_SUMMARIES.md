# News Summaries

The News page gives a short daily summary of the important news and a long
weekly article on everything that happened that week. Both are written by a
small local model from the full text of the articles, and both list their
sources. This file is the governing spec for that pipeline: the article
scraper, the model harness, and where the jobs run.

Status: agreed design, not built (2026-11-22).

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
  with the stack running) and 2 cores.
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
- **Prompts** live in code with a `PROMPT_VERSION` constant. Changing a
  prompt bumps the version.

Rough timing, assuming ~20 tokens a second reading and ~7 writing (not yet
measured on the server):

| Run | Work | Time |
|---|---|---|
| Daily | 10 cards + 1 paragraph | ~17 min |
| Weekly | ~5 new cards + ~7 sections + overview | ~45 min |

To measure on the server: `--verbose` prints the reading speed ("prompt
eval rate") and the writing speed ("eval rate"). Use a real article as
the prompt for a realistic reading speed.

```bash
docker compose exec ollama ollama run qwen3.5:4b-q4_K_M --think=false --verbose "<article text>"
```

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

- **The daily summary chains onto `daily_digest`** (07:30 weekdays, ~20
  minutes). Nothing else is scheduled until `weekdays_ingest` at 17:30
  (16:30 in winter).
- **The weekly summary chains onto `weekly_digest`** (07:30 Saturday, ~45
  minutes), 14 hours after the weekly retrain starts.
- **The summary steps never hold a DuckDB connection while the model
  runs:** read inputs, close, call the model, open, write, close. The lock
  is held for seconds, not for the ~20–45 minutes of model work. Keeping
  them apart in time also matters for speed, since the retrain and the
  model both want both cores.
- **The model steps stay out of the pool (below):** a read op and a write
  op take the slot, and the model op between them doesn't. The article
  fetch does keep its slot for the few minutes it runs at most, since passing
  the pages' HTML between ops would mean writing it to disk twice.

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

Open:

- Server benchmark numbers, to replace the timing estimates.
- Retrain run times.
