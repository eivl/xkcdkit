"""Tests for the Comic model and the wikitext cleaner."""

from datetime import date
from typing import Any

from xkcdkit.models import ArchiveEntry, Comic, wikitext_to_text


def test_comic_parses_xkcd_json(comic_json: dict[str, Any]) -> None:
    """Every field from the xkcd JSON lands on the model."""
    comic = Comic.model_validate(comic_json)
    assert comic.num == 614
    assert comic.title == "Woodpecker"
    assert comic.safe_title == "Woodpecker"
    assert comic.img == "https://imgs.xkcd.com/comics/woodpecker.png"
    assert comic.alt.startswith("If you don't have an extension cord")
    assert comic.link == ""
    assert comic.news == ""


def test_comic_coerces_date_parts(comic_json: dict[str, Any]) -> None:
    """Year, month and day arrive as strings and become integers."""
    comic = Comic.model_validate(comic_json)
    assert (comic.year, comic.month, comic.day) == (2009, 7, 24)
    assert comic.date == date(2009, 7, 24)


def test_comic_url(comic_json: dict[str, Any]) -> None:
    """The comic knows its own page URL."""
    assert Comic.model_validate(comic_json).url == "https://xkcd.com/614/"


def test_comic_accepts_empty_transcript_and_unicode(comic_json: dict[str, Any]) -> None:
    """Newer comics have an empty transcript; titles may contain unicode."""
    comic = Comic.model_validate({**comic_json, "transcript": "", "title": "Ünïcode ✓"})
    assert comic.transcript == ""
    assert comic.title == "Ünïcode ✓"


def test_comic_explanation_defaults(comic_json: dict[str, Any]) -> None:
    """Without explainxkcd data the explanation fields are empty, not missing."""
    comic = Comic.model_validate(comic_json)
    assert comic.explanation is None
    assert comic.explanation_revid is None
    assert comic.explanation_missing is False
    assert comic.synced_at is None
    assert comic.explanation_text == ""


def test_comic_explanation_text_uses_cleaner(comic_json: dict[str, Any], wikitext: str) -> None:
    """explanation_text is the plain-text Explanation section."""
    comic = Comic.model_validate({**comic_json, "explanation": wikitext})
    assert comic.explanation_text.startswith("Beret Guy observes a woodpecker.")


def test_archive_entry() -> None:
    """Archive entries parse ISO dates."""
    entry = ArchiveEntry(num=614, date="2009-7-24", title="Woodpecker")
    assert entry.date == date(2009, 7, 24)


def test_wikitext_keeps_only_explanation_section(wikitext: str) -> None:
    """Text stops before the Transcript heading."""
    text = wikitext_to_text(wikitext)
    assert "Transcript" not in text
    assert "{{comic" not in text
    assert text.endswith("friends.") or text.endswith(".")


def test_wikitext_strips_links_and_templates() -> None:
    """Wiki links, Wikipedia templates and bold markup become plain words."""
    src = (
        "==Explanation==\n"
        "{{incomplete|Created by a BOT. Do not remove.}}\n"
        "[[Beret Guy]] sees a {{w|woodpecker}} with '''drills'''.{{Citation needed}} "
        "See [[Megan|her]] and <ref>a source</ref> done.\n"
        "==Transcript==\n:ignored"
    )
    assert wikitext_to_text(src) == "Beret Guy sees a woodpecker with drills. See her and done."


def test_wikitext_handles_nested_templates() -> None:
    """Nested braces are removed completely, leaving no stray braces."""
    src = "==Explanation==\nA {{w|bird|{{nested}} thing}} sings."
    text = wikitext_to_text(src)
    assert "{" not in text
    assert "}" not in text
    assert text == "A thing sings." or text == "A bird sings."


def test_wikitext_without_heading_returns_whole_text() -> None:
    """Pages without section headings are returned cleaned in full."""
    assert wikitext_to_text("Just ''italic'' text.") == "Just italic text."


def test_wikitext_empty() -> None:
    """Empty or None input gives an empty string."""
    assert wikitext_to_text("") == ""
    assert wikitext_to_text(None) == ""


def test_wikitext_page_without_explanation_section() -> None:
    """A sectioned page with no Explanation heading yields nothing."""
    assert wikitext_to_text("==Transcript==\n:Some lines") == ""


def test_wikitext_unknown_template_vanishes() -> None:
    """Templates other than {{w|...}} are dropped entirely."""
    assert wikitext_to_text("==Explanation==\nA {{citation needed}} claim.") == "A claim."


def test_archive_entry_accepts_date_objects() -> None:
    """The loose date validator passes real dates through."""
    entry = ArchiveEntry(num=1, date=date(2006, 1, 1), title="Barrel - Part 1")
    assert entry.date == date(2006, 1, 1)
