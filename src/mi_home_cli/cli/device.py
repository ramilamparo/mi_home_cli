"""The `mi home` / `mi room` / `mi device` commands."""
from __future__ import annotations

import time
from typing import Annotated, Optional

import typer

from .. import render
from ..core.cloud import CloudApi
from ..core.registry import Device, Registry
from ..errors import DeviceNotFound, UsageError
from ..render import mask
from ..store import read_config, write_config
from .context import AppContext, OutputOption, pick_output

app = typer.Typer(help="Device list", no_args_is_help=True)
home_app = typer.Typer(help="Home", no_args_is_help=True)
room_app = typer.Typer(help="Room", no_args_is_help=True)
alias_app = typer.Typer(help="Device aliases", no_args_is_help=True)
app.add_typer(alias_app, name="alias")

# Once the cache is older than this, remind the user before using it (no automatic
# refresh, which would slow every command down)
STALE_AFTER = 7 * 24 * 3600


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def sync(app_ctx: AppContext) -> Registry:
    """Fetch the lists from the cloud again and persist them."""
    with app_ctx.session() as session:
        data = CloudApi(session).fetch_all()
        # Only gethome returns the uid, it is not available at login; add it to the
        # credentials while we are here
        if data.get("uid") and session.auth.uid != data["uid"]:
            auth = session.auth
            auth.uid = data["uid"]
            app_ctx.profile.write_auth(auth)
    registry = Registry.write(app_ctx.profile, data)
    render.info(
        f"[dim]Synced {len(registry.devices)} device(s), {len(registry.homes)} "
        "home(s)[/dim]"
    )
    return registry


def load_registry(app_ctx: AppContext, *, refresh: bool = False) -> Registry:
    """Get the device list: prefer the cache, sync once automatically if there is none."""
    if not refresh:
        registry = Registry.read(app_ctx.profile)
        if registry is not None:
            if registry.age > STALE_AFTER:
                render.warn(
                    f"The device cache is {registry.age // 86400} day(s) old; run `mi "
                    "device sync` to refresh if needed"
                )
            return registry
        render.info("[dim]No local device cache yet, syncing…[/dim]")
    return sync(app_ctx)


def resolve(app_ctx: AppContext, ref: str, **filters: object) -> Device:
    """Resolve a device, by default only within the default home.

    When it is found in another home, do not silently operate across homes — exactly
    what setting a default home is meant to prevent — but tell the user explicitly
    where it is and how to get around it.
    """
    registry = load_registry(app_ctx)
    scope = {**app_ctx.home_filter(), **filters}
    try:
        return registry.resolve(ref, **scope)
    except DeviceNotFound:
        home = app_ctx.default_home()
        if not home or "home_id" in filters:
            raise
        elsewhere = registry.filter(search=ref)
        if not elsewhere:
            raise
        names = ", ".join(
            f"{d.home_name}/{d.room_name or '-'}: {d.label}" for d in elsewhere[:5]
        )
        raise DeviceNotFound(
            f"The default home \"{home['name']}\" has no `{ref}`, but it was found in "
            f"{names}.",
            hint="Add --all-homes to work across homes, or switch the default home "
                 "with `mi home use`",
        ) from None


@home_app.command("list")
def home_list(ctx: typer.Context, output: OutputOption = None) -> None:
    """List homes."""
    app_ctx = _ctx(ctx)
    registry = load_registry(app_ctx)
    counts: dict[str, int] = {}
    for device in registry.devices:
        counts[device.home_id] = counts.get(device.home_id, 0) + 1
    default = app_ctx.default_home()
    fmt = pick_output(app_ctx, output)
    if fmt.value in ("json", "yaml"):
        render.output(
            [
                {
                    "home_id": home["home_id"],
                    "name": home["home_name"],
                    "rooms": len(home.get("rooms") or []),
                    "devices": counts.get(home["home_id"], 0),
                    "shared": bool(home.get("shared")),
                    "default": bool(default and default["id"] == home["home_id"]),
                }
                for home in registry.homes
            ],
            fmt,
        )
        return
    rows = [
        {
            "Home": home["home_name"]
            + (" *" if default and default["id"] == home["home_id"] else ""),
            "Rooms": len(home.get("rooms") or []),
            "Devices": counts.get(home["home_id"], 0),
            "Shared": "yes" if home.get("shared") else "no",
            "home_id": home["home_id"],
        }
        for home in registry.homes
    ]
    render.output(rows, fmt)


