"""Transaction listing, filters, keyset pagination, analytics, and owner isolation."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import import_csv, login, make_csv

pytestmark = pytest.mark.integration


@pytest.fixture
def loaded(api: TestClient, make_user: Callable) -> TestClient:
    """An analyst with 25 transactions (T0..T24) in USD and 3 in EUR (E0..E2)."""
    login(api, make_user())
    assert import_csv(api, make_csv(25))
    eur = make_csv(3).replace(",USD,", ",EUR,").replace("\nT", "\nE")
    assert import_csv(api, eur)
    return api


def all_pages(client: TestClient, limit: int, **params: str) -> list[list[dict]]:
    pages, cursor = [], None
    while True:
        query = {"limit": limit, **params} | ({"cursor": cursor} if cursor else {})
        body = client.get("/api/v1/transactions", params=query).json()
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages


def test_keyset_pages_cover_everything_once_newest_first(loaded: TestClient) -> None:
    pages = all_pages(loaded, limit=10)
    assert [len(p) for p in pages] == [10, 10, 8]
    rows = [r for p in pages for r in p]
    assert len({r["id"] for r in rows}) == 28
    keys = [(r["occurred_at"], r["id"]) for r in rows]
    assert keys == sorted(keys, reverse=True)


def test_amounts_are_exact_decimal_strings(loaded: TestClient) -> None:
    row = loaded.get("/api/v1/transactions", params={"limit": 1}).json()["items"][0]
    assert isinstance(row["amount"], str) and row["amount"].endswith(".00")


def test_filters_combine(loaded: TestClient) -> None:
    params = {
        "category": "travel",
        "date_from": "2025-01-05",
        "date_to": "2025-01-11",
        "min_amount": "15",
    }
    rows = loaded.get("/api/v1/transactions", params=params).json()["items"]
    # travel = even i; Jan 5..10 = i 4..9; amount 10+i >= 15 → i in {6, 8}
    assert sorted(r["external_ref"] for r in rows) == ["T6", "T8"]


def test_bad_cursor_is_400(loaded: TestClient) -> None:
    response = loaded.get("/api/v1/transactions", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400


def test_summary_never_mixes_currencies(loaded: TestClient) -> None:
    body = loaded.get("/api/v1/analytics/summary").json()
    totals = {t["currency"]: t for t in body["totals"]}
    assert totals["USD"]["count"] == 25
    assert totals["USD"]["total"] == str(sum(10 + i for i in range(25))) + ".00"  # 550.00
    assert totals["EUR"]["count"] == 3 and totals["EUR"]["total"] == "33.00"
    assert {m["month"] for m in body["by_month"]} == {"2025-01"}
    usd_categories = sum(c["count"] for c in body["by_category"] if c["currency"] == "USD")
    assert usd_categories == 25


def test_other_users_see_none_of_it(loaded: TestClient, make_user: Callable) -> None:
    some_id = loaded.get("/api/v1/transactions", params={"limit": 1}).json()["items"][0]["id"]
    login(loaded, make_user())
    assert loaded.get("/api/v1/transactions").json() == {"items": [], "next_cursor": None}
    assert loaded.get(f"/api/v1/transactions/{some_id}").status_code == 404
    summary = loaded.get("/api/v1/analytics/summary").json()
    assert summary == {"totals": [], "by_category": [], "by_month": []}
