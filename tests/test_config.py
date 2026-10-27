"""Tests for the settings file."""

from pathlib import Path

import pytest

from xkcdkit import XKCDError
from xkcdkit.config import DEFAULT_TOML, Settings, config_path, dump, load_settings, write_default


def test_config_path_honours_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """XKCDKIT_CONFIG overrides the platform config directory."""
    monkeypatch.setenv("XKCDKIT_CONFIG", str(tmp_path / "c.toml"))
    assert config_path() == tmp_path / "c.toml"


def test_config_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the override the file is config.toml in a directory named xkcdkit."""
    monkeypatch.delenv("XKCDKIT_CONFIG", raising=False)
    path = config_path()
    assert path.name == "config.toml"
    assert "xkcdkit" in path.parts


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    """No file means built-in defaults."""
    settings = load_settings(tmp_path / "none.toml")
    assert settings == Settings()
    assert settings.image.scale == 1.0
    assert settings.image.fit is False
    assert settings.tui.image_pane == 2
    assert settings.cli.margin == 1


def test_partial_file_overrides_only_what_it_sets(tmp_path: Path) -> None:
    """Keys not in the file keep their defaults."""
    path = tmp_path / "config.toml"
    path.write_text("[image]\nscale = 3\n[tui]\nimage_pane = 4\n", encoding="utf-8")
    settings = load_settings(path)
    assert settings.image.scale == 3.0
    assert settings.image.fit is False
    assert settings.tui.image_pane == 4


def test_invalid_values_are_reported(tmp_path: Path) -> None:
    """A bad value or broken TOML raises XKCDError naming the file."""
    path = tmp_path / "config.toml"
    path.write_text("[image]\nscale = -2\n", encoding="utf-8")
    with pytest.raises(XKCDError, match=r"config\.toml"):
        load_settings(path)
    path.write_text("not = = toml", encoding="utf-8")
    with pytest.raises(XKCDError, match=r"config\.toml"):
        load_settings(path)


def test_write_default_creates_commented_file_once(tmp_path: Path) -> None:
    """write_default creates the file with every key and never overwrites it."""
    path = tmp_path / "deep" / "config.toml"
    assert write_default(path) is True
    text = path.read_text(encoding="utf-8")
    assert "scale" in text
    assert "fit" in text
    assert "image_pane" in text
    assert load_settings(path) == Settings()
    path.write_text("[image]\nscale = 5\n", encoding="utf-8")
    assert write_default(path) is False
    assert load_settings(path).image.scale == 5.0


def test_dump_is_valid_toml_that_round_trips() -> None:
    """dump() renders every section and key as TOML that loads back to the same settings."""
    import tomllib

    settings = Settings.model_validate({"image": {"scale": 2.5, "fit": True}, "cli": {"margin": 0}})
    text = dump(settings)
    assert "[image]" in text
    assert "scale = 2.5" in text
    assert "fit = true" in text
    assert "margin = 0" in text
    assert Settings.model_validate(tomllib.loads(text)) == settings


def test_default_toml_matches_the_defaults() -> None:
    """The commented default file and the model defaults never drift apart."""
    import tomllib

    assert Settings.model_validate(tomllib.loads(DEFAULT_TOML)) == Settings()
