"""Semantic commands: `mi light`, `mi climate`, `mi cover`, `mi fan`.

All of them are sugar for `mi set`: plain-language options are translated into spec
properties and sent as one batch. Without any option, the device's current state is
shown.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

import typer

from .. import render
from ..core.registry import Device
from ..core.semantic import STATUS_PROPERTIES, Planner, format_color, parse_color
from ..core.spec import DeviceSpec, format_value
from ..errors import CloudError
from .context import (
    AppContext,
    DryRunOption,
    OutputOption,
    VerifyOption,
    apply_write_flags,
    pick_output,
)
from .prop import (
    ACCEPTED_CODES,
    _channel,
    _explain_code,
    _target,
    read_current,
    verify_after_write,
)

DeviceArg = Annotated[str, typer.Argument(help="Device name, alias or did")]


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _show_status(
    app_ctx: AppContext,
    device: Device,
    spec: DeviceSpec,
    domain: str,
    output: Any,
) -> None:
    props = [
        prop
        for name in STATUS_PROPERTIES[domain]
        if (prop := spec.by_name(name, readable=True)) is not None
    ]
    if not props:
        render.warn(f"{device.label} has no readable state properties")
        return
    with app_ctx.session() as session:
        results = _channel(app_ctx, session, device).get_props(
            [{"did": device.did, "siid": p.siid, "piid": p.piid} for p in props]
        )
    by_key = {(item.get("siid"), item.get("piid")): item for item in results}
    data: dict[str, Any] = {}
    for prop in props:
        item = by_key.get((prop.siid, prop.piid), {})
        if item.get("code") != 0:
            data[prop.description or prop.name] = _explain_code(
                int(item.get("code", -1))
            )
            continue
        value = item.get("value")
        data[prop.description or prop.name] = (
            format_color(value) if prop.name == "color" else format_value(prop, value)
        )
    render.output(data, pick_output(app_ctx, output), title=f"{device.label} ("
                                                            f"{device.location})")


def _apply(
    app_ctx: AppContext, device: Device, planner: Planner, output: Any
) -> None:
    params = planner.params(device.did)
    if app_ctx.dry_run:
        render.info("[dim]--dry-run: parsed only, nothing sent:[/dim]")
        render.output(
            [
                {
                    "Property": change.prop.full_name,
                    "id": change.prop.ref,
                    "Value to write": change.value,
                }
                for change in planner.changes
            ],
            pick_output(app_ctx, output),
        )
        return

    with app_ctx.session() as session:
        api = _channel(app_ctx, session, device)
        before = read_current(
            api, device.did, [change.prop for change in planner.changes]
        )
        results = api.set_props(params)
        actual = (
            verify_after_write(
                api,
                device.did,
                [(change.prop, change.value) for change in planner.changes],
            )
            if app_ctx.verify
            else {}
        )
    by_key = {(item.get("siid"), item.get("piid")): item for item in results}
    rows = []
    failed = False

    def shown(prop: Any, value: Any) -> str:
        if value is None:
            return "-"
        return (
            format_color(value)
            if prop.name == "color"
            else format_value(prop, value)
        )

    for change in planner.changes:
        key = (change.prop.siid, change.prop.piid)
        code = int(by_key.get(key, {}).get("code", -1))
        ok = code in ACCEPTED_CODES
        failed = failed or not ok
        result = _explain_code(code)
        if ok and key in actual:
            result = (
                "OK"
                if actual[key] == change.value
                else f"sent, still reads back as {shown(change.prop, actual[key])}"
            )
        rows.append(
            {
                "Property": change.prop.full_name,
                "Old value": shown(change.prop, before.get(key)),
                "New value": shown(change.prop, change.value),
                "Result": result,
            }
        )
    render.output(rows, pick_output(app_ctx, output), title=device.label)
    if failed:
        raise typer.Exit(code=CloudError.exit_code)


def _switch(planner: Planner, on: bool | None) -> None:
    if on is not None:
        planner.add_raw("--on/--off", ("on",), on)


def light(
    ctx: typer.Context,
    device: DeviceArg,
    on: Annotated[
        Optional[bool], typer.Option("--on/--off", help="Turn the light on / off")
    ] = None,
    brightness: Annotated[
        Optional[str], typer.Option("--brightness", "-b", help="Brightness, usually "
                                                               "1~100")
    ] = None,
    ct: Annotated[
        Optional[str], typer.Option("--ct", help="Color temperature in kelvin, e.g. "
                                                 "4000")
    ] = None,
    color: Annotated[
        Optional[str], typer.Option("--color", help="Color, e.g. #ff8800 or red")
    ] = None,
    mode: Annotated[
        Optional[str], typer.Option("--mode", help="Mode, e.g. Day / Night")
    ] = None,
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
    output: OutputOption = None,
) -> None:
    """Control a light. Shows the current state when no option is given."""
    app_ctx = apply_write_flags(_ctx(ctx), dry_run, verify)
    target, spec = _target(app_ctx, device)
    if on is None and not any((brightness, ct, color, mode)):
        _show_status(app_ctx, target, spec, "light", output)
        return

    planner = Planner(spec, target.label)
    _switch(planner, on)
    if brightness is not None:
        planner.add_parsed("--brightness", ("brightness",), brightness)
    if ct is not None:
        planner.add_parsed("--ct", ("color-temperature",), ct)
    if color is not None:
        planner.add_raw("--color", ("color",), parse_color(color))
    if mode is not None:
        planner.add_parsed("--mode", ("mode",), mode)
    _apply(app_ctx, target, planner, output)


def climate(
    ctx: typer.Context,
    device: DeviceArg,
    on: Annotated[
        Optional[bool], typer.Option("--on/--off", help="Power on / off")
    ] = None,
    mode: Annotated[
        Optional[str], typer.Option("--mode", help="Mode, e.g. Cool / Heat / Auto")
    ] = None,
    temp: Annotated[
        Optional[str], typer.Option("--temp", "-t", help="Target temperature")
    ] = None,
    fan: Annotated[
        Optional[str], typer.Option("--fan", help="Fan level")
    ] = None,
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
    output: OutputOption = None,
) -> None:
    """Control air conditioners, heaters and other climate devices. Shows the current state when no option is given."""
    app_ctx = apply_write_flags(_ctx(ctx), dry_run, verify)
    target, spec = _target(app_ctx, device)
    if on is None and not any((mode, temp, fan)):
        _show_status(app_ctx, target, spec, "climate", output)
        return

    planner = Planner(spec, target.label)
    _switch(planner, on)
    if mode is not None:
        planner.add_parsed("--mode", ("mode",), mode)
    if temp is not None:
        planner.add_parsed("--temp", ("target-temperature",), temp)
    if fan is not None:
        planner.add_parsed("--fan", ("fan-level", "speed-level"), fan)
    _apply(app_ctx, target, planner, output)


def cover(
    ctx: typer.Context,
    device: DeviceArg,
    open_: Annotated[bool, typer.Option("--open", help="Open")] = False,
    close: Annotated[bool, typer.Option("--close", help="Close")] = False,
    stop: Annotated[bool, typer.Option("--stop", help="Stop")] = False,
    position: Annotated[
        Optional[str], typer.Option("--position", "-p", help="Position in percent, "
                                                             "0~100")
    ] = None,
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
    output: OutputOption = None,
) -> None:
    """Control curtains and other open/close devices. Shows the current state when no option is given."""
    app_ctx = apply_write_flags(_ctx(ctx), dry_run, verify)
    target, spec = _target(app_ctx, device)
    if not any((open_, close, stop, position)):
        _show_status(app_ctx, target, spec, "cover", output)
        return
    if sum((open_, close, stop)) > 1:
        raise typer.BadParameter("Only one of --open / --close / --stop may be given")

    planner = Planner(spec, target.label)
    if open_:
        planner.add_enum("--open", ("motor-control",), "open")
    if close:
        planner.add_enum("--close", ("motor-control",), "close")
    if stop:
        planner.add_enum("--stop", ("motor-control",), "pause", "stop")
    if position is not None:
        planner.add_parsed("--position", ("target-position",), position)
    _apply(app_ctx, target, planner, output)


def fan(
    ctx: typer.Context,
    device: DeviceArg,
    on: Annotated[
        Optional[bool], typer.Option("--on/--off", help="On / off")
    ] = None,
    speed: Annotated[
        Optional[str], typer.Option("--speed", "-s", help="Fan level")
    ] = None,
    mode: Annotated[Optional[str], typer.Option("--mode", help="Mode")] = None,
    swing: Annotated[
        Optional[bool], typer.Option("--swing/--no-swing", help="Oscillation")
    ] = None,
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
    output: OutputOption = None,
) -> None:
    """Control fans, purifiers and other devices with levels. Shows the current state when no option is given."""
    app_ctx = apply_write_flags(_ctx(ctx), dry_run, verify)
    target, spec = _target(app_ctx, device)
    if on is None and swing is None and not any((speed, mode)):
        _show_status(app_ctx, target, spec, "fan", output)
        return

    planner = Planner(spec, target.label)
    _switch(planner, on)
    if speed is not None:
        planner.add_parsed("--speed", ("fan-level", "speed-level"), speed)
    if mode is not None:
        planner.add_parsed("--mode", ("mode",), mode)
    if swing is not None:
        planner.add_raw("--swing", ("horizontal-swing", "swing-mode"), swing)
    _apply(app_ctx, target, planner, output)
