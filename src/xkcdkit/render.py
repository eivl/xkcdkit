"""Terminal rendering: a text card for a comic and an image when the terminal can draw one."""

import io
import sys

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from xkcdkit.models import Comic


def comic_text(comic: Comic, explain: bool = False) -> RenderableType:
    """A panel with number, title, date, alt text and optionally the explanation."""
    header = Text.assemble(("#", "dim"), (str(comic.num), "bold"), "  ", (comic.title, "bold cyan"))
    body: list[RenderableType] = [Text(comic.alt, style="italic"), Text(comic.url, style="dim")]
    if explain:
        body += [Text(""), Text("Explanation", style="bold underline"), explanation_text(comic)]
    return Panel(Group(*body), title=header, subtitle=comic.date.isoformat(), title_align="left")


def explanation_text(comic: Comic) -> Text:
    """The explanation body, or a note when explainxkcd has no page."""
    if comic.explanation_missing or not comic.explanation_text:
        return Text("No explanation on explainxkcd yet.", style="dim")
    return Text(comic.explanation_text)


def comic_image(data: bytes) -> RenderableType:
    """A Rich renderable for the image bytes using the best protocol the terminal supports.

    textual-image probes the terminal on import, so it is imported here rather than
    at module load.
    """
    from textual_image.renderable import Image

    renderable: RenderableType = Image(io.BytesIO(data))
    return renderable


def can_draw() -> bool:
    """Whether drawing an image makes sense: only when stdout is a terminal."""
    return sys.stdout.isatty()
