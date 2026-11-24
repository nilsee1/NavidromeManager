"""Configuration management for nd-playlists."""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional
import urllib.parse
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when configuration validation or loading fails."""
    pass


@dataclass(frozen=True)
class Config:
    """Navidrome / Subsonic connection settings."""

    url: str
    user: str
    password: str = field(repr=False)
    timeout: float = 10.0


def load_config(
    url: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 10.0,
    env_file: Optional[Path | str] = None,
) -> Config:
    """Load configuration from CLI arguments, environment variables, or .env file.

    Priority:
    1. Explicit CLI arguments (if provided)
    2. Environment variables / .env file
    """
    if env_file:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        # Load default .env from current directory or parents
        load_dotenv(override=False)

    raw_url = url if url is not None else os.getenv("NAVIDROME_URL")
    raw_user = user if user is not None else os.getenv("NAVIDROME_USER")
    resolved_password = password if password is not None else os.getenv("NAVIDROME_PASSWORD")

    resolved_url = raw_url.strip() if raw_url is not None else ""
    resolved_user = raw_user.strip() if raw_user is not None else ""

    missing = []
    if not resolved_url:
        missing.append("NAVIDROME_URL (--url / -u)")
    if not resolved_user:
        missing.append("NAVIDROME_USER (--user / -U)")
    if not resolved_password:
        missing.append("NAVIDROME_PASSWORD (--password / -P)")

    if missing:
        raise ConfigError(
            f"Missing required configuration: {', '.join(missing)}.\n"
            "Please provide them as CLI arguments or set them in a .env file."
        )

    # Validate timeout
    try:
        timeout_val = float(timeout)
    except (ValueError, TypeError):
        raise ConfigError(f"Invalid timeout '{timeout}': timeout must be a valid number.")

    if timeout_val <= 0:
        raise ConfigError(f"Invalid timeout '{timeout}': timeout must be greater than 0.")

    # Validate URL: explicitly require scheme (http:// or https://) and valid hostname
    clean_url = resolved_url.rstrip("/")
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        raise ConfigError(
            f"Invalid URL '{clean_url}': URL must explicitly start with 'http://' or 'https://'."
        )

    parsed = urllib.parse.urlparse(clean_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError(
            f"Invalid URL '{clean_url}': URL must include a valid hostname."
        )

    return Config(
        url=clean_url,
        user=resolved_user,
        password=resolved_password,
        timeout=timeout_val,
    )
