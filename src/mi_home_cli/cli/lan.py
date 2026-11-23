"""`mi lan`: discovery and probing for direct LAN control."""
from __future__ import annotations

import json
import time
from typing import Annotated, Optional

import typer

from .. import render
from ..core import lan as lan_core
from ..core.channel import (
    LAN_CAPABLE_TYPES,
    clear_lan_failures,
    lan_capable,
    lan_failure,
    locate,
)
from ..errors import MiCliError
from ..render import OutputFormat
from .context import AppContext, OutputOption, pick_output
from .device import load_registry, resolve

app = typer.Typer(help="Direct LAN control", no_args_is_help=True)


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


@app.command("discover")
def lan_discover(
    ctx: typer.Context,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Seconds to wait for replies")
    ] = 3.0,
    address: Annotated[
        Optional[str],
        typer.Option("--address", help="Broadcast address, default 255.255.255.255"),
    ] = None,
    output: OutputOption = None,
) -> None:
    """Broadcast-scan the LAN for Mi Home devices and match them to the device list."""
    app_ctx = _ctx(ctx)
    found = lan_core.discover(timeout, address or lan_core.BROADCAST)
    if not found:
        render.warn("No device replied")
        render.info(
            "[dim]Check: same subnet as the devices? AP isolation enabled on the "
            "router? On macOS allow the terminal under System Settings → Privacy & "
            "Security → Local Network[/dim]"
        )
        return

    registry = load_registry(app_ctx)
    by_did = {device.did: device for device in registry.devices}
    cache = app_ctx.profile.read_lan()
    cache.update(
        {
            did: {"ip": item.ip, "seen_at": int(time.time())}
            for did, item in found.items()
        }
    )
    app_ctx.profile.write_lan(cache)
    # Being found again counts as new evidence: clear the "this device cannot work over
    # the LAN" mark
    clear_lan_failures(app_ctx.profile)

    rows = []
    for did, endpoint in sorted(found.items(), key=lambda kv: kv[1].ip):
        device = by_did.get(did)
        rows.append(
            {
                "Device": device.label if device else "(not in the device list)",
                "Room": (device.room_name or "-") if device else "-",
                "IP": endpoint.ip,
                "did": did,
                # In a broadcast scan this number includes queueing time and is not
                # round-trip latency, so do not call it "latency"
                "Reply time": f"{endpoint.elapsed_ms:.0f}ms",
                "Model": device.model if device else "-",
            }
        )
    render.output(rows, pick_output(app_ctx, output))
    render.info(f"[dim]{len(rows)} device(s) replied; addresses cached in "
                f"{app_ctx.profile.lan_path}[/dim]")


@app.command("status")
def lan_status(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    output: OutputOption = None,
) -> None:
    """Check whether a device can be reached directly, at which IP and how fast."""
    app_ctx = _ctx(ctx)
    target = resolve(app_ctx, device)
    data: dict[str, object] = {
        "Device": target.label,
        "did": target.did,
        "connect_type": target.connect_type,
        "LAN capable": "yes" if lan_capable(target) else "no",
    }
    if not lan_capable(target):
        data["Reason"] = (
            "no LAN token"
            if not target.token
            else f"connect_type is not one of {sorted(LAN_CAPABLE_TYPES)} (the device goes through a gateway)"
        )
        render.output(data, pick_output(app_ctx, output))
        return

    endpoint = locate(app_ctx.profile, target)
    if endpoint is None:
        data["Reachable"] = "no"
        data["Hint"] = "Same subnet? Device online? Run `mi lan discover` first"
    else:
        data["Reachable"] = "yes"
        data["IP"] = endpoint.ip
        data["Latency"] = (
            f"{endpoint.elapsed_ms:.0f}ms"
            if endpoint.is_rtt
            else f"{endpoint.elapsed_ms:.0f}ms (broadcast reply time, not round-trip latency)"
        )
        data["Device stamp"] = endpoint.stamp
    failure = lan_failure(app_ctx.profile, target.did)
    if failure:
        failed_at, reason = failure
        data["Last LAN call"] = (
            f"failed: {reason} ({time.strftime('%m-%d %H:%M', time.localtime(failed_at))})"
        )
        data["Description"] = "auto mode goes straight to the cloud; `mi lan discover` clears this mark"
    render.output(data, pick_output(app_ctx, output))


@app.command("raw")
def lan_raw(
    ctx: typer.Context,
    device: Annotated[
        str, typer.Argument(help="Device name, alias or did (quote names containing "
                                 "spaces)")
    ],
    method: Annotated[
        str, typer.Argument(help="miIO method name, e.g. miIO.info / get_properties")
    ],
    params: Annotated[
        Optional[str], typer.Option("--params", help="Parameters, as JSON")
    ] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="Seconds to wait")] = 5.0,
    output: OutputOption = None,
) -> None:
    """Send a raw miIO request straight to a device.

    For troubleshooting: every miIO device implements `miIO.info`, so it tells
    "is the protocol working" apart from "does the device support this method".
    """
    app_ctx = _ctx(ctx)
    target = resolve(app_ctx, device)
    if not target.token:
        raise MiCliError(f"{target.label} has no LAN token")
    endpoint = locate(app_ctx.profile, target)
    if endpoint is None:
        raise MiCliError(f"Cannot find {target.label} on the LAN; run `mi lan "
                         "discover` first")

    try:
        parsed = json.loads(params) if params else []
    except json.JSONDecodeError as err:
        raise MiCliError(f"--params is not valid JSON: {err}") from err

    lan = lan_core.LanDevice(target.did, target.token, endpoint)
    result = lan.call(method, parsed, timeout=timeout)
    render.output(
        result if isinstance(result, (dict, list)) else {"result": result},
        pick_output(app_ctx, output, default=OutputFormat.json),
    )


@app.command("list")
def lan_list(ctx: typer.Context, output: OutputOption = None) -> None:
    """List which devices in the device list should support direct LAN control."""
    app_ctx = _ctx(ctx)
    registry = load_registry(app_ctx)
    scope = app_ctx.home_filter()
    rows = [
        {
            "Device": device.label,
            "Room": device.room_name or "-",
            "Model": device.model,
            "connect_type": device.connect_type,
            "LAN capable": "yes" if lan_capable(device) else "no",
            "Online": "yes" if device.online else "no",
        }
        for device in registry.filter(**scope)
    ]
    rows.sort(key=lambda row: (row["LAN capable"] != "yes", str(row["Device"])))
    render.output(rows, pick_output(app_ctx, output))
    supported = sum(1 for row in rows if row["LAN capable"] == "yes")
    render.info(f"[dim]{supported} / {len(rows)} device(s) support direct LAN "
                "control[/dim]")
