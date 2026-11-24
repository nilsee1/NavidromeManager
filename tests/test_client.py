"""Unit tests for Subsonic API client, authentication, and error handling."""

import hashlib
import urllib.parse
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
from nd_playlists.models import Playlist


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
def test_subsonic_api_error_malformed_code(sample_config: Config) -> None:
    """Verify malformed error code falls back to 0 without raising ValueError."""
    error_payload = {
        "subsonic-response": {
            "status": "failed",
            "version": "1.16.1",
            "error": {"code": "not_an_int", "message": "Some custom error"},
        }
    }
    respx.get(f"{sample_config.url}/rest/ping").respond(json=error_payload)

    with SubsonicClient(sample_config) as client:
        with pytest.raises(SubsonicAPIError) as exc_info:
            client.ping()

        assert exc_info.value.code == 0
        assert "Some custom error" in exc_info.value.message


@respx.mock
def test_subsonic_api_error_null_error_obj(sample_config: Config) -> None:
    """Verify status='failed' with null error object does not crash."""
    error_payload = {
        "subsonic-response": {
            "status": "failed",
            "version": "1.16.1",
            "error": None,
        }
    }
    respx.get(f"{sample_config.url}/rest/ping").respond(json=error_payload)

    with SubsonicClient(sample_config) as client:
        with pytest.raises(SubsonicAPIError) as exc_info:
            client.ping()

        assert exc_info.value.code == 0
        assert "Unknown Subsonic error" in exc_info.value.message


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
def test_http_redirect_handling(sample_config: Config, mock_subsonic_ping_response: dict) -> None:
    """Verify client follows HTTP 308 redirects automatically."""
    target_url = "https://navidrome.secure.local:4533/rest/ping"
    respx.get(f"{sample_config.url}/rest/ping").respond(
        status_code=308,
        headers={"Location": target_url},
    )
    respx.get(target_url).respond(json=mock_subsonic_ping_response)

    with SubsonicClient(sample_config) as client:
        info = client.ping()
        assert info["status"] == "ok"


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
def test_get_playlists_with_null_playlists_container(sample_config: Config) -> None:
    """Verify get_playlists handles 'playlists': null safely without TypeError."""
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1", "playlists": None}}
    )

    with SubsonicClient(sample_config) as client:
        playlists = client.get_playlists()
        assert playlists == []


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
def test_get_playlist_not_found_on_null_response(sample_config: Config) -> None:
    """Verify get_playlist raises PlaylistNotFoundError when playlist object is null."""
    respx.get(f"{sample_config.url}/rest/getPlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1", "playlist": None}}
    )

    with SubsonicClient(sample_config) as client:
        with pytest.raises(PlaylistNotFoundError):
            client.get_playlist("non-existent-id")


@respx.mock
def test_delete_playlist_uses_post_and_form_data(sample_config: Config) -> None:
    """Verify delete_playlist issues POST request with x-www-form-urlencoded body."""
    route = respx.post(f"{sample_config.url}/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    with SubsonicClient(sample_config) as client:
        client.delete_playlist("pl-1")
        assert route.called
        request = route.calls.last.request
        assert request.method == "POST"
        body = urllib.parse.parse_qs(request.content.decode("utf-8"))
        assert body["id"] == ["pl-1"]
        assert body["u"] == [sample_config.user]
        assert "t" in body
        assert "s" in body


@respx.mock
def test_update_playlist_uses_post_and_form_data(sample_config: Config) -> None:
    """Verify update_playlist issues POST request with x-www-form-urlencoded body."""
    route = respx.post(f"{sample_config.url}/rest/updatePlaylist").respond(
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
        request = route.calls.last.request
        assert request.method == "POST"
        body = urllib.parse.parse_qs(request.content.decode("utf-8"))
        assert body["playlistId"] == ["pl-1"]
        assert body["name"] == ["New Name"]
        assert body["comment"] == ["Updated description"]
        assert body["public"] == ["true"]


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


@respx.mock
def test_resolve_playlist_with_passed_playlists_avoids_http_call(sample_config: Config) -> None:
    """Verify passing playlists to resolve_playlist avoids extra getPlaylists API calls (prevents N+1)."""
    route = respx.get(f"{sample_config.url}/rest/getPlaylists")

    preloaded = [
        Playlist(id="p1", name="Preloaded List 1"),
        Playlist(id="p2", name="Preloaded List 2"),
    ]

    with SubsonicClient(sample_config) as client:
        result = client.resolve_playlist("Preloaded List 2", playlists=preloaded)
        assert result.id == "p2"
        assert not route.called


@respx.mock
def test_get_song_found(sample_config: Config) -> None:
    """Verify get_song returns Track object when song exists."""
    song_payload = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "song": {
                "id": "trk-1",
                "title": "Song Title",
                "artist": "Artist Name",
                "album": "Album Name",
                "duration": 210,
                "path": "Artist/Album/01.mp3",
            },
        }
    }
    respx.get(f"{sample_config.url}/rest/getSong").respond(json=song_payload)

    with SubsonicClient(sample_config) as client:
        trk = client.get_song("trk-1")
        assert trk is not None
        assert trk.id == "trk-1"
        assert trk.title == "Song Title"
        assert trk.artist == "Artist Name"


