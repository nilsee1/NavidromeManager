"""Unit tests for configuration loading and validation."""

import pytest
from nd_playlists.config import ConfigError, load_config


def test_load_config_from_explicit_args() -> None:
    """Verify loading configuration directly from CLI arguments."""
    config = load_config(
        url="http://navidrome.example.com:4533/",
        user="custom_user",
        password="custom_password",
        timeout=15.0,
    )
    assert config.url == "http://navidrome.example.com:4533"
    assert config.user == "custom_user"
    assert config.password == "custom_password"
    assert config.timeout == 15.0


def test_load_config_adds_scheme_if_missing() -> None:
    """Verify load_config automatically prepends http:// if missing."""
    config = load_config(
        url="navidrome.local:4533",
        user="user",
        password="pass",
    )
    assert config.url == "http://navidrome.local:4533"


def test_load_config_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading configuration from environment variables."""
    monkeypatch.setenv("NAVIDROME_URL", "https://music.home.arpa")
    monkeypatch.setenv("NAVIDROME_USER", "env_user")
    monkeypatch.setenv("NAVIDROME_PASSWORD", "env_secret")

    config = load_config()
    assert config.url == "https://music.home.arpa"
    assert config.user == "env_user"
    assert config.password == "env_secret"


def test_cli_overrides_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CLI arguments take precedence over environment variables."""
    monkeypatch.setenv("NAVIDROME_URL", "https://music.home.arpa")
    monkeypatch.setenv("NAVIDROME_USER", "env_user")
    monkeypatch.setenv("NAVIDROME_PASSWORD", "env_secret")

    config = load_config(url="http://cli-override:4533", user="cli_user")
    assert config.url == "http://cli-override:4533"
    assert config.user == "cli_user"
    assert config.password == "env_secret"


def test_missing_config_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify missing required settings raise ConfigError."""
    monkeypatch.delenv("NAVIDROME_URL", raising=False)
    monkeypatch.delenv("NAVIDROME_USER", raising=False)
    monkeypatch.delenv("NAVIDROME_PASSWORD", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_config()

    error_msg = str(exc_info.value)
    assert "NAVIDROME_URL" in error_msg
    assert "NAVIDROME_USER" in error_msg
    assert "NAVIDROME_PASSWORD" in error_msg
