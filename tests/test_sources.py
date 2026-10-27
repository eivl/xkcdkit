"""Tests for the HTTP fetchers, served by an in-memory mock of both sites."""

import json
from pathlib import Path

import httpx2
import pytest

from xkcdkit import ComicNotFound, XKCDError
from xkcdkit.models import Comic
from xkcdkit.sources import (
    fetch_archive,
    fetch_comic,
    fetch_explanation,
    fetch_image,
    parse_archive,
    user_agent,
)

FIXTURES = Path(__file__).parent / "fixtures"
PNG = (FIXTURES / "tiny.png").read_bytes()


class FakeSites:
    """Route requests for xkcd.com and explainxkcd.com to fixture files."""

    def __init__(self) -> None:
        """Start with no requests seen."""
        self.requests: list[str] = []
        self.latest = json.loads((FIXTURES / "latest.json").read_text(encoding="utf-8"))
        self.comic = json.loads((FIXTURES / "614.json").read_text(encoding="utf-8"))
        self.explain = json.loads((FIXTURES / "explain_614.json").read_text(encoding="utf-8"))
        self.missing = json.loads((FIXTURES / "explain_missing.json").read_text(encoding="utf-8"))
        self.archive = (FIXTURES / "archive.html").read_text(encoding="utf-8")
        self.others = {
            1: {"title": "Barrel - Part 1"},
            2: {"title": "Petit Trees (sketch)"},
            403: {"title": "Convincing [/] Pickup Line", "alt": "see [sic] and [/b] end [link=x]y[/link]"},
            3315: {"title": "Forms of Water"},
        }

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        """Answer a request the way the real sites would."""
        self.requests.append(str(request.url))
        assert request.headers["user-agent"].startswith("xkcdkit/")
        host, path = request.url.host, request.url.path
        if host == "imgs.xkcd.com":
            return httpx2.Response(200, content=PNG)
        if host == "www.explainxkcd.com":
            page = request.url.params["page"]
            return httpx2.Response(200, json=self.explain if page == "614" else self.missing)
        if path == "/archive/":
            return httpx2.Response(200, text=self.archive)
        if path == "/info.0.json":
            return httpx2.Response(200, json=self.latest)
        num = int(path.strip("/").split("/")[0])
        if num == 614:
            return httpx2.Response(200, json=self.comic)
        if num == 500:
            return httpx2.Response(500, text="boom")
        if num == self.latest["num"]:
            return httpx2.Response(200, json=self.latest)
        if num in self.others:
            return httpx2.Response(200, json={**self.comic, "num": num, **self.others[num]})
        return httpx2.Response(404, text="not found")

    def client(self) -> httpx2.AsyncClient:
        """An async client wired to this fake."""
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(self.handle), headers={"User-Agent": user_agent()}
        )


@pytest.fixture
def sites() -> FakeSites:
    """A fresh fake of both sites."""
    return FakeSites()


def test_user_agent_names_project_and_version() -> None:
    """The User-Agent identifies the package so site owners can reach us."""
    agent = user_agent()
    assert agent.startswith("xkcdkit/")
    assert "github.com/eivl/xkcdkit" in agent


async def test_fetch_comic_by_number(sites: FakeSites) -> None:
    """A numbered comic comes from /N/info.0.json."""
    async with sites.client() as client:
        comic = await fetch_comic(client, 614)
    assert comic.num == 614
    assert comic.title == "Woodpecker"
    assert sites.requests == ["https://xkcd.com/614/info.0.json"]


async def test_fetch_latest(sites: FakeSites) -> None:
    """None means the latest comic."""
    async with sites.client() as client:
        comic = await fetch_comic(client, None)
    assert comic.num == 3316
    assert sites.requests == ["https://xkcd.com/info.0.json"]


async def test_fetch_missing_comic_raises_not_found(sites: FakeSites) -> None:
    """Comic 404 does not exist and raises ComicNotFound."""
    async with sites.client() as client:
        with pytest.raises(ComicNotFound):
            await fetch_comic(client, 404)


async def test_fetch_server_error_raises_xkcd_error(sites: FakeSites) -> None:
    """Other HTTP failures become XKCDError with the status in the message."""
    async with sites.client() as client:
        with pytest.raises(XKCDError, match="500"):
            await fetch_comic(client, 500)


async def test_fetch_network_error_raises_xkcd_error() -> None:
    """Transport failures are wrapped too."""

    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no network")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(fail)) as client:
        with pytest.raises(XKCDError, match="no network"):
            await fetch_comic(client, 614)


def test_parse_archive(archive_html: str) -> None:
    """Each anchor becomes an entry, newest first, with the unpadded date parsed."""
    entries = parse_archive(archive_html)
    assert entries[0].num == 3316
    assert entries[0].title == "Siege Engine"
    assert entries[0].date.isoformat() == "2026-10-26"
    assert any(entry.num == 614 and entry.title == "Woodpecker" for entry in entries)
    assert all(entry.num > 0 for entry in entries)


def test_parse_archive_keeps_titles_with_inline_html(archive_html: str) -> None:
    """Two real titles wrap words in a span or contain a literal <City> placeholder."""
    titles = {entry.num: entry.title for entry in parse_archive(archive_html)}
    assert titles[472] == "House of Pancakes"
    assert titles[3142] == "<City>-Style Pizza"


async def test_fetch_archive(sites: FakeSites) -> None:
    """The archive page is fetched and parsed."""
    async with sites.client() as client:
        entries = await fetch_archive(client)
    assert len(entries) == 9


async def test_fetch_explanation(sites: FakeSites) -> None:
    """An existing page yields its wikitext and revision id."""
    async with sites.client() as client:
        result = await fetch_explanation(client, 614)
    assert result is not None
    wikitext, revid = result
    assert "==Explanation==" in wikitext
    assert revid == 216714


async def test_fetch_explanation_missing(sites: FakeSites) -> None:
    """A missingtitle error means there is no page, not a failure."""
    async with sites.client() as client:
        assert await fetch_explanation(client, 99999) is None


async def test_fetch_image(sites: FakeSites) -> None:
    """Image bytes are returned as-is."""
    async with sites.client() as client:
        comic = await fetch_comic(client, 614)
        assert await fetch_image(client, comic) == PNG


class BrokenSites(FakeSites):
    """A fake where every endpoint answers HTTP 503."""

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        """Fail everything."""
        if request.url.host == "www.explainxkcd.com" and request.url.params["page"] == "7":
            return httpx2.Response(200, json={"error": {"code": "ratelimited", "info": "slow down"}})
        return httpx2.Response(503, text="down")


async def test_server_errors_are_wrapped_everywhere() -> None:
    """Archive, explanation and image fetches all raise XKCDError on bad status."""
    sites = BrokenSites()
    comic = Comic.model_validate(json.loads((FIXTURES / "614.json").read_text(encoding="utf-8")))
    async with sites.client() as client:
        with pytest.raises(XKCDError, match="503"):
            await fetch_archive(client)
        with pytest.raises(XKCDError, match="503"):
            await fetch_explanation(client, 614)
        with pytest.raises(XKCDError, match="slow down"):
            await fetch_explanation(client, 7)
        with pytest.raises(XKCDError, match="503"):
            await fetch_image(client, comic)
