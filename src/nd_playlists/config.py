"""Configuration management for nd-playlists."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when configuration validation or loading fails."""
    pass


@dataclass(frozen=True)
class Config:
    """Navidrome / Subsonic connection settings."""

    url: str
    user: str
    password: str
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

    resolved_url = url or os.getenv("NAVIDROME_URL")
    resolved_user = user or os.getenv("NAVIDROME_USER")
    resolved_password = password or os.getenv("NAVIDROME_PASSWORD")

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

    # Normalize URL: strip whitespace and trailing slashes
    clean_url = resolved_url.strip().rstrip("/")
    if not clean_url.startswith(("http://", "https://")):
        clean_url = f"http://{clean_url}"

    return Config(
        url=clean_url,
        user=resolved_user.strip(),
        password=resolved_password,
        timeout=max(1.0, float(timeout)),
    )
