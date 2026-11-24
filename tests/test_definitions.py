"""Unit tests for the Dagster definitions layer.

The ticker_data asset runs with a fake engine resource (no API keys, no
network); scheduled jobs are verified against the registry composition."""

from __future__ import annotations

import pytest
from dagster import DagsterInstance, ResourceDefinition, materialize
from dagster._core.definitions.partitions.context import partition_loading_context

from stockidence.ingest.endpoints import Cadence, scheduled_endpoints


@pytest.fixture
def defs():
    from stockidence.definitions import defs

    return defs


def test_definitions_expose_jobs_schedules_assets(defs):
    job_names = {j.name for j in defs.resolve_all_job_defs()}
    assert {"monthly_ingest", "weekdays_ingest", "overnight_ingest", "daily_ingest"} <= job_names

    schedule_names = {s.name for s in defs.schedules}
    assert {"monthly_schedule", "weekdays_schedule", "overnight_schedule", "daily_schedule"} <= schedule_names

    assert any("ticker_data" in str(k) for k in defs.resolve_asset_graph().get_all_asset_keys())


def test_ticker_asset_has_dynamic_ticker_partitions(defs):
    asset_def = defs.resolve_assets_def("ticker_data")
    assert asset_def.partitions_def.name == "ticker"  # type: ignore[union-attr]


def test_cadence_jobs_follow_registry():
    def names(job_name):
        cadence = {
            "monthly_ingest": Cadence.MONTHLY,
            "weekdays_ingest": Cadence.WEEKDAYS,
            "overnight_ingest": Cadence.OVERNIGHT,
            "daily_ingest": Cadence.DAILY,
        }[job_name]
        return {spec.name for spec in scheduled_endpoints() if spec.cadence == cadence}

    assert "commodities.gold" in names("monthly_ingest")
    assert "macro.cpi" in names("monthly_ingest")
    assert names("overnight_ingest") == {"top_gainers_losers"}
    assert "top_gainers_losers" not in names("weekdays_ingest")
    assert "ipo_calendar" in names("weekdays_ingest")
    assert "market_news" in names("daily_ingest")
    assert "quote" not in names("daily_ingest")


def test_movers_run_after_midnight_new_york(defs):
    overnight = next(s for s in defs.schedules if s.name == "overnight_schedule")
    assert overnight.job_name == "overnight_ingest"
    assert overnight.cron_schedule == "30 0 * * 2-6"  # Tue-Sat, for the Mon-Fri sessions
    assert overnight.execution_timezone == "America/New_York"


def test_ticker_data_asset_runs_with_fake_engine(tmp_path):
    from stockidence.definitions import ticker_data
    from stockidence.storage import Warehouse

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()

    class FakeEngine:
        warehouse = wh

        def __init__(self):
            self.seen: list[tuple[str, str]] = []

        def ingest_on_demand(self, endpoint, dimension, now=None):
            self.seen.append((endpoint, dimension))
            return FakeResult()

    class FakeResult:
        reason = "fake fetch"
        rows_written = 0

    engine = FakeEngine()
    instance = DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("ticker", ["AAPL"])
    with partition_loading_context(dynamic_partitions_store=instance):
        result = materialize(
            [ticker_data],
            resources={"engine": engine},
            partition_key="AAPL",
            raise_on_error=True,
            instance=instance,
        )
    assert result.success
    # transcript skipped (no earnings calendar row) but every other
    # on-demand endpoint was offered to the engine at ticker dimension
    assert ("quote", "AAPL") in engine.seen
    assert ("prices.daily", "AAPL") in engine.seen
    assert not any(endpoint == "earnings_call_transcript" for endpoint, _ in engine.seen)


def test_no_sensors_registered_push_model(defs):
    """Push model: nothing polls. The frontend launches jobs directly, so
    no sensor may remain registered."""
    assert list(defs.sensors or []) == []


def test_refresh_tickers_job_takes_ticker_config(defs):
    from stockidence.definitions import RefreshTickersConfig

    job = defs.get_job_def("refresh_tickers")
    assert "refresh_tickers_op" in job.graph.node_dict
    assert "tickers" in RefreshTickersConfig.model_fields


def test_quarterly_job_chains_refresh_dataset_retrain(defs):
    job = defs.get_job_def("quarterly_model_refresh")
    assert set(job.graph.node_dict) == {
        "quarterly_refresh_op",
        "rebuild_dataset_op",
        "retrain_model_op",
    }
    assert "quarterly_schedule" in {s.name for s in defs.schedules}


