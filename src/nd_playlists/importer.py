"""Playlist file parsing, track resolution, and import execution engine."""

from dataclasses import dataclass, field
import difflib
import json
from pathlib import Path
import re
from typing import Any, Literal, Optional
import unicodedata

from nd_playlists.client import SubsonicClient
from nd_playlists.models import Playlist, Track, _safe_int


class PlaylistImportError(Exception):
    """Base exception for playlist import errors."""
    pass


class InvalidPlaylistFileError(PlaylistImportError):
    """Raised when a playlist file cannot be parsed or lacks required fields."""
    pass


@dataclass
class ImportedTrack:
    """Source track information extracted from import file."""

    title: str
    id: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: int = 0
    path: Optional[str] = None
    raw_uri: Optional[str] = None

    @property
    def display_artist(self) -> str:
        return self.artist or "Unknown Artist"

    @property
    def display_album(self) -> str:
        return self.album or "Unknown Album"


@dataclass
class ImportedPlaylist:
    """Parsed playlist representation before resolution against Navidrome."""

    name: str
    source_path: Path
    comment: Optional[str] = None
    public: bool = False
    tracks: list[ImportedTrack] = field(default_factory=list)


@dataclass
class TrackMatchResult:
    """Result of resolving an ImportedTrack against server library."""

    source: ImportedTrack
    matched: Optional[Track] = None
    method: Literal["id", "path", "metadata", "unmatched"] = "unmatched"
    confidence: float = 0.0


@dataclass
class ImportResult:
    """Summary of an executed or dry-run playlist import."""

    playlist_name: str
    action: Literal["created", "replaced", "appended", "renamed", "skipped", "dry-run"]
    playlist_id: Optional[str] = None
    matched_count: int = 0
    unmatched_tracks: list[ImportedTrack] = field(default_factory=list)
    match_breakdown: dict[str, int] = field(
        default_factory=lambda: {"id": 0, "path": 0, "metadata": 0, "unmatched": 0}
    )


@dataclass
class ResolutionCache:
    """In-memory cache for Subsonic track searches and resolutions across runs."""

    id_cache: dict[str, Optional[Track]] = field(default_factory=dict)
    search_cache: dict[str, list[Track]] = field(default_factory=dict)
    track_cache: dict[str, TrackMatchResult] = field(default_factory=dict)


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for fuzzy matching: strip diacritics, case-fold, collapse punctuation and spaces."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = stripped.lower()
    collapsed = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", collapsed).strip()


def normalize_path(path_str: Optional[str]) -> str:
    """Normalize file path for comparison: lowercase, forward slashes, stripped of leading/trailing slashes."""
    if not path_str:
        return ""
    p = path_str.replace("\\", "/").strip().strip("/")
    p = re.sub(r"/+", "/", p)
    return p.strip("/").lower()


def path_matches(source_path: str, candidate_path: str) -> bool:
    """Check if candidate path matches source path exactly or by relative suffix."""
    s_norm = normalize_path(source_path)
    c_norm = normalize_path(candidate_path)
    if not s_norm or not c_norm:
        return False
    if s_norm == c_norm:
        return True
    if c_norm.endswith("/" + s_norm):
        return True
    if s_norm.endswith("/" + c_norm):
        return True
    return False


