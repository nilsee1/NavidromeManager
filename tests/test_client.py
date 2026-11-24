"""Unit tests for Subsonic API client, authentication, and error handling."""

import hashlib
import httpx
import pytest
import respx
from nd_playlists.client import (
    PlaylistAmbiguityError,
    PlaylistNotFoundError,
    SubsonicAPIError,
    SubsonicClient,
    SubsonicConnectionError,
    SubsonicTimeoutError,
)
from nd_playlists.config import Config


def test_auth_params_token_generation(sample_config: Config) -> None:
    """Verify cryptographically random salt and valid MD5 token calculation."""
    client = SubsonicClient(sample_config)
    params1 = client._get_auth_params()
    params2 = client._get_auth_params()

    # Per-request salt must be random and at least 8 chars
    assert len(params1["s"]) >= 8
    assert len(params2["s"]) >= 8
    assert params1["s"] != params2["s"]

    # Verify MD5 token calculation: md5(password + salt)
    expected_token1 = hashlib.md5((sample_config.password + params1["s"]).encode("utf-8")).hexdigest()
    assert params1["t"] == expected_token1
    assert params1["u"] == sample_config.user
    assert params1["v"] == "1.16.1"
    assert params1["c"] == "nd-playlists"
    assert params1["f"] == "json"


@respx.mock
def test_ping_success(sample_config: Config, mock_subsonic_ping_response: dict) -> None:
    """Verify successful ping request."""
    respx.get(f"{sample_config.url}/rest/ping").respond(json=mock_subsonic_ping_response)

    with SubsonicClient(sample_config) as client:
        info = client.ping()
        assert info["status"] == "ok"
        assert info["serverVersion"] == "0.51.0"
        assert info["openSubsonic"] is True


@respx.mock
def test_subsonic_api_error_response(sample_config: Config) -> None:
    """Verify Subsonic application errors (HTTP 200 with status='failed') raise SubsonicAPIError."""
    error_payload = {
        "subsonic-response": {
            "status": "failed",
            "version": "1.16.1",
            "error": {"code": 40, "message": "Wrong username or password"},
        }
    }
    respx.get(f"{sample_config.url}/rest/ping").respond(json=error_payload)

    with SubsonicClient(sample_config) as client:
        with pytest.raises(SubsonicAPIError) as exc_info:
            client.ping()

        assert exc_info.value.code == 40
        assert "Wrong username or password" in exc_info.value.message


@respx.mock
def test_connection_error(sample_config: Config) -> None:
    """Verify connection errors raise SubsonicConnectionError."""
    respx.get(f"{sample_config.url}/rest/ping").mock(side_effect=httpx.ConnectError("Connection refused"))

    with SubsonicClient(sample_config) as client:
        with pytest.raises(SubsonicConnectionError) as exc_info:
            client.ping()
        assert "Unable to connect" in str(exc_info.value)


@respx.mock
def test_timeout_error(sample_config: Config) -> None:
    """Verify request timeout raises SubsonicTimeoutError."""
    respx.get(f"{sample_config.url}/rest/ping").mock(side_effect=httpx.TimeoutException("Timed out"))

    with SubsonicClient(sample_config) as client:
        with pytest.raises(SubsonicTimeoutError) as exc_info:
            client.ping()
        assert "timed out" in str(exc_info.value)


@respx.mock
def test_get_playlists(sample_config: Config, mock_subsonic_playlists_response: dict) -> None:
    """Verify fetching and parsing all playlists."""
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    with SubsonicClient(sample_config) as client:
        playlists = client.get_playlists()
        assert len(playlists) == 5
        assert playlists[0].id == "pl-1"
        assert playlists[0].name == "Rock Anthems"
        assert playlists[1].song_count == 0


@respx.mock
def test_get_playlist_details(sample_config: Config, mock_subsonic_playlist_details_response: dict) -> None:
    """Verify fetching a single playlist with tracks."""
    respx.get(f"{sample_config.url}/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    with SubsonicClient(sample_config) as client:
        playlist = client.get_playlist("pl-1")
        assert playlist.id == "pl-1"
        assert len(playlist.tracks) == 2
        assert playlist.tracks[0].title == "Bohemian Rhapsody"
        assert playlist.tracks[1].artist == "Eagles"


@respx.mock
def test_delete_playlist(sample_config: Config) -> None:
    """Verify deleting a playlist."""
    route = respx.get(f"{sample_config.url}/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    with SubsonicClient(sample_config) as client:
        client.delete_playlist("pl-1")
        assert route.called
        assert route.calls.last.request.url.params["id"] == "pl-1"


@respx.mock
def test_update_playlist(sample_config: Config) -> None:
    """Verify updating playlist metadata."""
    route = respx.get(f"{sample_config.url}/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    with SubsonicClient(sample_config) as client:
        client.update_playlist(
            playlist_id="pl-1",
            name="New Name",
            comment="Updated description",
            public=True,
        )
        assert route.called
        params = route.calls.last.request.url.params
        assert params["playlistId"] == "pl-1"
        assert params["name"] == "New Name"
        assert params["comment"] == "Updated description"
        assert params["public"] == "true"


@respx.mock
def test_resolve_playlist_by_id(sample_config: Config, mock_subsonic_playlists_response: dict) -> None:
    """Verify resolving playlist by exact ID."""
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    with SubsonicClient(sample_config) as client:
        p = client.resolve_playlist("pl-1")
        assert p.id == "pl-1"
        assert p.name == "Rock Anthems"


@respx.mock
def test_resolve_playlist_by_name(sample_config: Config, mock_subsonic_playlists_response: dict) -> None:
    """Verify resolving playlist by case-insensitive name."""
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    with SubsonicClient(sample_config) as client:
        p = client.resolve_playlist("rock anthems")
        assert p.id == "pl-1"


@respx.mock
def test_resolve_playlist_ambiguity(sample_config: Config, mock_subsonic_playlists_response: dict) -> None:
    """Verify resolving ambiguous playlist name raises PlaylistAmbiguityError."""
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    with SubsonicClient(sample_config) as client:
        with pytest.raises(PlaylistAmbiguityError) as exc_info:
            client.resolve_playlist("Duplicate Name")

        assert len(exc_info.value.matches) == 2
        assert exc_info.value.identifier == "Duplicate Name"


@respx.mock
def test_resolve_playlist_not_found(sample_config: Config, mock_subsonic_playlists_response: dict) -> None:
    """Verify resolving non-existent playlist raises PlaylistNotFoundError."""
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    with SubsonicClient(sample_config) as client:
        with pytest.raises(PlaylistNotFoundError):
            client.resolve_playlist("Non-existent")
