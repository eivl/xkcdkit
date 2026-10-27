"""Tests for the Textual browser, driven headless through Pilot."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from textual.widgets import Input, OptionList, Static

from xkcdkit import AsyncXKCD
from xkcdkit.tui import XKCDApp

from .test_sources import BrokenSites, FakeSites


def listed(app: XKCDApp) -> list[int]:
    """Comic numbers currently shown in the archive list, top to bottom."""
    options = app.query_one(OptionList)
    return [int(str(options.get_option_at_index(i).id)) for i in range(options.option_count)]


def pane(app: XKCDApp, pane_id: str) -> str:
    """Plain text of one of the text panes."""
    return str(app.query_one(f"#{pane_id}", Static).content)


async def settled(app: XKCDApp, pilot) -> None:  # type: ignore[no-untyped-def]
    """Wait for every worker to finish and the screen to settle."""
    await app.workers.wait_for_complete()
    await pilot.pause()


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
        await settled(app, pilot)
        assert listed(app)[0] == 3316
        assert len(listed(app)) == 9
        assert "Siege Engine" in app.sub_title
        assert "Elephant's Foot" in pane(app, "alt")


async def test_filter_narrows_and_clears(app: XKCDApp) -> None:
    """Typing in the filter box keeps only fuzzy matches; clearing restores everything."""
    async with app.run_test() as pilot:
        await settled(app, pilot)
        await pilot.press("slash")
        assert app.focused is app.query_one("#filter", Input)
        await pilot.press(*"woodpek")
        await pilot.pause()
        assert listed(app) == [614]
        await pilot.press(*(["backspace"] * 7), *"zzzzzz")
        await pilot.pause()
        assert listed(app) == []
        await pilot.press("enter")
        await pilot.press(*(["backspace"] * 6))
        await pilot.pause()
        assert len(listed(app)) == 9


async def test_enter_in_filter_opens_first_match(app: XKCDApp) -> None:
    """Enter in the filter box opens the top hit and fills every pane."""
    async with app.run_test() as pilot:
        await settled(app, pilot)
        await pilot.press("slash", *"wood", "enter")
        await settled(app, pilot)
        assert "Woodpecker" in app.sub_title
        assert "Beret Guy observes" in pane(app, "explanation")
        assert "extension cord" in pane(app, "alt")


async def test_list_enter_opens_highlighted_comic(app: XKCDApp) -> None:
    """J moves down the list and enter opens that row."""
    async with app.run_test() as pilot:
        await settled(app, pilot)
        await pilot.press("j", "j", "k", "enter")
        await settled(app, pilot)
        assert "Forms of Water" in app.sub_title


async def test_random_latest_and_image_toggle(app: XKCDApp) -> None:
    """R loads a random comic, l the latest, i hides the image pane."""
    async with app.run_test() as pilot:
        await settled(app, pilot)
        await pilot.press("r")
        await settled(app, pilot)
        assert "Woodpecker" in app.sub_title
        image_pane = app.query_one("#image-pane")
        assert image_pane.display is True
        await pilot.press("i")
        assert image_pane.display is False
        await pilot.press("l")
        await settled(app, pilot)
        assert "Siege Engine" in app.sub_title


async def test_bracketed_text_is_shown_literally(app: XKCDApp) -> None:
    """Alt text containing markup-like brackets is displayed as is, not parsed."""
    async with app.run_test() as pilot:
        await settled(app, pilot)
        app.open(403)
        await settled(app, pilot)
        assert "Convincing [/] Pickup Line" in app.sub_title
        assert "see [sic] and [/b] end [link=x]y[/link]" in pane(app, "alt")


async def test_help_and_sync(app: XKCDApp) -> None:
    """? shows the key help and s runs a sync and reports in a notification."""
    async with app.run_test(notifications=True) as pilot:
        await settled(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert any("random" in str(n.message) for n in app._notifications)
        await pilot.press("s")
        await settled(app, pilot)
        assert any("Synced" in str(n.message) for n in app._notifications)


async def test_open_failure_is_notified(app: XKCDApp) -> None:
    """A comic that fails to load produces an error notification, not a crash."""
    async with app.run_test(notifications=True) as pilot:
        await settled(app, pilot)
        app.open(405)
        await settled(app, pilot)
        assert any("no comic 405" in str(n.message) for n in app._notifications)


async def test_bad_image_data_is_reported_not_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrupt image bytes produce a warning notification and the text panes still fill."""
    monkeypatch.setattr("tests.test_sources.PNG", b"not a png")
    client = AsyncXKCD(db=tmp_path / "bad.sqlite3", client=FakeSites().client(), explain_delay=0)
    app = XKCDApp(client)
    async with app.run_test(notifications=True) as pilot:
        await settled(app, pilot)
        assert "Siege Engine" in app.sub_title
        assert any("Image unavailable" in str(n.message) for n in app._notifications)
    await client.close()


async def test_offline_start_and_sync_keep_the_app_alive(tmp_path: Path) -> None:
    """With every request failing, the app still starts, reports errors, and survives s and r."""
    client = AsyncXKCD(db=tmp_path / "off.sqlite3", client=BrokenSites().client(), explain_delay=0)
    app = XKCDApp(client)
    async with app.run_test(notifications=True) as pilot:
        await settled(app, pilot)
        assert listed(app) == []
        assert any("503" in str(n.message) for n in app._notifications)
        await pilot.press("s")
        await settled(app, pilot)
        await pilot.press("r")
        await settled(app, pilot)
        assert app.is_running
        assert len([n for n in app._notifications if "503" in str(n.message)]) >= 3
    await client.close()
