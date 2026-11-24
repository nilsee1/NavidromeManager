"""Unit tests for Typer CLI commands and Rich terminal output."""

import json
from pathlib import Path
import pytest
import respx
from typer.testing import CliRunner
from nd_playlists.cli import app

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
    delete_route = respx.get("http://navidrome.local:4533/rest/deletePlaylist")

    result = runner.invoke(app, ["delete", "pl-1", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN ACTIVE" in result.stdout
    assert not delete_route.called


@respx.mock
def test_cli_delete_with_yes(mock_subsonic_playlists_response: dict) -> None:
    """Test delete command with -y skips confirmation."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.get("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "pl-1", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Rock Anthems'" in result.stdout
    assert delete_route.called


@respx.mock
def test_cli_delete_empty_playlists(mock_subsonic_playlists_response: dict) -> None:
    """Test delete --empty targets empty playlists."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.get("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "--empty", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Empty Draft'" in result.stdout
    assert delete_route.called


@respx.mock
def test_cli_delete_pattern(mock_subsonic_playlists_response: dict) -> None:
    """Test delete --pattern targets matching playlist names."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    delete_route = respx.get("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["delete", "--pattern", "Chill*", "-y"])
    assert result.exit_code == 0
    assert "Deleted 'Chill Beats'" in result.stdout
    assert delete_route.called


@respx.mock
def test_cli_delete_with_backup(
    tmp_path: Path,
    mock_subsonic_playlists_response: dict,
    mock_subsonic_playlist_details_response: dict,
) -> None:
    """Test delete command with --backup-dir exports before deleting."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    respx.get("http://navidrome.local:4533/rest/getPlaylist").respond(json=mock_subsonic_playlist_details_response)
    respx.get("http://navidrome.local:4533/rest/deletePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    backup_dir = tmp_path / "backups"
    result = runner.invoke(app, ["delete", "pl-1", "--backup-dir", str(backup_dir), "-y"])
    assert result.exit_code == 0
    assert backup_dir.exists()

    # Verify backup file was created
    backup_files = list(backup_dir.glob("*.json"))
    assert len(backup_files) == 1
    data = json.loads(backup_files[0].read_text(encoding="utf-8"))
    assert data["name"] == "Rock Anthems"
    assert len(data["tracks"]) == 2


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
def test_cli_update_metadata(mock_subsonic_playlists_response: dict) -> None:
    """Test update command."""
    respx.get("http://navidrome.local:4533/rest/getPlaylists").respond(json=mock_subsonic_playlists_response)
    update_route = respx.get("http://navidrome.local:4533/rest/updatePlaylist").respond(
        json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    )

    result = runner.invoke(app, ["update", "pl-1", "--name", "Modern Rock", "--public"])
    assert result.exit_code == 0
    assert "Successfully updated playlist" in result.stdout
    assert update_route.called
    assert update_route.calls.last.request.url.params["name"] == "Modern Rock"
    assert update_route.calls.last.request.url.params["public"] == "true"


def test_cli_missing_credentials_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error message when credentials are missing."""
    monkeypatch.delenv("NAVIDROME_URL", raising=False)
    monkeypatch.delenv("NAVIDROME_USER", raising=False)
    monkeypatch.delenv("NAVIDROME_PASSWORD", raising=False)

    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 1
    assert "Configuration Error" in result.stderr or "Configuration Error" in result.stdout