@room_app.command("list")
def room_list(
    ctx: typer.Context,
    home: Annotated[Optional[str], typer.Option("--home", help="Only this home")] = None,
    output: OutputOption = None,
) -> None:
    """List rooms."""
    app_ctx = _ctx(ctx)
    registry = load_registry(app_ctx)
    counts: dict[tuple[str, str], int] = {}
    for device in registry.devices:
        key = (device.home_id, device.room_id)
        counts[key] = counts.get(key, 0) + 1
    default = None if home else app_ctx.default_home()
    fmt = pick_output(app_ctx, output)
    rows = []
    for item in registry.homes:
        if home and home.lower() not in item["home_name"].lower():
            continue
        if default and default["id"] != item["home_id"]:
            continue
        for room in item.get("rooms") or []:
            count = counts.get((item["home_id"], room["room_id"]), 0)
            rows.append(
                {
                    "home_id": item["home_id"],
                    "home": item["home_name"],
                    "room_id": room["room_id"],
                    "room": room["room_name"],
                    "devices": count,
                }
                if fmt.value in ("json", "yaml")
                else {
                    "Home": item["home_name"],
                    "Room": room["room_name"],
                    "Devices": count,
                    "room_id": room["room_id"],
                }
            )
    render.output(rows, fmt)


@app.command("list")
def device_list(
    ctx: typer.Context,
    home: Annotated[Optional[str], typer.Option("--home", help="Only this home")] = None,
    room: Annotated[Optional[str], typer.Option("--room", help="Only this room")] = None,
    model: Annotated[Optional[str], typer.Option("--model", help="Only this model")] = None,
    search: Annotated[
        Optional[str], typer.Option("--search", "-s", help="Search by name / model")
    ] = None,
    online: Annotated[
        Optional[bool],
        typer.Option("--online/--offline", help="Only online / offline devices"),
    ] = None,
    wide: Annotated[
        bool, typer.Option("--wide", "-w", help="Also show did, IP and firmware")
    ] = False,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Refresh the cache from the cloud first")
    ] = False,
    output: OutputOption = None,
) -> None:
    """List devices."""
    app_ctx = _ctx(ctx)
    registry = load_registry(app_ctx, refresh=refresh)
    scope = {} if home else app_ctx.home_filter()
    devices = registry.filter(
        home=home, room=room, model=model, online=online, search=search, **scope
    )
    fmt = pick_output(app_ctx, output)
    if fmt.value in ("json", "yaml"):
        render.output(
            [
                {**device.to_json(), "token": mask(device.token)}
                for device in devices
            ],
            fmt,
        )
        return
    render.output([device.summary(wide=wide) for device in devices], fmt)
    if fmt.value == "table":
        current = None if home else app_ctx.default_home()
        note = f", showing only \"{current['name']}\"; add --all-homes to see everything" if current else ""
        render.info(f"[dim]{len(devices)} device(s) in total{note}[/dim]")


@app.command("show")
def device_show(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    output: OutputOption = None,
) -> None:
    """Show the details of one device."""
    app_ctx = _ctx(ctx)
    target = resolve(app_ctx, device)
    fmt = pick_output(app_ctx, output)
    if fmt.value in ("json", "yaml"):
        render.output({**target.to_json(), "token": mask(target.token)}, fmt)
        return
    render.output(target.detail(), fmt)


@app.command("sync")
def device_sync(ctx: typer.Context) -> None:
    """Re-fetch homes, rooms and the device list from the cloud."""
    app_ctx = _ctx(ctx)
    started = time.time()
    registry = sync(app_ctx)
    render.success(
        f"Sync complete: {len(registry.devices)} device(s) in "
        f"{time.time() - started:.1f}s"
    )


@app.command("token")
def device_token(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    show: Annotated[
        bool, typer.Option("--show-secrets", help="Show in plain text (masked by "
                                                  "default)")
    ] = False,
) -> None:
    """Print a device's LAN token."""
    app_ctx = _ctx(ctx)
    target = resolve(app_ctx, device)
    if not target.token:
        raise UsageError(f"{target.label} has no LAN token")
    print(target.token if show else mask(target.token))


@alias_app.command("set")
def alias_set(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name or did")],
    alias: Annotated[str, typer.Argument(help="Alias to set")],
) -> None:
    """Give a device a short name."""
    app_ctx = _ctx(ctx)
    target = resolve(app_ctx, device)
    aliases = app_ctx.profile.read_aliases()
    aliases[alias] = target.did
    app_ctx.profile.write_aliases(aliases)
    render.success(f"{target.label} → alias `{alias}`")


