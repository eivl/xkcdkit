"""Tests for terminal rendering."""

import io
from typing import Any

import pytest
from PIL import Image as PILImage
from rich.console import Console
from rich.text import Text

from xkcdkit import XKCDError
from xkcdkit.models import Comic
from xkcdkit.render import can_draw, comic_image, comic_text, framed


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


def png(width: int, height: int) -> bytes:
    """A blank PNG of the given pixel size."""
    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def width_of(renderable: Any, console_width: int = 100) -> int:
    """Widest rendered line, in cells."""
    console = Console(
        width=console_width, height=60, file=io.StringIO(), force_terminal=False, color_system=None
    )
    console.print(renderable)
    return max(len(line) for line in console.file.getvalue().splitlines())  # type: ignore[attr-defined]


def test_comic_image_renders_png_bytes() -> None:
    """Image bytes become a renderable that produces output without a TTY."""
    assert render(comic_image(png(8, 4))).strip() != ""


def test_comic_image_scale_multiplies_natural_size() -> None:
    """scale=2 draws the image twice as wide as scale=1."""
    natural = width_of(comic_image(png(200, 100)))
    assert width_of(comic_image(png(200, 100), scale=2)) == natural * 2


def test_comic_image_fit_fills_the_terminal_width() -> None:
    """fit=True uses the whole console width whatever the source size.

    The fallback renderer rounds cell counts from a guessed cell size, which on
    Windows lands one cell short, so allow a cell of slack.
    """
    assert 88 <= width_of(comic_image(png(200, 100), fit=True), console_width=90) <= 90


def test_comic_image_rejects_bad_bytes() -> None:
    """Corrupt data is an XKCDError, not a PIL traceback."""
    with pytest.raises(XKCDError, match="image"):
        comic_image(b"not a png")


def test_can_draw_is_false_without_a_tty() -> None:
    """Under test capture stdout is not a terminal, so no image should be attempted."""
    assert can_draw() is False


def test_framed_adds_margin_around_the_output() -> None:
    """A margin of 1 adds a blank line above and below and two spaces on each side."""
    lines = [line.rstrip() for line in render(framed([Text("x")], margin=1)).split("\n")]
    assert lines[0] == ""
    assert lines[1] == "  x"
    assert lines[2] == ""


def test_framed_zero_margin_is_tight() -> None:
    """margin=0 leaves the output untouched."""
    assert render(framed([Text("x")], margin=0)) == "x\n"
