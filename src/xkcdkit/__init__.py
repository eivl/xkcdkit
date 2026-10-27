"""xkcd comics as a library, a CLI and a TUI, with a local cache.

Quick start::

    from xkcdkit import AsyncXKCD

    async with AsyncXKCD() as xk:
        comic = await xk.get(614)
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("xkcdkit")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"


class XKCDError(Exception):
    """Base class for every error raised by xkcdkit."""


class ComicNotFound(XKCDError):
    """Raised when xkcd has no comic with the requested number."""


LAZY = {
    "AsyncXKCD": "xkcdkit.client",
    "XKCD": "xkcdkit.client",
    "ArchiveEntry": "xkcdkit.models",
    "Comic": "xkcdkit.models",
}


def __getattr__(name: str) -> object:
    """Import the heavier submodules only when their names are first used."""
    if name in LAZY:
        module = __import__(LAZY[name], fromlist=[name])
        return getattr(module, name)
    raise AttributeError(f"module 'xkcdkit' has no attribute {name!r}")

__all__ = [
    "XKCD",
    "ArchiveEntry",
    "AsyncXKCD",
    "Comic",
    "ComicNotFound",
    "XKCDError",
    "__version__",
]
