"""Data models for Subsonic playlists and tracks."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Gracefully parse an integer handling None, empty strings, floats, and tags like '1/12'."""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    val_str = str(value).strip()
    if not val_str:
        return default
    if "/" in val_str:
        val_str = val_str.split("/")[0].strip()
    try:
        return int(val_str)
    except (ValueError, TypeError):
        try:
            return int(float(val_str))
        except (ValueError, TypeError):
            return default


def format_duration(seconds: Optional[int | float]) -> str:
    """Format duration in seconds to HH:MM:SS."""
    if seconds is None or seconds < 0:
        return "00:00:00"
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass
class Track:
    """Represents a single audio track in a Subsonic playlist."""

    id: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: int = 0
    track_number: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    suffix: Optional[str] = None
    path: Optional[str] = None

    @property
    def formatted_duration(self) -> str:
        """Formatted duration HH:MM:SS."""
        return format_duration(self.duration)

    @property
    def display_artist(self) -> str:
        """Artist name or fallback."""
        return self.artist or "Unknown Artist"

    @property
    def display_album(self) -> str:
        """Album name or fallback."""
        return self.album or "Unknown Album"

    @classmethod
    def from_subsonic_dict(cls, data: dict[str, Any]) -> "Track":
        """Parse Subsonic track entry dictionary."""
        parsed_duration = _safe_int(data.get("duration"), default=0)
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title") or "Unknown Title"),
            artist=data.get("artist"),
            album=data.get("album"),
            duration=parsed_duration if parsed_duration is not None else 0,
            track_number=_safe_int(data.get("track"), default=None),
            year=_safe_int(data.get("year"), default=None),
            genre=data.get("genre"),
            size=_safe_int(data.get("size"), default=None),
            content_type=data.get("contentType"),
            suffix=data.get("suffix"),
            path=data.get("path"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert track to serializable dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": self.duration,
            "formattedDuration": self.formatted_duration,
            "trackNumber": self.track_number,
            "year": self.year,
            "genre": self.genre,
            "size": self.size,
            "contentType": self.content_type,
            "suffix": self.suffix,
            "path": self.path,
        }


@dataclass
class Playlist:
    """Represents a Subsonic / Navidrome playlist."""

    id: str
    name: str
    comment: Optional[str] = None
    owner: Optional[str] = None
    public: bool = False
    song_count: int = 0
    duration: int = 0
    created: Optional[str] = None
    changed: Optional[str] = None
    cover_art: Optional[str] = None
    tracks: list[Track] = field(default_factory=list)

    @property
    def formatted_duration(self) -> str:
        """Formatted total duration HH:MM:SS."""
        return format_duration(self.duration)

    @property
    def formatted_changed(self) -> str:
        """Formatted last modified timestamp."""
        if not self.changed:
            return "-"
        try:
            # Handle ISO-8601 strings
            dt = datetime.fromisoformat(self.changed.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return str(self.changed)

    @classmethod
    def from_subsonic_dict(cls, data: dict[str, Any]) -> "Playlist":
        """Parse Subsonic playlist dictionary."""
        # Parse tracks if present in `entry`
        raw_entries = data.get("entry") or []
        if isinstance(raw_entries, dict):
            raw_entries = [raw_entries]
        tracks = [
            Track.from_subsonic_dict(entry)
            for entry in raw_entries
            if isinstance(entry, dict)
        ]

        # Public flag can be boolean or string
        raw_public = data.get("public", False)
        if isinstance(raw_public, str):
            public = raw_public.lower() in ("true", "1", "yes")
        else:
            public = bool(raw_public)

        parsed_song_count = _safe_int(data.get("songCount"))
        song_count = parsed_song_count if parsed_song_count is not None else len(tracks)

        parsed_duration = _safe_int(data.get("duration"))
        duration = parsed_duration if parsed_duration is not None else sum(t.duration for t in tracks)

        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "Untitled")),
            comment=data.get("comment"),
            owner=data.get("owner"),
            public=public,
            song_count=song_count,
            duration=duration,
            created=data.get("created"),
            changed=data.get("changed"),
            cover_art=data.get("coverArt"),
            tracks=tracks,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert playlist and all its tracks to dictionary for JSON export."""
        return {
            "id": self.id,
            "name": self.name,
            "comment": self.comment,
            "owner": self.owner,
            "public": self.public,
            "songCount": self.song_count,
            "duration": self.duration,
            "formattedDuration": self.formatted_duration,
            "created": self.created,
            "changed": self.changed,
            "coverArt": self.cover_art,
            "tracks": [track.to_dict() for track in self.tracks],
        }

    def to_m3u8(self) -> str:
        """Generate standard Extended M3U8 content for the playlist."""
        def _clean_str(val: str) -> str:
            return val.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()

        clean_name = _clean_str(self.name)
        lines = [
            "#EXTM3U",
            f"#PLAYLIST:{clean_name}",
        ]
        for track in self.tracks:
            artist = _clean_str(track.display_artist)
            title = _clean_str(track.title)
            lines.append(f"#EXTINF:{track.duration},{artist} - {title}")
            if track.path:
                uri = _clean_str(track.path)
            else:
                safe_artist = artist.replace("/", "_").replace("\\", "_")
                safe_title = title.replace("/", "_").replace("\\", "_")
                suffix = _clean_str(track.suffix or "mp3").lstrip(".")
                uri = f"{safe_artist} - {safe_title}.{suffix}"
                uri = _clean_str(uri)
            lines.append(uri)

        return "\n".join(lines) + "\n"
