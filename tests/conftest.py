"""Shared pytest fixtures and mock responses."""

import pytest
from nd_playlists.config import Config


@pytest.fixture
def sample_config() -> Config:
    """Fixture providing a standard test Config."""
    return Config(
        url="http://navidrome.local:4533",
        user="testuser",
        password="secretpassword",
        timeout=5.0,
    )


@pytest.fixture
def mock_subsonic_ping_response() -> dict:
    """Sample successful ping response."""
    return {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "type": "navidrome",
            "serverVersion": "0.51.0",
            "openSubsonic": True,
        }
    }


@pytest.fixture
def mock_subsonic_playlists_response() -> dict:
    """Sample getPlaylists response with multiple playlists."""
    return {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "playlists": {
                "playlist": [
                    {
                        "id": "pl-1",
                        "name": "Rock Anthems",
                        "comment": "Best 70s and 80s rock",
                        "owner": "testuser",
                        "public": True,
                        "songCount": 2,
                        "duration": 500,
                        "created": "2024-01-01T10:00:00Z",
                        "changed": "2024-01-02T12:00:00Z",
                    },
                    {
                        "id": "pl-2",
                        "name": "Empty Draft",
                        "comment": None,
                        "owner": "testuser",
                        "public": False,
                        "songCount": 0,
                        "duration": 0,
                        "created": "2024-01-03T10:00:00Z",
                        "changed": "2024-01-03T10:00:00Z",
                    },
                    {
                        "id": "pl-3",
                        "name": "Chill Beats",
                        "comment": "Lofi hip hop",
                        "owner": "otheruser",
                        "public": True,
                        "songCount": 1,
                        "duration": 180,
                        "created": "2024-01-04T10:00:00Z",
                        "changed": "2024-01-04T10:00:00Z",
                    },
                    {
                        "id": "pl-4",
                        "name": "Duplicate Name",
                        "owner": "testuser",
                        "songCount": 1,
                        "duration": 200,
                    },
                    {
                        "id": "pl-5",
                        "name": "Duplicate Name",
                        "owner": "otheruser",
                        "songCount": 3,
                        "duration": 600,
                    },
                ]
            },
        }
    }


@pytest.fixture
def mock_subsonic_playlist_details_response() -> dict:
    """Sample getPlaylist response with tracklist."""
    return {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "playlist": {
                "id": "pl-1",
                "name": "Rock Anthems",
                "comment": "Best 70s and 80s rock",
                "owner": "testuser",
                "public": True,
                "songCount": 2,
                "duration": 500,
                "created": "2024-01-01T10:00:00Z",
                "changed": "2024-01-02T12:00:00Z",
                "entry": [
                    {
                        "id": "track-101",
                        "title": "Bohemian Rhapsody",
                        "artist": "Queen",
                        "album": "A Night at the Opera",
                        "duration": 354,
                        "track": 11,
                        "year": 1975,
                        "genre": "Rock",
                        "path": "Queen/A Night at the Opera/11 - Bohemian Rhapsody.flac",
                        "suffix": "flac",
                    },
                    {
                        "id": "track-102",
                        "title": "Hotel California",
                        "artist": "Eagles",
                        "album": "Hotel California",
                        "duration": 391,
                        "track": 1,
                        "year": 1976,
                        "genre": "Classic Rock",
                        "path": "Eagles/Hotel California/01 - Hotel California.mp3",
                        "suffix": "mp3",
                    },
                ],
            },
        }
    }