def parse_json_playlist(path: Path) -> ImportedPlaylist:
    """Parse JSON playlist file exported by nd-playlists or backup files."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        raise InvalidPlaylistFileError(f"Failed to read '{path}': {exc}") from exc

    try:
        data = json.loads(content)
    except Exception as exc:
        raise InvalidPlaylistFileError(f"Invalid JSON in '{path}': {exc}") from exc

    if not isinstance(data, dict):
        raise InvalidPlaylistFileError(
            f"Expected JSON object in '{path}', got {type(data).__name__}."
        )

    name = data.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        raise InvalidPlaylistFileError(f"Missing required field 'name' in '{path}'.")

    raw_public = data.get("public", False)
    if isinstance(raw_public, str):
        public = raw_public.lower() in ("true", "1", "yes")
    else:
        public = bool(raw_public)

    raw_tracks = data.get("tracks")
    if raw_tracks is None:
        raw_tracks = data.get("entry") or []
    if isinstance(raw_tracks, dict):
        raw_tracks = [raw_tracks]

    imported_tracks: list[ImportedTrack] = []
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        trk_id = item.get("id")
        title = str(item.get("title") or "").strip()
        if not title:
            if item.get("path"):
                title = Path(item["path"]).stem
            else:
                title = "Unknown Title"
        dur = _safe_int(item.get("duration"), default=0)

        imported_tracks.append(
            ImportedTrack(
                id=str(trk_id) if trk_id is not None and str(trk_id).strip() else None,
                title=title,
                artist=item.get("artist"),
                album=item.get("album"),
                duration=dur if dur is not None else 0,
                path=item.get("path"),
                raw_uri=item.get("path"),
            )
        )

    return ImportedPlaylist(
        name=name.strip(),
        source_path=path,
        comment=data.get("comment"),
        public=public,
        tracks=imported_tracks,
    )


def parse_m3u8_playlist(path: Path) -> ImportedPlaylist:
    """Parse #EXTM3U / .m3u8 / .m3u playlist file."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
    except Exception as exc:
        raise InvalidPlaylistFileError(f"Failed to read '{path}': {exc}") from exc

    playlist_name = path.stem
    tracks: list[ImportedTrack] = []

    pending_duration = 0
    pending_artist: Optional[str] = None
    pending_title: Optional[str] = None
    has_extinf = False

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("#"):
            if line.startswith("#PLAYLIST:"):
                pname = line[len("#PLAYLIST:"):].strip()
                if pname:
                    playlist_name = pname
            elif line.startswith("#EXTINF:"):
                extinf_content = line[len("#EXTINF:"):].strip()
                if "," in extinf_content:
                    dur_part, info_part = extinf_content.split(",", 1)
                    dur_str = dur_part.split()[0].strip()
                    pending_duration = _safe_int(dur_str, default=0) or 0
                    info_part = info_part.strip()
                    if " - " in info_part:
                        pending_artist, pending_title = info_part.split(" - ", 1)
                        pending_artist = pending_artist.strip()
                        pending_title = pending_title.strip()
                    else:
                        pending_artist = None
                        pending_title = info_part.strip()
                else:
                    pending_duration = _safe_int(extinf_content, default=0) or 0
                    pending_artist = None
                    pending_title = None
                has_extinf = True
            # Ignore other # directives or comments
            continue

        # File path / URI line
        raw_uri = line
        if has_extinf:
            title = pending_title or Path(raw_uri).stem or "Unknown Title"
            artist = pending_artist
            duration = pending_duration
        else:
            title = Path(raw_uri).stem or "Unknown Title"
            artist = None
            duration = 0

        tracks.append(
            ImportedTrack(
                id=None,
                title=title,
                artist=artist,
                album=None,
                duration=duration,
                path=raw_uri,
                raw_uri=raw_uri,
            )
        )

        pending_duration = 0
        pending_artist = None
        pending_title = None
        has_extinf = False

    return ImportedPlaylist(
        name=playlist_name,
        source_path=path,
        comment=None,
        public=False,
        tracks=tracks,
    )


def load_playlist_file(path: Path) -> ImportedPlaylist:
    """Dispatch file loader based on extension (.json, .m3u8, .m3u)."""
    if not path.is_file():
        raise InvalidPlaylistFileError(f"Path '{path}' is not a valid file.")

    suffix = path.suffix.lower()
    if suffix == ".json":
        return parse_json_playlist(path)
    elif suffix in (".m3u8", ".m3u"):
        return parse_m3u8_playlist(path)
    else:
        raise InvalidPlaylistFileError(
            f"Unsupported playlist file format '{path.suffix}'. Supported formats: .json, .m3u8, .m3u"
        )


