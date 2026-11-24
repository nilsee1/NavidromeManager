"""Unit tests for data models, durations, and serializers."""

from nd_playlists.models import Playlist, Track, format_duration


def test_format_duration() -> None:
    """Test format_duration across various inputs."""
    assert format_duration(0) == "00:00:00"
    assert format_duration(None) == "00:00:00"
    assert format_duration(-10) == "00:00:00"
    assert format_duration(45) == "00:00:45"
    assert format_duration(65) == "00:01:05"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(36000) == "10:00:00"


def test_track_parsing_and_serialization() -> None:
    """Verify Track parsing from Subsonic dict and serialization."""
    raw = {
        "id": "trk-1",
        "title": "Echoes",
        "artist": "Pink Floyd",
        "album": "Meddle",
        "duration": 1414,
        "track": 6,
        "year": 1971,
        "genre": "Progressive Rock",
        "path": "Pink Floyd/Meddle/06 - Echoes.flac",
        "suffix": "flac",
    }
    track = Track.from_subsonic_dict(raw)
    assert track.id == "trk-1"
    assert track.title == "Echoes"
    assert track.artist == "Pink Floyd"
    assert track.display_artist == "Pink Floyd"
    assert track.formatted_duration == "00:23:34"

    d = track.to_dict()
    assert d["title"] == "Echoes"
    assert d["formattedDuration"] == "00:23:34"
    assert d["suffix"] == "flac"


def test_playlist_parsing_and_m3u8_generation() -> None:
    """Verify Playlist parsing and Extended M3U8 generation."""
    raw = {
        "id": "pl-test",
        "name": "Roadtrip",
        "comment": "Cruising tracks",
        "owner": "nils",
        "public": True,
        "songCount": 2,
        "duration": 500,
        "changed": "2024-05-10T14:30:00Z",
        "entry": [
            {
                "id": "t1",
                "title": "Song 1",
                "artist": "Artist 1",
                "duration": 200,
                "path": "Music/Artist 1/Song 1.mp3",
            },
            {
                "id": "t2",
                "title": "Song 2",
                "artist": "Artist 2",
                "duration": 300,
                "path": "Music/Artist 2/Song 2.mp3",
            },
        ],
    }
    playlist = Playlist.from_subsonic_dict(raw)
    assert playlist.id == "pl-test"
    assert playlist.name == "Roadtrip"
    assert playlist.public is True
    assert playlist.formatted_duration == "00:08:20"
    assert "2024-05-10" in playlist.formatted_changed
    assert len(playlist.tracks) == 2

    # Check M3U8 export
    m3u8 = playlist.to_m3u8()
    assert "#EXTM3U" in m3u8
    assert "#PLAYLIST:Roadtrip" in m3u8
    assert "#EXTINF:200,Artist 1 - Song 1" in m3u8
    assert "Music/Artist 1/Song 1.mp3" in m3u8
    assert "#EXTINF:300,Artist 2 - Song 2" in m3u8
    assert "Music/Artist 2/Song 2.mp3" in m3u8

    # Check JSON dict export
    p_dict = playlist.to_dict()
    assert p_dict["id"] == "pl-test"
    assert len(p_dict["tracks"]) == 2
