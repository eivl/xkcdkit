"""A lazygit-style browser: archive on the left, image and text panes on the right."""

import io
from typing import ClassVar

from PIL import Image as PILImage
from rapidfuzz import fuzz
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, OptionList, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option
from textual_image.widget import Image

from xkcdkit import XKCDError
from xkcdkit.client import AsyncXKCD
from xkcdkit.models import ArchiveEntry, Comic
from xkcdkit.sources import fetch_image

HELP = "j/k move  / filter  enter open  r random  l latest  i image  s sync  q quit"


def option(entry: ArchiveEntry) -> Option:
    """An archive row: bold number, then the title, keyed by the comic number."""
    return Option(Text.assemble((f"{entry.num:>5}", "bold"), "  ", entry.title), id=str(entry.num))


class XKCDApp(App[None]):
    """Browse the xkcd archive with images, alt text, transcripts and explanations."""

    TITLE = "xkcd"
    CSS = """
    #archive-pane { width: 40; border: round $primary; }
    #archive { height: 1fr; }
    #image-pane { height: 2fr; border: round $secondary; align: center middle; }
    TabbedContent { height: 1fr; }
    .text { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor('down')", "Down"),
        Binding("k", "cursor('up')", "Up"),
        Binding("slash", "focus_filter", "Filter", key_display="/"),
        Binding("r", "random", "Random"),
        Binding("l", "latest", "Latest"),
        Binding("i", "toggle_image", "Image"),
        Binding("s", "sync", "Sync"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, client: AsyncXKCD) -> None:
        """Keep the client; the store it holds feeds the archive list."""
        super().__init__()
        self.client = client
        self.entries: list[ArchiveEntry] = []

    def compose(self) -> ComposeResult:
        """Build the two-column layout."""
        yield Header()
        with Horizontal():
            with Vertical(id="archive-pane"):
                yield Input(placeholder="filter titles", id="filter")
                yield OptionList(id="archive")
            with Vertical():
                yield Vertical(Image(id="image"), id="image-pane")
                with TabbedContent():
                    with TabPane("Alt text", id="tab-alt"):
                        yield VerticalScroll(Static(id="alt", classes="text", markup=False))
                    with TabPane("Transcript", id="tab-transcript"):
                        yield VerticalScroll(Static(id="transcript", classes="text", markup=False))
                    with TabPane("Explanation", id="tab-explanation"):
                        yield VerticalScroll(Static(id="explanation", classes="text", markup=False))
        yield Footer()

    def on_mount(self) -> None:
        """Show the cached archive (syncing it on first run) and open the latest comic."""
        self.query_one(OptionList).focus()
        self.entries = self.client.store.archive()
        self.show_entries(self.entries)
        if not self.entries:
            self.action_sync()
        self.open(None)

    def show_entries(self, entries: list[ArchiveEntry]) -> None:
        """Replace the list contents."""
        archive = self.query_one(OptionList)
        archive.clear_options()
        archive.add_options(option(entry) for entry in entries)
        archive.highlighted = 0 if entries else None

    def on_input_changed(self, event: Input.Changed) -> None:
        """Fuzzy-filter the archive list as the user types."""
        query = event.value.strip().lower()
        if not query:
            self.show_entries(self.entries)
            return
        scored = [(fuzz.WRatio(query, e.title.lower()), e) for e in self.entries]
        self.show_entries([e for score, e in scored if score >= 70])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the filter opens the first match."""
        archive = self.query_one(OptionList)
        if archive.option_count:
            self.open(int(str(archive.get_option_at_index(0).id)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on a row opens that comic."""
        self.open(int(str(event.option.id)))

    @work(exclusive=True, group="open")
    async def open(self, num: int | None) -> None:
        """Fetch comic ``num`` (or the latest, or a random one for -1) and show it."""
        try:
            if num is None:
                comic = await self.client.latest()
            elif num < 0:
                comic = await self.client.random()
            else:
                comic = await self.client.get(num)
            await self.show_comic(comic)
        except XKCDError as exc:
            self.notify(str(exc), severity="error")

    async def show_comic(self, comic: Comic) -> None:
        """Fill the panes from a comic."""
        self.sub_title = f"#{comic.num}  {comic.title}  ({comic.date.isoformat()})"
        self.query_one("#alt", Static).update(comic.alt)
        self.query_one("#transcript", Static).update(comic.transcript or "No transcript.")
        explanation = comic.explanation_text or "No explanation on explainxkcd yet."
        self.query_one("#explanation", Static).update(explanation)
        if self.query_one("#image-pane").display:
            await self.show_image(comic)

    async def show_image(self, comic: Comic) -> None:
        """Download and display the comic image, reporting rather than crashing on bad data."""
        try:
            data = await fetch_image(self.client.http, comic)
            self.query_one("#image", Image).image = PILImage.open(io.BytesIO(data))
        except (XKCDError, OSError) as exc:
            self.notify(f"Image unavailable: {exc}", severity="warning")

    def action_cursor(self, direction: str) -> None:
        """Move the archive cursor with j/k."""
        archive = self.query_one(OptionList)
        archive.action_cursor_down() if direction == "down" else archive.action_cursor_up()

    def action_focus_filter(self) -> None:
        """Jump to the filter box."""
        self.query_one("#filter", Input).focus()

    def action_random(self) -> None:
        """Open a random comic."""
        self.open(-1)

    def action_latest(self) -> None:
        """Open the newest comic."""
        self.open(None)

    def action_toggle_image(self) -> None:
        """Show or hide the image pane."""
        pane = self.query_one("#image-pane")
        pane.display = not pane.display

    @work(exclusive=True, group="sync")
    async def action_sync(self) -> None:
        """Refresh the archive and latest comic, then report."""
        try:
            added = await self.client.sync()
        except XKCDError as exc:
            self.notify(str(exc), severity="error")
            return
        self.entries = self.client.store.archive()
        self.show_entries(self.entries)
        self.notify(f"Synced: {added} new comic(s).")

    def action_help(self) -> None:
        """Show the key bindings."""
        self.notify(HELP, title="Keys", timeout=8)


def run_tui(client: AsyncXKCD) -> None:
    """Start the browser and close the client when it exits."""
    try:
        XKCDApp(client).run()
    finally:
        client.store.close()