def resolve_track(
    client: SubsonicClient,
    track: ImportedTrack,
    cache: Optional[ResolutionCache] = None,
    min_confidence: float = 0.80,
    skip_id_lookup: bool = False,
) -> TrackMatchResult:
    """Resolve an ImportedTrack against server library using 3-tier matching."""
    if cache is None:
        cache = ResolutionCache()

    cache_key = (
        f"{track.id}|{track.title}|{track.artist}|{track.album}|"
        f"{track.path}|{track.duration}|{skip_id_lookup}|{min_confidence}"
    )
    if cache_key in cache.track_cache:
        cached = cache.track_cache[cache_key]
        return TrackMatchResult(
            source=track,
            matched=cached.matched,
            method=cached.method,
            confidence=cached.confidence,
        )

    # --- Tier 1 (Exact ID - JSON only) ---
    if track.id and not skip_id_lookup:
        song: Optional[Track] = None
        if track.id in cache.id_cache:
            song = cache.id_cache[track.id]
        else:
            try:
                song = client.get_song(track.id)
            except Exception:
                song = None
            cache.id_cache[track.id] = song

        if song is not None:
            res = TrackMatchResult(source=track, matched=song, method="id", confidence=1.0)
            cache.track_cache[cache_key] = res
            return res

    # --- Collect candidates for Tier 2 and Tier 3 ---
    def get_search_candidates(q: str) -> list[Track]:
        q_clean = q.strip()
        if not q_clean:
            return []
        if q_clean in cache.search_cache:
            return cache.search_cache[q_clean]
        try:
            results = client.search_songs(q_clean, count=20)
        except Exception:
            results = []
        cache.search_cache[q_clean] = results
        return results

    primary_query = track.title
    if not primary_query and track.path:
        primary_query = Path(track.path).stem

    candidates: list[Track] = []
    seen_cand_ids: set[str] = set()

    def add_candidates(cands: list[Track]) -> None:
        for c in cands:
            if c.id not in seen_cand_ids:
                seen_cand_ids.add(c.id)
                candidates.append(c)

    if track.artist and track.title:
        add_candidates(get_search_candidates(f"{track.artist} {track.title}"))

    if primary_query:
        add_candidates(get_search_candidates(primary_query))

    if not candidates and track.artist:
        add_candidates(get_search_candidates(track.artist))

    # --- Tier 2 (Path match) ---
    search_path = track.path or track.raw_uri
    if search_path:
        for cand in candidates:
            if cand.path and path_matches(search_path, cand.path):
                res = TrackMatchResult(source=track, matched=cand, method="path", confidence=1.0)
                cache.track_cache[cache_key] = res
                return res

    # --- Tier 3 (Metadata & fuzzy match) ---
    if candidates:
        norm_s_title = normalize_text(track.title)
        norm_s_artist = normalize_text(track.artist)
        norm_s_album = normalize_text(track.album)

        scored_candidates: list[tuple[float, float, Track]] = []

        for cand in candidates:
            norm_c_title = normalize_text(cand.title)
            norm_c_artist = normalize_text(cand.artist)
            norm_c_album = normalize_text(cand.album)

            title_ratio = difflib.SequenceMatcher(None, norm_s_title, norm_c_title).ratio()

            if norm_s_artist and norm_c_artist:
                artist_ratio = difflib.SequenceMatcher(None, norm_s_artist, norm_c_artist).ratio()
            elif not norm_s_artist and not norm_c_artist:
                artist_ratio = 1.0
            else:
                artist_ratio = 0.0

            score = (0.55 * title_ratio) + (0.35 * artist_ratio)

            if norm_s_album and norm_c_album:
                album_ratio = difflib.SequenceMatcher(None, norm_s_album, norm_c_album).ratio()
                if album_ratio >= 0.8:
                    score += 0.05

            dur_diff = float("inf")
            if track.duration > 0 and cand.duration > 0:
                dur_diff = abs(track.duration - cand.duration)
                if dur_diff <= 3:
                    score += 0.05

            score = min(score, 1.0)
            scored_candidates.append((score, dur_diff, cand))

        # Best score first, duration difference as tie-breaker
        scored_candidates.sort(key=lambda item: (-item[0], item[1]))

        best_score, _, best_cand = scored_candidates[0]
        if best_score >= min_confidence:
            res = TrackMatchResult(
                source=track, matched=best_cand, method="metadata", confidence=round(best_score, 4)
            )
            cache.track_cache[cache_key] = res
            return res

    # Unmatched
    res = TrackMatchResult(source=track, matched=None, method="unmatched", confidence=0.0)
    cache.track_cache[cache_key] = res
    return res


