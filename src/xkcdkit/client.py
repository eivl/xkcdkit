"""High-level clients: ``AsyncXKCD`` does the work, ``XKCD`` wraps it for sync code."""

import asyncio
import random
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx2

from xkcdkit import ComicNotFound, XKCDError
from xkcdkit.models import ArchiveEntry, Comic
from xkcdkit.sources import (
    EXPLAIN_BATCH,
    fetch_archive,
    fetch_comic,
    fetch_explanation,
    fetch_explanations,
    user_agent,
)
from xkcdkit.store import Store, utc_now

Progress = Callable[[int, int], None]
RETRY_MISSING_AFTER = timedelta(days=1)
WORKERS = 8


class AsyncXKCD:
    """Fetch, cache and search xkcd comics with explainxkcd explanations.

    Example::

        async with AsyncXKCD() as xk:
            comic = await xk.get(614)
            print(comic.title, comic.alt)

    Args:
        db: Database path. Defaults to the platform user data directory or ``$XKCDKIT_DB``.
        client: An ``httpx2.AsyncClient`` to use instead of the built-in one.
        timeout: Request timeout in seconds for the built-in client.
        explain_delay: Minimum seconds between explainxkcd requests during bulk syncs.
    """

    def __init__(
        self,
        db: Path | str | None = None,
        client: httpx2.AsyncClient | None = None,
        timeout: float = 20.0,
        explain_delay: float = 1.0,
    ) -> None:
        """Open the store and prepare the HTTP client."""
        self.store = Store(db)
        self.http = client or httpx2.AsyncClient(
            timeout=timeout, headers={"User-Agent": user_agent()}, follow_redirects=True
        )
        self.explain_delay = explain_delay
        self.explain_lock = asyncio.Lock()
        self.last_explain = 0.0

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Close connections on exit."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client and the database."""
        await self.http.aclose()
        self.store.close()

    async def complete(self, comic: Comic) -> Comic:
        """Attach the explainxkcd page when it exists and stamp the sync time."""
        found = await fetch_explanation(self.http, comic.num)
        self.last_explain = time.monotonic()
        return self.attach(comic, found)

    def attach(self, comic: Comic, found: tuple[str, int] | None) -> Comic:
        """Copy a comic with explanation data (or a note of its absence) and a fresh sync time."""
        wikitext, revid = found if found else (None, None)
        return comic.model_copy(
            update={
                "explanation": wikitext,
                "explanation_revid": revid,
                "explanation_missing": wikitext is None,
                "synced_at": utc_now(),
            }
        )

    def fresh(self, comic: Comic) -> bool:
        """A cached comic is fresh unless its explanation is absent and that is a day old."""
        if comic.explanation is not None:
            return True
        if not comic.explanation_missing or comic.synced_at is None:
            return False
        return utc_now() - comic.synced_at < RETRY_MISSING_AFTER

    async def get(self, num: int) -> Comic:
        """Return comic ``num`` from the cache, fetching and caching it when needed.

        Raises:
            ComicNotFound: when xkcd has no such comic.
            XKCDError: on network or server failures.
        """
        cached = self.store.get(num)
        if cached and self.fresh(cached):
            return cached
        comic = await self.complete(await fetch_comic(self.http, num))
        self.store.replace(comic)
        return comic

    async def latest(self) -> Comic:
        """Return the newest comic, always checking xkcd.com for its number."""
        comic = await fetch_comic(self.http, None)
        self.store.set_meta("latest_num", str(comic.num))
        if not self.store.has(comic.num):
            self.store.put(await self.complete(comic))
        return await self.get(comic.num)

    async def random(self) -> Comic:
        """Return a random comic, using the archive index for the number range."""
        entries = self.store.archive() or await self.refresh_archive()
        return await self.get(random.choice([entry.num for entry in entries]))

    async def search(self, query: str, limit: int = 10) -> list[Comic]:
        """Fuzzy-search cached comics by title, alt text, transcript and explanation."""
        return [comic for comic, _ in self.store.search(query, limit)]

    async def explain(self, num: int) -> str:
        """The plain-text explanation for comic ``num``; empty when explainxkcd has none."""
        return (await self.get(num)).explanation_text

    async def refresh_archive(self) -> list[ArchiveEntry]:
        """Fetch the archive page and store it as the index."""
        entries = await fetch_archive(self.http)
        self.store.put_archive(entries)
        return entries

    async def sync(self, full: bool = False, progress: Progress | None = None, explain: bool = True) -> int:
        """Refresh the archive index and the latest comic; with ``full`` fetch every comic.

        A full sync walks every number from 1 to the latest, so it does not depend
        on the archive page. With ``explain=False`` it skips explainxkcd, which is
        much faster; ``resync`` or a later ``get`` fills the explanations in.
        Returns the number of comics newly added to the cache.
        """
        before = self.store.count()
        await self.refresh_archive()
        latest = await self.latest()
        if full:
            cached = set(self.store.nums())
            nums = [n for n in range(1, latest.num + 1) if n not in cached]
            await self.fetch_many(nums, progress, explain)
            self.store.set_meta("last_full_sync_at", utc_now().isoformat())
        self.store.set_meta("last_sync_at", utc_now().isoformat())
        return self.store.count() - before

    async def resync(self, max_age: timedelta = timedelta(days=30), progress: Progress | None = None) -> int:
        """Re-fetch comics older than ``max_age`` or without explanation data. Returns the count."""
        return await self.fetch_many(self.store.stale(max_age), progress)

    async def fetch_many(self, nums: list[int], progress: Progress | None, explain: bool = True) -> int:
        """Fetch and store comics in batches of ``EXPLAIN_BATCH``.

        Within a batch xkcd.com is fetched concurrently and explainxkcd answers for the
        whole batch in one paced request. Each batch is committed as a unit, so an
        interrupted run keeps every finished batch. Numbers xkcd lacks are skipped.
        """
        fetched = 0
        for start in range(0, len(nums), EXPLAIN_BATCH):
            comics = await self.fetch_comics(nums[start : start + EXPLAIN_BATCH])
            if explain and comics:
                await self.pace()
                found = await fetch_explanations(self.http, [comic.num for comic in comics])
                comics = [self.attach(comic, found[comic.num]) for comic in comics]
            for comic in comics:
                self.store.replace(comic)
            fetched += len(comics)
            if progress:
                progress(min(start + EXPLAIN_BATCH, len(nums)), len(nums))
        return fetched

    async def fetch_comics(self, nums: list[int]) -> list[Comic]:
        """Fetch several comics from xkcd.com, a few at a time, skipping numbers it lacks."""
        limit = asyncio.Semaphore(WORKERS)

        async def one(num: int) -> Comic | None:
            async with limit:
                try:
                    return await fetch_comic(self.http, num)
                except ComicNotFound:
                    return None

        return [comic for comic in await asyncio.gather(*(one(num) for num in nums)) if comic]

    async def pace(self) -> None:
        """Wait until ``explain_delay`` has passed since the previous explainxkcd request."""
        async with self.explain_lock:
            wait = self.last_explain + self.explain_delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_explain = time.monotonic()


