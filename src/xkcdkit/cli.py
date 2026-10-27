"""The ``xkcd`` command line interface."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any

import typer
from rich.console import Console

from xkcdkit import XKCDError, __version__
from xkcdkit.client import AsyncXKCD
from xkcdkit.models import Comic
from xkcdkit.render import can_draw, comic_image, comic_text
from xkcdkit.sources import fetch_image

app = typer.Typer(help="xkcd comics in your terminal.", no_args_is_help=True, add_completion=False)
console = Console()
Num = Annotated[int, typer.Argument(help="Comic number.")]
NoImage = Annotated[bool, typer.Option("--no-image", help="Do not draw the image.")]
Explain = Annotated[bool, typer.Option("--explain", "-e", help="Include the explanation.")]


@dataclass
class Settings:
    """Options shared by every command."""

    json: bool = False
    db: str | None = None


def open_client(db: str | None) -> AsyncXKCD:
    """Create the client; tests replace this to inject fakes."""
    return AsyncXKCD(db=db)


def version(flag: bool) -> None:
    """Print the version and exit when ``--version`` is given."""
    if flag:
        console.print(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    json: Annotated[bool, typer.Option("--json", help="Print JSON for piping.")] = False,
    db: Annotated[str | None, typer.Option(help="Database file (default: user data dir).")] = None,
    _: Annotated[bool, typer.Option("--version", callback=version, is_eager=True)] = False,
) -> None:
    """Fetch, browse and search xkcd comics with explanations from explainxkcd."""
    ctx.obj = Settings(json=json, db=db)


def run(ctx: typer.Context, action: Callable[[AsyncXKCD], Awaitable[Any]]) -> Any:
    """Run an async action against a client, turning XKCDError into exit code 1."""

    async def go() -> Any:
        async with open_client(ctx.obj.db) as xk:
            return await action(xk)

    try:
        return asyncio.run(go())
    except XKCDError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(1) from exc


async def present(ctx: typer.Context, xk: AsyncXKCD, comic: Comic, image: bool, explain: bool) -> None:
    """Print a comic as JSON or as a card with an optional image."""
    if ctx.obj.json:
        console.print_json(comic.model_dump_json())
        return
    if image and can_draw():
        console.print(comic_image(await fetch_image(xk.http, comic)))
    console.print(comic_text(comic, explain=explain))


@app.command()
def show(ctx: typer.Context, num: Num, no_image: NoImage = False, explain: Explain = False) -> None:
    """Show one comic by number."""
    run(ctx, lambda xk: show_comic(ctx, xk, xk.get(num), no_image, explain))


@app.command()
def latest(ctx: typer.Context, no_image: NoImage = False, explain: Explain = False) -> None:
    """Show the newest comic."""
    run(ctx, lambda xk: show_comic(ctx, xk, xk.latest(), no_image, explain))


@app.command()
def random(ctx: typer.Context, no_image: NoImage = False, explain: Explain = False) -> None:
    """Show a random comic."""
    run(ctx, lambda xk: show_comic(ctx, xk, xk.random(), no_image, explain))


async def show_comic(
    ctx: typer.Context, xk: AsyncXKCD, pending: Awaitable[Comic], no_image: bool, explain: bool
) -> None:
    """Await a comic and present it."""
    await present(ctx, xk, await pending, image=not no_image, explain=explain)


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Words from the title, alt text or explanation.")],
    limit: Annotated[int, typer.Option(help="Maximum number of hits.")] = 10,
) -> None:
    """Fuzzy-search cached comics. Run sync --full first for the whole archive."""
    hits: list[Comic] = run(ctx, lambda xk: xk.search(query, limit))
    if ctx.obj.json:
        console.print_json(data=[comic.model_dump(mode="json") for comic in hits])
        return
    for comic in hits:
        console.print(f"[bold]{comic.num:>5}[/]  {comic.title}  [dim]{comic.date.isoformat()}[/]")


@app.command()
def explain(ctx: typer.Context, num: Num) -> None:
    """Print the explanation for a comic."""
    text: str = run(ctx, lambda xk: xk.explain(num))
    if ctx.obj.json:
        console.print_json(data={"num": num, "explanation": text})
        return
    console.print(text or "No explanation on explainxkcd yet.", markup=False)


@app.command()
def sync(
    ctx: typer.Context,
    full: Annotated[bool, typer.Option("--full", help="Fetch every comic and explanation.")] = False,
) -> None:
    """Refresh the archive index and latest comic; with --full, download everything."""
    with console.status("Syncing") as status:
        added: int = run(
            ctx, lambda xk: xk.sync(full, lambda done, total: status.update(f"Syncing {done}/{total}"))
        )
    console.print(f"{added} new comic{'s' if added != 1 else ''} cached.")


@app.command()
def resync(
    ctx: typer.Context,
    max_age: Annotated[int, typer.Option(help="Refresh comics synced more than this many days ago.")] = 30,
) -> None:
    """Re-fetch stale comics and those still missing an explanation."""
    with console.status("Resyncing") as status:
        count: int = run(
            ctx,
            lambda xk: xk.resync(
                timedelta(days=max_age), lambda done, total: status.update(f"Resyncing {done}/{total}")
            ),
        )
    console.print(f"{count} comic{'s' if count != 1 else ''} refreshed.")


@app.command()
def tui(ctx: typer.Context) -> None:
    """Open the interactive browser."""
    from xkcdkit.tui import run_tui

    run_tui(open_client(ctx.obj.db))