def import_playlist(
    client: SubsonicClient,
    imported: ImportedPlaylist,
    on_conflict: Literal["skip", "replace", "append", "rename"] = "skip",
    dry_run: bool = False,
    min_confidence: float = 0.80,
    skip_id_lookup: bool = False,
    allow_duplicates: bool = False,
    name_override: Optional[str] = None,
    cache: Optional[ResolutionCache] = None,
) -> ImportResult:
    """Execute playlist import workflow with conflict handling, track resolution, and dry-run."""
    if cache is None:
        cache = ResolutionCache()

    name = name_override if name_override is not None else imported.name

    # Check existing playlists owned by the authenticated user
    all_playlists = client.get_playlists()
    user_lower = client.config.user.lower()
    user_playlists = [p for p in all_playlists if p.owner and p.owner.lower() == user_lower]
    name_lower = name.strip().lower()
    matching_existing = [p for p in user_playlists if p.name.strip().lower() == name_lower]
    existing = matching_existing[0] if matching_existing else None

    # Track resolution
    matched_tracks: list[Track] = []
    unmatched_tracks: list[ImportedTrack] = []
    breakdown = {"id": 0, "path": 0, "metadata": 0, "unmatched": 0}

    for trk in imported.tracks:
        res = resolve_track(
            client=client,
            track=trk,
            cache=cache,
            min_confidence=min_confidence,
            skip_id_lookup=skip_id_lookup,
        )
        if res.matched:
            matched_tracks.append(res.matched)
            breakdown[res.method] = breakdown.get(res.method, 0) + 1
        else:
            unmatched_tracks.append(trk)
            breakdown["unmatched"] = breakdown.get("unmatched", 0) + 1

    matched_song_ids = [t.id for t in matched_tracks]

    # Dry-run returns without performing mutating API calls
    if dry_run:
        return ImportResult(
            playlist_name=name,
            action="dry-run",
            playlist_id=existing.id if existing else None,
            matched_count=len(matched_song_ids),
            unmatched_tracks=unmatched_tracks,
            match_breakdown=breakdown,
        )

    # Handle conflict if an existing playlist with the same name exists
    if existing:
        if on_conflict == "skip":
            return ImportResult(
                playlist_name=name,
                action="skipped",
                playlist_id=existing.id,
                matched_count=len(matched_song_ids),
                unmatched_tracks=unmatched_tracks,
                match_breakdown=breakdown,
            )

        elif on_conflict == "replace":
            client.create_playlist(playlist_id=existing.id, song_ids=matched_song_ids)
            if imported.comment is not None or imported.public:
                client.update_playlist(
                    playlist_id=existing.id,
                    comment=imported.comment,
                    public=imported.public,
                )
            return ImportResult(
                playlist_name=name,
                action="replaced",
                playlist_id=existing.id,
                matched_count=len(matched_song_ids),
                unmatched_tracks=unmatched_tracks,
                match_breakdown=breakdown,
            )

        elif on_conflict == "append":
            full_existing = client.get_playlist(existing.id)
            existing_song_ids = {t.id for t in full_existing.tracks}

            if allow_duplicates:
                songs_to_add = matched_song_ids
            else:
                songs_to_add = [sid for sid in matched_song_ids if sid not in existing_song_ids]

            if songs_to_add:
                client.update_playlist(playlist_id=existing.id, song_ids_to_add=songs_to_add)

            return ImportResult(
                playlist_name=name,
                action="appended",
                playlist_id=existing.id,
                matched_count=len(songs_to_add),
                unmatched_tracks=unmatched_tracks,
                match_breakdown=breakdown,
            )

        elif on_conflict == "rename":
            existing_names = {p.name.strip().lower() for p in user_playlists}
            new_name = f"{name} (Imported)"
            idx = 2
            while new_name.strip().lower() in existing_names:
                new_name = f"{name} (Imported {idx})"
                idx += 1

            pl = client.create_playlist(name=new_name, song_ids=matched_song_ids)
            if imported.comment is not None or imported.public:
                client.update_playlist(
                    playlist_id=pl.id,
                    comment=imported.comment,
                    public=imported.public,
                )
            return ImportResult(
                playlist_name=new_name,
                action="renamed",
                playlist_id=pl.id,
                matched_count=len(matched_song_ids),
                unmatched_tracks=unmatched_tracks,
                match_breakdown=breakdown,
            )

    # No conflict: create new playlist
    pl = client.create_playlist(name=name, song_ids=matched_song_ids)
    if imported.comment is not None or imported.public:
        client.update_playlist(
            playlist_id=pl.id,
            comment=imported.comment,
            public=imported.public,
        )

    return ImportResult(
        playlist_name=name,
        action="created",
        playlist_id=pl.id,
        matched_count=len(matched_song_ids),
        unmatched_tracks=unmatched_tracks,
        match_breakdown=breakdown,
    )
