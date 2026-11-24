"""Unit tests for Typer CLI commands and Rich terminal output."""

import json
from pathlib import Path
import pytest
import respx
import typer
from typer.testing import CliRunner
from nd_playlists.cli import app, handle_errors, sanitize_filename

runner = CliRunner()


@pytest.fixture(autouse=True)
def set_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set standard environment credentials for CLI tests."""
    monkeypatch.setenv("NAVIDROME_URL", "http://navidrome.local:4533")
    monkeypatch.setenv("NAVIDROME_USER", "testuser")
    monkeypatch.setenv("NAVIDROME_PASSWORD", "secretpassword")


def test_cli_version() -> None:
    """Test --version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "nd-playlists version" in result.stdout


@respx.mock
def test_cli_ping(mock_subsonic_ping_response: dict) -> None:
    """Test ping command output."""
    respx.get("http://navidrome.local:4533/rest/ping").respond(json=mock_subsonic_ping_response)

    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 0
    assert "Connected (OK)" in result.stdout
    assert "0.51.0" in result.stdout


@respx.mock
def test_cli_list_playlists(mock_subsonic_playlists_response: dict) -> None:
    """Test list command displays playlists in table."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Rock Anthems" in result.stdout
    assert "Empty Draft" in result.stdout
    assert "Chill Beats" in result.stdout


@respx.mock
def test_cli_list_filter_search(mock_subsonic_playlists_response: dict) -> None:
    """Test list command with --search filter."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    result = runner.invoke(app, ["list", "--search", "rock"])
    assert result.exit_code == 0
    assert "Rock Anthems" in result.stdout
    assert "Chill Beats" not in result.stdout


@respx.mock
def test_cli_list_filter_empty(mock_subsonic_playlists_response: dict) -> None:
    """Test list command with --empty filter."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    result = runner.invoke(app, ["list", "--empty"])
    assert result.exit_code == 0
    assert "Empty Draft" in result.stdout
    assert "Rock Anthems" not in result.stdout


@respx.mock
def test_cli_list_filter_owner(mock_subsonic_playlists_response: dict) -> None:
    """Test list command with --owner filter."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    result = runner.invoke(app, ["list", "--owner", "otheruser"])
    assert result.exit_code == 0
    assert "Chill Beats" in result.stdout
    assert "Rock Anthems" not in result.stdout


@respx.mock
def test_cli_show_playlist(
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Test show command renders tracks."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    result = runner.invoke(app, ["show", "Rock Anthems"])
    assert result.exit_code == 0
    assert "Bohemian Rhapsody" in result.stdout
    assert "Hotel California" in result.stdout
    assert "Queen" in result.stdout
    assert "Eagles" in result.stdout


@respx.mock
def test_cli_show_sequential_track_numbering(
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Verify show command displays playlist sequence numbers (1, 2) instead of album track numbers (11, 1)."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    result = runner.invoke(app, ["show", "Rock Anthems"])
    assert result.exit_code == 0
    # In mock_subsonic_playlist_details_response:
    # Track 1 has album track 11, Track 2 has album track 1
    # Sequential numbers must be 1 and 2
    output_lines = [line.strip() for line in result.stdout.splitlines() if "Bohemian Rhapsody" in line or "Hotel California" in line]
    assert len(output_lines) == 2
    assert output_lines[0].startswith("1 ") or " 1 " in output_lines[0]
    assert output_lines[1].startswith("2 ") or " 2 " in output_lines[1]


@respx.mock
def test_cli_rich_bracket_escaping() -> None:
    """Verify playlist names containing Rich markup tags like '[2026]' or '[/Live]' render safely without MarkupError."""
    bracket_playlists = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "playlists": {
                "playlist": [
                    {
                        "id": "pl-bracket",
                        "name": "Mix [2026] [/Live]",
                        "comment": "Testing [bold]tags[/bold]",
                        "owner": "testuser",
                        "public": True,
                        "songCount": 1,
                        "duration": 180,
                    }
                ]
            },
        }
    }
    bracket_details = {
        "subsonic-response": {
            "status": "ok",
            "version": "1.16.1",
            "playlist": {
                "id": "pl-bracket",
                "name": "Mix [2026] [/Live]",
                "comment": "Testing [bold]tags[/bold]",
                "owner": "testuser",
                "public": True,
                "songCount": 1,
                "duration": 180,
                "entry": [
                    {
                        "id": "trk-b",
                        "title": "Song [Remix]",
                        "artist": "Artist [DJ]",
                        "album": "Album [Deluxe]",
                        "duration": 180,
                    }
                ],
            },
        }
    }
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=bracket_playlists)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=bracket_details)

    # list command
    res_list = runner.invoke(app, ["list"])
    assert res_list.exit_code == 0
    assert "Mix [2026]" in res_list.stdout
    assert "[/Live]" in res_list.stdout

    # show command
    res_show = runner.invoke(app, ["show", "Mix [2026] [/Live]"])
    assert res_show.exit_code == 0
    assert "Mix [2026] [/Live]" in res_show.stdout
    assert "Song [Remix]" in res_show.stdout


