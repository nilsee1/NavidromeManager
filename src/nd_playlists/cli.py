"""CLI commands and Rich output formatting for nd-playlists."""

from contextlib import contextmanager
import fnmatch
import json
from pathlib import Path
from typing import Generator, List, Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from nd_playlists import __version__
from nd_playlists.client import (
    PlaylistAmbiguityError,
    PlaylistNotFoundError,
    SubsonicAPIError,
    SubsonicClient,
    SubsonicConnectionError,
    SubsonicError,
    SubsonicTimeoutError,
)
from nd_playlists.config import ConfigError, load_config
from nd_playlists.models import Playlist

app = typer.Typer(
    name="nd-playlists",
    help="Manage and delete playlists on a Navidrome server using the Subsonic / OpenSubsonic REST API.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


@contextmanager
def handle_errors() -> Generator[None, None, None]:
    """Context manager to trap known exceptions and display styled Rich error messages."""
    try:
        yield
    except ConfigError as exc:
        err_console.print(f"[bold red]Configuration Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except SubsonicTimeoutError as exc:
        err_console.print(f"[bold red]Timeout Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except SubsonicConnectionError as exc:
        err_console.print(f"[bold red]Connection Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except SubsonicAPIError as exc:
        err_console.print(
            f"[bold red]Subsonic API Error (Code {exc.code}):[/bold red] {exc.message}"
        )
        raise typer.Exit(code=1)
    except PlaylistAmbiguityError as exc:
        err_console.print(
            f"[bold yellow]Ambiguous Identifier:[/bold yellow] Found {len(exc.matches)} playlists "
            f"with the name '[bold]{exc.identifier}[/]'.\nPlease specify the target by its unique ID:\n"
        )
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Playlist ID", style="cyan")
        table.add_column("Name", style="bold white")
        table.add_column("Owner", style="magenta")
        table.add_column("Tracks", justify="right")
        table.add_column("Duration", justify="right")
        for match in exc.matches:
            table.add_row(
                match.id,
                match.name,
                match.owner or "N/A",
                str(match.song_count),
                match.formatted_duration,
            )
        err_console.print(table)
        raise typer.Exit(code=1)
    except PlaylistNotFoundError as exc:
        err_console.print(f"[bold red]Not Found:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except SubsonicError as exc:
        err_console.print(f"[bold red]Subsonic Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        err_console.print(f"[bold red]Unexpected Error:[/bold red] {exc}")
        raise typer.Exit(code=1)


def get_client(
    ctx: typer.Context,
    url: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> SubsonicClient:
    """Instantiate SubsonicClient using command overrides or global context settings."""
    cb_data = ctx.obj or {}
    resolved_url = url or cb_data.get("url")
    resolved_user = user or cb_data.get("user")
    resolved_password = password or cb_data.get("password")
    timeout = cb_data.get("timeout", 10.0)

    config = load_config(
        url=resolved_url,
        user=resolved_user,
        password=resolved_password,
        timeout=timeout,
    )
    return SubsonicClient(config)


def sanitize_filename(name: str) -> str:
    """Sanitize a playlist name for safe filesystem storage."""
    safe = "".join(c if (c.isalnum() or c in (" ", ".", "_", "-")) else "_" for c in name)
    return safe.strip() or "playlist"


def version_callback(value: bool) -> None:
    """Callback to print version and exit cleanly."""
    if value:
        console.print(
            f"[bold cyan]nd-playlists[/bold cyan] version [bold green]{__version__}[/bold green]"
        )
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    url: Optional[str] = typer.Option(
        None, "--url", "-u", help="Navidrome server URL (e.g. http://localhost:4533)"
    ),
    user: Optional[str] = typer.Option(
        None, "--user", "-U", help="Navidrome username"
    ),
    password: Optional[str] = typer.Option(
        None, "--password", "-P", help="Navidrome password"
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", "-t", help="HTTP request timeout in seconds"
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """nd-playlists: Manage and delete playlists on a Navidrome server."""
    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["user"] = user
    ctx.obj["password"] = password
    ctx.obj["timeout"] = timeout


@app.command("ping")
def ping_cmd(
    ctx: typer.Context,
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Override Navidrome password"),
) -> None:
    """Verify server connectivity, authentication, and Subsonic API details."""
    with handle_errors():
        with get_client(ctx, url, user, password) as client:
            info = client.ping()

            table = Table(title="Navidrome Server Connectivity", border_style="green")
            table.add_column("Property", style="bold cyan")
            table.add_column("Value", style="bold white")

            table.add_row("Server URL", client.config.url)
            table.add_row("User", client.config.user)
            table.add_row("Status", "[bold green]Connected (OK)[/bold green]")
            table.add_row("Server Type", str(info.get("type", "navidrome")))
            table.add_row("Server Version", str(info.get("serverVersion", "unknown")))
            table.add_row("Subsonic API Version", str(info.get("version", "1.16.1")))
            open_subsonic = "[green]Yes[/green]" if info.get("openSubsonic") else "[dim]No[/dim]"
            table.add_row("OpenSubsonic Support", open_subsonic)

            console.print(table)


def _list_playlists_impl(
    ctx: typer.Context,
    search: Optional[str] = None,
    empty: bool = False,
    owner: Optional[str] = None,
    url: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> None:
    with handle_errors():
        with get_client(ctx, url, user, password) as client:
            playlists = client.get_playlists()

            filtered: list[Playlist] = []
            for p in playlists:
                if search and search.lower() not in p.name.lower():
                    continue
                if empty and p.song_count > 0:
                    continue
                if owner and (not p.owner or p.owner.lower() != owner.lower()):
                    continue
                filtered.append(p)

            if not filtered:
                if playlists:
                    console.print("[yellow]No playlists found matching the specified filters.[/yellow]")
                else:
                    console.print("[yellow]No playlists found on this server.[/yellow]")
                return

            table = Table(
                title=f"Navidrome Playlists ({len(filtered)}/{len(playlists)})",
                border_style="blue",
            )
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Name", style="bold white")
            table.add_column("Tracks", justify="right")
            table.add_column("Duration", justify="right")
            table.add_column("Owner", style="magenta")
            table.add_column("Public", justify="center")
            table.add_column("Last Modified", style="dim")

            for pl in filtered:
                track_style = "yellow" if pl.song_count == 0 else "green"
                tracks_str = f"[{track_style}]{pl.song_count}[/{track_style}]"
                public_str = "[green]Yes[/green]" if pl.public else "[dim]No[/dim]"

                table.add_row(
                    pl.id,
                    pl.name,
                    tracks_str,
                    pl.formatted_duration,
                    pl.owner or "-",
                    public_str,
                    pl.formatted_changed,
                )

            console.print(table)


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    search: Optional[str] = typer.Option(
        None, "--search", "-s", help="Filter playlists by case-insensitive name substring"
    ),
    empty: bool = typer.Option(
        False, "--empty", help="Show only playlists with 0 tracks"
    ),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Filter playlists by owner username"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Override Navidrome password"),
) -> None:
    """Fetch and list playlists with optional search, empty, and owner filters."""
    _list_playlists_impl(ctx, search, empty, owner, url, user, password)


@app.command("ls", hidden=True)
def ls_cmd(
    ctx: typer.Context,
    search: Optional[str] = typer.Option(None, "--search", "-s"),
    empty: bool = typer.Option(False, "--empty"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o"),
    url: Optional[str] = typer.Option(None, "--url", "-u"),
    user: Optional[str] = typer.Option(None, "--user", "-U"),
    password: Optional[str] = typer.Option(None, "--password", "-P"),
) -> None:
    """Alias for list."""
    _list_playlists_impl(ctx, search, empty, owner, url, user, password)


@app.command("show")
def show_cmd(
    ctx: typer.Context,
    identifier: str = typer.Argument(
        ..., help="Playlist ID or case-insensitive exact name"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Override Navidrome password"),
) -> None:
    """Show details and tracklist for a playlist by ID or exact name."""
    with handle_errors():
        with get_client(ctx, url, user, password) as client:
            target = client.resolve_playlist(identifier)
            playlist = client.get_playlist(target.id)

            metadata_lines = [
                f"[bold cyan]ID:[/bold cyan] {playlist.id}",
                f"[bold cyan]Owner:[/bold cyan] {playlist.owner or 'N/A'}",
                f"[bold cyan]Tracks:[/bold cyan] {playlist.song_count}",
                f"[bold cyan]Total Duration:[/bold cyan] {playlist.formatted_duration}",
                f"[bold cyan]Public:[/bold cyan] {'Yes' if playlist.public else 'No'}",
                f"[bold cyan]Last Modified:[/bold cyan] {playlist.formatted_changed}",
            ]
            if playlist.comment:
                metadata_lines.append(f"[bold cyan]Comment:[/bold cyan] [italic]{playlist.comment}[/italic]")

            console.print(
                Panel(
                    "\n".join(metadata_lines),
                    title=f"[bold white]Playlist: {playlist.name}[/bold white]",
                    border_style="cyan",
                )
            )

            if not playlist.tracks:
                console.print("[yellow]This playlist contains 0 tracks.[/yellow]")
                return

            table = Table(
                title=f"Tracks ({len(playlist.tracks)})",
                border_style="blue",
            )
            table.add_column("#", justify="right", style="dim", no_wrap=True)
            table.add_column("Title", style="bold white")
            table.add_column("Artist", style="cyan")
            table.add_column("Album", style="magenta")
            table.add_column("Duration", justify="right", style="green")

            for idx, track in enumerate(playlist.tracks, start=1):
                track_num = str(track.track_number) if track.track_number is not None else str(idx)
                table.add_row(
                    track_num,
                    track.title,
                    track.display_artist,
                    track.display_album,
                    track.formatted_duration,
                )

            console.print(table)


def _delete_playlists_impl(
    ctx: typer.Context,
    identifiers: Optional[List[str]] = None,
    empty: bool = False,
    pattern: Optional[str] = None,
    dry_run: bool = False,
    yes: bool = False,
    backup_dir: Optional[Path] = None,
    backup_format: str = "json",
    url: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> None:
    with handle_errors():
        with get_client(ctx, url, user, password) as client:
            all_playlists = client.get_playlists()
            targets: dict[str, Playlist] = {}

            # 1. Match positional identifiers
            if identifiers:
                for ident in identifiers:
                    target = client.resolve_playlist(ident)
                    targets[target.id] = target

            # 2. Match empty playlists
            if empty:
                for p in all_playlists:
                    if p.song_count == 0:
                        targets[p.id] = p

            # 3. Match glob pattern
            if pattern:
                for p in all_playlists:
                    if fnmatch.fnmatch(p.name.lower(), pattern.lower()):
                        targets[p.id] = p

            if not targets:
                console.print(
                    "[yellow]No playlists matched or targeted for deletion.[/yellow]\n"
                    "Specify one or more identifiers, or use --empty or --pattern <glob>."
                )
                return

            target_list = list(targets.values())

            # Display deletion queue table
            table = Table(
                title=f"Playlists Queued for Deletion ({len(target_list)})",
                border_style="red",
            )
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Name", style="bold white")
            table.add_column("Tracks", justify="right")
            table.add_column("Duration", justify="right")
            table.add_column("Owner", style="magenta")

            for pl in target_list:
                table.add_row(
                    pl.id,
                    pl.name,
                    str(pl.song_count),
                    pl.formatted_duration,
                    pl.owner or "-",
                )

            console.print(table)

            if dry_run:
                console.print(
                    f"\n[bold yellow]DRY RUN ACTIVE:[/] Would delete {len(target_list)} playlist(s). "
                    "No changes were made."
                )
                return

            # Perform backup if requested
            if backup_dir:
                backup_dir.mkdir(parents=True, exist_ok=True)
                fmt = backup_format.lower()
                if fmt not in ("json", "m3u8"):
                    raise ConfigError(f"Unsupported backup format: '{backup_format}'. Choose 'json' or 'm3u8'.")

                console.print(f"[dim]Backing up {len(target_list)} playlist(s) to {backup_dir}...[/dim]")
                for pl in target_list:
                    full_pl = client.get_playlist(pl.id)
                    safe_name = sanitize_filename(full_pl.name)
                    backup_path = backup_dir / f"{safe_name}_{full_pl.id}.{fmt}"

                    if fmt == "json":
                        content = json.dumps(full_pl.to_dict(), indent=2, ensure_ascii=False)
                    else:
                        content = full_pl.to_m3u8()

                    backup_path.write_text(content, encoding="utf-8")
                    console.print(f"  [green]✓[/green] Backed up '[bold]{full_pl.name}[/]' -> [dim]{backup_path.name}[/dim]")

            # Confirmation prompt
            if not yes:
                prompt_text = (
                    f"[bold red]Are you sure you want to permanently delete {len(target_list)} playlist(s)?[/bold red]"
                )
                if not Confirm.ask(prompt_text, default=False):
                    console.print("[yellow]Deletion cancelled by user.[/yellow]")
                    return

            # Execute deletion
            success_count = 0
            failed_count = 0
            for pl in target_list:
                try:
                    client.delete_playlist(pl.id)
                    console.print(f"  [green]✓[/green] Deleted '[bold]{pl.name}[/]' (ID: {pl.id})")
                    success_count += 1
                except Exception as exc:
                    err_console.print(f"  [red]✗[/red] Failed to delete '[bold]{pl.name}[/]' (ID: {pl.id}): {exc}")
                    failed_count += 1

            if failed_count > 0:
                err_console.print(
                    f"\n[bold yellow]Completed with warnings:[/] {success_count} deleted, {failed_count} failed."
                )
                raise typer.Exit(code=1)
            else:
                console.print(
                    f"\n[bold green]Successfully deleted {success_count} playlist(s).[/bold green]"
                )


@app.command("delete")
def delete_cmd(
    ctx: typer.Context,
    identifiers: Optional[List[str]] = typer.Argument(
        None, help="One or more playlist IDs or exact names"
    ),
    empty: bool = typer.Option(
        False, "--empty", help="Target all playlists with 0 tracks"
    ),
    pattern: Optional[str] = typer.Option(
        None, "--pattern", "-p", help="Target playlists matching a wildcard glob (e.g. 'Temp*')"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview deletions without deleting anything"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip interactive confirmation prompt"
    ),
    backup_dir: Optional[Path] = typer.Option(
        None, "--backup-dir", "-b", help="Backup playlists to directory before deleting"
    ),
    backup_format: str = typer.Option(
        "json", "--backup-format", help="Backup format: 'json' or 'm3u8'"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Override Navidrome password"),
) -> None:
    """Delete one or more playlists with safety guardrails (confirmation, dry-run, backup)."""
    _delete_playlists_impl(
        ctx,
        identifiers=identifiers,
        empty=empty,
        pattern=pattern,
        dry_run=dry_run,
        yes=yes,
        backup_dir=backup_dir,
        backup_format=backup_format,
        url=url,
        user=user,
        password=password,
    )


@app.command("rm", hidden=True)
def rm_cmd(
    ctx: typer.Context,
    identifiers: Optional[List[str]] = typer.Argument(None),
    empty: bool = typer.Option(False, "--empty"),
    pattern: Optional[str] = typer.Option(None, "--pattern", "-p"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    backup_dir: Optional[Path] = typer.Option(None, "--backup-dir", "-b"),
    backup_format: str = typer.Option("json", "--backup-format"),
    url: Optional[str] = typer.Option(None, "--url", "-u"),
    user: Optional[str] = typer.Option(None, "--user", "-U"),
    password: Optional[str] = typer.Option(None, "--password", "-P"),
) -> None:
    """Alias for delete."""
    _delete_playlists_impl(
        ctx,
        identifiers=identifiers,
        empty=empty,
        pattern=pattern,
        dry_run=dry_run,
        yes=yes,
        backup_dir=backup_dir,
        backup_format=backup_format,
        url=url,
        user=user,
        password=password,
    )


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    identifier: str = typer.Argument(
        ..., help="Playlist ID or exact name to export"
    ),
    format: str = typer.Option(
        "json", "--format", "-f", help="Export format: 'json' or 'm3u8'"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Target output file path"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Override Navidrome password"),
) -> None:
    """Export a playlist's metadata and tracklist to .json or .m3u8."""
    with handle_errors():
        fmt = format.lower()
        if fmt not in ("json", "m3u8"):
            raise ConfigError(f"Invalid format '{format}'. Supported formats are 'json' and 'm3u8'.")

        with get_client(ctx, url, user, password) as client:
            target = client.resolve_playlist(identifier)
            playlist = client.get_playlist(target.id)

            if fmt == "json":
                content = json.dumps(playlist.to_dict(), indent=2, ensure_ascii=False)
                ext = ".json"
            else:
                content = playlist.to_m3u8()
                ext = ".m3u8"

            if output:
                out_path = output
            else:
                safe_name = sanitize_filename(playlist.name)
                out_path = Path(f"{safe_name}{ext}")

            if out_path.parent and not out_path.parent.exists():
                out_path.parent.mkdir(parents=True, exist_ok=True)

            out_path.write_text(content, encoding="utf-8")
            console.print(
                f"[green]✓[/green] Exported playlist '[bold]{playlist.name}[/]' "
                f"({len(playlist.tracks)} tracks) to [bold cyan]{out_path}[/bold cyan] ({len(content.encode('utf-8'))} bytes)"
            )


@app.command("update")
def update_cmd(
    ctx: typer.Context,
    identifier: str = typer.Argument(
        ..., help="Playlist ID or exact name to update"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="New playlist name"
    ),
    comment: Optional[str] = typer.Option(
        None, "--comment", "-c", help="New comment / description"
    ),
    public: Optional[bool] = typer.Option(
        None, "--public/--private", help="Set playlist visibility to public or private"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help="Override Navidrome password"),
) -> None:
    """Update basic playlist metadata (name, comment, public/private)."""
    with handle_errors():
        if name is None and comment is None and public is None:
            console.print(
                "[yellow]No update options specified.[/yellow]\n"
                "Provide at least one of: --name, --comment, or --public / --private."
            )
            raise typer.Exit(code=1)

        with get_client(ctx, url, user, password) as client:
            target = client.resolve_playlist(identifier)
            client.update_playlist(
                playlist_id=target.id,
                name=name,
                comment=comment,
                public=public,
            )

            changes = []
            if name is not None:
                changes.append(f"name -> '{name}'")
            if comment is not None:
                changes.append(f"comment -> '{comment}'")
            if public is not None:
                changes.append(f"public -> {public}")

            console.print(
                f"[green]✓[/green] Successfully updated playlist '[bold]{target.name}[/]' ({target.id}):\n"
                f"  {', '.join(changes)}"
            )


if __name__ == "__main__":
    app()
