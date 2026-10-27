# xkcdkit

xkcd comics as a Python library, a command line tool and a terminal browser.
Everything you look at is cached in a local SQLite database, together with the
explanation from [explainxkcd](https://www.explainxkcd.com/), so repeat lookups
and searches never touch the network.

```
$ xkcd show 614
╭─ #614  Woodpecker ───────────────────────────────────────────────╮
│ If you don't have an extension cord I can get that too.  Because │
│ we're friends!  Right?                                           │
│ https://xkcd.com/614/                                            │
╰──────────────────────────────────────────────────── 2009-07-24 ──╯
```

On a terminal that supports the kitty graphics protocol or sixel, the comic
image is drawn above the card.

## Install

### As a library

```sh
pip install xkcdkit
# or
uv add xkcdkit
```

### As a command line tool and TUI

Install it in its own isolated environment so it never conflicts with your
projects:

```sh
pipx install xkcdkit
# or
uv tool install xkcdkit
```

Either way you get the `xkcd` command.

### Linux and macOS

The commands above work as written. If you prefer not to install anything
permanently:

```sh
uvx xkcdkit show 614
```

### Windows

On Windows the Python launcher is called `py`, and `python` is often not on
your PATH (or opens the Microsoft Store). Use the launcher for everything that
starts with `python`:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
pipx install xkcdkit
```

or, with uv installed:

```powershell
uv tool install xkcdkit
```

Images need Windows Terminal 1.22 or newer, which supports sixel. The old
console host (`conhost.exe`) cannot draw images, and xkcdkit falls back to a
text-only card there.

## Command line

```
xkcd show 614            # one comic by number
xkcd show 614 --explain  # with the explainxkcd explanation
xkcd latest              # the newest comic
xkcd random              # a random comic
xkcd search "woodpecker" # fuzzy search over cached titles, alt text, transcripts and explanations
xkcd explain 614         # just the explanation, as plain text
xkcd sync                # refresh the archive index and the latest comic
xkcd sync --full         # download every comic and explanation (about an hour, see below)
xkcd resync              # re-fetch comics older than 30 days or still missing an explanation
xkcd tui                 # open the browser
```

Add `--json` before the command to get machine-readable output for piping:

```sh
xkcd --json show 614 | jq .alt
xkcd --json search "sandwich" | jq '.[].num'
```

`--no-image` skips the picture. Images are also skipped automatically when
stdout is not a terminal, so pipes always get clean text.

### The browser

`xkcd tui` opens a two-pane browser in the spirit of lazygit: the archive on
the left, the comic on the right with tabs for alt text, transcript and
explanation.

| Key     | Action                           |
| ------- | -------------------------------- |
| `j`/`k` | move through the archive         |
| `/`     | filter the archive by title      |
| `Enter` | open the selected comic          |
| `r`     | random comic                     |
| `l`     | latest comic                     |
| `i`     | show or hide the image pane      |
| `s`     | sync the archive index           |
| `?`     | key help                         |
| `q`     | quit                             |

## Library

The async client is the primary API. It is built for I/O bound programs such
as bots and web services.

```python
from xkcdkit import AsyncXKCD

async with AsyncXKCD() as xk:
    comic = await xk.get(614)
    print(comic.title, comic.alt, comic.img)
    print(comic.explanation_text[:200])

    latest = await xk.latest()
    hits = await xk.search("sandwich", limit=5)
    await xk.sync()  # archive index + latest comic
```

A blocking twin exists for scripts and the REPL. It runs each call on its own
event loop, so it cannot be used from inside async code.

```python
from xkcdkit import XKCD

with XKCD() as xk:
    print(xk.random().title)
```

A minimal discord.py command looks like this:

```python
@bot.command()
async def xkcd(ctx, num: int):
    async with AsyncXKCD() as xk:
        try:
            comic = await xk.get(num)
        except ComicNotFound:
            await ctx.send(f"There is no xkcd {num}.")
            return
    await ctx.send(f"**{comic.title}**\n{comic.img}\n*{comic.alt}*")
```

Keep one `AsyncXKCD` open for the lifetime of a long-running program rather
than creating one per request; it holds an HTTP connection pool and the
database connection.

### The `Comic` model

`Comic` is a pydantic model with every field from the xkcd JSON (`num`,
`title`, `safe_title`, `alt`, `img`, `transcript`, `link`, `news`, `year`,
`month`, `day`) plus:

| Field                 | Meaning                                                     |
| --------------------- | ----------------------------------------------------------- |
| `explanation`         | full explainxkcd page wikitext, or `None`                   |
| `explanation_revid`   | the wiki revision that was fetched                          |
| `explanation_missing` | `True` when explainxkcd had no page at sync time            |
| `synced_at`           | when the row was written (UTC)                              |
| `explanation_text`    | property: the Explanation section as plain text             |
| `date`, `url`         | properties: publication date and the comic's page           |

`comic.model_dump_json()` gives you the same JSON the CLI prints.

## Data, caching and freshness

- The database lives in your platform's user data directory
  (`~/.local/share/xkcdkit/xkcd.sqlite3` on Linux, `~/Library/Application
  Support/xkcdkit/` on macOS, `%LOCALAPPDATA%\xkcdkit\` on Windows). Set
  `XKCDKIT_DB` or pass `--db` / `db=` to put it elsewhere.
- Comics are immutable once stored. A cached comic is served as is, except
  when its explanation was missing more than a day ago; then explainxkcd is
  asked again on the next access.
- `resync` re-fetches rows older than `--max-age` days (default 30) and every
  row still flagged `explanation_missing`. Recently synced data is trusted.
- Roughly 1 to 2 percent of comics have no explainxkcd page yet. Those rows
  carry `explanation_missing = True` so your code can decide what to do.

### Being polite to explainxkcd

explainxkcd is a volunteer-run wiki. Its robots policy asks for one request
per second, so a full sync fetches one explanation per second and sends a
User-Agent that names this project and its repository. A complete first
`sync --full` therefore takes about an hour. On-demand lookups are not
delayed.

## Terminal image support

| Terminal                     | Protocol | Status                    |
| ---------------------------- | -------- | ------------------------- |
| kitty, Ghostty               | kitty    | works                     |
| WezTerm, foot, iTerm2        | sixel    | works                     |
| Windows Terminal 1.22+       | sixel    | works                     |
| VS Code terminal             | sixel    | enable `terminal.integrated.enableImages` |
| tmux                         | –        | falls back to half-block unicode |
| GNOME Terminal, conhost      | –        | falls back to half-block unicode |

Detection and rendering are done by [textual-image](https://github.com/lnqs/textual-image).

## Development

```sh
git clone https://github.com/eivl/xkcdkit
cd xkcdkit
uv sync --all-groups
uv run pre-commit install
uv run pytest
uv run tox          # all supported Python versions
```

The code base is deliberately small: seven modules, short functions, a
docstring on everything. ruff (with pydocstyle), mypy strict, flake8 and
zizmor run in pre-commit and in CI.

### Releasing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
On every push to `main`, python-semantic-release reads the commit messages,
bumps the version in `pyproject.toml`, updates `CHANGELOG.md`, tags the
release and publishes to PyPI through trusted publishing. `feat:` bumps the
minor version, `fix:` the patch version, and a `BREAKING CHANGE:` footer the
major version.

Trusted publishing has to be registered once on PyPI under
*Publishing → Add a new pending publisher* with these values:

| Field            | Value          |
| ---------------- | -------------- |
| PyPI project     | `xkcdkit`      |
| Owner            | `eivl`         |
| Repository       | `xkcdkit`      |
| Workflow         | `release.yml`  |
| Environment      | `pypi`         |

and a GitHub environment named `pypi` must exist in the repository settings.

## License

MIT