class XKCD:
    """Blocking twin of ``AsyncXKCD`` for scripts and REPL use.

    Each call runs on its own short-lived event loop, so it cannot be used
    from code that is already inside one. Use ``AsyncXKCD`` there.
    """

    def __init__(
        self,
        db: Path | str | None = None,
        client_factory: Callable[[], httpx2.AsyncClient] | None = None,
        timeout: float = 20.0,
        explain_delay: float = 1.0,
    ) -> None:
        """Remember the settings; connections are opened per call."""
        self.db = db
        self.client_factory = client_factory
        self.timeout = timeout
        self.explain_delay = explain_delay

    def __enter__(self) -> Self:
        """Enter the context manager."""
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Nothing to close: each call closes its own resources."""

    def run(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Run one ``AsyncXKCD`` method to completion on a fresh event loop."""

        async def call() -> Any:
            client = self.client_factory() if self.client_factory else None
            async with AsyncXKCD(self.db, client, self.timeout, self.explain_delay) as xk:
                return await getattr(xk, method)(*args, **kwargs)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(call())
        raise XKCDError("XKCD cannot run inside an event loop; use AsyncXKCD")

    def get(self, num: int) -> Comic:
        """See ``AsyncXKCD.get``."""
        return self.run("get", num)  # type: ignore[no-any-return]

    def latest(self) -> Comic:
        """See ``AsyncXKCD.latest``."""
        return self.run("latest")  # type: ignore[no-any-return]

    def random(self) -> Comic:
        """See ``AsyncXKCD.random``."""
        return self.run("random")  # type: ignore[no-any-return]

    def search(self, query: str, limit: int = 10) -> list[Comic]:
        """See ``AsyncXKCD.search``."""
        return self.run("search", query, limit)  # type: ignore[no-any-return]

    def explain(self, num: int) -> str:
        """See ``AsyncXKCD.explain``."""
        return self.run("explain", num)  # type: ignore[no-any-return]

    def sync(self, full: bool = False, progress: Progress | None = None, explain: bool = True) -> int:
        """See ``AsyncXKCD.sync``."""
        return self.run("sync", full, progress, explain)  # type: ignore[no-any-return]

    def resync(self, max_age: timedelta = timedelta(days=30), progress: Progress | None = None) -> int:
        """See ``AsyncXKCD.resync``."""
        return self.run("resync", max_age, progress)  # type: ignore[no-any-return]
