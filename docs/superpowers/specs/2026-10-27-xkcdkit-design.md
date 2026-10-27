# xkcdkit design

Date: 2026-10-27. Status: approved in conversation.

## Purpose

xkcdkit is one installable Python package with three surfaces:

1. A library (`import xkcdkit`) for programmers, for example a Discord bot
   that fetches comics. Async is the primary API; a sync wrapper exists.
2. A CLI (`xkcd`) that prints a comic with title, alt text and the image
   drawn in the terminal, or emits JSON for piping.
3. A TUI (`xkcd tui`) in the style of lazygit/lazydocker for browsing the
   archive, viewing comics and reading explanations.

All surfaces share a local SQLite cache that fills as you browse and can be
filled completely with a scrape command.

Success looks like: a reader can read the whole codebase top to bottom and
understand it. Functions are short, documented and few. Tests cover nearly
everything.

## Constraints

- Python >= 3.12 (textual-image requires it). Tested on 3.12 to 3.15.
- Works on Linux, macOS and Windows. Image rendering degrades gracefully.
- Dependencies: typer, pydantic, textual, httpx2, textual-image (pulls in
  pillow and rich), rapidfuzz, platformdirs. Nothing else at runtime.
- No underscore-prefixed module-level names. Underscore prefixes are allowed
  for genuinely private class members only.
- Every public function and class has a docstring. Enforced by ruff.

## Data sources

| Source | URL | Notes |
|---|---|---|
| Latest comic | `https://xkcd.com/info.0.json` | JSON |
| Comic N | `https://xkcd.com/N/info.0.json` | JSON, 404 for missing (404 itself) |
| Archive | `https://xkcd.com/archive/` | HTML; one anchor per comic with number, date and title |
| Explanation | `https://www.explainxkcd.com/wiki/api.php?action=parse&page=N&redirects=1&prop=wikitext|revid&format=json&formatversion=2` | MediaWiki API; `missingtitle` error when absent |

explainxkcd asks for gentle crawling and a 1 second delay. Rules:

- Descriptive `User-Agent` on every request: `xkcdkit/<version> (+https://github.com/eivl/xkcdkit)`.
- On-demand lookups have no delay.
- Bulk sync fetches xkcd.com with concurrency 4 and explainxkcd one page per
  second.

## Data model

`Comic` (pydantic) holds every xkcd JSON field: num, title, safe_title,
alt, img, transcript, link, news, year, month, day. Plus:

- `explanation`: full page wikitext from explainxkcd, or None.
- `explanation_revid`: wiki revision id, or None.
- `explanation_missing`: True when explainxkcd had no page at sync time.
- `synced_at`: UTC datetime the row was written.

Derived, not stored: `date` (a `datetime.date`), `explanation_text`
(wikitext reduced to plain text: templates, links and markup stripped),
`url` (`https://xkcd.com/N/`).

`ArchiveEntry`: num, date, title. From the archive page.

## Storage

SQLite via the standard library, in the platformdirs user data directory
(`xkcdkit/xkcd.sqlite3`), overridable with `XKCDKIT_DB`.

Tables:

- `comics`: one row per comic, columns matching `Comic`. Insert only. A row
  is never updated except by `resync`, which replaces it wholesale.
- `archive`: num, date, title. Replaced on every sync.
- `meta`: key, value. Keys: `latest_num`, `last_sync_at`, `last_full_sync_at`.

Freshness rules:

- A cached comic with `explanation_missing` and `synced_at` older than 24
  hours is re-fetched on access.
- `resync` re-fetches comics whose `synced_at` is older than `max_age`
  (default 30 days) and all rows with `explanation_missing`.
- Comics synced recently are trusted and never re-fetched.

Search: rapidfuzz `partial_ratio` over title, alt, transcript and
explanation text, scored per field with title weighted highest. Returns
the top N matches above a cutoff.

## Library API

```python
from xkcdkit import AsyncXKCD, XKCD

async with AsyncXKCD() as xk:
    comic = await xk.get(614)
    latest = await xk.latest()
    rnd = await xk.random()
    hits = await xk.search("woodpecker", limit=5)
    await xk.sync()  # archive + latest, fill gaps lazily
    await xk.sync(full=True)  # every comic and explanation
    await xk.resync(max_age=timedelta(days=7))

with XKCD() as xk:  # same methods, blocking
    comic = xk.get(614)
```

