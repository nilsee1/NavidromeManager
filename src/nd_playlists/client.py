"""Subsonic / OpenSubsonic REST API Client."""

import hashlib
import secrets
from typing import Any, Optional
import httpx

from nd_playlists.config import Config
from nd_playlists.models import Playlist, Track


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
        self.client = http_client or httpx.Client(timeout=config.timeout, follow_redirects=True)

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

    def _request(
        self,
        endpoint: str,
        params: Optional[dict[str, Any] | list[tuple[str, Any]]] = None,
        method: str = "GET",
    ) -> dict[str, Any]:
        """Perform an HTTP request to <NAVIDROME_URL>/rest/<endpoint> and validate the response."""
        clean_endpoint = endpoint.strip().lstrip("/")
        url = f"{self.config.url}/rest/{clean_endpoint}"

        payload_dict: dict[str, Any] = self._get_auth_params()
        payload_tuples: list[tuple[str, str]] = list(payload_dict.items())

        if params:
            if isinstance(params, dict):
                for k, v in params.items():
                    if v is None:
                        continue
                    if isinstance(v, (list, tuple)):
                        payload_dict[k] = [str(x) for x in v if x is not None]
                        for item in v:
                            if item is not None:
                                payload_tuples.append((k, str(item)))
                    else:
                        payload_dict[k] = str(v)
                        payload_tuples.append((k, str(v)))
            elif isinstance(params, (list, tuple)):
                for k, v in params:
                    if v is not None:
                        payload_tuples.append((k, str(v)))
                        if k in payload_dict:
                            if isinstance(payload_dict[k], list):
                                payload_dict[k].append(str(v))
                            else:
                                payload_dict[k] = [payload_dict[k], str(v)]
                        else:
                            payload_dict[k] = str(v)

        try:
            method_upper = method.upper()
            if method_upper == "POST":
                response = self.client.post(url, data=payload_dict)
            elif method_upper == "GET":
                response = self.client.get(url, params=payload_tuples)
            else:
                response = self.client.request(method_upper, url, params=payload_tuples)
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

        if not isinstance(data, dict):
            raise SubsonicAPIError(
                code=-1, message="Server response was not a valid JSON object."
            )

        subsonic_response = data.get("subsonic-response")
        if not isinstance(subsonic_response, dict):
            raise SubsonicAPIError(
                code=-1, message="Missing 'subsonic-response' envelope in API response."
            )

        status = subsonic_response.get("status")
        if status == "failed":
            error_data = subsonic_response.get("error") or {}
            raw_code = error_data.get("code", 0)
            try:
                code = int(raw_code)
            except (ValueError, TypeError):
                code = 0
            message = str(error_data.get("message") or "Unknown Subsonic error occurred.")
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
        playlists_container = resp.get("playlists") or {}
        raw_list = playlists_container.get("playlist") or []
        if isinstance(raw_list, dict):
            raw_list = [raw_list]
        return [Playlist.from_subsonic_dict(item) for item in raw_list if isinstance(item, dict)]

    def get_playlist(self, playlist_id: str) -> Playlist:
        """Fetch a single playlist with full tracklist via /rest/getPlaylist."""
        resp = self._request("getPlaylist", {"id": playlist_id})
        playlist_data = resp.get("playlist")
        if not playlist_data or not isinstance(playlist_data, dict):
            raise PlaylistNotFoundError(f"Playlist with ID '{playlist_id}' not found.")
        return Playlist.from_subsonic_dict(playlist_data)

    def delete_playlist(self, playlist_id: str) -> None:
        """Delete a playlist via /rest/deletePlaylist."""
        self._request("deletePlaylist", {"id": playlist_id}, method="POST")

    def get_song(self, song_id: str) -> Optional[Track]:
        """Fetch song details via /rest/getSong.

        Returns:
            Track if found, or None if Subsonic error 70 (not found) or empty song.
        """
        try:
            resp = self._request("getSong", {"id": song_id})
        except SubsonicAPIError as exc:
            if exc.code == 70:
                return None
            raise

        song_data = resp.get("song")
        if not song_data or not isinstance(song_data, dict) or not song_data.get("id"):
            return None
        return Track.from_subsonic_dict(song_data)

    def search_songs(self, query: str, count: int = 20) -> list[Track]:
        """Search songs via /rest/search3.

        Returns:
            List of matching Track objects.
        """
        params = {
            "query": query,
            "artistCount": 0,
            "albumCount": 0,
            "songCount": count,
        }
        resp = self._request("search3", params)
        search_res = resp.get("searchResult3") or resp.get("searchResult2") or {}
        raw_songs = search_res.get("song")
        if raw_songs is None:
            return []
        if isinstance(raw_songs, dict):
            raw_songs = [raw_songs]
        return [
            Track.from_subsonic_dict(item)
            for item in raw_songs
            if isinstance(item, dict) and item.get("id")
        ]

    def create_playlist(
        self,
        name: Optional[str] = None,
        playlist_id: Optional[str] = None,
        song_ids: Optional[list[str]] = None,
    ) -> Playlist:
        """Create a new playlist or replace an existing playlist's tracks via /rest/createPlaylist.

        Handles large playlists safely by creating/resetting with the first 100 songs,
        then appending remaining songs in chunks of 100 via update_playlist.
        """
        if not name and not playlist_id:
            raise SubsonicAPIError(code=-1, message="Either 'name' or 'playlist_id' must be provided.")

        params: dict[str, Any] = {}
        if playlist_id is not None:
            params["playlistId"] = playlist_id
        if name is not None:
            params["name"] = name

        all_song_ids = song_ids or []
        first_chunk = all_song_ids[:100]
        if first_chunk:
            params["songId"] = first_chunk

        resp = self._request("createPlaylist", params, method="POST")

        playlist_data = resp.get("playlist")
        target_id: Optional[str] = None
        if isinstance(playlist_data, dict) and playlist_data.get("id"):
            target_id = str(playlist_data["id"])
        elif playlist_id:
            target_id = playlist_id
        elif name:
            target = self.resolve_playlist(name)
            target_id = target.id

        if not target_id:
            raise SubsonicAPIError(code=-1, message="Could not determine created playlist ID.")

        if len(all_song_ids) > 100:
            remaining_chunks = all_song_ids[100:]
            self.update_playlist(playlist_id=target_id, song_ids_to_add=remaining_chunks)
            return self.get_playlist(target_id)

        if isinstance(playlist_data, dict) and playlist_data.get("id"):
            return Playlist.from_subsonic_dict(playlist_data)

        return self.get_playlist(target_id)

    def update_playlist(
        self,
        playlist_id: str,
        name: Optional[str] = None,
        comment: Optional[str] = None,
        public: Optional[bool] = None,
        song_ids_to_add: Optional[list[str]] = None,
    ) -> None:
        """Update playlist metadata and/or add songs via /rest/updatePlaylist."""
        base_params: dict[str, Any] = {"playlistId": playlist_id}
        if name is not None:
            base_params["name"] = name
        if comment is not None:
            base_params["comment"] = comment
        if public is not None:
            base_params["public"] = "true" if public else "false"

        if not song_ids_to_add:
            self._request("updatePlaylist", base_params, method="POST")
            return

        chunk_size = 100
        for i in range(0, len(song_ids_to_add), chunk_size):
            chunk = song_ids_to_add[i : i + chunk_size]
            params = dict(base_params) if i == 0 else {"playlistId": playlist_id}
            params["songIdToAdd"] = chunk
            self._request("updatePlaylist", params, method="POST")

    def resolve_playlist(
        self,
        identifier: str,
        playlists: Optional[list[Playlist]] = None,
    ) -> Playlist:
        """Resolve a playlist by exact ID first, or by case-insensitive exact name match.

        Raises:
            PlaylistAmbiguityError: When multiple playlists have the same matching name.
            PlaylistNotFoundError: When no matching playlist is found.
        """
        all_playlists = playlists if playlists is not None else self.get_playlists()

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
