"""Shared fixtures: captured responses from xkcd.com and explainxkcd.com."""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


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
    return load_json("explain_614.json")["parse"]["wikitext"]  # type: ignore[no-any-return]


@pytest.fixture
def archive_html() -> str:
    """A trimmed copy of the xkcd archive page."""
    return (FIXTURES / "archive.html").read_text(encoding="utf-8")
