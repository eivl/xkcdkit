"""A lazygit-style browser: archive on the left, image and text panes on the right."""

import io

from PIL import Image as PILImage
from rapidfuzz import fuzz
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static, TabbedContent, TabPane
from textual_image.widget import Image

from xkcdkit import XKCDError
from xkcdkit.client import AsyncXKCD
from xkcdkit.models import ArchiveEntry, Comic
from xkcdkit.sources import fetch_image

HELP = "j/k move  / filter  enter open  r random  l latest  i image  s sync  q quit"


class ArchiveItem(ListItem):
    """One archive row carrying its comic number."""

    def __init__(self, entry: ArchiveEntry) -> None:
        """Render the entry as number and title."""
        super().__init__(Static(f"[bold]{entry.num:>5}[/]  {entry.title}", markup=True))
        self.num = entry.num
        self.title = entry.title


class XKCDApp(App[None]):
    """Browse the xkcd archive with images, alt text, transcripts and explanations."""

    TITLE = "xkcd"
    CSS = """
    #archive-pane { width: 36; border: round $primary; }
    #archive { height: 1fr; }
    #image-pane { height: 2fr; border: round $secondary; align: center middle; }
    TabbedContent { height: 1fr; }
    .text { padding: 0 1; }
    """
    BINDINGS = [
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
                yield ListView(id="archive")
            with Vertical():
                yield Vertical(Image(id="image"), id="image-pane")
                with TabbedContent():
                    with TabPane("Alt text", id="tab-alt"):
                        yield VerticalScroll(Static(id="alt", classes="text"))
                    with TabPane("Transcript", id="tab-transcript"):
                        yield VerticalScroll(Static(id="transcript", classes="text"))
                    with TabPane("Explanation", id="tab-explanation"):
                        yield VerticalScroll(Static(id="explanation", classes="text"))
        yield Footer()

    async def on_mount(self) -> None:
        """Fill the archive list (syncing it if empty) and open the latest comic."""
        self.query_one(ListView).focus()
        await self.load_archive()
        self.open(None)

    async def load_archive(self) -> None:
        """Read the archive index from the store, fetching it on first run."""
        self.entries = self.client.store.archive()
        if not self.entries:
            await self.client.sync()
            self.entries = self.client.store.archive()
        self.show_entries(self.entries)

    def show_entries(self, entries: list[ArchiveEntry]) -> None:
        """Replace the list contents."""
        archive = self.query_one(ListView)
        archive.clear()
        archive.extend(ArchiveItem(entry) for entry in entries)
        archive.index = 0

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
        first = self.query(ArchiveItem).first() if self.query(ArchiveItem) else None
        if first:
            self.open(first.num)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter on a row opens that comic."""
        if isinstance(event.item, ArchiveItem):
            self.open(event.item.num)

    @work(exclusive=True)
    async def open(self, num: int | None) -> None:
        """Fetch comic ``num`` (or the latest) and show it."""
        try:
            comic = await self.client.latest() if num is None else await self.client.get(num)
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
        archive = self.query_one(ListView)
        archive.action_cursor_down() if direction == "down" else archive.action_cursor_up()

    def action_focus_filter(self) -> None:
        """Jump to the filter box."""
        self.query_one("#filter", Input).focus()

    def action_random(self) -> None:
        """Open a random comic."""
        self.open_random()

    @work(exclusive=True)
    async def open_random(self) -> None:
        """Worker behind the r key."""
        await self.show_comic(await self.client.random())

    def action_latest(self) -> None:
        """Open the newest comic."""
        self.open(None)

    def action_toggle_image(self) -> None:
        """Show or hide the image pane."""
        pane = self.query_one("#image-pane")
        pane.display = not pane.display

    @work(exclusive=True)
    async def action_sync(self) -> None:
        """Refresh the archive and latest comic, then report."""
        added = await self.client.sync()
        await self.load_archive()
        self.notify(f"Synced: {added} new comic(s).")

    def action_help(self) -> None:
        """Show the key bindings."""
        self.notify(HELP, title="Keys", timeout=8)


def run_tui(client: AsyncXKCD) -> None:
    """Start the browser. Probes the terminal for image support before Textual takes over."""
    import textual_image.renderable  # noqa: F401  (must run before the app starts)

    XKCDApp(client).run()