@alias_app.command("list")
def alias_list(ctx: typer.Context, output: OutputOption = None) -> None:
    """List all aliases."""
    app_ctx = _ctx(ctx)
    registry = load_registry(app_ctx)
    by_did = {device.did: device for device in registry.devices}
    rows = [
        {
            "Alias": alias,
            "Device": by_did[did].name if did in by_did else "(no longer in the device "
                                                         "list)",
            "did": did,
        }
        for alias, did in sorted(app_ctx.profile.read_aliases().items())
    ]
    render.output(rows, pick_output(app_ctx, output))


@alias_app.command("rm")
def alias_rm(ctx: typer.Context, alias: str) -> None:
    """Delete an alias."""
    app_ctx = _ctx(ctx)
    aliases = app_ctx.profile.read_aliases()
    if alias not in aliases:
        raise UsageError(f"Alias `{alias}` does not exist")
    aliases.pop(alias)
    app_ctx.profile.write_aliases(aliases)
    render.success(f"Deleted alias `{alias}`")


@home_app.command("use")
def home_use(
    ctx: typer.Context,
    name: Annotated[
        Optional[str], typer.Argument(help="Home name or home_id; shows the current "
                                           "default when omitted")
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="Clear the default home and go back to all "
                                           "homes")
    ] = False,
) -> None:
    """Set the default home. Once set, device lookup, device list and room list only look at this home."""
    app_ctx = _ctx(ctx)
    config = read_config(app_ctx.root)

    if clear:
        config.pop("home", None)
        write_config(config, app_ctx.root)
        render.success("Default home cleared; devices of all homes are now visible")
        return

    if not name:
        current = app_ctx.default_home()
        if current:
            render.info(f"Current default home: {current['name']} ({current['id']})")
        else:
            render.info("No default home has been set; devices of all homes are visible")
        return

    home = load_registry(app_ctx).find_home(name)
    config["home"] = {"id": home["home_id"], "name": home["home_name"]}
    write_config(config, app_ctx.root)
    render.success(f"Default home set to \"{home['home_name']}\"")


def _clear_default_home(app_ctx: AppContext) -> bool:
    """Remove the default home from the config; returns whether one was set before."""
    config = read_config(app_ctx.root)
    if config.pop("home", None) is None:
        return False
    write_config(config, app_ctx.root)
    return True


@home_app.command("unset")
def home_unset(ctx: typer.Context) -> None:
    """Clear the default home and go back to all homes (same as `mi home use --clear`)."""
    app_ctx = _ctx(ctx)
    if _clear_default_home(app_ctx):
        render.success("Default home cleared; devices of all homes are now visible")
    else:
        render.info("No default home is set; devices of all homes are visible")


@home_app.command("select")
def home_select(ctx: typer.Context) -> None:
    """Pick the default home interactively (or choose to clear it)."""
    app_ctx = _ctx(ctx)
    homes = load_registry(app_ctx).homes
    if not homes:
        raise UsageError(
            "No homes to choose from", hint="Run `mi device sync` first to sync from the cloud"
        )
    if not render.is_tty():
        raise UsageError(
            "select needs an interactive terminal",
            hint="In scripts use `mi home use <home>` or `mi home unset`",
        )

    default = app_ctx.default_home()
    counts: dict[str, int] = {}
    for device in load_registry(app_ctx).devices:
        counts[device.home_id] = counts.get(device.home_id, 0) + 1

    render.info("Choose the default home:")
    for index, home in enumerate(homes, start=1):
        mark = " *" if default and default["id"] == home["home_id"] else ""
        render.info(
            f"  {index}. {home['home_name']}{mark} ({counts.get(home['home_id'], 0)} "
            "device(s))"
        )
    render.info("  0. No default home (all homes visible)")

    choice = typer.prompt("Enter a number", type=int)
    if choice == 0:
        if _clear_default_home(app_ctx):
            render.success("Default home cleared; devices of all homes are now visible")
        else:
            render.info("No default home is set; devices of all homes are visible")
        return
    if not 1 <= choice <= len(homes):
        raise UsageError(f"Number {choice} is out of range (0–{len(homes)})")

    home = homes[choice - 1]
    config = read_config(app_ctx.root)
    config["home"] = {"id": home["home_id"], "name": home["home_name"]}
    write_config(config, app_ctx.root)
    render.success(f"Default home set to \"{home['home_name']}\"")
