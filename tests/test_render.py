"""Tests for terminal rendering."""

import io
from typing import Any

from PIL import Image as PILImage
from rich.console import Console

from xkcdkit.models import Comic
from xkcdkit.render import can_draw, comic_image, comic_text


def render(renderable: Any) -> str:
    """Render to plain text at a fixed width."""
    console = Console(width=100, file=io.StringIO(), force_terminal=False, color_system=None)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined, no-any-return]


def test_comic_text_has_title_number_date_and_alt(comic_json: dict[str, Any]) -> None:
    """The text view shows the essentials on top and the alt text below."""
    out = render(comic_text(Comic.model_validate(comic_json)))
    assert "#614" in out
    assert "Woodpecker" in out
    assert "2009-07-24" in out
    assert "If you don't have an extension cord" in out
    assert "https://xkcd.com/614/" in out
    assert "Explanation" not in out


def test_comic_text_with_explanation(comic_json: dict[str, Any], wikitext: str) -> None:
    """With explain=True the plain-text explanation is included."""
    comic = Comic.model_validate({**comic_json, "explanation": wikitext})
    out = render(comic_text(comic, explain=True))
    assert "Beret Guy observes a woodpecker" in out


def test_comic_text_marks_missing_explanation(comic_json: dict[str, Any]) -> None:
    """A comic flagged as missing says so instead of showing nothing."""
    comic = Comic.model_validate({**comic_json, "explanation_missing": True})
    assert "No explanation" in render(comic_text(comic, explain=True))


def test_comic_image_renders_png_bytes() -> None:
    """Image bytes become a renderable that produces output without a TTY."""
    buffer = io.BytesIO()
    PILImage.new("RGB", (8, 4), "white").save(buffer, format="PNG")
    out = render(comic_image(buffer.getvalue()))
    assert out.strip() != ""


def test_can_draw_is_false_without_a_tty() -> None:
    """Under test capture stdout is not a terminal, so no image should be attempted."""
    assert can_draw() is False
