# nd-playlists 🎵

A clean, modular, production-ready Python CLI tool to manage and safely delete playlists on a self-hosted **Navidrome** server using the official **Subsonic / OpenSubsonic REST API**.

---

## ✨ Features

- **🔐 Secure Authentication:** Implements modern Subsonic authentication using per-request cryptographically random salts (`s`) and MD5 hashed tokens (`t = md5(password + salt)`).
- **📋 Playlist Listing & Filtering:** Rich terminal tables displaying ID, name, track count, formatted `HH:MM:SS` duration, owner, public status, and last modified date. Filter by search string, owner, or zero-track empty playlists.
- **🔍 Detailed Playlist Inspection:** Inspect tracks with `#`, Title, Artist, Album, and Duration. Resolves playlists by exact ID or case-insensitive exact name with ambiguity detection.
- **🛡️ Safe Playlist Deletion:**
  - Select playlists by positional IDs/names, `--empty` (0 tracks), or `--pattern <glob>` (e.g. `Temp*`).
  - Pre-deletion inspection table.
  - Interactive confirmation prompt (`Confirm.ask`) with `-y` / `--yes` override.
  - `--dry-run` preview mode.
  - Automatic backup export (`--backup-dir <dir>` in JSON or M3U8 format) before deletion.
- **💾 Export Playlists:** Export playlist metadata and tracks to standard `.json` or Extended `.m3u8`.
- **✏️ Metadata Updates:** Update playlist name, description/comment, or toggle public/private visibility.
- **⚙️ Flexible Configuration:** Load credentials via `.env` file, environment variables, or CLI arguments (`--url`, `--user`, `--password`).

---

## 🚀 Installation

Requires **Python 3.11+**.

```bash
# Clone the repository
git clone <repo-url>
cd NavidromeManager

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package in editable mode with development dependencies
pip install -e ".[dev]"
```

After installation, the `nd-playlists` command is available in your shell.

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in your Navidrome credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
NAVIDROME_URL=http://localhost:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=supersecretpassword
```

Alternatively, you can export these environment variables directly or pass `--url`, `--user`, and `--password` to any command.

---

## 📖 Usage & Commands

### 1. Check Server Connectivity (`ping`)

Verify server connectivity, authentication, and Subsonic API versions:

```bash
nd-playlists ping
```

Output displays a Rich table with the server URL, connection status, Navidrome version, Subsonic API version, and OpenSubsonic support.

---

### 2. List Playlists (`list` / `ls`)

Display all playlists in a formatted Rich table:

```bash
# List all playlists
nd-playlists list

# Filter by case-insensitive name search
nd-playlists list --search "chill"

# Show only empty playlists (0 tracks)
nd-playlists list --empty

# Filter by owner username
nd-playlists list --owner admin
```

---

### 3. Show Playlist Tracks (`show`)

Inspect tracks and metadata for a playlist by its ID or exact name:

```bash
# By playlist ID
nd-playlists show 839d5257-2e52-4464-9669-e74f85e4da8d

# By exact playlist name (case-insensitive)
nd-playlists show "Rock Favorites"
```

*Note: If multiple playlists share the exact same name, `nd-playlists` displays an ambiguity table listing the conflicting playlist IDs and prompts you to specify the ID instead.*

---

### 4. Delete Playlists (`delete` / `rm`)

Delete playlists with safety guardrails:

```bash
# Delete by ID or name (prompts for confirmation)
nd-playlists delete "Old Playlist"

# Preview deletions without deleting anything
nd-playlists delete --empty --dry-run

# Delete all empty playlists without prompting
nd-playlists delete --empty -y

# Delete all playlists matching a pattern with automated backup
nd-playlists delete --pattern "Temp*" --backup-dir ./backups --backup-format json -y

# Delete multiple specific playlists
nd-playlists rm id-1 id-2 "Test Playlist"
```

#### Safety Guardrails:
1. **Pre-deletion summary table:** Displays every playlist queued for deletion before making changes.
2. **Interactive confirmation:** Asks `Are you sure you want to permanently delete X playlist(s)?` unless `-y` or `--yes` is specified.
3. **Dry-run mode:** `--dry-run` simulates the deletion and previews affected playlists.
4. **Automated backup:** `--backup-dir <path>` backs up each playlist (and its full track list) as `.json` or `.m3u8` before issuing the delete call.

---

### 5. Export Playlist (`export`)

Export playlist metadata and tracks to `.json` or `.m3u8`:

```bash
# Export to JSON (default file: <sanitized_name>.json)
nd-playlists export "Road Trip" --format json

# Export to Extended M3U8 playlist file
nd-playlists export "Road Trip" --format m3u8 --output ~/Music/road_trip.m3u8
```

---

### 6. Update Playlist Metadata (`update`)

Update a playlist's name, description comment, or public/private visibility:

```bash
# Rename a playlist
nd-playlists update "Workout" --name "Intense Workout"

# Update comment and set to public
nd-playlists update "Intense Workout" --comment "Gym tracks 2026" --public

# Make a playlist private
nd-playlists update "Intense Workout" --private
```

---

## 🛠️ CLI Options & Overrides

Global flags can be passed before or directly after any subcommand:

| Option | Flag | Description |
|---|---|---|
| `--url` | `-u` | Navidrome server base URL |
| `--user` | `-U` | Navidrome username |
| `--password` | `-P` | Navidrome password |
| `--timeout` | `-t` | HTTP request timeout in seconds (default: `10.0`) |
| `--version` | `-V` | Print version and exit |
| `--help` | `-h` | Display command help |

---

## 🧪 Running Tests

The test suite covers configuration loading, Subsonic API authentication, token generation, error handling, models, and CLI commands.

```bash
# Run tests with pytest
.venv/bin/pytest -v
```

---

## 📁 Project Architecture

```
NavidromeManager/
├── pyproject.toml               # Packaging & dependencies
├── .env.example                 # Environment configuration template
├── README.md                    # Documentation
├── src/
│   └── nd_playlists/
│       ├── __init__.py          # Package initialization
│       ├── config.py            # Environment & CLI config loading
│       ├── models.py            # Playlist and Track dataclasses & serializers
│       ├── client.py            # Subsonic REST client & authentication
│       └── cli.py               # Typer commands & Rich terminal UI
└── tests/
    ├── conftest.py              # Test fixtures & mocks
    ├── test_config.py           # Configuration tests
    ├── test_models.py           # Data model & serialization tests
    ├── test_client.py           # API client & auth tests
    └── test_cli.py              # CLI command tests
```
