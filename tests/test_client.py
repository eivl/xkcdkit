"""Tests for the async client and its sync wrapper."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xkcdkit import XKCD, AsyncXKCD, ComicNotFound, XKCDError
from xkcdkit.store import Store

from .test_sources import FakeSites


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A temporary database path."""
    return tmp_path / "xkcd.sqlite3"


@pytest.fixture
def sites() -> FakeSites:
    """A fresh fake of both sites."""
    return FakeSites()


@pytest.fixture
async def xk(sites: FakeSites, db: Path) -> AsyncIterator[AsyncXKCD]:
    """An async client over the fake sites and a temp database, no bulk delay."""
    async with AsyncXKCD(db=db, client=sites.client(), explain_delay=0) as client:
        yield client


async def test_get_fetches_and_caches(xk: AsyncXKCD, sites: FakeSites) -> None:
    """The first get hits both sites; the second is served from the cache."""
    first = await xk.get(614)
    assert first.title == "Woodpecker" and first.explanation_revid == 216714
    assert len(sites.requests) == 2
    second = await xk.get(614)
    assert second == first
    assert len(sites.requests) == 2


async def test_get_without_explanation(xk: AsyncXKCD, sites: FakeSites) -> None:
    """explain=False skips explainxkcd and stores the comic flagged missing-explanation."""
    comic = await xk.get(614, explain=False)
    assert comic.explanation is None and comic.explanation_missing is True
    assert len(sites.requests) == 1


async def test_get_missing_comic(xk: AsyncXKCD) -> None:
    """A number xkcd never published raises ComicNotFound."""
    with pytest.raises(ComicNotFound):
        await xk.get(404)


async def test_get_flags_missing_explanation(xk: AsyncXKCD) -> None:
    """When explainxkcd has no page the comic is stored with the flag set."""
    comic = await xk.get(1)
    assert comic.explanation_missing is True and comic.explanation is None


async def test_missing_explanation_is_retried_after_a_day(
    xk: AsyncXKCD, sites: FakeSites, db: Path
) -> None:
    """A stale missing-explanation row is re-fetched on access; a fresh one is not."""
    await xk.get(1)
    assert len(sites.requests) == 2
    await xk.get(1)
    assert len(sites.requests) == 2
    with Store(db) as store:
        old = (await xk.get(1)).model_copy(update={"synced_at": datetime.now(UTC) - timedelta(days=2)})
        store.replace(old)
    await xk.get(1)
    assert len(sites.requests) == 4


async def test_latest(xk: AsyncXKCD, sites: FakeSites) -> None:
    """latest() always asks xkcd.com and records the number in meta."""
    comic = await xk.latest()
    assert comic.num == 3316
    assert xk.store.get_meta("latest_num") == "3316"


async def test_random_uses_archive(xk: AsyncXKCD, monkeypatch: pytest.MonkeyPatch) -> None:
    """random() picks a number from the archive and returns that comic."""
    monkeypatch.setattr("random.choice", lambda nums: 614 if 614 in nums else nums[0])
    comic = await xk.random()
    assert comic.num == 614
    assert len(xk.store.archive()) == 7


async def test_search_returns_comics(xk: AsyncXKCD) -> None:
    """search() returns cached comics, best match first."""
    await xk.get(614)
    await xk.get(1)
    hits = await xk.search("woodpeckr", limit=1)
    assert [comic.num for comic in hits] == [614]


async def test_explain_returns_plain_text(xk: AsyncXKCD) -> None:
    """explain() returns the plain-text explanation, fetching the comic if needed."""
    text = await xk.explain(614)
    assert text.startswith("Beret Guy observes a woodpecker.")


async def test_explain_missing_is_empty(xk: AsyncXKCD) -> None:
    """A comic without an explanation page explains to an empty string."""
    assert await xk.explain(1) == ""


async def test_sync_light(xk: AsyncXKCD, sites: FakeSites) -> None:
    """A light sync stores the archive and the latest comic only."""
    fetched = await xk.sync()
    assert fetched == 1
    assert len(xk.store.archive()) >= 7
    assert xk.store.has(3316)
    assert xk.store.get_meta("last_sync_at") is not None
    assert xk.store.get_meta("last_full_sync_at") is None


async def test_sync_full_fetches_everything_and_skips_gaps(xk: AsyncXKCD) -> None:
    """A full sync fetches every archive entry, tolerates missing comics, reports progress."""
    seen: list[tuple[int, int]] = []
    fetched = await xk.sync(full=True, progress=lambda done, total: seen.append((done, total)))
    assert fetched >= 5
    assert xk.store.has(1) and xk.store.has(614) and xk.store.has(3316)
    assert not xk.store.has(405)
    assert seen[-1][0] == seen[-1][1]
    assert xk.store.get_meta("last_full_sync_at") is not None


async def test_sync_full_skips_already_cached(xk: AsyncXKCD, sites: FakeSites) -> None:
    """Comics already in the cache are not fetched again."""
    await xk.sync(full=True)
    before = len(sites.requests)
    assert await xk.sync(full=True) == 0
    # archive + latest, plus one retry of the archive entry xkcd answers 404 for
    assert len(sites.requests) == before + 3


async def test_resync_refetches_stale(xk: AsyncXKCD, sites: FakeSites) -> None:
    """resync() replaces rows older than max_age and rows missing explanations."""
    await xk.get(614)
    await xk.get(1)
    old = (await xk.get(614)).model_copy(update={"synced_at": datetime.now(UTC) - timedelta(days=90)})
    xk.store.replace(old)
    before = len(sites.requests)
    assert await xk.resync(max_age=timedelta(days=30)) == 2
    assert len(sites.requests) == before + 4
    refreshed = xk.store.get(614)
    assert refreshed is not None and refreshed.synced_at > old.synced_at


def test_sync_wrapper(sites: FakeSites, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """XKCD offers the same calls without await."""
    monkeypatch.setattr("random.choice", lambda nums: 614)
    with XKCD(db=db, client_factory=sites.client, explain_delay=0) as xk:
        assert xk.get(614).title == "Woodpecker"
        assert xk.latest().num == 3316
        assert xk.sync() == 0
        assert [c.num for c in xk.search("woodpecker")] == [614]
        assert xk.explain(614).startswith("Beret Guy")
        assert xk.random().num > 0
        assert xk.resync() == 1


async def test_sync_wrapper_refuses_running_loop(sites: FakeSites, db: Path) -> None:
    """Calling the sync wrapper inside an event loop gives a clear error."""
    with XKCD(db=db, client_factory=sites.client) as xk, pytest.raises(XKCDError, match="AsyncXKCD"):
        xk.get(614)


async def test_default_client_and_db(monkeypatch: pytest.MonkeyPatch, db: Path) -> None:
    """Without arguments the client builds its own httpx2 client and uses the default path."""
    monkeypatch.setenv("XKCDKIT_DB", str(db))
    async with AsyncXKCD() as xk:
        assert xk.store.path == db
        assert xk.http.headers["user-agent"].startswith("xkcdkit/")
