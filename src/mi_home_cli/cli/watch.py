"""`mi watch`: watch devices change in real time.

Uses a long-lived cloud MQTT connection, not polling — a line appears the moment a
property changes, an event fires, or a device goes online or offline.
"""
from __future__ import annotations

import json
import queue
import time
from typing import Annotated, Any, Optional

import typer

from .. import render
from ..core.mqtt import CloudMqtt, Message, topic_events, topic_props, topic_state
from ..core.registry import Device
from ..core.spec import DeviceSpec, SpecStore, format_value
from ..errors import UsageError
from ..render import OutputFormat
from .context import AppContext, OutputOption, pick_output
from .device import load_registry


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _load_specs(
    app_ctx: AppContext, devices: list[Device]
) -> dict[str, DeviceSpec]:
    """Prepare all specs involved, used to turn siid/piid into property names.

    The first time they are fetched one by one from miot-spec.org, afterwards the cache
    is used. Devices whose spec cannot be fetched degrade to showing the bare
    siid.piid, which does not affect watch itself.
    """
    specs: dict[str, DeviceSpec] = {}
    urns = {device.urn for device in devices}
    store = SpecStore(app_ctx.profile, timeout=app_ctx.timeout)
    missing = [
        urn for urn in urns if not store._cache_path(urn).exists()  # noqa: SLF001
    ]
    if missing:
        render.info(f"[dim]First run, fetching {len(missing)} spec(s)…[/dim]")
    for urn in urns:
        try:
            specs[urn] = store.get(urn)
        except Exception as err:  # one broken spec must not bring down the whole watch
            render.warn(f"Failed to fetch spec ({urn}): {err}")
    return specs


def _describe(
    message: Message,
    device: Device,
    spec: DeviceSpec | None,
    previous: dict[tuple[str, int, int], Any],
) -> dict[str, Any] | None:
    """Turn one pushed message into a displayable row; returns None when it is filtered out."""
    stamp = time.strftime("%H:%M:%S")
    base = {
        "Time": stamp,
        "Device": device.label,
        "Room": device.room_name or "-",
    }
    if message.kind == "state":
        return {
            **base,
            "Type": "Online state",
            "Name": "-",
            "Change": "online" if message.state == "online" else "offline",
            "_json": {"kind": "state", "state": message.state},
        }
    if message.kind == "event":
        event = None
        if spec:
            event = next(
                (
                    item
                    for item in spec.events
                    if item.siid == message.siid and item.eiid == message.iid
                ),
                None,
            )
        name = event.full_name if event else f"{message.siid}.{message.iid}"
        return {
            **base,
            "Type": "Event",
            "Name": event.description if event else name,
            "Change": json.dumps(message.arguments, ensure_ascii=False)
            if message.arguments
            else "-",
            "_json": {
                "kind": "event",
                "event": name,
                "arguments": message.arguments,
            },
        }

    prop = (
        spec.property_at(message.siid, message.iid)
        if spec and message.siid is not None and message.iid is not None
        else None
    )
    name = prop.full_name if prop else f"{message.siid}.{message.iid}"
    key = (device.did, message.siid or -1, message.iid or -1)
    old = previous.get(key)
    previous[key] = message.value
    shown_new = format_value(prop, message.value) if prop else str(message.value)
    shown_old = (
        (format_value(prop, old) if prop else str(old)) if old is not None else None
    )
    return {
        **base,
        "Type": "Property",
        "Name": prop.description if prop else name,
        "Change": f"{shown_old} → {shown_new}" if shown_old is not None else shown_new,
        "_json": {
            "kind": "prop",
            "property": name,
            "value": message.value,
            "old": old,
        },
    }