def test_full_ticker_run_executes_green_for_partition(tmp_path):
    """Sensor RunRequests launch the full per-ticker asset graph. Materialize
    it end-to-end against a seeded warehouse (fake engine = no network) and
    require success plus a persisted confidence rating."""
    from dagster import ResourceDefinition, materialize

    from stockidence.ingest.engine import IngestEngine
    from stockidence.definitions import (
        m_advanced_analytics,
        m_prices_monthly,
        m_prices_weekly,
        m_technical_indicators,
        stg_prices_daily,
        ticker_data,
        ticker_score,
    )
    from stockidence.storage import Warehouse
    from test_scoring import _seed_bars, _seed_fundamentals, _seed_profile, _seed_quotes, _seed_sentiment

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    for seed in (_seed_bars, _seed_fundamentals, _seed_profile,
                 _seed_sentiment):
        seed(wh, "UND1")
    _seed_quotes(wh, "UND1", price=319.5)  # last bar close of the ramp

    class FakeResult:
        reason = "fake fetch"
        rows_written = 0

    class FakeEngine:
        warehouse = wh

        def ingest_on_demand(self, endpoint, dimension, now=None):
            return FakeResult()

    instance = DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("ticker", ["UND1"])
    with partition_loading_context(dynamic_partitions_store=instance):
        result = materialize(
            [ticker_data, stg_prices_daily, m_prices_weekly, m_prices_monthly,
             m_advanced_analytics, m_technical_indicators, ticker_score],
            resources={"engine": FakeEngine()},
            partition_key="UND1",
            instance=instance,
            raise_on_error=True,
        )
    assert result.success

    row = wh.connect(read_only=True).execute(
        "SELECT rating, confidence_score FROM mart.m_confidence_ratings "
        "WHERE ticker = 'UND1'"
    ).fetchone()
    assert row is not None
    assert row[0] in ("Buy", "Strong Buy")
    assert 55.0 <= row[1] <= 85.0

def test_scheduled_and_retrain_ops_share_the_warehouse_pool(defs):
    """Every op a schedule or a retrain runs claims the one-slot warehouse
    pool, so overlapping jobs queue instead of failing on the DuckDB lock.
    The site-triggered jobs stay out, so a visitor never waits on a retrain."""
    from stockidence.definitions import WAREHOUSE_POOL

    site_triggered = {"refresh_tickers", "refresh_quotes"}
    # the model ops never open the warehouse, so they don't hold the slot
    # through 30-55 minutes of model work
    model_ops = {"write_story_cards_op", "write_summaries_op"}
    jobs = {j.name: j for j in defs.resolve_all_job_defs() if not j.name.startswith("__")}
    assert {s.job_name for s in defs.schedules} | {"model_retrain", "weekly_rank"} <= set(jobs)
    for name, job in jobs.items():
        for node_name, node in job.graph.node_dict.items():
            expected = None if name in site_triggered or node_name in model_ops else WAREHOUSE_POOL
            assert node.definition.pool == expected, (name, node_name, node.definition.pool)


def test_the_engine_resource_never_opens_the_warehouse(tmp_path, monkeypatch):
    """Resources start before an op claims its pool slot, so opening the
    warehouse there fails on a retrain's lock instead of waiting for it."""
    from stockidence import storage
    from stockidence.definitions import engine_resource

    path = tmp_path / "w.duckdb"
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", str(path))

    def refuse(*_args, **_kwargs):
        raise AssertionError("opened the warehouse while starting the resource")

    with monkeypatch.context() as m:
        m.setattr(storage.duckdb, "connect", refuse)
        engine = engine_resource()
    assert not path.exists()

    with engine.warehouse.connect(read_only=True) as con:  # the op's first connection
        tables = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"raw_gainers_losers", "watermarks", "news_summaries"} <= tables


def test_a_failed_schema_bootstrap_is_tried_again(tmp_path, monkeypatch):
    from stockidence.storage import Warehouse

    wh = Warehouse(tmp_path / "w.duckdb", create_schema=True)
    calls = []
    real = Warehouse.init_schema

    def flaky(self):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("locked")
        real(self)

    monkeypatch.setattr(Warehouse, "init_schema", flaky)
    with pytest.raises(RuntimeError, match="locked"):
        wh.connect()
    wh.connect().close()
    wh.connect().close()
    assert len(calls) == 2  # retried once, then never again


def test_digest_jobs_end_with_the_summaries(defs):
    for name in ("daily_digest", "weekly_digest"):
        nodes = list(defs.get_job_def(name).graph.node_dict)
        assert nodes[-5:] == ["read_summary_inputs_op", "write_story_cards_op", "save_story_cards_op",
                              "write_summaries_op", "save_summaries_op"]


