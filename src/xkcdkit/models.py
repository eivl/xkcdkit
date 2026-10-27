"""Data models for comics and archive entries, plus a wikitext cleaner."""

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
LINK = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
EXTERNAL_LINK = re.compile(r"\[\w+://\S+\s+([^\]]*)\]")
TAG = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<[^>]+>", re.DOTALL)
HEADING = re.compile(r"^==+\s*(.*?)\s*==+\s*$", re.MULTILINE)


class Comic(BaseModel):
    """One xkcd comic, as served by xkcd.com, with explainxkcd data attached.

    Field names match the xkcd JSON so the payload can be validated directly.
    The explanation fields are filled from explainxkcd when available.
    """

    model_config = ConfigDict(coerce_numbers_to_str=False)

    num: int
    title: str
    safe_title: str = ""
    alt: str = ""
    img: str = ""
    transcript: str = ""
    link: str = ""
    news: str = ""
    year: int
    month: int
    day: int
    explanation: str | None = None
    explanation_revid: int | None = None
    explanation_missing: bool = False
    synced_at: dt.datetime | None = None

    @property
    def date(self) -> dt.date:
        """Publication date assembled from year, month and day."""
        return dt.date(self.year, self.month, self.day)

    @property
    def url(self) -> str:
        """The comic's page on xkcd.com."""
        return f"https://xkcd.com/{self.num}/"

    @property
    def explanation_text(self) -> str:
        """The explainxkcd Explanation section as plain text, or empty."""
        return wikitext_to_text(self.explanation)


class ArchiveEntry(BaseModel):
    """One line of the xkcd archive page: number, date and title."""

    num: int
    date: dt.date = Field(description="Publication date.")
    title: str

    @field_validator("date", mode="before")
    @classmethod
    def parse_loose_date(cls, value: object) -> object:
        """Accept the archive's unpadded dates such as ``2009-7-24``."""
        if isinstance(value, str):
            year, month, day = (int(part) for part in value.split("-"))
            return dt.date(year, month, day)
        return value


def explanation_section(wikitext: str) -> str:
    """Return the body of the Explanation section, or the whole text if unsectioned."""
    headings = list(HEADING.finditer(wikitext))
    if not headings:
        return wikitext
    for index, heading in enumerate(headings):
        if heading.group(1).lower() == "explanation":
            end = headings[index + 1].start() if index + 1 < len(headings) else len(wikitext)
            return wikitext[heading.end() : end]
    return ""


def expand_template(match: re.Match[str]) -> str:
    """Replace a template: ``{{w|page|label}}`` becomes its label, others vanish."""
    parts = match.group(1).split("|")
    if parts[0].strip().lower() == "w" and len(parts) > 1:
        return parts[-1].strip()
    return ""


def wikitext_to_text(wikitext: str | None) -> str:
    """Reduce explainxkcd wikitext to readable plain text.

    Keeps only the Explanation section, drops templates and tags, turns links
    into their visible text and collapses whitespace into paragraphs.
    """
    if not wikitext:
        return ""
    text = explanation_section(wikitext)
    while TEMPLATE.search(text):
        text = TEMPLATE.sub(expand_template, text)
    text = TAG.sub("", text)
    text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = EXTERNAL_LINK.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)
