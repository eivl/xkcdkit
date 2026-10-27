"""Tests for the Textual browser, driven headless through Pilot."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from textual.widgets import Input, ListView, Static

from xkcdkit import AsyncXKCD
from xkcdkit.tui import ArchiveItem, XKCDApp

from .test_sources import FakeSites


@pytest.fixture
async def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[XKCDApp]:
    """An app over the fake sites with a deterministic random choice."""
    monkeypatch.setattr("random.choice", lambda nums: 614)
    client = AsyncXKCD(db=tmp_path / "tui.sqlite3", client=FakeSites().client(), explain_delay=0)
    yield XKCDApp(client)
    await client.close()


async def test_archive_list_is_populated_and_latest_shown(app: XKCDApp) -> None:
    """On start the archive is synced into the list and the latest comic is open."""
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        items = app.query(ArchiveItem)
        assert len(items) == 7
        assert items.first().num == 3316
        assert "Siege Engine" in app.sub_title
        assert "Elephant's Foot" in str(app.query_one("#alt", Static).content)


async def test_filter_narrows_the_list(app: XKCDApp) -> None:
    """Typing in the filter box keeps only fuzzy matches."""
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("slash")
        assert app.focused is app.query_one("#filter", Input)
        await pilot.press(*"woodpek")
        await pilot.pause()
        nums = [item.num for item in app.query(ArchiveItem)]
        assert nums == [614]


async def test_enter_opens_selected_comic(app: XKCDApp) -> None:
    """Selecting an entry loads that comic into the panes."""
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("slash", *"wood", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Woodpecker" in app.sub_title
        assert "Beret Guy observes" in str(app.query_one("#explanation", Static).content)
        assert "extension cord" in str(app.query_one("#alt", Static).content)


async def test_keys_random_image_toggle_and_navigation(app: XKCDApp) -> None:
    """r loads a random comic, i hides the image pane, j/k move the list cursor."""
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Woodpecker" in app.sub_title
        pane = app.query_one("#image-pane")
        assert pane.display is True
        await pilot.press("i")
        assert pane.display is False
        archive = app.query_one(ListView)
        await pilot.press("j", "j", "k")
        assert archive.index == 1
        await pilot.press("l")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Siege Engine" in app.sub_title


async def test_help_and_sync(app: XKCDApp) -> None:
    """? shows the key help and s runs a sync and reports in a notification."""
    async with app.run_test(notifications=True) as pilot:
        await app.workers.wait_for_complete()
        await pilot.press("question_mark")
        await pilot.pause()
        assert any("random" in str(n.message) for n in app._notifications)
        await pilot.press("s")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert any("Synced" in str(n.message) for n in app._notifications)


async def test_bad_image_data_is_reported_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrupt image bytes produce a warning notification and the text panes still fill."""
    monkeypatch.setattr("tests.test_sources.PNG", b"not a png")
    client = AsyncXKCD(db=tmp_path / "bad.sqlite3", client=FakeSites().client(), explain_delay=0)
    app = XKCDApp(client)
    async with app.run_test(notifications=True) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Siege Engine" in app.sub_title
        assert any("Image unavailable" in str(n.message) for n in app._notifications)
    await client.close()
