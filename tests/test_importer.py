"""Unit tests for playlist importer: parsers, track resolution, and import execution."""

import json
from pathlib import Path
import pytest
import respx
from nd_playlists.client import SubsonicClient
from nd_playlists.config import Config
from nd_playlists.importer import (
    ImportResult,
    ImportedPlaylist,
    ImportedTrack,
    InvalidPlaylistFileError,
    ResolutionCache,
    import_playlist,
    load_playlist_file,
    normalize_path,
    normalize_text,
    parse_json_playlist,
    parse_m3u8_playlist,
    path_matches,
    resolve_track,
)
from nd_playlists.models import Playlist, Track


def test_normalize_text_and_path() -> None:
    """Verify normalize_text strips diacritics, case-folds, and cleans punctuation."""
    assert normalize_text("Beyoncé - Halo (Remix)") == "beyonce halo remix"
    assert normalize_text("AC/DC: Back in Black!") == "ac dc back in black"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""

    # Path normalization
    assert normalize_path(r"Artist\Album\01 Track.flac") == "artist/album/01 track.flac"
    assert normalize_path("///music/artist/track.mp3///") == "music/artist/track.mp3"


def test_path_matches() -> None:
    """Verify path_matches handles exact equality, relative suffix, and Windows/Unix slashes."""
    assert path_matches("Artist/Album/01.flac", "artist/album/01.flac")
    assert path_matches(r"D:\Music\Artist\Album\01.flac", "Artist/Album/01.flac")
    assert path_matches("Artist/Album/01.flac", "/var/media/music/Artist/Album/01.flac")
    assert path_matches(r"E:\Music\Band\Song.mp3", r"Band\Song.mp3")
    assert not path_matches("ArtistA/Album/01.flac", "ArtistB/Album/01.flac")


def test_parse_json_playlist_valid_and_legacy(tmp_path: Path) -> None:
    """Verify parse_json_playlist parses modern and legacy json files."""
    valid_data = {
        "schemaVersion": 1,
        "name": "My Rock Mix",
        "comment": "Guitar solos",
        "public": True,
        "tracks": [
            {
                "id": "t-1",
                "title": "Stairway to Heaven",
                "artist": "Led Zeppelin",
                "album": "Led Zeppelin IV",
                "duration": 482,
                "path": "Led Zeppelin/Led Zeppelin IV/04 Stairway to Heaven.flac",
            }
        ],
    }
    json_file = tmp_path / "rock.json"
    json_file.write_text(json.dumps(valid_data), encoding="utf-8")

    pl = parse_json_playlist(json_file)
    assert pl.name == "My Rock Mix"
    assert pl.comment == "Guitar solos"
    assert pl.public is True
    assert len(pl.tracks) == 1
    assert pl.tracks[0].id == "t-1"
    assert pl.tracks[0].title == "Stairway to Heaven"
    assert pl.tracks[0].duration == 482

    # Legacy backup without schemaVersion
    legacy_data = {
        "id": "pl-leg",
        "name": "Old Backup",
        "tracks": [{"id": "t-old", "title": "Oldie"}],
    }
    legacy_file = tmp_path / "legacy.json"
    legacy_file.write_text(json.dumps(legacy_data), encoding="utf-8")
    leg_pl = parse_json_playlist(legacy_file)
    assert leg_pl.name == "Old Backup"
    assert len(leg_pl.tracks) == 1


def test_parse_json_playlist_malformed_and_missing_name(tmp_path: Path) -> None:
    """Verify parse_json_playlist raises InvalidPlaylistFileError on bad syntax or missing name."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(InvalidPlaylistFileError):
        parse_json_playlist(bad_json)

    missing_name = tmp_path / "noname.json"
    missing_name.write_text(json.dumps({"comment": "No name here"}), encoding="utf-8")
    with pytest.raises(InvalidPlaylistFileError):
        parse_json_playlist(missing_name)


def test_parse_m3u8_playlist_with_and_without_header(tmp_path: Path) -> None:
    """Verify parse_m3u8_playlist handles #PLAYLIST:, fallback to stem, and artist/title splitting."""
    content_with_header = """#EXTM3U
#PLAYLIST:Workout Hits
#EXTINF:215,Queen - Don't Stop Me Now
Queen/Jazz/Don't Stop Me Now.mp3
#EXTINF:180,Title Only No Artist
Pop/Track01.mp3
"""
    m3u8_file = tmp_path / "custom.m3u8"
    m3u8_file.write_text(content_with_header, encoding="utf-8")

    pl = parse_m3u8_playlist(m3u8_file)
    assert pl.name == "Workout Hits"
    assert len(pl.tracks) == 2
    assert pl.tracks[0].title == "Don't Stop Me Now"
    assert pl.tracks[0].artist == "Queen"
    assert pl.tracks[0].duration == 215
    assert pl.tracks[0].path == "Queen/Jazz/Don't Stop Me Now.mp3"

    assert pl.tracks[1].title == "Title Only No Artist"
    assert pl.tracks[1].artist is None
    assert pl.tracks[1].duration == 180

    # Without #PLAYLIST: header -> falls back to stem
    plain_content = """#EXTM3U
#EXTINF:200,Artist - Song
Song.mp3
"""
    fallback_file = tmp_path / "fallback_name.m3u8"
    fallback_file.write_text(plain_content, encoding="utf-8")
    pl_fallback = parse_m3u8_playlist(fallback_file)
    assert pl_fallback.name == "fallback_name"


