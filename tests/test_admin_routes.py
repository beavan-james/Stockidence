"""The POST routes that launch pipeline runs: shut without the admin token,
and checked tickers once open. No Dagster or warehouse: the launches and
the symbol-list check are stubbed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stockidence.api import auth
from stockidence.api.app import app
from stockidence.service import dagster_client, warehouse

TOKEN = "test-admin-token"
ADMIN = {"X-Admin-Token": TOKEN}

client = TestClient(app)


@pytest.fixture
def launches(monkeypatch):
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(auth, "configured_token", lambda: TOKEN)
    monkeypatch.setattr(
        dagster_client, "submit_refresh_run", lambda t: calls.append(("refresh", t)) or "run-1"
    )
    monkeypatch.setattr(
        dagster_client, "submit_quotes_run", lambda t: calls.append(("quotes", t)) or "run-2"
    )
    monkeypatch.setattr(
        warehouse, "tickers_outside_coverage", lambda t: [x for x in t if x == "ZZZZ"]
    )
    return calls


@pytest.mark.parametrize("path", ["/api/pipeline/refresh", "/api/quotes/refresh"])
def test_a_launch_without_the_token_is_refused(launches, path):
    assert client.post(path, json={"tickers": ["AAPL"]}).status_code == 401
    wrong = client.post(path, json={"tickers": ["AAPL"]}, headers={"X-Admin-Token": "guess"})
    assert wrong.status_code == 401
    assert launches == []


@pytest.mark.parametrize("path", ["/api/pipeline/refresh", "/api/quotes/refresh"])
def test_the_routes_stay_shut_while_no_token_is_set(launches, monkeypatch, path):
    monkeypatch.setattr(auth, "configured_token", lambda: "")
    # an empty header can't match an unset token
    response = client.post(path, json={"tickers": ["AAPL"]}, headers={"X-Admin-Token": ""})
    assert response.status_code == 403
    assert launches == []


def test_refresh_with_the_token_launches_the_cleaned_list(launches):
    response = client.post(
        "/api/pipeline/refresh", json={"tickers": [" aapl", "AAPL", "msft", ""]}, headers=ADMIN
    )
    assert response.status_code == 202
    assert response.json() == {"run_id": "run-1", "tickers": ["AAPL", "MSFT"]}
    assert launches == [("refresh", ["AAPL", "MSFT"])]


@pytest.mark.parametrize(
    ("tickers", "detail"),
    [
        ([], "no tickers"),
        (["AAPL", "ZZZZ"], "ZZZZ"),
        (["AAPL", "<script>"], "<SCRIPT>"),
        ([f"T{i}" for i in range(101)], "at most 100"),
    ],
)
def test_refresh_refuses_a_bad_list(launches, tickers, detail):
    response = client.post("/api/pipeline/refresh", json={"tickers": tickers}, headers=ADMIN)
    assert response.status_code == 422
    assert detail in response.json()["detail"]
    assert launches == []


def test_the_symbol_check_is_skipped_when_the_list_cant_be_read(launches, monkeypatch):
    monkeypatch.setattr(warehouse, "tickers_outside_coverage", lambda t: None)
    response = client.post("/api/pipeline/refresh", json={"tickers": ["ZZZZ"]}, headers=ADMIN)
    assert response.status_code == 202


def test_quotes_refresh_keeps_its_25_ticker_cap(launches):
    ok = client.post("/api/quotes/refresh", json={"tickers": ["AAPL"]}, headers=ADMIN)
    assert ok.status_code == 202
    assert launches == [("quotes", ["AAPL"])]
    many = [f"T{i}" for i in range(dagster_client.MAX_QUOTES_REFRESH + 1)]
    response = client.post("/api/quotes/refresh", json={"tickers": many}, headers=ADMIN)
    assert response.status_code == 422


def test_reads_need_no_token():
    assert client.get("/api/health").status_code == 200
