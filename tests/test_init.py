"""Package-level tests."""

import xkcdkit


def test_version_is_set() -> None:
    """The package exposes a non-empty version string."""
    assert isinstance(xkcdkit.__version__, str)
    assert xkcdkit.__version__


def test_not_found_is_an_xkcd_error() -> None:
    """ComicNotFound can be caught as the base XKCDError."""
    assert issubclass(xkcdkit.ComicNotFound, xkcdkit.XKCDError)