def test_load_playlist_file_dispatch_and_unsupported(tmp_path: Path) -> None:
    """Verify load_playlist_file dispatches based on extension and rejects unsupported formats."""
    json_path = tmp_path / "test.json"
    json_path.write_text(json.dumps({"name": "Test", "tracks": []}), encoding="utf-8")
    assert load_playlist_file(json_path).name == "Test"

    m3u_path = tmp_path / "test.m3u"
    m3u_path.write_text("#EXTM3U\n#EXTINF:100,A - B\npath.mp3", encoding="utf-8")
    assert load_playlist_file(m3u_path).name == "test"

    unsupported = tmp_path / "test.txt"
    unsupported.write_text("hello", encoding="utf-8")
    with pytest.raises(InvalidPlaylistFileError):
        load_playlist_file(unsupported)


@respx.mock
def test_resolve_track_tier1_exact_id_hit(sample_config: Config) -> None:
    """Verify Tier 1 matches directly by ID with confidence 1.0."""
    respx.get(f"{sample_config.url}/rest/getSong").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "song": {"id": "song-123", "title": "Target Song", "artist": "Band", "duration": 200},
            }
        }
    )

    track = ImportedTrack(id="song-123", title="Target Song", artist="Band", duration=200)
    with SubsonicClient(sample_config) as client:
        res = resolve_track(client, track)
        assert res.method == "id"
        assert res.confidence == 1.0
        assert res.matched is not None
        assert res.matched.id == "song-123"


@respx.mock
def test_resolve_track_tier1_fallback_to_tier2_path(sample_config: Config) -> None:
    """Verify Tier 1 failure (e.g. error 70) falls back to Tier 2 path matching."""
    # getSong fails with 70
    respx.get(f"{sample_config.url}/rest/getSong").respond(
        json={
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "error": {"code": 70, "message": "Song not found"},
            }
        }
    )
    # search3 returns candidate with matching path
    respx.get(f"{sample_config.url}/rest/search3").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "searchResult3": {
                    "song": [
                        {
                            "id": "new-server-id",
                            "title": "Target Song",
                            "artist": "Band",
                            "duration": 200,
                            "path": "Band/Album/01 Target Song.flac",
                        }
                    ]
                },
            }
        }
    )

    track = ImportedTrack(
        id="old-server-id",
        title="Target Song",
        artist="Band",
        duration=200,
        path=r"D:\Music\Band\Album\01 Target Song.flac",
    )
    with SubsonicClient(sample_config) as client:
        res = resolve_track(client, track)
        assert res.method == "path"
        assert res.confidence == 1.0
        assert res.matched is not None
        assert res.matched.id == "new-server-id"


@respx.mock
def test_resolve_track_tier3_fuzzy_and_duration_tie_breaking(sample_config: Config) -> None:
    """Verify Tier 3 fuzzy metadata matching with duration tie-breaking."""
    # Source track has duration 180 (Radio edit)
    # Server has Radio edit (180s) and Album version (360s)
    respx.get(f"{sample_config.url}/rest/search3").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "searchResult3": {
                    "song": [
                        {
                            "id": "long-ver",
                            "title": "Epic Track",
                            "artist": "Rock Band",
                            "duration": 360,
                            "path": "path1.mp3",
                        },
                        {
                            "id": "radio-edit",
                            "title": "Epic Track",
                            "artist": "Rock Band",
                            "duration": 182,  # within 3 seconds
                            "path": "path2.mp3",
                        },
                    ]
                },
            }
        }
    )

    track = ImportedTrack(
        id=None,
        title="Epic Track (Single)",
        artist="Rock Band",
        duration=180,
    )
    with SubsonicClient(sample_config) as client:
        res = resolve_track(client, track, min_confidence=0.70)
        assert res.method == "metadata"
        assert res.matched is not None
        assert res.matched.id == "radio-edit"


