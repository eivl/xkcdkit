"""Tests for the SQLite store."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xkcdkit.models import ArchiveEntry, Comic
from xkcdkit.store import Store, default_path


def make_comic(num: int = 614, **extra: Any) -> Comic:
    """Build a comic with sensible defaults for tests."""
    base = {
        "num": num,
        "title": f"Comic {num}",
        "safe_title": f"Comic {num}",
        "alt": "alt text",
        "img": f"https://imgs.xkcd.com/comics/{num}.png",
        "year": 2009,
        "month": 7,
        "day": 24,
    }
    return Comic.model_validate({**base, **extra})


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """A store in a temporary directory."""
    with Store(tmp_path / "xkcd.sqlite3") as store:
        yield store


def test_creates_missing_parent_directories(tmp_path: Path) -> None:
    """The first run creates the data directory."""
    path = tmp_path / "deep" / "nested" / "xkcd.sqlite3"
    with Store(path):
        pass
    assert path.exists()


def test_default_path_honours_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """XKCDKIT_DB overrides the platform data directory."""
    monkeypatch.setenv("XKCDKIT_DB", str(tmp_path / "custom.db"))
    assert default_path() == tmp_path / "custom.db"


def test_default_path_without_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the override the file lives in a user data directory named xkcdkit."""
    monkeypatch.delenv("XKCDKIT_DB", raising=False)
    path = default_path()
    assert path.name == "xkcd.sqlite3"
    assert "xkcdkit" in path.parts


def test_put_and_get_round_trip(store: Store, comic_json: dict[str, Any], wikitext: str) -> None:
    """All fields survive a round trip, including timezone-aware datetimes."""
    synced = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    comic = Comic.model_validate(
        {**comic_json, "explanation": wikitext, "explanation_revid": 216714, "synced_at": synced}
    )
    store.put(comic)
    assert store.get(614) == comic
    assert store.has(614)
    assert not store.has(1)
    assert store.get(1) is None


def test_put_stamps_synced_at_when_missing(store: Store) -> None:
    """A comic without synced_at gets the current UTC time."""
    before = datetime.now(UTC)
    store.put(make_comic())
    fetched = store.get(614)
    assert fetched is not None
    assert fetched.synced_at is not None
    assert fetched.synced_at >= before


def test_put_is_insert_only(store: Store) -> None:
    """A second put for the same number keeps the first row."""
    store.put(make_comic(title="first"))
    store.put(make_comic(title="second"))
    fetched = store.get(614)
    assert fetched is not None
    assert fetched.title == "first"


def test_replace_overwrites(store: Store) -> None:
    """replace() is the one way to change a stored comic."""
    store.put(make_comic(title="first"))
    store.replace(make_comic(title="second"))
    fetched = store.get(614)
    assert fetched is not None
    assert fetched.title == "second"


def test_nums_and_count(store: Store) -> None:
    """Stored numbers come back sorted."""
    for num in (3, 1, 2):
        store.put(make_comic(num))
    assert store.nums() == [1, 2, 3]
    assert store.count() == 3


def test_archive_round_trip_and_replace(store: Store) -> None:
    """The archive is replaced wholesale and returned newest first."""
    store.put_archive([ArchiveEntry(num=1, date="2006-1-1", title="Barrel - Part 1")])
    store.put_archive(
        [
            ArchiveEntry(num=1, date="2006-1-1", title="Barrel - Part 1"),
            ArchiveEntry(num=2, date="2006-1-1", title="Petit Trees (sketch)"),
        ]
    )
    entries = store.archive()
    assert [entry.num for entry in entries] == [2, 1]
    assert entries[1].title == "Barrel - Part 1"


def test_meta(store: Store) -> None:
    """Meta values are plain strings and overwrite on set."""
    assert store.get_meta("latest_num") is None
    store.set_meta("latest_num", "3316")
    store.set_meta("latest_num", "3317")
    assert store.get_meta("latest_num") == "3317"


def test_stale_returns_old_missing_and_unexplained(store: Store) -> None:
    """Rows older than max_age, flagged missing, or never explained are stale."""
    old = datetime.now(UTC) - timedelta(days=40)
    store.put(make_comic(1, synced_at=old))
    store.put(make_comic(2, explanation_missing=True))
    store.put(make_comic(3, explanation="==Explanation==\nText."))
    store.put(make_comic(4))
    assert store.stale(timedelta(days=30)) == [1, 2, 4]


def test_search_fuzzy_title(store: Store) -> None:
    """A misspelled title still finds the comic and ranks it first."""
    store.put(make_comic(614, title="Woodpecker"))
    store.put(make_comic(1, title="Barrel - Part 1"))
    results = store.search("woodpeckr")
    assert results[0][0].num == 614
    assert results[0][1] > 80


def test_search_covers_explanation(store: Store, comic_json: dict[str, Any], wikitext: str) -> None:
    """Explanation text is searchable too."""
    store.put(Comic.model_validate({**comic_json, "explanation": wikitext}))
    store.put(make_comic(1, title="Barrel"))
    results = store.search("power drill birthday", limit=1)
    assert [comic.num for comic, _ in results] == [614]


def test_search_limit_and_cutoff(store: Store) -> None:
    """Unrelated comics are not returned and the limit is honoured."""
    for num in range(1, 6):
        store.put(make_comic(num, title=f"Totally unrelated {num}"))
    assert store.search("zzzzqqq") == []
    assert len(store.search("unrelated", limit=2)) == 2