def _summary_job(tmp_path, llm):
    """The five summary ops after a stand-in digest op, on a warehouse with
    one picked story and its article text."""
    from dagster import job, op

    from stockidence.definitions import _summarize
    from stockidence.storage import Warehouse

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        con.execute(
            "INSERT INTO mart.news_digest_stories (period, digest_date, rank, headline, summary, url,"
            " published_at, tickers, n_articles, n_outlets, coverage, reaction, category, on_site, score)"
            " VALUES ('daily', '2026-11-20', 1, 'Nvidia beats', 'Nvidia topped estimates.',"
            " 'https://a.example/1', '2026-11-19 21:00', ['NVDA'], 1, 1, 0, 0, 0, 0, 0.5)")
        con.execute("INSERT INTO mart.news_digest_articles VALUES ('daily', '2026-11-20', 1, 'a1')")
        con.execute("INSERT INTO staging.stg_news_articles (article_id, published_at, headline, url)"
                    " VALUES ('a1', '2026-11-19 21:00', 'Nvidia beats', 'https://a.example/1')")
        con.execute("INSERT INTO staging.stg_news_article_text VALUES ('https://a.example/1', ?, 200,"
                    " false, 'x', '2026-11-20 12:00:00+00')", [" ".join(["Nvidia revenue rose."] * 70)])

    class FakeEngine:
        warehouse = wh

    @op
    def built_digest() -> dict:
        return {"digests": [{"period": "daily", "digest_date": "2026-11-20"}]}

    @job(resource_defs={"engine": ResourceDefinition.hardcoded_resource(FakeEngine()),
                        "llm": ResourceDefinition.hardcoded_resource(llm)})
    def summaries_only():
        _summarize(built_digest())

    return wh, summaries_only


def test_summary_ops_run_after_a_digest(tmp_path):
    import json

    from stockidence.summaries.model import ESTIMATE, Reply

    class Writer:
        model = "fake"
        count_tokens = ESTIMATE

        def chat(self, system, user, *, max_output, temperature=None, schema=None):
            if schema:
                text = json.dumps({"what": "Nvidia revenue rose.", "why_it_matters": "",
                                   "companies": [{"ticker": "NVDA", "name": "Nvidia"}],
                                   "government": [], "figures": []})
            else:
                text = "Nvidia (NVDA) reported that revenue rose. " + "Traders took note. " * 55
            return Reply(text, 10, 10, 1.0, False)

    wh, summaries_only = _summary_job(tmp_path, Writer())
    result = summaries_only.execute_in_process(instance=DagsterInstance.ephemeral())
    assert result.success
    out = result.output_for_node("save_summaries_op")
    assert out["cards"] == 1 and out["summary_parts"] == 1 and "summary_inputs" not in out
    with wh.connect(read_only=True) as con:
        assert con.execute("SELECT status FROM mart.news_summaries").fetchall() == [("ok",)]


def test_a_model_outage_saves_the_cards_then_fails(tmp_path):
    from stockidence.summaries.model import ESTIMATE, ModelUnavailable

    class Down:
        model = "fake"
        count_tokens = ESTIMATE

        def chat(self, *a, **kw):
            raise ModelUnavailable("connection refused")

    wh, summaries_only = _summary_job(tmp_path, Down())
    result = summaries_only.execute_in_process(instance=DagsterInstance.ephemeral(), raise_on_error=False)
    assert not result.success
    assert [e.step_key for e in result.all_events if e.event_type_value == "STEP_FAILURE"] == [
        "save_story_cards_op"]
    with wh.connect(read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM mart.news_story_cards").fetchone()[0] == 0


def test_digest_jobs_read_the_picked_articles(defs):
    for name in ("daily_digest", "weekly_digest"):
        nodes = set(defs.get_job_def(name).graph.node_dict)
        assert {"fetch_articles_op", "stage_article_text_op"} <= nodes


def test_article_ops_run_after_a_digest(tmp_path):
    """The two article ops in a job of their own: no stories to read on an
    empty warehouse, so nothing is fetched, but every log line and output
    key is exercised."""
    from dagster import job, op

    from stockidence.definitions import fetch_articles_op, stage_article_text_op
    from stockidence.storage import Warehouse

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()

    class FakeEngine:
        warehouse = wh

    @op
    def built_digest() -> dict:
        return {"digests": [{"period": "weekly", "digest_date": "2026-11-20"}]}

    @job(resource_defs={"engine": ResourceDefinition.hardcoded_resource(FakeEngine())})
    def articles_only():
        stage_article_text_op(fetch_articles_op(built_digest()))

    result = articles_only.execute_in_process(instance=DagsterInstance.ephemeral())
    assert result.success
    out = result.output_for_node("stage_article_text_op")
    assert out["articles"]["stories"] == 0 and out["articles"]["page_requests"] == 0
    assert out["article_text"] == 0
