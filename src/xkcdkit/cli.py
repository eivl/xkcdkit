"""The ``xkcd`` command line interface."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any

import typer
from rich.console import Console, RenderableType
from rich.text import Text

from xkcdkit import XKCDError, __version__
from xkcdkit.client import AsyncXKCD
from xkcdkit.config import DEFAULT_TOML, CliSettings, config_path, dump, load_settings, write_default
from xkcdkit.models import Comic
from xkcdkit.render import can_draw, comic_image, comic_text, framed
from xkcdkit.sources import fetch_image

app = typer.Typer(help="xkcd comics in your terminal.", no_args_is_help=True)
console = Console()
errors = Console(stderr=True)
Num = Annotated[int, typer.Argument(help="Comic number.")]
Json = Annotated[bool, typer.Option("--json", help="Print JSON for piping.")]
Scale = Annotated[float | None, typer.Option("--scale", "-s", help="Image size multiplier.")]
Fit = Annotated[bool, typer.Option("--fit", help="Fill the terminal with the image.")]
NoImage = Annotated[bool, typer.Option("--no-image", help="Do not draw the image.")]
Explain = Annotated[bool, typer.Option("--explain", "-e", help="Include the explanation.")]


@dataclass
class Settings:
    """Options shared by every command."""

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
    db: Annotated[str | None, typer.Option(help="Database file (default: user data dir).")] = None,
    _: Annotated[bool, typer.Option("--version", callback=version, is_eager=True)] = False,
) -> None:
    """Fetch, browse and search xkcd comics with explanations from explainxkcd."""
    ctx.obj = Settings(db=db)
    if write_default():
        errors.print(f"Created settings file: {config_path()}", markup=False, soft_wrap=True)


def run(ctx: typer.Context, action: Callable[[AsyncXKCD], Awaitable[Any]]) -> Any:
    """Run an async action against a client, turning XKCDError into exit code 1."""

    async def go() -> Any:
        async with open_client(ctx.obj.db) as xk:
            return await action(xk)

    try:
        return asyncio.run(go())
    except XKCDError as exc:
        errors.print(f"error: {exc}", markup=False, highlight=False)
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        errors.print(
            "Interrupted. Everything fetched so far is saved; run the command again to continue.",
            soft_wrap=True,
        )
        raise typer.Exit(130) from None


@dataclass
class View:
    """How a comic should be presented."""

    json: bool = False
    image: bool = True
    explain: bool = False
    scale: float = 1.0
    fit: bool = False
    layout: CliSettings = field(default_factory=CliSettings)


def view(json: bool, no_image: bool, explain: bool, scale: float | None, fit: bool) -> View:
    """Combine command flags with the settings file; flags win."""
    settings = load_settings()
    image = settings.image
    return View(json, not no_image, explain, scale or image.scale, fit or image.fit, settings.cli)


async def present(xk: AsyncXKCD, pending: Awaitable[Comic], view: View) -> None:
    """Await a comic and print it as JSON or as a framed card with an optional image."""
    comic = await pending
    if view.json:
        console.print_json(comic.model_dump_json())
        return
    parts: list[RenderableType] = []
    if view.image and can_draw():
        parts.append(comic_image(await fetch_image(xk.http, comic), view.scale, view.fit))
    parts.append(comic_text(comic, explain=view.explain))
    console.print(framed(parts, view.layout.padding, view.layout.gap_lines))


@app.command()
def show(
    ctx: typer.Context,
    num: Num,
    no_image: NoImage = False,
    explain: Explain = False,
    json: Json = False,
    scale: Scale = None,
    fit: Fit = False,
) -> None:
    """Show one comic by number."""
    run(ctx, lambda xk: present(xk, xk.get(num), view(json, no_image, explain, scale, fit)))


@app.command()
def latest(
    ctx: typer.Context,
    no_image: NoImage = False,
    explain: Explain = False,
    json: Json = False,
    scale: Scale = None,
    fit: Fit = False,
) -> None:
    """Show the newest comic."""
    run(ctx, lambda xk: present(xk, xk.latest(), view(json, no_image, explain, scale, fit)))


@app.command()
def random(
    ctx: typer.Context,
    no_image: NoImage = False,
    explain: Explain = False,
    json: Json = False,
    scale: Scale = None,
    fit: Fit = False,
) -> None:
    """Show a random comic."""
    run(ctx, lambda xk: present(xk, xk.random(), view(json, no_image, explain, scale, fit)))


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Words from the title, alt text or explanation.")],
    limit: Annotated[int, typer.Option(help="Maximum number of hits.")] = 10,
    json: Json = False,
) -> None:
    """Fuzzy-search cached comics. Run sync --full first for the whole archive."""
    hits: list[Comic] = run(ctx, lambda xk: xk.search(query, limit))
    if json:
        console.print_json(data=[comic.model_dump(mode="json") for comic in hits])
        return
    for comic in hits:
        console.print(
            Text.assemble(
                (f"{comic.num:>5}", "bold"), "  ", comic.title, "  ", (comic.date.isoformat(), "dim")
            )
        )


@app.command()
def explain(ctx: typer.Context, num: Num, json: Json = False) -> None:
    """Print the explanation for a comic."""
    text: str = run(ctx, lambda xk: xk.explain(num))
    if json:
        console.print_json(data={"num": num, "explanation": text})
        return
    console.print(text or "No explanation on explainxkcd yet.", markup=False)


@app.command()
def sync(
    ctx: typer.Context,
    full: Annotated[bool, typer.Option("--full", help="Fetch every comic and explanation.")] = False,
    no_explain: Annotated[
        bool, typer.Option("--no-explain", help="Skip explainxkcd for now (much faster); resync fills it in.")
    ] = False,
) -> None:
    """Refresh the archive index and latest comic; with --full, download everything."""
    with console.status("Syncing") as status:
        added: int = run(
            ctx,
            lambda xk: xk.sync(
                full, lambda done, total: status.update(f"Syncing {done}/{total}"), explain=not no_explain
            ),
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

    run_tui(open_client(ctx.obj.db), load_settings())


@app.command()
def config(
    init: Annotated[bool, typer.Option("--init", help="Create the file with defaults if missing.")] = False,
    show_defaults: Annotated[bool, typer.Option("--show-defaults", help="Print the default file.")] = False,
) -> None:
    """Show where settings live and their effective values.

    Keys missing from the file take their defaults, so a new version never needs
    the file rewritten; --show-defaults prints every key with its comment.
    """
    path = config_path()
    if show_defaults:
        console.print(DEFAULT_TOML, markup=False, soft_wrap=True, end="")
    elif init:
        console.print(
            f"{'created' if write_default(path) else 'exists'}: {path}", markup=False, soft_wrap=True
        )
    else:
        console.print(f"# settings file: {path}", markup=False, soft_wrap=True)
        console.print(dump(load_settings(path)), markup=False, soft_wrap=True, end="")
