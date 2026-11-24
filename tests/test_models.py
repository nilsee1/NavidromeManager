"""Unit tests for data models, durations, safe int parsing, and serializers."""

from datetime import datetime, timezone
from nd_playlists.models import Playlist, Track, _safe_int, format_duration


def test_safe_int() -> None:
    """Verify _safe_int helper across various valid, empty, and malformed inputs."""
    assert _safe_int(None) is None
    assert _safe_int(None, default=0) == 0
    assert _safe_int("") is None
    assert _safe_int("   ", default=10) == 10
    assert _safe_int("42") == 42
    assert _safe_int(42) == 42
    assert _safe_int(42.9) == 42
    assert _safe_int("1/12") == 1
    assert _safe_int(" 05 / 20 ") == 5
    assert _safe_int("invalid") is None
    assert _safe_int("invalid", default=99) == 99


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
        "duration": "1414",
        "track": "6/12",
        "year": "1971",
        "genre": "Progressive Rock",
        "size": "50000000",
        "path": "Pink Floyd/Meddle/06 - Echoes.flac",
        "suffix": "flac",
    }
    track = Track.from_subsonic_dict(raw)
    assert track.id == "trk-1"
    assert track.title == "Echoes"
    assert track.artist == "Pink Floyd"
    assert track.display_artist == "Pink Floyd"
    assert track.duration == 1414
    assert track.track_number == 6
    assert track.year == 1971
    assert track.size == 50000000
    assert track.formatted_duration == "00:23:34"

    d = track.to_dict()
    assert d["title"] == "Echoes"
    assert d["formattedDuration"] == "00:23:34"
    assert d["trackNumber"] == 6
    assert d["year"] == 1971
    assert d["size"] == 50000000
    assert d["suffix"] == "flac"


def test_track_parsing_malformed_integer_fields() -> None:
    """Verify Track handles empty or invalid integer fields without crashing."""
    raw = {
        "id": "trk-2",
        "title": "Minimal",
        "duration": "",
        "track": "invalid",
        "year": None,
        "size": "",
    }
    track = Track.from_subsonic_dict(raw)
    assert track.duration == 0
    assert track.track_number is None
    assert track.year is None
    assert track.size is None


def test_playlist_parsing_and_null_entries() -> None:
    """Verify Playlist handles 'entry': null and null counts gracefully."""
    raw = {
        "id": "pl-null",
        "name": "Empty List",
        "entry": None,
        "songCount": "",
        "duration": None,
    }
    playlist = Playlist.from_subsonic_dict(raw)
    assert playlist.id == "pl-null"
    assert playlist.name == "Empty List"
    assert playlist.tracks == []
    assert playlist.song_count == 0
    assert playlist.duration == 0


def test_playlist_formatted_changed_timezone_conversion() -> None:
    """Verify formatted_changed converts timezone-aware ISO-8601 timestamps to local time."""
    # Create a playlist with a fixed UTC timestamp
    iso_utc = "2024-06-15T12:30:00Z"
    playlist = Playlist(id="p1", name="Test", changed=iso_utc)

    # Compute expected local time representation
    dt_utc = datetime(2024, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
    expected_local = dt_utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")

    assert playlist.formatted_changed == expected_local


def test_playlist_to_m3u8_newline_and_slash_sanitization() -> None:
    """Verify to_m3u8() sanitizes newlines from names/artists and slashes from fallback filenames."""
    playlist = Playlist(
        id="pl-m3u8",
        name="Summer\r\nVibes\nMix",
        tracks=[
            Track(
                id="t1",
                title="Sunny\nDay",
                artist="Artist\r\nOne",
                duration=180,
                path="Music/Summer/Sunny Day.mp3",
            ),
            Track(
                id="t2",
                title="Track/With/Slashes",
                artist="AC/DC",
                duration=200,
                path=None,  # Will use fallback filename
                suffix="flac",
            ),
        ],
    )

    m3u8 = playlist.to_m3u8()
    lines = m3u8.strip().split("\n")

    # Header and playlist name on single line without internal newlines
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#PLAYLIST:Summer Vibes Mix"

    # Track 1: path preserved, artist and title cleaned
    assert lines[2] == "#EXTINF:180,Artist One - Sunny Day"
    assert lines[3] == "Music/Summer/Sunny Day.mp3"

    # Track 2: fallback filename has slashes converted to underscores
    assert lines[4] == "#EXTINF:200,AC/DC - Track/With/Slashes"
    assert lines[5] == "AC_DC - Track_With_Slashes.flac"
    assert "/" not in lines[5]
    assert "\\" not in lines[5]


def test_playlist_to_dict_metadata() -> None:
    """Verify to_dict() adds schemaVersion: 1 and exportedAt timestamp."""
    playlist = Playlist(
        id="pl-test",
        name="Test Playlist",
        comment="Comment",
        owner="testuser",
        public=True,
        tracks=[
            Track(id="t1", title="Song 1", duration=120),
        ],
    )
    d = playlist.to_dict()
    assert d["schemaVersion"] == 1
    assert "exportedAt" in d
    assert d["id"] == "pl-test"
    assert d["name"] == "Test Playlist"
    assert d["comment"] == "Comment"
    assert d["owner"] == "testuser"
    assert d["public"] is True
    assert len(d["tracks"]) == 1
    assert d["tracks"][0]["title"] == "Song 1"


def test_playlist_from_export_dict_modern_and_legacy() -> None:
    """Verify from_export_dict() parses both modern schema v1 and legacy backups."""
    modern_data = {
        "schemaVersion": 1,
        "exportedAt": "2024-01-01T00:00:00Z",
        "id": "pl-mod",
        "name": "Modern Playlist",
        "comment": "Nice songs",
        "owner": "user1",
        "public": True,
        "songCount": 1,
        "duration": 240,
        "tracks": [
            {
                "id": "trk-1",
                "title": "Title 1",
                "artist": "Artist 1",
                "album": "Album 1",
                "duration": 240,
                "trackNumber": 3,
                "year": 2020,
                "path": "Artist 1/Album 1/03 Title 1.mp3",
            }
        ],
    }
    pl = Playlist.from_export_dict(modern_data)
    assert pl.id == "pl-mod"
    assert pl.name == "Modern Playlist"
    assert pl.comment == "Nice songs"
    assert pl.owner == "user1"
    assert pl.public is True
    assert pl.song_count == 1
    assert pl.duration == 240
    assert len(pl.tracks) == 1
    assert pl.tracks[0].title == "Title 1"
    assert pl.tracks[0].track_number == 3

    # Legacy backup without schemaVersion and with string boolean public
    legacy_data = {
        "id": "pl-leg",
        "name": "Legacy Playlist",
        "public": "true",
        "tracks": [
            {
                "id": "trk-leg",
                "title": "Legacy Song",
                "track": 1,
            }
        ],
    }
    pl_leg = Playlist.from_export_dict(legacy_data)
    assert pl_leg.id == "pl-leg"
    assert pl_leg.name == "Legacy Playlist"
    assert pl_leg.public is True
    assert len(pl_leg.tracks) == 1
    assert pl_leg.tracks[0].track_number == 1

