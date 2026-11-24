"""CLI commands and Rich output formatting for nd-playlists."""

from contextlib import contextmanager
import fnmatch
import json
from pathlib import Path
import sys
from typing import Generator, List, Optional
import typer
from rich.console import Console
from rich.markup import escape
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

PASSWORD_HELP = (
    "Navidrome password. Note: Prefer using NAVIDROME_PASSWORD, .env, or --password-stdin "
    "to avoid exposing secrets in process lists or shell history."
)

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
    except typer.Exit:
        raise
    except ConfigError as exc:
        err_console.print(f"[bold red]Configuration Error:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1)
    except SubsonicTimeoutError as exc:
        err_console.print(f"[bold red]Timeout Error:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1)
    except SubsonicConnectionError as exc:
        err_console.print(f"[bold red]Connection Error:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1)
    except SubsonicAPIError as exc:
        err_console.print(
            f"[bold red]Subsonic API Error (Code {exc.code}):[/bold red] {escape(exc.message)}"
        )
        raise typer.Exit(code=1)
    except PlaylistAmbiguityError as exc:
        err_console.print(
            f"[bold yellow]Ambiguous Identifier:[/bold yellow] Found {len(exc.matches)} playlists "
            f"with the name '[bold]{escape(exc.identifier)}[/]'.\nPlease specify the target by its unique ID:\n"
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
                escape(match.name),
                escape(match.owner or "N/A"),
                str(match.song_count),
                match.formatted_duration,
            )
        err_console.print(table)
        raise typer.Exit(code=1)
    except PlaylistNotFoundError as exc:
        err_console.print(f"[bold red]Not Found:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1)
    except SubsonicError as exc:
        err_console.print(f"[bold red]Subsonic Error:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1)
    except Exception as exc:
        err_console.print(f"[bold red]Unexpected Error:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1)


def get_client(
    ctx: typer.Context,
    url: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    timeout: Optional[float] = None,
) -> SubsonicClient:
    """Instantiate SubsonicClient using command overrides or global context settings."""
    cb_data = ctx.obj or {}
    resolved_url = url or cb_data.get("url")
    resolved_user = user or cb_data.get("user")
    resolved_password = password or cb_data.get("password")
    resolved_timeout = timeout if timeout is not None else cb_data.get("timeout", 10.0)
    env_file = cb_data.get("env_file")

    config = load_config(
        url=resolved_url,
        user=resolved_user,
        password=resolved_password,
        timeout=resolved_timeout,
        env_file=env_file,
    )
    return SubsonicClient(config)


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """Sanitize a playlist name or ID for safe filesystem storage (guarding against traversal and length limits)."""
    safe = "".join(c if (c.isalnum() or c in (" ", ".", "_", "-")) else "_" for c in name)
    safe = safe.strip(" .")
    if not safe or safe in (".", ".."):
        return "playlist"
    if len(safe) > max_length:
        safe = safe[:max_length].rstrip(" .")
        if not safe:
            return "playlist"
    return safe


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
        None, "--password", "-P", help=PASSWORD_HELP
    ),
    password_stdin: bool = typer.Option(
        False, "--password-stdin", help="Read Navidrome password from standard input"
    ),
    env_file: Optional[Path] = typer.Option(
        None, "--env-file", help="Path to custom .env file to load configuration from"
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
    resolved_password = password
    if password_stdin:
        resolved_password = sys.stdin.read().rstrip("\r\n")

    ctx.obj["url"] = url
    ctx.obj["user"] = user
    ctx.obj["password"] = resolved_password
    ctx.obj["timeout"] = timeout
    ctx.obj["env_file"] = env_file


@app.command("ping")
def ping_cmd(
    ctx: typer.Context,
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help=PASSWORD_HELP),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Override HTTP request timeout in seconds"),
) -> None:
    """Verify server connectivity, authentication, and Subsonic API details."""
    with handle_errors():
        with get_client(ctx, url, user, password, timeout) as client:
            info = client.ping()

            table = Table(title="Navidrome Server Connectivity", border_style="green")
            table.add_column("Property", style="bold cyan")
            table.add_column("Value", style="bold white")

            table.add_row("Server URL", escape(client.config.url))
            table.add_row("User", escape(client.config.user))
            table.add_row("Status", "[bold green]Connected (OK)[/bold green]")
            table.add_row("Server Type", escape(str(info.get("type", "navidrome"))))
            table.add_row("Server Version", escape(str(info.get("serverVersion", "unknown"))))
            table.add_row("Subsonic API Version", escape(str(info.get("version", "1.16.1"))))
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
    timeout: Optional[float] = None,
) -> None:
    with handle_errors():
        with get_client(ctx, url, user, password, timeout) as client:
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
                    escape(pl.name),
                    tracks_str,
                    pl.formatted_duration,
                    escape(pl.owner or "-"),
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
    password: Optional[str] = typer.Option(None, "--password", "-P", help=PASSWORD_HELP),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Override HTTP request timeout in seconds"),
) -> None:
    """Fetch and list playlists with optional search, empty, and owner filters."""
    _list_playlists_impl(ctx, search, empty, owner, url, user, password, timeout)


@app.command("ls", hidden=True)
def ls_cmd(
    ctx: typer.Context,
    search: Optional[str] = typer.Option(None, "--search", "-s"),
    empty: bool = typer.Option(False, "--empty"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o"),
    url: Optional[str] = typer.Option(None, "--url", "-u"),
    user: Optional[str] = typer.Option(None, "--user", "-U"),
    password: Optional[str] = typer.Option(None, "--password", "-P"),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t"),
) -> None:
    """Alias for list."""
    _list_playlists_impl(ctx, search, empty, owner, url, user, password, timeout)


@app.command("show")
def show_cmd(
    ctx: typer.Context,
    identifier: str = typer.Argument(
        ..., help="Playlist ID or case-insensitive exact name"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help=PASSWORD_HELP),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Override HTTP request timeout in seconds"),
) -> None:
    """Show details and tracklist for a playlist by ID or exact name."""
    with handle_errors():
        with get_client(ctx, url, user, password, timeout) as client:
            target = client.resolve_playlist(identifier)
            playlist = client.get_playlist(target.id)

            metadata_lines = [
                f"[bold cyan]ID:[/bold cyan] {escape(playlist.id)}",
                f"[bold cyan]Owner:[/bold cyan] {escape(playlist.owner or 'N/A')}",
                f"[bold cyan]Tracks:[/bold cyan] {playlist.song_count}",
                f"[bold cyan]Total Duration:[/bold cyan] {playlist.formatted_duration}",
                f"[bold cyan]Public:[/bold cyan] {'Yes' if playlist.public else 'No'}",
                f"[bold cyan]Last Modified:[/bold cyan] {playlist.formatted_changed}",
            ]
            if playlist.comment:
                metadata_lines.append(f"[bold cyan]Comment:[/bold cyan] [italic]{escape(playlist.comment)}[/italic]")

            console.print(
                Panel(
                    "\n".join(metadata_lines),
                    title=f"[bold white]Playlist: {escape(playlist.name)}[/bold white]",
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
                table.add_row(
                    str(idx),
                    escape(track.title),
                    escape(track.display_artist),
                    escape(track.display_album),
                    track.formatted_duration,
                )

            console.print(table)


def _delete_playlists_impl(
    ctx: typer.Context,
    identifiers: Optional[List[str]] = None,
    empty: bool = False,
    pattern: Optional[str] = None,
    all_owners: bool = False,
    dry_run: bool = False,
    yes: bool = False,
    backup_dir: Optional[Path] = None,
    backup_format: str = "json",
    url: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    timeout: Optional[float] = None,
) -> None:
    with handle_errors():
        # 1. Validate backup format upfront before touching filesystem, network, or prompting
        fmt = backup_format.lower()
        if backup_dir and fmt not in ("json", "m3u8"):
            raise ConfigError(f"Unsupported backup format: '{backup_format}'. Choose 'json' or 'm3u8'.")

        with get_client(ctx, url, user, password, timeout) as client:
            all_playlists = client.get_playlists()
            targets: dict[str, Playlist] = {}

            # 2. Match positional identifiers (explicit targets, ignore owner filtering)
            if identifiers:
                for ident in identifiers:
                    target = client.resolve_playlist(ident, playlists=all_playlists)
                    targets[target.id] = target

            # 3. Match bulk filter flags (--empty and/or --pattern) with logical AND
            if empty or pattern:
                for p in all_playlists:
                    # Prevent accidental deletion of other users' playlists unless --all-owners is passed
                    if not all_owners:
                        if not p.owner or p.owner.lower() != client.config.user.lower():
                            continue
                    if empty and p.song_count > 0:
                        continue
                    if pattern and not fnmatch.fnmatch(p.name.lower(), pattern.lower()):
                        continue
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
                    escape(pl.name),
                    str(pl.song_count),
                    pl.formatted_duration,
                    escape(pl.owner or "-"),
                )

            console.print(table)

            if dry_run:
                console.print(
                    f"\n[bold yellow]DRY RUN ACTIVE:[/] Would delete {len(target_list)} playlist(s). "
                    "No changes were made."
                )
                return

            # 4. Confirmation prompt MUST occur before backup download/writing and deletion
            if not yes:
                prompt_text = (
                    f"[bold red]Are you sure you want to permanently delete {len(target_list)} playlist(s)?[/bold red]"
                )
                if not Confirm.ask(prompt_text, default=False):
                    console.print("[yellow]Deletion cancelled by user.[/yellow]")
                    return

            # 5. Perform backup if requested and confirmed
            if backup_dir:
                backup_dir.mkdir(parents=True, exist_ok=True)
                console.print(f"[dim]Backing up {len(target_list)} playlist(s) to {backup_dir}...[/dim]")
                for pl in target_list:
                    full_pl = client.get_playlist(pl.id)
                    safe_name = sanitize_filename(full_pl.name)
                    safe_id = sanitize_filename(full_pl.id)
                    backup_path = backup_dir / f"{safe_name}_{safe_id}.{fmt}"

                    if fmt == "json":
                        content = json.dumps(full_pl.to_dict(), indent=2, ensure_ascii=False)
                    else:
                        content = full_pl.to_m3u8()

                    backup_path.write_text(content, encoding="utf-8")
                    console.print(f"  [green]✓[/green] Backed up '[bold]{escape(full_pl.name)}[/]' -> [dim]{escape(backup_path.name)}[/dim]")

            # 6. Execute deletion
            success_count = 0
            failed_count = 0
            for pl in target_list:
                try:
                    client.delete_playlist(pl.id)
                    console.print(f"  [green]✓[/green] Deleted '[bold]{escape(pl.name)}[/]' (ID: {escape(pl.id)})")
                    success_count += 1
                except Exception as exc:
                    err_console.print(f"  [red]✗[/red] Failed to delete '[bold]{escape(pl.name)}[/]' (ID: {escape(pl.id)}): {escape(str(exc))}")
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
    all_owners: bool = typer.Option(
        False, "--all-owners", help="Allow matching playlists owned by other users when filtering"
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
    password: Optional[str] = typer.Option(None, "--password", "-P", help=PASSWORD_HELP),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Override HTTP request timeout in seconds"),
) -> None:
    """Delete one or more playlists with safety guardrails (confirmation, dry-run, backup)."""
    _delete_playlists_impl(
        ctx,
        identifiers=identifiers,
        empty=empty,
        pattern=pattern,
        all_owners=all_owners,
        dry_run=dry_run,
        yes=yes,
        backup_dir=backup_dir,
        backup_format=backup_format,
        url=url,
        user=user,
        password=password,
        timeout=timeout,
    )


@app.command("rm", hidden=True)
def rm_cmd(
    ctx: typer.Context,
    identifiers: Optional[List[str]] = typer.Argument(None),
    empty: bool = typer.Option(False, "--empty"),
    pattern: Optional[str] = typer.Option(None, "--pattern", "-p"),
    all_owners: bool = typer.Option(False, "--all-owners"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    backup_dir: Optional[Path] = typer.Option(None, "--backup-dir", "-b"),
    backup_format: str = typer.Option("json", "--backup-format"),
    url: Optional[str] = typer.Option(None, "--url", "-u"),
    user: Optional[str] = typer.Option(None, "--user", "-U"),
    password: Optional[str] = typer.Option(None, "--password", "-P"),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t"),
) -> None:
    """Alias for delete."""
    _delete_playlists_impl(
        ctx,
        identifiers=identifiers,
        empty=empty,
        pattern=pattern,
        all_owners=all_owners,
        dry_run=dry_run,
        yes=yes,
        backup_dir=backup_dir,
        backup_format=backup_format,
        url=url,
        user=user,
        password=password,
        timeout=timeout,
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
    force: bool = typer.Option(
        False, "--force", "-F", help="Overwrite existing output file"
    ),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Override Navidrome server URL"),
    user: Optional[str] = typer.Option(None, "--user", "-U", help="Override Navidrome username"),
    password: Optional[str] = typer.Option(None, "--password", "-P", help=PASSWORD_HELP),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Override HTTP request timeout in seconds"),
) -> None:
    """Export a playlist's metadata and tracklist to .json or .m3u8."""
    with handle_errors():
        fmt = format.lower()
        if fmt not in ("json", "m3u8"):
            raise ConfigError(f"Invalid format '{format}'. Supported formats are 'json' and 'm3u8'.")

        with get_client(ctx, url, user, password, timeout) as client:
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

            if out_path.is_dir():
                raise ConfigError(
                    f"Target output path '{out_path}' is an existing directory, not a file."
                )

            if out_path.exists() and not force:
                raise ConfigError(
                    f"Target output file '{out_path}' already exists. Use --force / -F to overwrite."
                )

            if out_path.parent and not out_path.parent.exists():
                out_path.parent.mkdir(parents=True, exist_ok=True)

            out_path.write_text(content, encoding="utf-8")
            console.print(
                f"[green]✓[/green] Exported playlist '[bold]{escape(playlist.name)}[/]' "
                f"({len(playlist.tracks)} tracks) to [bold cyan]{escape(str(out_path))}[/bold cyan] ({len(content.encode('utf-8'))} bytes)"
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
    password: Optional[str] = typer.Option(None, "--password", "-P", help=PASSWORD_HELP),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Override HTTP request timeout in seconds"),
) -> None:
    """Update basic playlist metadata (name, comment, public/private)."""
    with handle_errors():
        if name is None and comment is None and public is None:
            console.print(
                "[yellow]No update options specified.[/yellow]\n"
                "Provide at least one of: --name, --comment, or --public / --private."
            )
            raise typer.Exit(code=1)

        with get_client(ctx, url, user, password, timeout) as client:
            target = client.resolve_playlist(identifier)
            client.update_playlist(
                playlist_id=target.id,
                name=name,
                comment=comment,
                public=public,
            )

            changes = []
            if name is not None:
                changes.append(f"name -> '{escape(name)}'")
            if comment is not None:
                changes.append(f"comment -> '{escape(comment)}'")
            if public is not None:
                changes.append(f"public -> {public}")

            console.print(
                f"[green]✓[/green] Successfully updated playlist '[bold]{escape(target.name)}[/]' ({escape(target.id)}):\n"
                f"  {', '.join(changes)}"
            )


if __name__ == "__main__":
    app()
