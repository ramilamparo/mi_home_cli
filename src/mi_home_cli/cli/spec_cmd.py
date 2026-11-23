"""The `mi spec` commands: look up what a device can do."""
from __future__ import annotations

import shutil
import time
from typing import Annotated, Optional

import typer

from .. import render
from ..core.spec import DeviceSpec, SpecStore, unit_symbol
from ..render import OutputFormat
from .context import AppContext, OutputOption, pick_output
from .device import resolve

app = typer.Typer(help="Device capabilities (MIoT spec)", no_args_is_help=True)
cache_app = typer.Typer(help="Spec cache", no_args_is_help=True)
app.add_typer(cache_app, name="cache")


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def load_spec(app_ctx: AppContext, target: str, *, refresh: bool = False):
    """target may be a device (name / alias / did) or a urn directly."""
    store = SpecStore(app_ctx.profile, timeout=app_ctx.timeout)
    if target.startswith("urn:"):
        return None, store.get(target, refresh=refresh)
    device = resolve(app_ctx, target)
    return device, store.get(device.urn, refresh=refresh)


def describe_action_inputs(spec: DeviceSpec, action) -> str:
    """Turn an action's input piids into property names, so the user knows what to pass."""
    names = []
    for piid in action.in_piids:
        prop = spec.property_at(action.siid, piid)
        names.append(prop.name if prop else str(piid))
    return ", ".join(names)


def _property_rows(spec: DeviceSpec) -> list[dict[str, object]]:
    return [
        {
            "Service": prop.service,
            "Property": prop.name,
            "id": prop.ref,
            "Access": prop.access_text(),
            "Type": prop.format,
            "Values": prop.range_text(),
            "Unit": unit_symbol(prop.unit) or "-",
            "Description": prop.description,
        }
        for prop in spec.properties
    ]


@app.command("show")
def spec_show(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Device name, alias, did or urn")],
    siid: Annotated[Optional[int], typer.Option("--siid", help="Only this service")] = None,
    readable: Annotated[bool, typer.Option("--readable", help="Only readable properties")] = False,
    writable: Annotated[bool, typer.Option("--writable", help="Only writable properties")] = False,
    actions: Annotated[bool, typer.Option("--actions", help="List actions instead")] = False,
    refresh: Annotated[bool, typer.Option("--refresh", help="Ignore the cache and "
                                                            "fetch again")] = False,
    output: OutputOption = None,
) -> None:
    """List a device's properties (or actions)."""
    app_ctx = _ctx(ctx)
    device, spec = load_spec(app_ctx, target, refresh=refresh)
    fmt = pick_output(app_ctx, output)

    if actions:
        rows = [
            {
                "Service": action.service,
                "Action": action.name,
                "id": action.ref,
                "Inputs": describe_action_inputs(spec, action) or "-",
                "Description": action.description,
            }
            for action in spec.actions
            if siid is None or action.siid == siid
        ]
        render.output(rows, fmt)
        return

    rows = _property_rows(spec)
    if siid is not None:
        rows = [row for row in rows if row["id"].split(".")[0] == str(siid)]
    if readable:
        rows = [row for row in rows if "r" in row["Access"]]
    if writable:
        rows = [row for row in rows if "w" in row["Access"]]
    if fmt is OutputFormat.table:
        # The value-range column blows the table up in narrow terminals; truncate when
        # there is not enough width
        width = shutil.get_terminal_size((120, 24)).columns
        if width < 140:
            for row in rows:
                text = str(row["Values"])
                if len(text) > 34:
                    row["Values"] = text[:33] + "…"
        title = f"{device.label} · {spec.description}" if device else spec.description
        render.output(rows, fmt, title=title)
        return
    render.output(rows, fmt)


@app.command("search")
def spec_search(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Device name, alias, did or urn")],
    keyword: Annotated[str, typer.Argument(help="Keyword, matched against names and "
                                                "descriptions")],
    output: OutputOption = None,
) -> None:
    """Search a device's properties and actions for a keyword."""
    app_ctx = _ctx(ctx)
    _, spec = load_spec(app_ctx, target)
    needle = keyword.lower()
    rows: list[dict[str, object]] = []
    for prop in spec.properties:
        if needle in f"{prop.full_name} {prop.description}".lower():
            rows.append(
                {
                    "Type": "Property",
                    "Name": prop.full_name,
                    "id": prop.ref,
                    "Access": prop.access_text(),
                    "Description": prop.description,
                    "Values": prop.range_text(),
                }
            )
    for action in spec.actions:
        if needle in f"{action.full_name} {action.description}".lower():
            rows.append(
                {
                    "Type": "Action",
                    "Name": action.full_name,
                    "id": action.ref,
                    "Access": "-",
                    "Description": action.description,
                    "Values": "-",
                }
            )
    render.output(rows, pick_output(app_ctx, output))


@app.command("dump")
def spec_dump(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Device name, alias, did or urn")],
    output: OutputOption = None,
) -> None:
    """Dump the full spec, handy for feeding scripts."""
    app_ctx = _ctx(ctx)
    _, spec = load_spec(app_ctx, target)
    data = {
        "urn": spec.urn,
        "description": spec.description,
        "properties": [
            {
                "siid": p.siid,
                "piid": p.piid,
                "name": p.full_name,
                "description": p.description,
                "format": p.format,
                "access": p.access,
                "unit": p.unit,
                "value_range": p.value_range,
                "value_list": [
                    {"value": v.value, "description": v.description}
                    for v in p.value_list
                ],
            }
            for p in spec.properties
        ],
        "actions": [
            {
                "siid": a.siid,
                "aiid": a.aiid,
                "name": a.full_name,
                "description": a.description,
                "in": a.in_piids,
            }
            for a in spec.actions
        ],
        "events": [
            {
                "siid": e.siid,
                "eiid": e.eiid,
                "name": e.full_name,
                "description": e.description,
            }
            for e in spec.events
        ],
    }
    render.output(data, pick_output(app_ctx, output, default=OutputFormat.json))


@cache_app.command("info")
def cache_info(ctx: typer.Context, output: OutputOption = None) -> None:
    """Show which specs are cached."""
    app_ctx = _ctx(ctx)
    spec_dir = app_ctx.profile.spec_dir
    rows = []
    for path in sorted(spec_dir.glob("*.json")) if spec_dir.is_dir() else []:
        stat = path.stat()
        rows.append(
            {
                "urn": path.stem,
                "Size": f"{stat.st_size / 1024:.0f} KB",
                "Cached at": time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)
                ),
            }
        )
    render.output(rows, pick_output(app_ctx, output))


@cache_app.command("clear")
def cache_clear(ctx: typer.Context) -> None:
    """Clear the spec cache."""
    app_ctx = _ctx(ctx)
    spec_dir = app_ctx.profile.spec_dir
    count = 0
    if spec_dir.is_dir():
        for path in spec_dir.glob("*.json"):
            path.unlink()
            count += 1
    render.success(f"Cleared {count} cached spec(s)")