@respx.mock
def test_get_song_error_70_returns_none(sample_config: Config) -> None:
    """Verify get_song returns None when Subsonic responds with error 70 (data not found)."""
    error_payload = {
        "subsonic-response": {
            "status": "failed",
            "version": "1.16.1",
            "error": {"code": 70, "message": "Song not found"},
        }
    }
    respx.get(f"{sample_config.url}/rest/getSong").respond(json=error_payload)

    with SubsonicClient(sample_config) as client:
        trk = client.get_song("non-existent-trk")
        assert trk is None


@respx.mock
def test_get_song_empty_returns_none(sample_config: Config) -> None:
    """Verify get_song returns None when song payload is empty or null."""
    empty_payload = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "song": None,
        }
    }
    respx.get(f"{sample_config.url}/rest/getSong").respond(json=empty_payload)

    with SubsonicClient(sample_config) as client:
        trk = client.get_song("empty-trk")
        assert trk is None


@respx.mock
def test_search_songs_success_and_variations(sample_config: Config) -> None:
    """Verify search_songs handles list of songs, single song, and null results."""
    # 1. Normal list response
    list_payload = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "searchResult3": {
                "song": [
                    {"id": "s1", "title": "Track 1", "artist": "Artist 1", "duration": 150},
                    {"id": "s2", "title": "Track 2", "artist": "Artist 2", "duration": 180},
                ]
            },
        }
    }
    route = respx.get(f"{sample_config.url}/rest/search3").respond(json=list_payload)

    with SubsonicClient(sample_config) as client:
        results = client.search_songs("query", count=10)
        assert len(results) == 2
        assert results[0].id == "s1"
        assert results[1].title == "Track 2"

    # 2. Single dict response
    single_payload = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "searchResult3": {
                "song": {"id": "s3", "title": "Only One", "artist": "Solo", "duration": 200}
            },
        }
    }
    route.respond(json=single_payload)
    with SubsonicClient(sample_config) as client:
        results = client.search_songs("solo")
        assert len(results) == 1
        assert results[0].id == "s3"

    # 3. Null response
    null_payload = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "searchResult3": {"song": None},
        }
    }
    route.respond(json=null_payload)
    with SubsonicClient(sample_config) as client:
        results = client.search_songs("nothing")
        assert results == []


@respx.mock
def test_create_playlist_small_and_large_chunking(sample_config: Config) -> None:
    """Verify create_playlist handles <= 100 tracks in one call and chunks > 100 tracks."""
    create_route = respx.post(f"{sample_config.url}/rest/createPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {
                    "id": "pl-new",
                    "name": "New Playlist",
                    "songCount": 100,
                    "duration": 2000,
                },
            }
        }
    )
    update_route = respx.post(f"{sample_config.url}/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )
    get_route = respx.get(f"{sample_config.url}/rest/getPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {
                    "id": "pl-new",
                    "name": "New Playlist",
                    "songCount": 150,
                    "duration": 3000,
                    "entry": [{"id": f"t-{i}", "title": f"Track {i}", "duration": 20} for i in range(150)],
                },
            }
        }
    )

    with SubsonicClient(sample_config) as client:
        # 1. <= 100 tracks: only createPlaylist called
        pl = client.create_playlist(name="New Playlist", song_ids=[f"t-{i}" for i in range(50)])
        assert pl.id == "pl-new"
        assert not update_route.called

        # 2. 150 tracks: createPlaylist (100) + updatePlaylist (50) + getPlaylist
        create_route.calls.clear()
        update_route.calls.clear()
        get_route.calls.clear()

        pl_large = client.create_playlist(name="New Playlist", song_ids=[f"t-{i}" for i in range(150)])
        assert create_route.called
        assert update_route.called
        assert get_route.called
        assert pl_large.song_count == 150

        # Check updatePlaylist request had songIdToAdd
        update_req = update_route.calls.last.request
        update_body = urllib.parse.parse_qs(update_req.content.decode("utf-8"))
        assert len(update_body["songIdToAdd"]) == 50


@respx.mock
def test_update_playlist_chunking_large(sample_config: Config) -> None:
    """Verify update_playlist chunks song_ids_to_add in batches of 100."""
    update_route = respx.post(f"{sample_config.url}/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    with SubsonicClient(sample_config) as client:
        # 250 tracks to add -> 3 POST calls (100, 100, 50)
        client.update_playlist(
            playlist_id="pl-1",
            name="Updated Name",
            song_ids_to_add=[f"id-{i}" for i in range(250)],
        )
        assert update_route.call_count == 3
        # First call has name and 100 songs
        first_body = urllib.parse.parse_qs(update_route.calls[0].request.content.decode("utf-8"))
        assert first_body["name"] == ["Updated Name"]
        assert len(first_body["songIdToAdd"]) == 100
        # Third call has remaining 50 songs
        third_body = urllib.parse.parse_qs(update_route.calls[2].request.content.decode("utf-8"))
        assert len(third_body["songIdToAdd"]) == 50

