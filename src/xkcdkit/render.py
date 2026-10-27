"""Terminal rendering: a text card for a comic and an image when the terminal can draw one."""

import io
import sys

from PIL import Image as PILImage
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from xkcdkit import XKCDError
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


def comic_image(data: bytes, scale: float = 1.0, fit: bool = False) -> RenderableType:
    """A Rich renderable for the image bytes using the best protocol the terminal supports.

    ``scale`` multiplies the image's natural terminal size; ``fit`` instead fills the
    terminal while keeping the aspect ratio. textual-image probes the terminal on
    import, so it is imported here rather than at module load.

    Raises:
        XKCDError: when the bytes are not an image.
    """
    from textual_image.renderable import Image

    try:
        picture: PILImage.Image = PILImage.open(io.BytesIO(data))
        picture.load()
    except OSError as exc:
        raise XKCDError(f"not an image: {exc}") from exc
    if fit:
        renderable: RenderableType = Image(picture, width="auto", height="auto")
        return renderable
    if scale != 1:
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)))
    renderable = Image(picture)
    return renderable


def framed(renderables: list[RenderableType], padding: tuple[int, int, int, int], gap: int) -> RenderableType:
    """Stack renderables ``gap`` blank lines apart inside ``padding`` (top, right, bottom, left)."""
    spaced: list[RenderableType] = []
    for part in renderables:
        spaced += [Text("")] * gap if spaced else []
        spaced.append(part)
    if not any(padding):
        return Group(*spaced)
    return Padding(Group(*spaced), padding)


def can_draw() -> bool:
    """Whether drawing an image makes sense: only when stdout is a terminal."""
    return sys.stdout.isatty()
