"""Shared fixtures: captured responses from xkcd.com and explainxkcd.com."""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_user_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep every test away from the developer's real settings file and database."""
    monkeypatch.setenv("XKCDKIT_CONFIG", str(tmp_path / "isolated-config.toml"))
    monkeypatch.setenv("XKCDKIT_DB", str(tmp_path / "isolated.sqlite3"))


def load_json(name: str) -> dict[str, Any]:
    """Read a JSON fixture by file name."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture
def comic_json() -> dict[str, Any]:
    """Raw xkcd JSON for comic 614."""
    return load_json("614.json")


@pytest.fixture
def wikitext() -> str:
    """Full explainxkcd wikitext for comic 614."""
    page = load_json("explain_614.json")["query"]["pages"][0]
    return page["revisions"][0]["slots"]["main"]["content"]  # type: ignore[no-any-return]


@pytest.fixture
def archive_html() -> str:
    """A trimmed copy of the xkcd archive page."""
    return (FIXTURES / "archive.html").read_text(encoding="utf-8")
