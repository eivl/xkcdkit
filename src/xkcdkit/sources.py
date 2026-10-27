"""Fetchers for xkcd.com and explainxkcd.com.

Every function takes an ``httpx2.AsyncClient`` so callers control pooling,
timeouts and, in tests, the transport.
"""

import html
import re
from typing import Any

import httpx2

from xkcdkit import ComicNotFound, XKCDError, __version__
from xkcdkit.models import ArchiveEntry, Comic

XKCD = "https://xkcd.com"
EXPLAIN_API = "https://www.explainxkcd.com/wiki/api.php"
ARCHIVE_LINK = re.compile(r'<a href="/(\d+)/" title="([^"]+)">(.*?)</a>', re.DOTALL)
HTML_TAG = re.compile(r"</?[a-z][a-z0-9]*(?:\s[^>]*)?>")


def user_agent() -> str:
    """A User-Agent that names the project, as both sites ask of bots."""
    return f"xkcdkit/{__version__} (+https://github.com/eivl/xkcdkit)"


async def request(client: httpx2.AsyncClient, url: str, **params: Any) -> httpx2.Response:
    """GET ``url`` and wrap transport failures in ``XKCDError``."""
    try:
        return await client.get(url, params=params or None)
    except httpx2.HTTPError as exc:
        raise XKCDError(f"{url}: {exc}") from exc


async def fetch_comic(client: httpx2.AsyncClient, num: int | None) -> Comic:
    """Fetch comic ``num`` from xkcd.com, or the latest comic when ``num`` is None."""
    url = f"{XKCD}/info.0.json" if num is None else f"{XKCD}/{num}/info.0.json"
    response = await request(client, url)
    if response.status_code == 404:
        raise ComicNotFound(f"xkcd has no comic {num}")
    if response.status_code != 200:
        raise XKCDError(f"{url}: HTTP {response.status_code}")
    return Comic.model_validate(response.json())


def parse_archive(page: str) -> list[ArchiveEntry]:
    """Turn the archive page's anchors into entries, in page order (newest first)."""
    return [
        ArchiveEntry(num=int(num), date=date, title=html.unescape(HTML_TAG.sub("", title)))
        for num, date, title in ARCHIVE_LINK.findall(page)
    ]


async def fetch_archive(client: httpx2.AsyncClient) -> list[ArchiveEntry]:
    """Fetch and parse https://xkcd.com/archive/."""
    response = await request(client, f"{XKCD}/archive/")
    if response.status_code != 200:
        raise XKCDError(f"archive: HTTP {response.status_code}")
    return parse_archive(response.text)


async def fetch_explanation(client: httpx2.AsyncClient, num: int) -> tuple[str, int] | None:
    """Fetch the explainxkcd page for ``num`` as ``(wikitext, revid)``, or None if absent."""
    response = await request(
        client,
        EXPLAIN_API,
        action="parse",
        page=str(num),
        redirects=1,
        prop="wikitext|revid",
        format="json",
        formatversion=2,
    )
    if response.status_code != 200:
        raise XKCDError(f"explainxkcd: HTTP {response.status_code}")
    payload = response.json()
    if "error" in payload:
        if payload["error"].get("code") == "missingtitle":
            return None
        raise XKCDError(f"explainxkcd: {payload['error'].get('info', 'unknown error')}")
    return payload["parse"]["wikitext"], int(payload["parse"]["revid"])


async def fetch_image(client: httpx2.AsyncClient, comic: Comic) -> bytes:
    """Download the comic's image bytes."""
    response = await request(client, comic.img)
    if response.status_code != 200:
        raise XKCDError(f"{comic.img}: HTTP {response.status_code}")
    return response.content
