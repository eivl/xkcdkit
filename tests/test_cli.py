"""Tests for the command line interface."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from xkcdkit import AsyncXKCD, __version__
from xkcdkit.cli import app

from .test_sources import FakeSites

runner = CliRunner()


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeSites]:
    """Point the CLI at the fake sites and a temporary database."""
    sites = FakeSites()
    monkeypatch.setattr("random.choice", lambda nums: 614)

    def open_client(db: str | None) -> AsyncXKCD:
        return AsyncXKCD(db=db or tmp_path / "cli.sqlite3", client=sites.client(), explain_delay=0)

    monkeypatch.setattr("xkcdkit.cli.open_client", open_client)
    yield sites


def test_version() -> None:
    """--version prints the package version and exits cleanly."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_show_prints_text(fake_client: FakeSites) -> None:
    """show prints the title, alt text and no image when stdout is not a terminal."""
    result = runner.invoke(app, ["show", "614"])
    assert result.exit_code == 0
    assert "Woodpecker" in result.output and "extension cord" in result.output
    assert not any("imgs.xkcd.com" in url for url in fake_client.requests)


def test_show_json_is_pipeable() -> None:
    """--json prints only a JSON document."""
    result = runner.invoke(app, ["--json", "show", "614"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["num"] == 614 and data["explanation_revid"] == 216714


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
    """latest and random behave like show for their comic."""
    assert "Siege Engine" in runner.invoke(app, ["latest"]).output
    assert "Woodpecker" in runner.invoke(app, ["random"]).output


def test_search_lists_matches() -> None:
    """search prints number and title for each hit; --json gives a list."""
    runner.invoke(app, ["show", "614"])
    runner.invoke(app, ["show", "1"])
    result = runner.invoke(app, ["search", "woodpeckr"])
    assert result.exit_code == 0 and "614" in result.output and "Woodpecker" in result.output
    data = json.loads(runner.invoke(app, ["--json", "search", "woodpeckr"]).output)
    assert [comic["num"] for comic in data] == [614]


def test_explain_prints_text() -> None:
    """explain prints the plain-text explanation."""
    result = runner.invoke(app, ["explain", "614"])
    assert result.output.startswith("Beret Guy observes a woodpecker")


def test_sync_reports_count() -> None:
    """sync and sync --full report how many comics were added."""
    assert "1 new comic" in runner.invoke(app, ["sync"]).output
    result = runner.invoke(app, ["sync", "--full"])
    assert result.exit_code == 0 and "new comic" in result.output


def test_resync_reports_count() -> None:
    """resync reports how many comics were refreshed."""
    runner.invoke(app, ["show", "1"])
    result = runner.invoke(app, ["resync", "--max-age", "0"])
    assert result.exit_code == 0 and "1 comic" in result.output


def test_db_option_is_used(tmp_path: Path) -> None:
    """--db selects the database file."""
    db = tmp_path / "elsewhere.sqlite3"
    assert runner.invoke(app, ["--db", str(db), "show", "614"]).exit_code == 0
    assert db.exists()
