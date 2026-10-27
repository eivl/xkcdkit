"""Tests for the command line interface."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from xkcdkit import AsyncXKCD, __version__
from xkcdkit.cli import app
from xkcdkit.cli import open_client as real_open_client

from .test_sources import FakeSites

runner = CliRunner()


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSites:
    """Point the CLI at the fake sites and a temporary database."""
    sites = FakeSites()
    monkeypatch.setattr("random.choice", lambda nums: 614)

    def open_client(db: str | None) -> AsyncXKCD:
        return AsyncXKCD(db=db or tmp_path / "cli.sqlite3", client=sites.client(), explain_delay=0)

    monkeypatch.setattr("xkcdkit.cli.open_client", open_client)
    return sites


def test_version() -> None:
    """--version prints the package version and exits cleanly."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_show_prints_text(fake_client: FakeSites) -> None:
    """Show prints the title, alt text and no image when stdout is not a terminal."""
    result = runner.invoke(app, ["show", "614"])
    assert result.exit_code == 0
    assert "Woodpecker" in result.output
    assert "extension cord" in result.output
    assert not any("imgs.xkcd.com" in url for url in fake_client.requests)


def test_show_json_is_pipeable() -> None:
    """--json prints only a JSON document."""
    result = runner.invoke(app, ["show", "614", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["num"] == 614
    assert data["explanation_revid"] == 216714


def test_show_with_explanation() -> None:
    """--explain includes the explanation."""
    result = runner.invoke(app, ["show", "614", "--explain"])
    assert "Beret Guy observes a woodpecker" in result.output


def test_show_missing_comic_fails_cleanly() -> None:
    """A missing comic is an error message and exit code 1, not a traceback."""
    result = runner.invoke(app, ["show", "404"])
    assert result.exit_code == 1
    assert "no comic 404" in result.output
    assert "Traceback" not in result.output


def test_latest_and_random() -> None:
    """Latest and random behave like show for their comic."""
    assert "Siege Engine" in runner.invoke(app, ["latest"]).output
    assert "Woodpecker" in runner.invoke(app, ["random"]).output


def test_search_lists_matches() -> None:
    """Search prints number and title for each hit; --json gives a list."""
    runner.invoke(app, ["show", "614"])
    runner.invoke(app, ["show", "1"])
    result = runner.invoke(app, ["search", "woodpeckr"])
    assert result.exit_code == 0
    assert "614" in result.output
    assert "Woodpecker" in result.output
    data = json.loads(runner.invoke(app, ["search", "woodpeckr", "--json"]).output)
    assert [comic["num"] for comic in data] == [614]


def test_explain_prints_text() -> None:
    """Explain prints the plain-text explanation."""
    result = runner.invoke(app, ["explain", "614"])
    assert result.output.startswith("Beret Guy observes a woodpecker")


def test_sync_reports_count(fake_client: FakeSites) -> None:
    """Sync and sync --full report how many comics were added."""
    fake_client.latest["num"] = 4
    assert "1 new comic" in runner.invoke(app, ["sync"]).output
    result = runner.invoke(app, ["sync", "--full"])
    assert result.exit_code == 0
    assert "2 new comics" in result.output


def test_resync_reports_count() -> None:
    """Resync reports how many comics were refreshed."""
    runner.invoke(app, ["show", "1"])
    result = runner.invoke(app, ["resync", "--max-age", "0"])
    assert result.exit_code == 0
    assert "1 comic" in result.output


def test_db_option_is_used(tmp_path: Path) -> None:
    """--db selects the database file."""
    db = tmp_path / "elsewhere.sqlite3"
    assert runner.invoke(app, ["--db", str(db), "show", "614"]).exit_code == 0
    assert db.exists()


def test_explain_json() -> None:
    """Explain --json wraps the text in an object."""
    data = json.loads(runner.invoke(app, ["explain", "614", "--json"]).output)
    assert data["num"] == 614
    assert data["explanation"].startswith("Beret Guy")


def test_image_is_drawn_on_a_terminal(monkeypatch: pytest.MonkeyPatch, fake_client: FakeSites) -> None:
    """When stdout is a terminal the image is fetched and printed above the card."""
    monkeypatch.setattr("xkcdkit.cli.can_draw", lambda: True)
    result = runner.invoke(app, ["show", "614"])
    assert result.exit_code == 0
    assert any("imgs.xkcd.com" in url for url in fake_client.requests)


def test_tui_command_starts_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tui command hands a client to run_tui."""
    started: list[AsyncXKCD] = []
    monkeypatch.setattr("xkcdkit.tui.run_tui", started.append)
    assert runner.invoke(app, ["tui"]).exit_code == 0
    assert len(started) == 1


def test_open_client_uses_default_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The real factory honours XKCDKIT_DB."""
    monkeypatch.setenv("XKCDKIT_DB", str(tmp_path / "env.sqlite3"))
    client = real_open_client(None)
    assert client.store.path == tmp_path / "env.sqlite3"
    client.store.close()


def test_errors_go_to_stderr_and_keep_stdout_clean() -> None:
    """With --json a failure leaves stdout empty so pipelines never see non-JSON."""
    result = runner.invoke(app, ["show", "404", "--json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "no comic 404" in result.stderr


def test_titles_with_brackets_are_printed_literally() -> None:
    """Rich markup in comic text must not be interpreted or crash the output."""
    runner.invoke(app, ["show", "403"])
    result = runner.invoke(app, ["search", "pickup"])
    assert result.exit_code == 0
    assert "Convincing [/] Pickup Line" in result.output
    shown = runner.invoke(app, ["show", "403"])
    assert shown.exit_code == 0
    assert "see [sic] and [/b] end" in shown.output