def watch(
    ctx: typer.Context,
    devices: Annotated[
        Optional[list[str]], typer.Argument(help="Devices to watch; all of them when "
                                                 "omitted")
    ] = None,
    props: Annotated[
        Optional[list[str]],
        typer.Option("--prop", help="Only these properties, repeatable, e.g. --prop on"),
    ] = None,
    events: Annotated[
        bool, typer.Option("--events/--no-events", help="Include events")
    ] = True,
    state: Annotated[
        bool, typer.Option("--state/--no-state", help="Include online/offline changes")
    ] = True,
    all_updates: Annotated[
        bool,
        typer.Option(
            "--all-updates",
            help="Also show periodic reports whose value did not change (only real "
                 "changes by default)",
        ),
    ] = False,
    exit_after: Annotated[
        Optional[int], typer.Option("--exit-after", help="Exit after N messages")
    ] = None,
    duration: Annotated[
        Optional[float], typer.Option("--duration", help="Exit after this many seconds")
    ] = None,
    output: OutputOption = None,
) -> None:
    """Watch property changes, events and online/offline changes live. Ctrl-C to quit."""
    app_ctx = _ctx(ctx)
    registry = load_registry(app_ctx)
    scope = app_ctx.home_filter()

    if devices:
        targets = [registry.resolve(ref, **scope) for ref in devices]
    else:
        targets = registry.filter(**scope)
    if not targets:
        raise UsageError("No devices to watch")

    specs = _load_specs(app_ctx, targets)
    by_did = {device.did: device for device in targets}
    fmt = pick_output(app_ctx, output)
    wanted_props = {name.lower() for name in (props or [])}

    topics: list[str] = []
    for device in targets:
        topics.append(topic_props(device.did))
        if events:
            topics.append(topic_events(device.did))
        if state and not device.did.startswith(("blt.", "proxy.")):
            # The cloud sends no online/offline state for Bluetooth and gateway sub-
            # devices, so subscribing is pointless
            topics.append(topic_state(device.did))

    with app_ctx.session() as session:
        identity = app_ctx.profile.identity(session.region)
        # Make sure the token is fresh first; it is also the password for the long-lived
        # connection
        session.access_token()
        client = CloudMqtt(
            region=session.region,
            client_id=identity.device_id,
            token_provider=session.access_token,
            debug=app_ctx.verbose,
            on_note=lambda text: render.info(f"[dim]{text}[/dim]"),
            on_state_change=lambda ok: render.info(
                "[dim]Connected[/dim]" if ok else "[yellow]Connection lost, "
                                            "reconnecting…[/yellow]"
            ),
        )
        client.subscribe(topics)
        render.info(
            f"[dim]Watching {len(targets)} device(s) ({len(topics)} subscription(s)), "
            "Ctrl-C to quit[/dim]"
        )
        previous: dict[tuple[str, int, int], Any] = {}
        seen = 0
        repeats = 0
        deadline = time.monotonic() + duration if duration else None
        try:
            client.start()
            while True:
                if deadline and time.monotonic() >= deadline:
                    break
                try:
                    message = client.messages.get(timeout=0.5)
                except queue.Empty:
                    continue
                device = by_did.get(message.did)
                if device is None:
                    continue
                # Devices periodically re-report the same value; do not flood the screen
                # by default — watch is about changes
                if (
                    not all_updates
                    and message.kind == "prop"
                    and previous.get((device.did, message.siid or -1, message.iid or -1))
                    == message.value
                ):
                    repeats += 1
                    continue
                row = _describe(message, device, specs.get(device.urn), previous)
                if row is None:
                    continue
                if wanted_props and row["_json"].get("kind") == "prop":
                    name = str(row["_json"]["property"]).lower()
                    if not any(
                        item == name or item == name.split(".")[-1]
                        for item in wanted_props
                    ):
                        continue
                _emit(row, fmt, device)
                seen += 1
                if exit_after and seen >= exit_after:
                    break
        except KeyboardInterrupt:
            render.info("")
        finally:
            client.stop()
        tail = f"; {repeats} more report(s) with unchanged values were skipped" if repeats else ""
        render.info(f"[dim]{seen} message(s) in total{tail}[/dim]")


def _emit(row: dict[str, Any], fmt: OutputFormat, device: Device) -> None:
    """Streaming output: one line per message; a table makes no sense here."""
    payload = row.pop("_json")
    if fmt in (OutputFormat.json, OutputFormat.yaml):
        print(
            json.dumps(
                {
                    "ts": int(time.time()),
                    "time": row["Time"],
                    "did": device.did,
                    "device": device.label,
                    "room": device.room_name,
                    **payload,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return
    if fmt is OutputFormat.plain:
        print(
            f"{row['Time']}\t{device.label}\t{row['Name']}\t{row['Change']}",
            flush=True,
        )
        return
    icon = {"Property": "·", "Event": "!", "Online state": "~"}.get(str(row["Type"]), "·")
    render.stream(
        f"[dim]{row['Time']}[/dim] {icon} [cyan]{row['Device']}[/cyan] [dim]"
        f"{row['Room']}[/dim] {row['Name']}  {row['Change']}"
    )