@respx.mock
def test_resolve_track_unmatched_below_confidence(sample_config: Config) -> None:
    """Verify candidate below min_confidence results in method='unmatched'."""
    respx.get(f"{sample_config.url}/rest/search3").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "searchResult3": {
                    "song": [
                        {
                            "id": "diff-song",
                            "title": "Totally Different Track",
                            "artist": "Another Artist",
                            "duration": 200,
                        }
                    ]
                },
            }
        }
    )

    track = ImportedTrack(id=None, title="Target Title", artist="My Artist", duration=200)
    with SubsonicClient(sample_config) as client:
        res = resolve_track(client, track, min_confidence=0.80)
        assert res.method == "unmatched"
        assert res.matched is None


@respx.mock
def test_resolve_track_skip_id_lookup_and_cache(sample_config: Config) -> None:
    """Verify --skip-id-lookup skips Tier 1 and cache prevents duplicate API calls."""
    get_song_route = respx.get(f"{sample_config.url}/rest/getSong")
    search_route = respx.get(f"{sample_config.url}/rest/search3").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "searchResult3": {
                    "song": [{"id": "meta-id", "title": "Same Song", "artist": "Singer", "duration": 150}]
                },
            }
        }
    )

    track = ImportedTrack(id="id-should-be-skipped", title="Same Song", artist="Singer", duration=150)
    cache = ResolutionCache()

    with SubsonicClient(sample_config) as client:
        # First call with skip_id_lookup=True (queries both artist+title and title)
        res1 = resolve_track(client, track, cache=cache, skip_id_lookup=True)
        assert res1.matched is not None
        assert res1.matched.id == "meta-id"
        assert not get_song_route.called
        assert search_route.call_count == 2

        # Second call with same track uses cache (no additional HTTP requests)
        res2 = resolve_track(client, track, cache=cache, skip_id_lookup=True)
        assert res2.matched is not None
        assert res2.matched.id == "meta-id"
        assert search_route.call_count == 2


@respx.mock
def test_import_playlist_conflict_modes_and_dry_run(sample_config: Config, tmp_path: Path) -> None:
    """Verify all four conflict modes (skip, replace, append, rename) and dry-run."""
    existing_playlists_payload = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "playlists": {
                "playlist": [
                    {
                        "id": "pl-exist",
                        "name": "Favorites",
                        "owner": sample_config.user,
                        "songCount": 1,
                        "duration": 100,
                    }
                ]
            },
        }
    }
    respx.get(f"{sample_config.url}/rest/getPlaylists").respond(json=existing_playlists_payload)

    # getSong for track
    respx.get(f"{sample_config.url}/rest/getSong").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "song": {"id": "trk-10", "title": "Track 10", "duration": 100},
            }
        }
    )

    create_route = respx.post(f"{sample_config.url}/rest/createPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {"id": "pl-new-id", "name": "Created"},
            }
        }
    )
    update_route = respx.post(f"{sample_config.url}/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )
    get_pl_route = respx.get(f"{sample_config.url}/rest/getPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {
                    "id": "pl-exist",
                    "name": "Favorites",
                    "entry": [{"id": "trk-existing", "title": "Existing Track", "duration": 100}],
                },
            }
        }
    )

    imported_pl = ImportedPlaylist(
        name="Favorites",
        source_path=tmp_path / "fav.json",
        comment="Imported comment",
        public=True,
        tracks=[ImportedTrack(id="trk-10", title="Track 10", duration=100)],
    )

    with SubsonicClient(sample_config) as client:
        # 1. Dry run: zero POST requests made
        create_route.calls.clear()
        update_route.calls.clear()
        res_dry = import_playlist(client, imported_pl, on_conflict="replace", dry_run=True)
        assert res_dry.action == "dry-run"
        assert res_dry.matched_count == 1
        assert not create_route.called
        assert not update_route.called

        # 2. Conflict: skip
        res_skip = import_playlist(client, imported_pl, on_conflict="skip")
        assert res_skip.action == "skipped"
        assert res_skip.playlist_id == "pl-exist"
        assert not create_route.called

        # 3. Conflict: replace
        create_route.calls.clear()
        update_route.calls.clear()
        res_replace = import_playlist(client, imported_pl, on_conflict="replace")
        assert res_replace.action == "replaced"
        assert create_route.called
        assert update_route.called  # metadata restoration (comment, public)

        # 4. Conflict: append
        create_route.calls.clear()
        update_route.calls.clear()
        res_append = import_playlist(client, imported_pl, on_conflict="append")
        assert res_append.action == "appended"
        assert update_route.called
        assert res_append.matched_count == 1

        # 5. Conflict: rename
        create_route.calls.clear()
        update_route.calls.clear()
        res_rename = import_playlist(client, imported_pl, on_conflict="rename")
        assert res_rename.action == "renamed"
        assert res_rename.playlist_name == "Favorites (Imported)"
        assert create_route.called
