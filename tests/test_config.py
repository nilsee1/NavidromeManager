"""Unit tests for configuration loading and validation."""

from pathlib import Path
import pytest
from nd_playlists.config import Config, ConfigError, load_config


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


def test_load_config_requires_explicit_scheme() -> None:
    """Verify load_config rejects URLs without explicit http:// or https://."""
    with pytest.raises(ConfigError) as exc_info:
        load_config(
            url="navidrome.local:4533",
            user="user",
            password="pass",
        )
    assert "explicitly start with 'http://' or 'https://'" in str(exc_info.value)


def test_load_config_requires_valid_hostname() -> None:
    """Verify load_config rejects URLs with invalid or missing hostname."""
    with pytest.raises(ConfigError) as exc_info:
        load_config(
            url="http://:4533",
            user="user",
            password="pass",
        )
    assert "valid hostname" in str(exc_info.value)


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


def test_whitespace_only_env_vars_trigger_missing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify whitespace-only URL and user are treated as missing after stripping."""
    monkeypatch.setenv("NAVIDROME_URL", "   ")
    monkeypatch.setenv("NAVIDROME_USER", "\t  \n")
    monkeypatch.setenv("NAVIDROME_PASSWORD", "valid_secret")

    with pytest.raises(ConfigError) as exc_info:
        load_config()

    error_msg = str(exc_info.value)
    assert "NAVIDROME_URL" in error_msg
    assert "NAVIDROME_USER" in error_msg
    assert "NAVIDROME_PASSWORD" not in error_msg


def test_password_preserves_spaces() -> None:
    """Verify password is not stripped so intentional leading/trailing spaces are preserved."""
    config = load_config(
        url="http://localhost:4533",
        user="testuser",
        password="  secret_with_spaces  ",
    )
    assert config.password == "  secret_with_spaces  "


def test_password_hidden_in_repr() -> None:
    """Verify password does not appear in repr(Config)."""
    config = Config(
        url="http://localhost:4533",
        user="testuser",
        password="supersecretpassword",
        timeout=10.0,
    )
    repr_str = repr(config)
    assert "supersecretpassword" not in repr_str
    assert "password=" not in repr_str
    assert "testuser" in repr_str
    assert "http://localhost:4533" in repr_str


def test_timeout_validation() -> None:
    """Verify timeout <= 0 raises ConfigError."""
    with pytest.raises(ConfigError) as exc_0:
        load_config(
            url="http://localhost:4533",
            user="testuser",
            password="pwd",
            timeout=0,
        )
    assert "greater than 0" in str(exc_0.value)

    with pytest.raises(ConfigError) as exc_neg:
        load_config(
            url="http://localhost:4533",
            user="testuser",
            password="pwd",
            timeout=-2.5,
        )
    assert "greater than 0" in str(exc_neg.value)


def test_custom_env_file(tmp_path: Path) -> None:
    """Verify loading from a custom .env file."""
    custom_env = tmp_path / "custom.env"
    custom_env.write_text(
        "NAVIDROME_URL=https://custom.navidrome.org\n"
        "NAVIDROME_USER=custom_env_user\n"
        "NAVIDROME_PASSWORD=custom_env_pwd\n",
        encoding="utf-8",
    )

    config = load_config(env_file=custom_env)
    assert config.url == "https://custom.navidrome.org"
    assert config.user == "custom_env_user"
    assert config.password == "custom_env_pwd"
