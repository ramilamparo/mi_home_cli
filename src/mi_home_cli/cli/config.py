"""`mi config`: default settings."""
from __future__ import annotations

from typing import Annotated, Any

import typer

from .. import render
from ..core import const
from ..errors import UsageError
from ..render import OutputFormat
from ..store import read_config, write_config
from .context import AppContext, OutputOption, pick_output

app = typer.Typer(help="Default settings", no_args_is_help=True)

# Configurable keys, each with its own validation / conversion
KEYS = {
    "profile": "Default profile",
    "region": "Default region: " + "/".join(const.CLOUD_SERVERS),
    "output": "Default output format: table/json/yaml/plain",
    "home": "Default home (same as mi home use)",
    "channel": "Default control channel: cloud / auto / lan",
    "scan_device_name": "Name shown under Xiaomi's \"logged-in devices\" for QR "
                        "logins (default: mi-home-cli/version)",
}

CHANNELS = ("cloud", "auto", "lan")


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _check_key(key: str) -> None:
    if key not in KEYS:
        raise UsageError(
            f"Unknown config key `{key}`",
            hint="Available keys: " + ", ".join(KEYS),
        )


def _coerce(app_ctx: AppContext, key: str, value: str) -> Any:
    if key == "region":
        if value not in const.CLOUD_SERVERS:
            raise UsageError(f"Unknown region `{value}`; choose from: "
                             f"{', '.join(const.CLOUD_SERVERS)}")
        return value
    if key == "output":
        try:
            return OutputFormat(value).value
        except ValueError as err:
            raise UsageError(f"Unknown output format `{value}`") from err
    if key == "channel":
        if value not in CHANNELS:
            raise UsageError(f"Unknown channel `{value}`; choose from: "
                             f"{', '.join(CHANNELS)}")
        return value
    if key == "home":
        # Store id + name: filtering by id survives renames, the name is for display
        from .device import load_registry

        home = load_registry(app_ctx).find_home(value)
        return {"id": home["home_id"], "name": home["home_name"]}
    if key == "scan_device_name":
        # This value is sent as the HTTP User-Agent, and HTTP headers can only be
        # ASCII/Latin-1; characters such as CJK cannot travel in a UA, so reject them
        # here with a clear explanation.
        value = value.strip()
        if not value:
            raise UsageError("The device name must not be empty")
        try:
            value.encode("latin-1")
        except UnicodeEncodeError as err:
            raise UsageError(
                "The device name must be ASCII only (it is sent as the HTTP "
                "User-Agent, which cannot carry non-ASCII characters)"
            ) from err
        return value
    return value


def _display(value: Any) -> str:
    if isinstance(value, dict) and "name" in value:
        return f"{value['name']} ({value.get('id', '')})"
    return str(value)


@app.command("list")
def config_list(ctx: typer.Context, output: OutputOption = None) -> None:
    """List all config keys."""
    app_ctx = _ctx(ctx)
    config = read_config(app_ctx.root)
    rows = [
        {
            "Key": key,
            "Value": _display(config[key]) if key in config else "-",
            "Description": description,
        }
        for key, description in KEYS.items()
    ]
    render.output(rows, pick_output(app_ctx, output))
    render.info(f"[dim]Config file: {app_ctx.root / 'config.json'}[/dim]")


@app.command("get")
def config_get(ctx: typer.Context, key: Annotated[str, typer.Argument()]) -> None:
    """Read a config key."""
    app_ctx = _ctx(ctx)
    _check_key(key)
    value = read_config(app_ctx.root).get(key)
    print(_display(value) if value is not None else "")


@app.command("set")
def config_set(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument()],
    value: Annotated[str, typer.Argument()],
) -> None:
    """Set a config key."""
    app_ctx = _ctx(ctx)
    _check_key(key)
    config = read_config(app_ctx.root)
    config[key] = _coerce(app_ctx, key, value)
    write_config(config, app_ctx.root)
    render.success(f"{key} = {_display(config[key])}")


@app.command("unset")
def config_unset(ctx: typer.Context, key: Annotated[str, typer.Argument()]) -> None:
    """Unset a config key."""
    app_ctx = _ctx(ctx)
    _check_key(key)
    config = read_config(app_ctx.root)
    if config.pop(key, None) is None:
        render.info(f"{key} was not set")
        return
    write_config(config, app_ctx.root)
    render.success(f"Cleared {key}")


@app.command("path")
def config_path(ctx: typer.Context) -> None:
    """Print the config directory."""
    print(_ctx(ctx).root)
