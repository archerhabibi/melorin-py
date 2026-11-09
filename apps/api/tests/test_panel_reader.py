"""One paging loop for panel reads (audit T08)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from melorin.modules.vpn.panel_reader import PanelReader, read_pages


def rows(start: int, n: int):
    return [SimpleNamespace(username=f"u{i}") for i in range(start, start + n)]


class Source:
    """A panel with ``n`` users that answers ``(page, total)`` like the adapters do."""

    def __init__(self, n: int, *, report_total: bool = True):
        self.all = rows(0, n)
        self.report_total = report_total
        self.calls: list[tuple[int, int]] = []

    async def fetch(self, *, offset: int, limit: int):
        self.calls.append((offset, limit))
        return self.all[offset : offset + limit], (len(self.all) if self.report_total else None)


@pytest.mark.asyncio
async def test_reads_every_page_and_stops_at_a_short_page():
    src = Source(250, report_total=False)
    listing = await read_pages(src.fetch, page_size=100, max_rows=10_000)
    assert len(listing.rows) == 250 and listing.complete and listing.total is None
    assert src.calls == [(0, 100), (100, 100), (200, 100)]


@pytest.mark.asyncio
async def test_stops_as_soon_as_the_reported_total_is_reached():
    src = Source(200)  # exactly two full pages: the total saves a third, empty request
    listing = await read_pages(src.fetch, page_size=100, max_rows=10_000)
    assert len(listing.rows) == 200 and listing.total == 200 and listing.complete
    assert len(src.calls) == 2


@pytest.mark.asyncio
async def test_an_empty_first_page_is_an_empty_complete_listing():
    listing = await read_pages(Source(0).fetch, page_size=100, max_rows=100)
    assert listing.rows == [] and listing.complete


@pytest.mark.asyncio
async def test_reaching_max_rows_marks_the_listing_incomplete():
    src = Source(1000, report_total=False)
    listing = await read_pages(src.fetch, page_size=100, max_rows=300)
    assert len(listing.rows) == 300 and listing.complete is False


@pytest.mark.asyncio
async def test_a_repeated_row_counts_once_against_the_total():
    async def fetch(*, offset: int, limit: int):
        # page one repeats "u0"; the panel says there are 3 distinct users
        pages = {0: rows(0, 2) + rows(0, 1), 3: rows(2, 1)}
        return pages.get(offset, []), 3

    by_row = await read_pages(fetch, page_size=3, max_rows=100)
    assert len(by_row.rows) == 3  # no key: the row count reaches the total at once
    keyed = await read_pages(fetch, page_size=3, max_rows=100, key=lambda r: r.username)
    assert [r.username for r in keyed.rows] == ["u0", "u1", "u0", "u2"] and keyed.complete


@pytest.mark.asyncio
async def test_panel_reader_pages_accounts_and_owner_accounts_with_their_own_calls():
    seen: list[tuple] = []

    class Adapter:
        async def list_accounts(self, *, offset, limit):
            seen.append(("all", offset, limit))
            return rows(offset, 1) if offset == 0 else [], None

        async def list_owner_accounts(self, username, *, offset, limit):
            seen.append(("owner", username, offset, limit))
            return [], 0

    reader = PanelReader(Adapter())
    assert len((await reader.accounts(page_size=5, max_rows=50)).rows) == 1
    owner = await reader.owner_accounts("shop-a", page_size=5, max_rows=50)
    assert owner.rows == [] and owner.total == 0 and owner.complete
    assert seen == [("all", 0, 5), ("owner", "shop-a", 0, 5)]


@pytest.mark.asyncio
async def test_read_many_returns_none_for_a_failing_account_and_reports_it():
    class Adapter:
        async def get_account(self, username):
            if username == "bad":
                raise RuntimeError("panel hiccup")
            return None if username == "gone" else {"username": username}

    accounts = [SimpleNamespace(id=i, username=u) for i, u in enumerate(["ok", "bad", "gone"])]
    errors: list[str] = []
    out = await PanelReader(Adapter()).read_many(accounts, concurrency=2, on_error=lambda a, e: errors.append(a.username))
    assert out == {0: {"username": "ok"}, 1: None, 2: None} and errors == ["bad"]


@pytest.mark.asyncio
async def test_account_read_goes_through_the_seed_hook_first():
    seeded: list[str] = []

    class Adapter:
        async def get_account(self, username):
            return username.upper()

    def seed(adapter, account):
        seeded.append(account.username)
        return adapter

    assert await PanelReader(Adapter(), seed=seed).account(SimpleNamespace(username="abc")) == "ABC"
    assert seeded == ["abc"]
