"""Subsonic / OpenSubsonic REST API Client."""

import hashlib
import secrets
from typing import Any, Optional
import httpx

from nd_playlists.config import Config
from nd_playlists.models import Playlist


class SubsonicError(Exception):
    """Base exception for Subsonic API errors."""
    pass


class SubsonicAPIError(SubsonicError):
    """Application-level error returned inside Subsonic JSON response."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"Subsonic error {code}: {message}")
        self.code = code
        self.message = message


class SubsonicConnectionError(SubsonicError):
    """Raised when connection to Navidrome / Subsonic server fails."""
    pass


class SubsonicTimeoutError(SubsonicError):
    """Raised when an API request times out."""
    pass


class PlaylistNotFoundError(SubsonicError):
    """Raised when a requested playlist does not exist."""
    pass


class PlaylistAmbiguityError(SubsonicError):
    """Raised when multiple playlists match a name query."""

    def __init__(self, identifier: str, matches: list[Playlist]) -> None:
        super().__init__(f"Multiple playlists found with name '{identifier}'")
        self.identifier = identifier
        self.matches = matches


class SubsonicClient:
    """Subsonic REST API client with modern MD5 token authentication."""

    API_VERSION = "1.16.1"
    CLIENT_NAME = "nd-playlists"

    def __init__(self, config: Config, http_client: Optional[httpx.Client] = None) -> None:
        self.config = config
        self._owns_client = http_client is None
        self.client = http_client or httpx.Client(timeout=config.timeout)

    def close(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "SubsonicClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _get_auth_params(self) -> dict[str, str]:
        """Generate cryptographically secure salt and MD5 token authentication parameters.

        Token calculation: t = md5(password + salt).hexdigest()
        """
        # Cryptographically secure random alphanumeric salt (at least 8 chars, here 32 hex chars)
        salt = secrets.token_hex(16)
        token = hashlib.md5((self.config.password + salt).encode("utf-8")).hexdigest()

        return {
            "u": self.config.user,
            "t": token,
            "s": salt,
            "v": self.API_VERSION,
            "c": self.CLIENT_NAME,
            "f": "json",
        }

    def _request(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Perform a GET request to <NAVIDROME_URL>/rest/<endpoint> and validate the response."""
        clean_endpoint = endpoint.strip().lstrip("/")
        url = f"{self.config.url}/rest/{clean_endpoint}"

        query_params = self._get_auth_params()
        if params:
            for k, v in params.items():
                if v is not None:
                    query_params[k] = str(v)

        try:
            response = self.client.get(url, params=query_params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SubsonicTimeoutError(
                f"Request to '{endpoint}' timed out after {self.config.timeout:.1f}s."
            ) from exc
        except httpx.ConnectError as exc:
            raise SubsonicConnectionError(
                f"Unable to connect to Navidrome server at {self.config.url}."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SubsonicConnectionError(
                f"Server returned HTTP status {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise SubsonicConnectionError(
                f"Network communication error: {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise SubsonicAPIError(
                code=-1, message="Server response was not valid JSON."
            ) from exc

        subsonic_response = data.get("subsonic-response")
        if not isinstance(subsonic_response, dict):
            raise SubsonicAPIError(
                code=-1, message="Missing 'subsonic-response' envelope in API response."
            )

        status = subsonic_response.get("status")
        if status == "failed":
            error_data = subsonic_response.get("error", {})
            code = int(error_data.get("code", 0))
            message = error_data.get("message", "Unknown Subsonic error occurred.")
            raise SubsonicAPIError(code=code, message=message)

        if status != "ok":
            raise SubsonicAPIError(
                code=-1, message=f"Unexpected Subsonic API status: '{status}'"
            )

        return subsonic_response

    def ping(self) -> dict[str, Any]:
        """Call /rest/ping to verify connectivity and authentication."""
        resp = self._request("ping")
        return {
            "status": resp.get("status", "ok"),
            "version": resp.get("version", "unknown"),
            "type": resp.get("type", "navidrome"),
            "serverVersion": resp.get("serverVersion", "unknown"),
            "openSubsonic": resp.get("openSubsonic", False),
        }

    def get_playlists(self) -> list[Playlist]:
        """Fetch all playlists via /rest/getPlaylists."""
        resp = self._request("getPlaylists")
        playlists_container = resp.get("playlists", {})
        raw_list = playlists_container.get("playlist", [])
        if isinstance(raw_list, dict):
            raw_list = [raw_list]
        return [Playlist.from_subsonic_dict(item) for item in raw_list]

    def get_playlist(self, playlist_id: str) -> Playlist:
        """Fetch a single playlist with full tracklist via /rest/getPlaylist."""
        resp = self._request("getPlaylist", {"id": playlist_id})
        playlist_data = resp.get("playlist")
        if not playlist_data or not isinstance(playlist_data, dict):
            raise PlaylistNotFoundError(f"Playlist with ID '{playlist_id}' not found.")
        return Playlist.from_subsonic_dict(playlist_data)

    def delete_playlist(self, playlist_id: str) -> None:
        """Delete a playlist via /rest/deletePlaylist."""
        self._request("deletePlaylist", {"id": playlist_id})

    def update_playlist(
        self,
        playlist_id: str,
        name: Optional[str] = None,
        comment: Optional[str] = None,
        public: Optional[bool] = None,
    ) -> None:
        """Update playlist metadata via /rest/updatePlaylist."""
        params: dict[str, Any] = {"playlistId": playlist_id}
        if name is not None:
            params["name"] = name
        if comment is not None:
            params["comment"] = comment
        if public is not None:
            params["public"] = "true" if public else "false"

        self._request("updatePlaylist", params)

    def resolve_playlist(self, identifier: str) -> Playlist:
        """Resolve a playlist by exact ID first, or by case-insensitive exact name match.

        Raises:
            PlaylistAmbiguityError: When multiple playlists have the same matching name.
            PlaylistNotFoundError: When no matching playlist is found.
        """
        all_playlists = self.get_playlists()

        # 1. Check exact ID match
        for p in all_playlists:
            if p.id == identifier:
                return p

        # 2. Check case-insensitive exact name match
        ident_lower = identifier.strip().lower()
        name_matches = [p for p in all_playlists if p.name.strip().lower() == ident_lower]

        if len(name_matches) == 1:
            return name_matches[0]

        if len(name_matches) > 1:
            raise PlaylistAmbiguityError(identifier=identifier, matches=name_matches)

        raise PlaylistNotFoundError(
            f"No playlist found matching ID or name '{identifier}'."
        )