def test_handle_errors_does_not_catch_typer_exit() -> None:
    """Verify handle_errors does not catch typer.Exit as an Unexpected Error."""
    with pytest.raises(typer.Exit) as exc_info:
        with handle_errors():
            raise typer.Exit(code=2)
    assert exc_info.value.exit_code == 2


@respx.mock
def test_cli_show_ambiguous_error(mock_subsonic_playlists_response: dict) -> None:
    """Test show command when multiple playlists share the same name."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    result = runner.invoke(app, ["show", "Duplicate Name"])
    assert result.exit_code == 1
    assert "Ambiguous Identifier" in result.stderr or "Ambiguous Identifier" in result.stdout
    assert "pl-4" in result.stderr or "pl-4" in result.stdout
    assert "pl-5" in result.stderr or "pl-5" in result.stdout


@respx.mock
def test_cli_delete_dry_run(mock_subsonic_playlists_response: dict) -> None:
    """Test delete command with --dry-run does not call delete endpoint."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist")

    result = runner.invoke(app, ["delete", "pl-1", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN ACTIVE" in result.stdout
    assert not delete_route.called


@respx.mock
def test_cli_delete_with_yes(mock_subsonic_playlists_response: dict) -> None:
    """Test delete command with -y skips confirmation and sends POST."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "pl-1", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Rock Anthems'" in result.stdout
    assert delete_route.called
    assert delete_route.calls.last.request.method == "POST"


@respx.mock
def test_cli_delete_empty_playlists(mock_subsonic_playlists_response: dict) -> None:
    """Test delete --empty targets empty playlists owned by testuser."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "--empty", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Empty Draft'" in result.stdout
    assert delete_route.called


@respx.mock
def test_cli_delete_pattern(mock_subsonic_playlists_response: dict) -> None:
    """Test delete --pattern targets matching playlist names owned by testuser."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "--pattern", "Rock*", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Rock Anthems'" in result.stdout
    assert delete_route.called


@respx.mock
def test_cli_delete_and_semantics_and_owner_filtering(mock_subsonic_playlists_response: dict) -> None:
    """Verify --empty and --pattern combine with logical AND and only target current user's playlists."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    # pl-2 is empty and named "Empty Draft", owned by testuser
    # pl-1 is "Rock Anthems", not empty
    # Pattern "Empty*" with --empty should match ONLY pl-2
    result = runner.invoke(app, ["delete", "--empty", "--pattern", "Empty*", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Empty Draft'" in result.stdout
    assert delete_route.call_count == 1

    # Pattern "Rock*" with --empty should match NOTHING because Rock Anthems is not empty
    delete_route.reset()
    result_none = runner.invoke(app, ["delete", "--empty", "--pattern", "Rock*", "-y"])
    assert result_none.exit_code == 0
    assert "No playlists matched" in result_none.stdout
    assert not delete_route.called

    # Pattern "Chill*" is owned by otheruser -> by default should NOT be deleted
    delete_route.reset()
    result_other = runner.invoke(app, ["delete", "--pattern", "Chill*", "-y"])
    assert result_other.exit_code == 0
    assert "No playlists matched" in result_other.stdout
    assert not delete_route.called


@respx.mock
def test_cli_delete_all_owners_flag(mock_subsonic_playlists_response: dict) -> None:
    """Verify --all-owners allows bulk filtering across all users' playlists."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "--pattern", "Chill*", "--all-owners", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Chill Beats'" in result.stdout
    assert delete_route.called


@respx.mock
def test_cli_delete_cancelling_confirmation_prevents_backups_and_directory(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify declining the confirmation prompt does not create backup directory or files."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.post("http://navidrome.local:4533/rest/deletePlaylist")

    backup_dir = tmp_path / "cancelled_backups"
    # Provide "n" to confirmation prompt
    result = runner.invoke(
        app,
        ["delete", "pl-1", "--backup-dir", str(backup_dir)],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "Deletion cancelled by user" in result.stdout
    assert not backup_dir.exists()
    assert not delete_route.called


@respx.mock
def test_cli_delete_invalid_backup_format_fails_early(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify unsupported backup format fails early before prompting or creating directories."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    backup_dir = tmp_path / "invalid_fmt_backups"

    result = runner.invoke(
        app,
        ["delete", "pl-1", "--backup-dir", str(backup_dir), "--backup-format", "yaml", "-y"],
    )
    assert result.exit_code == 1
    assert "Unsupported backup format" in (result.stderr + result.stdout)
    assert not backup_dir.exists()


@respx.mock
def test_cli_delete_with_backup(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Test delete command with --backup-dir exports before deleting."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)
    respx.post("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    backup_dir = tmp_path / "backups"
    result = runner.invoke(app, ["delete", "pl-1", "--backup-dir", str(backup_dir), "-y"])
    assert result.exit_code == 0
    assert backup_dir.exists()

    # Verify backup file was created with sanitized name and ID
    backup_files = list(backup_dir.glob("*.json"))
    assert len(backup_files) == 1
    assert "Rock Anthems_pl-1.json" in backup_files[0].name
    data = json.loads(backup_files[0].read_text(encoding="utf-8"))
    assert data["name"] == "Rock Anthems"
    assert len(data["tracks"]) == 2


def test_sanitize_filename_edge_cases() -> None:
    """Verify sanitize_filename handles dots, slashes in ID, empty names, and length truncation."""
    assert sanitize_filename("") == "playlist"
    assert sanitize_filename("   ") == "playlist"
    assert sanitize_filename(".") == "playlist"
    assert sanitize_filename("..") == "playlist"
    assert sanitize_filename("...") == "playlist"
    assert sanitize_filename("  .  ") == "playlist"
    assert sanitize_filename("pl/id/with/slash") == "pl_id_with_slash"
    assert "/" not in sanitize_filename("pl/id/with/slash")

    long_name = "A" * 200
    sanitized = sanitize_filename(long_name, max_length=150)
    assert len(sanitized) == 150
    assert sanitized == "A" * 150


@respx.mock
def test_cli_export_json_and_m3u8(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Test export command for json and m3u8 formats."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    # Export JSON
    json_path = tmp_path / "exported.json"
    result_json = runner.invoke(app, ["export", "pl-1", "--format", "json", "--output", str(json_path)])
    assert result_json.exit_code == 0
    assert json_path.exists()
    assert "Bohemian Rhapsody" in json_path.read_text(encoding="utf-8")

    # Export M3U8
    m3u8_path = tmp_path / "exported.m3u8"
    result_m3u8 = runner.invoke(app, ["export", "pl-1", "--format", "m3u8", "--output", str(m3u8_path)])
    assert result_m3u8.exit_code == 0
    assert m3u8_path.exists()
    assert "#EXTM3U" in m3u8_path.read_text(encoding="utf-8")


@respx.mock
def test_cli_export_overwrite_protection(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Verify export fails when destination file exists unless --force is specified, and rejects directories."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    target_file = tmp_path / "existing.json"
    target_file.write_text("initial content", encoding="utf-8")

    # Attempt export without --force -> should fail
    result_fail = runner.invoke(app, ["export", "pl-1", "--output", str(target_file)])
    assert result_fail.exit_code == 1
    assert "already exists" in (result_fail.stderr + result_fail.stdout)
    assert target_file.read_text(encoding="utf-8") == "initial content"

    # Attempt export with --force -> should succeed
    result_force = runner.invoke(app, ["export", "pl-1", "--output", str(target_file), "--force"])
    assert result_force.exit_code == 0
    assert "Bohemian Rhapsody" in target_file.read_text(encoding="utf-8")

    # Attempt export where output is a directory -> should fail
    target_dir = tmp_path / "a_directory"
    target_dir.mkdir()
    result_dir = runner.invoke(app, ["export", "pl-1", "--output", str(target_dir)])
    assert result_dir.exit_code == 1
    assert "existing directory" in (result_dir.stderr + result_dir.stdout)


@respx.mock
def test_cli_update_metadata(mock_subsonic_playlists_response: dict) -> None:
    """Test update command sends POST request."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    update_route = respx.post("http://navidrome.local:4533/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["update", "pl-1", "--name", "Modern Rock", "--public"])
    assert result.exit_code == 0
    assert "Successfully updated playlist" in result.stdout
    assert update_route.called
    assert update_route.calls.last.request.method == "POST"


@respx.mock
def test_cli_password_stdin(mock_subsonic_ping_response: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test passing password via --password-stdin."""
    monkeypatch.delenv("NAVIDROME_PASSWORD", raising=False)
    respx.get("http://navidrome.local:4533/rest/ping").respond(json=mock_subsonic_ping_response)

    result = runner.invoke(
        app,
        ["--password-stdin", "ping"],
        input="stdin_secret_password\n",
    )
    assert result.exit_code == 0
    assert "Connected (OK)" in result.stdout


@respx.mock
def test_cli_custom_env_file(tmp_path: Path, mock_subsonic_ping_response: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test specifying custom --env-file option."""
    monkeypatch.delenv("NAVIDROME_URL", raising=False)
    monkeypatch.delenv("NAVIDROME_USER", raising=False)
    monkeypatch.delenv("NAVIDROME_PASSWORD", raising=False)

    env_path = tmp_path / ".custom_env"
    env_path.write_text(
        "NAVIDROME_URL=http://navidrome.local:4533\n"
        "NAVIDROME_USER=custom_user\n"
        "NAVIDROME_PASSWORD=custom_pass\n",
        encoding="utf-8",
    )
    respx.get("http://navidrome.local:4533/rest/ping").respond(json=mock_subsonic_ping_response)

    result = runner.invoke(app, ["--env-file", str(env_path), "ping"])
    assert result.exit_code == 0
    assert "Connected (OK)" in result.stdout


def test_cli_missing_credentials_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error message when credentials are missing."""
    monkeypatch.delenv("NAVIDROME_URL", raising=False)
    monkeypatch.delenv("NAVIDROME_USER", raising=False)
    monkeypatch.delenv("NAVIDROME_PASSWORD", raising=False)

    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 1
    assert "Configuration Error" in result.stderr or "Configuration Error" in result.stdout


# ==============================================================================
# Bulk Export and Import CLI Tests
# ==============================================================================

@respx.mock
def test_cli_bulk_export_all_and_pattern_and_owner(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Verify bulk export options --all, --pattern, --owner, and --output-dir."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    # 1. Export --all to output-dir
    out_dir_all = tmp_path / "all_exports"
    res_all = runner.invoke(app, ["export", "--all", "-d", str(out_dir_all)])
    assert res_all.exit_code == 0
    assert "Successfully exported 5 playlist(s)" in res_all.stdout
    assert len(list(out_dir_all.glob("*.json"))) == 5

    # 2. Export --pattern 'Rock*'
    out_dir_pat = tmp_path / "pat_exports"
    res_pat = runner.invoke(app, ["export", "--pattern", "Rock*", "-d", str(out_dir_pat)])
    assert res_pat.exit_code == 0
    assert "Successfully exported 1 playlist(s)" in res_pat.stdout
    assert len(list(out_dir_pat.glob("*.json"))) == 1

    # 3. Export --owner 'otheruser'
    out_dir_owner = tmp_path / "owner_exports"
    res_owner = runner.invoke(app, ["export", "--all", "--owner", "otheruser", "-d", str(out_dir_owner)])
    assert res_owner.exit_code == 0
    assert "Successfully exported 2 playlist(s)" in res_owner.stdout
    assert len(list(out_dir_owner.glob("*.json"))) == 2


@respx.mock
def test_cli_export_rejects_output_for_multiple_playlists(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify using --output with multiple playlists raises ConfigError."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)

    res = runner.invoke(app, ["export", "--all", "-o", str(tmp_path / "out.json")])
    assert res.exit_code == 1
    assert "Cannot use --output when exporting multiple playlists" in (res.stderr + res.stdout)


@respx.mock
def test_cli_bulk_export_overwrite_force(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Verify bulk export respects overwrite protection unless --force is specified."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)

    out_dir = tmp_path / "force_test"
    out_dir.mkdir()
    existing_file = out_dir / "Rock Anthems.json"
    existing_file.write_text("old", encoding="utf-8")

    # Without --force -> fail
    res_fail = runner.invoke(app, ["export", "--pattern", "Rock*", "-d", str(out_dir)])
    assert res_fail.exit_code == 1
    assert "already exists" in (res_fail.stderr + res_fail.stdout)
    assert existing_file.read_text(encoding="utf-8") == "old"

    # With --force -> succeed
    res_force = runner.invoke(app, ["export", "--pattern", "Rock*", "-d", str(out_dir), "--force"])
    assert res_force.exit_code == 0
    assert "Successfully exported 1 playlist(s)" in res_force.stdout
    assert existing_file.read_text(encoding="utf-8") != "old"


@respx.mock
def test_cli_import_single_file_and_dry_run(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify import command with single file, dry-run, and creation."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getSong").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "song": {"id": "trk-101", "title": "Song One", "artist": "Artist One", "duration": 180},
            }
        }
    )
    create_route = respx.post("http://navidrome.local:4533/rest/createPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {"id": "pl-newly-created", "name": "New Mix"},
            }
        }
    )

    playlist_data = {
        "name": "New Mix",
        "tracks": [{"id": "trk-101", "title": "Song One", "artist": "Artist One", "duration": 180}],
    }
    file_path = tmp_path / "import_me.json"
    file_path.write_text(json.dumps(playlist_data), encoding="utf-8")

    # 1. Dry run
    res_dry = runner.invoke(app, ["import", str(file_path), "--dry-run"])
    assert res_dry.exit_code == 0
    assert "dry-run" in res_dry.stdout
    assert not create_route.called

    # 2. Real import
    res_real = runner.invoke(app, ["import", str(file_path)])
    assert res_real.exit_code == 0
    assert "created" in res_real.stdout
    assert create_route.called


@respx.mock
def test_cli_import_directory_and_report(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify importing a directory discovers files, renders summary table, and generates --report."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getSong").respond(
        json={
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "error": {"code": 70, "message": "Song not found"},
            }
        }
    )
    respx.get("http://navidrome.local:4533/rest/search3").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1", "searchResult3": {"song": None}}}
    )
    respx.post("http://navidrome.local:4533/rest/createPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {"id": "pl-dir-1", "name": "Dir Playlist"},
            }
        }
    )

    import_dir = tmp_path / "playlists_dir"
    import_dir.mkdir()

    p1 = import_dir / "01_mix.json"
    p1.write_text(
        json.dumps(
            {
                "name": "Dir Playlist 1",
                "tracks": [{"id": "t-missing", "title": "Missing Song", "artist": "Ghost"}],
            }
        ),
        encoding="utf-8",
    )

    p2 = import_dir / "02_mix.m3u8"
    p2.write_text(
        "#EXTM3U\n#PLAYLIST:Dir Playlist 2\n#EXTINF:200,Ghost - Unmatched Track\nghost.mp3\n",
        encoding="utf-8",
    )

    report_path = tmp_path / "unmatched_report.json"
    res = runner.invoke(app, ["import", str(import_dir), "--report", str(report_path)])
    assert res.exit_code == 0
    assert "Dir Playlist 1" in res.stdout
    assert "Dir Playlist 2" in res.stdout
    assert "Unmatched Tracks" in res.stdout
    assert "Missing Song" in res.stdout
    assert "Unmatched Track" in res.stdout

    # Verify report file
    assert report_path.exists()
    report_json = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_json["summary"]["total_unmatched_tracks"] == 2
    assert len(report_json["playlists"]) == 2


@respx.mock
def test_cli_import_name_override_valid_and_invalid(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify --name works for single file and is rejected for multiple files."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    create_route = respx.post("http://navidrome.local:4533/rest/createPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {"id": "pl-renamed", "name": "Overridden Name"},
            }
        }
    )

    f1 = tmp_path / "p1.json"
    f1.write_text(json.dumps({"name": "Original Name", "tracks": []}), encoding="utf-8")
    f2 = tmp_path / "p2.json"
    f2.write_text(json.dumps({"name": "Second List", "tracks": []}), encoding="utf-8")

    # Valid: single file with --name
    res_single = runner.invoke(app, ["import", str(f1), "--name", "Overridden Name"])
    assert res_single.exit_code == 0
    assert "Overridden Name" in res_single.stdout
    assert create_route.called

    # Invalid: multiple files with --name
    res_multi = runner.invoke(app, ["import", str(f1), str(f2), "--name", "Bad Override"])
    assert res_multi.exit_code == 1
    assert "Cannot use --name when importing multiple playlist files" in (res_multi.stderr + res_multi.stdout)


@respx.mock
def test_cli_import_conflict_modes(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
) -> None:
    """Verify CLI --on-conflict options (skip, replace, append, rename)."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getSong").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "song": {"id": "trk-101", "title": "Bohemian Rhapsody", "duration": 354},
            }
        }
    )
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {
                    "id": "pl-1",
                    "name": "Rock Anthems",
                    "entry": [{"id": "trk-101", "title": "Bohemian Rhapsody", "duration": 354}],
                },
            }
        }
    )
    respx.post("http://navidrome.local:4533/rest/createPlaylist").respond(
        json={
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
                "playlist": {"id": "pl-renamed", "name": "Rock Anthems (Imported)"},
            }
        }
    )
    respx.post("http://navidrome.local:4533/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    # Rock Anthems exists and is owned by testuser
    pl_file = tmp_path / "rock_import.json"
    pl_file.write_text(
        json.dumps(
            {
                "name": "Rock Anthems",
                "tracks": [{"id": "trk-101", "title": "Bohemian Rhapsody", "duration": 354}],
            }
        ),
        encoding="utf-8",
    )

    # 1. skip
    res_skip = runner.invoke(app, ["import", str(pl_file), "--on-conflict", "skip"])
    assert res_skip.exit_code == 0
    assert "skipped" in res_skip.stdout

    # 2. replace
    res_replace = runner.invoke(app, ["import", str(pl_file), "--on-conflict", "replace"])
    assert res_replace.exit_code == 0
    assert "replaced" in res_replace.stdout

    # 3. rename
    res_rename = runner.invoke(app, ["import", str(pl_file), "--on-conflict", "rename"])
    assert res_rename.exit_code == 0
    assert "renamed" in res_rename.stdout
    assert "Rock Anthems" in res_rename.stdout
    assert "(Imported)" in res_rename.stdout


def test_cli_import_validation_errors(tmp_path: Path) -> None:
    """Verify validation errors for invalid --min-confidence, bad --on-conflict, or empty dir."""
    dummy_file = tmp_path / "dummy.json"
    dummy_file.write_text("{}", encoding="utf-8")

    # Invalid confidence
    res_conf = runner.invoke(app, ["import", str(dummy_file), "--min-confidence", "1.5"])
    assert res_conf.exit_code == 1
    assert "--min-confidence must be between 0.0 and 1.0" in (res_conf.stderr + res_conf.stdout)

    # Invalid conflict
    res_conf_strat = runner.invoke(app, ["import", str(dummy_file), "--on-conflict", "explode"])
    assert res_conf_strat.exit_code == 1
    assert "Invalid --on-conflict strategy" in (res_conf_strat.stderr + res_conf_strat.stdout)

    # Empty directory
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    res_empty = runner.invoke(app, ["import", str(empty_dir)])
    assert res_empty.exit_code == 1
    assert "No supported playlist files" in (res_empty.stderr + res_empty.stdout)