`XKCD` wraps `AsyncXKCD` and runs each call with `asyncio.run`. It cannot
be used from inside a running event loop; the docstring says so.

Both accept `db` (path), `client` (an httpx2 client, for injection in tests)
and `timeout`.

## Modules

| Module | Contents |
|---|---|
| `models.py` | `Comic`, `ArchiveEntry`, `wikitext_to_text` |
| `sources.py` | `fetch_comic`, `fetch_latest`, `fetch_archive`, `fetch_explanation`, `user_agent` |
| `store.py` | `Store` class: open, put, get, list, search, meta, stale queries |
| `client.py` | `AsyncXKCD`, `XKCD` |
| `render.py` | `comic_text`, `comic_image`, `can_draw` |
| `cli.py` | typer app |
| `tui.py` | textual app |
| `__init__.py` | exports and `__version__` |

Target: under about 800 lines of source excluding tests.

## CLI

```
xkcd show 614 [--no-image] [--explain] [--json]
xkcd latest   [same flags]
xkcd random   [same flags]
xkcd search "query" [--limit 10] [--json]
xkcd explain 614 [--json]
xkcd sync [--full]
xkcd resync [--max-age DAYS]
xkcd tui
xkcd --version
```

`--json` prints the `Comic` model as JSON and nothing else, so output can
be piped. Images are drawn with textual-image's Rich renderable when the
terminal supports kitty or sixel, half-block unicode otherwise, and are
skipped entirely when stdout is not a TTY or `--no-image` is given.

## TUI

Layout, lazygit style:

```
+----------------------+------------------------------------+
| Archive [filter: _ ] |  image                             |
| 3316 Siege Engine    |                                    |
| 3315 Forms of Water  |                                    |
| ...                  +------------------------------------+
|                      | [Alt] [Transcript] [Explanation]   |
|                      | text                               |
+----------------------+------------------------------------+
| j/k move  / filter  enter open  r random  l latest  i image  s sync  ? help  q quit |
```

The archive list comes from the `archive` table and is fuzzy filtered as
you type. Opening an entry fetches and caches the comic. The image pane can
be toggled off. The explanation tab shows plain text derived from wikitext.
Sync runs in a worker and reports progress in the footer.

## Error handling

- Network errors surface as `XKCDError` with a readable message. The CLI
  prints it to stderr and exits 1.
- A missing comic number raises `ComicNotFound`.
- A missing explanation is not an error: the comic is returned with
  `explanation_missing=True`.

## Testing

- pytest with pytest-asyncio. HTTP is mocked with `httpx2.MockTransport`
  returning fixtures captured from the real endpoints.
- Store tests use a temporary database path.
- CLI tests use typer's `CliRunner`. TUI tests use Textual's `Pilot`.
- coverage.py with `fail_under = 95`.
- tox (tox-uv) runs the suite on 3.12, 3.13, 3.14 and 3.15 in CI.

## Tooling and repository

- uv for project management, `uv_build` as the build backend.
- ruff: lint (including pydocstyle `D` rules, Google convention) and format.
- mypy strict. flake8 configured to agree with ruff's line length.
- pre-commit: ruff, ruff-format, mypy, flake8, zizmor, actionlint, uv-lock
  check and standard hygiene hooks.
- GitHub Actions, all actions pinned by SHA:
  - `ci.yml`: lint, type check, tox matrix with coverage.
  - `release.yml`: python-semantic-release bumps the version from
    conventional commits, tags, builds with uv and publishes to PyPI via
    trusted publishing in a `pypi` environment.
  - `security.yml`: zizmor and actionlint on pull requests, OpenSSF
    Scorecard weekly.
  - dependabot for GitHub Actions and Python dependencies.
- Repo: `github.com/eivl/xkcdkit`, public. Package name `xkcdkit`, import
  `xkcdkit`, command `xkcd`.

## README

Sections: what it is, install for library use (pip / uv add), install for
CLI and TUI (pipx / uv tool), Linux and macOS quick start, Windows quick
start noting that the Python launcher is `py` so commands read
`py -m pip ...` and `py -m pipx ...`, terminal image support matrix,
library examples including a minimal Discord-style async usage, data and
cache notes, and the explainxkcd rate limit.
