"""User settings from a small TOML file in the platform config directory."""

import json
import os
import tomllib
from pathlib import Path
from typing import Annotated

from platformdirs import user_config_path
from pydantic import BaseModel, Field, ValidationError

from xkcdkit import XKCDError

DEFAULT_TOML = """# xkcdkit settings. Every key is optional; these are the defaults.

[image]
# CLI: multiply the image's natural terminal size (1 = as the terminal sizes it, 2 = twice as big).
scale = 1.0
# CLI: ignore scale and fill the terminal, keeping the aspect ratio.
fit = false

[tui]
# Height of the image pane relative to the text pane (1 to 8). Change live with + and -.
image_pane = 2

[cli]
# Blank space around a printed comic: lines above and below, twice as many columns
# left and right, and the same number of lines between the image and the text card.
# 0 gives a tight layout.
margin = 1
# Override single sides if you like; anything left unset follows margin.
# top = 1
# bottom = 1
# left = 2
# right = 2
# gap = 1
"""


class ImageSettings(BaseModel):
    """How the CLI draws images."""

    scale: float = Field(default=1.0, gt=0, le=16)
    fit: bool = False


class TuiSettings(BaseModel):
    """How the browser lays itself out."""

    image_pane: int = Field(default=2, ge=1, le=8)


Side = Annotated[int | None, Field(default=None, ge=0, le=16)]


class CliSettings(BaseModel):
    """How the command line lays out its output."""

    margin: int = Field(default=1, ge=0, le=8)
    top: Side = None
    bottom: Side = None
    left: Side = None
    right: Side = None
    gap: Side = None

    @property
    def padding(self) -> tuple[int, int, int, int]:
        """Blank space as (top, right, bottom, left); unset sides follow ``margin``."""
        top = self.margin if self.top is None else self.top
        bottom = self.margin if self.bottom is None else self.bottom
        left = self.margin * 2 if self.left is None else self.left
        right = self.margin * 2 if self.right is None else self.right
        return top, right, bottom, left

    @property
    def gap_lines(self) -> int:
        """Blank lines between the image and the text card; follows ``margin`` when unset."""
        return self.margin if self.gap is None else self.gap


class Settings(BaseModel):
    """All settings, mirroring the sections of the TOML file."""

    image: ImageSettings = ImageSettings()
    tui: TuiSettings = TuiSettings()
    cli: CliSettings = CliSettings()


def dump(settings: Settings) -> str:
    """Render settings as TOML text, one section per model."""
    lines: list[str] = []
    for section, values in settings.model_dump().items():
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in values.items() if value is not None)
        lines.append("")
    return "\n".join(lines)


def config_path() -> Path:
    """Settings file location: ``$XKCDKIT_CONFIG`` or the platform user config directory."""
    override = os.environ.get("XKCDKIT_CONFIG")
    if override:
        return Path(override)
    return user_config_path("xkcdkit") / "config.toml"


def load_settings(path: Path | None = None) -> Settings:
    """Read the settings file, falling back to defaults when it does not exist.

    Raises:
        XKCDError: when the file is not valid TOML or holds an invalid value.
    """
    path = path or config_path()
    if not path.exists():
        return Settings()
    try:
        return Settings.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise XKCDError(f"{path}: {exc}") from exc


def write_default(path: Path | None = None) -> bool:
    """Create the settings file with documented defaults. Returns False if it already exists."""
    path = path or config_path()
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    return True
