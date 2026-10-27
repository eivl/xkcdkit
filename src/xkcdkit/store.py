"""Local SQLite cache of comics, the archive index and sync metadata."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self

from platformdirs import user_data_path
from rapidfuzz import fuzz

from xkcdkit.models import ArchiveEntry, Comic

COLUMNS = list(Comic.model_fields)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS comics ({", ".join(COLUMNS)}, PRIMARY KEY (num));
CREATE TABLE IF NOT EXISTS archive (num INTEGER PRIMARY KEY, date TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
SEARCH_CUTOFF = 60.0


def default_path() -> Path:
    """Database location: ``$XKCDKIT_DB`` or the platform user data directory."""
    override = os.environ.get("XKCDKIT_DB")
    if override:
        return Path(override)
    return user_data_path("xkcdkit") / "xkcd.sqlite3"


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Store:
    """Insert-only cache of comics with fuzzy search.

    Use as a context manager so the connection is closed::

        with Store() as store:
            comic = store.get(614)
    """

    def __init__(self, path: Path | str | None = None) -> None:
        """Open (and create if needed) the database at ``path``."""
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def __enter__(self) -> Self:
        """Enter the context manager."""
        return self

    def __exit__(
        self, *exc: tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
    ) -> None:
        """Close the connection on exit."""
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self.db.close()

    def write(self, comic: Comic, verb: str) -> None:
        """Insert a comic using ``verb`` (``OR IGNORE`` or ``OR REPLACE``)."""
        stamped = comic.model_copy(update={"synced_at": comic.synced_at or utc_now()})
        row = stamped.model_dump(mode="json")
        columns, marks = ", ".join(COLUMNS), ", ".join("?" for _ in COLUMNS)
        sql = f"INSERT {verb} INTO comics ({columns}) VALUES ({marks})"  # noqa: S608 - all constants
        with self.db:
            self.db.execute(sql, [row[column] for column in COLUMNS])

    def put(self, comic: Comic) -> None:
        """Store a comic unless one with the same number already exists."""
        self.write(comic, "OR IGNORE")

    def replace(self, comic: Comic) -> None:
        """Store a comic, overwriting any existing row with the same number."""
        self.write(comic, "OR REPLACE")

    def get(self, num: int) -> Comic | None:
        """Return the cached comic ``num`` or None."""
        row = self.db.execute("SELECT * FROM comics WHERE num = ?", (num,)).fetchone()
        return Comic.model_validate(dict(row)) if row else None

    def has(self, num: int) -> bool:
        """Whether comic ``num`` is cached."""
        return self.get(num) is not None

    def nums(self) -> list[int]:
        """All cached comic numbers, ascending."""
        return [row[0] for row in self.db.execute("SELECT num FROM comics ORDER BY num")]

    def count(self) -> int:
        """Number of cached comics."""
        return int(self.db.execute("SELECT COUNT(*) FROM comics").fetchone()[0])

    def all(self) -> list[Comic]:
        """Every cached comic, ascending by number."""
        rows = self.db.execute("SELECT * FROM comics ORDER BY num")
        return [Comic.model_validate(dict(row)) for row in rows]

    def put_archive(self, entries: list[ArchiveEntry]) -> None:
        """Replace the archive index with ``entries``."""
        with self.db:
            self.db.execute("DELETE FROM archive")
            self.db.executemany(
                "INSERT OR REPLACE INTO archive VALUES (?, ?, ?)",
                [(e.num, e.date.isoformat(), e.title) for e in entries],
            )

    def archive(self) -> list[ArchiveEntry]:
        """The archive index, newest first."""
        rows = self.db.execute("SELECT * FROM archive ORDER BY num DESC")
        return [ArchiveEntry.model_validate(dict(row)) for row in rows]

    def set_meta(self, key: str, value: str) -> None:
        """Store a metadata value such as ``last_sync_at``."""
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        """Read a metadata value, or None when unset."""
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def stale(self, max_age: timedelta) -> list[int]:
        """Numbers of comics older than ``max_age`` or still missing an explanation."""
        cutoff = (utc_now() - max_age).isoformat()
        rows = self.db.execute(
            "SELECT num FROM comics WHERE synced_at < ? OR explanation_missing ORDER BY num",
            (cutoff,),
        )
        return [row[0] for row in rows]

    def search(self, query: str, limit: int = 10) -> list[tuple[Comic, float]]:
        """Fuzzy-search titles, alt text, transcripts and explanations.

        Returns ``(comic, score)`` pairs, best first, scores from 0 to 100.
        """
        scored = [(comic, score_comic(comic, query)) for comic in self.all()]
        hits = [(comic, score) for comic, score in scored if score >= SEARCH_CUTOFF]
        hits.sort(key=lambda hit: (-hit[1], hit[0].num))
        return hits[:limit]


def score_comic(comic: Comic, query: str) -> float:
    """Score a comic against a query: exact-ish titles win, long text counts a bit less."""
    title = float(fuzz.WRatio(query, comic.title, processor=str.lower))
    body = " ".join([comic.alt, comic.transcript, comic.explanation_text])
    text = float(fuzz.token_set_ratio(query, body, processor=str.lower))
    return max(title, 0.9 * text)
