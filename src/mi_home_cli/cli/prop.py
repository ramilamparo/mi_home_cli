"""`mi get` / `mi set` / `mi action`, plus on/off/toggle."""
from __future__ import annotations

import time
from typing import Annotated, Any, Optional

import typer

from .. import render
from ..core.channel import DeviceChannel, open_device_channel
from ..core.registry import Device
from ..core.session import Session
from ..core.spec import Action, DeviceSpec, Property, format_value, parse_value
from ..errors import (
    CloudError,
    InvalidValue,
    MiCliError,
    SpecNotFound,
    UsageError,
)
from ..render import OutputFormat
from .context import (
    AppContext,
    DryRunOption,
    OutputOption,
    VerifyOption,
    apply_write_flags,
    pick_output,
)
from .device import resolve
from .spec_cmd import describe_action_inputs, load_spec


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _channel(
    app_ctx: AppContext, session: Session, device: Device
) -> DeviceChannel:
    """Open the control channel according to --channel."""
    return open_device_channel(
        session,
        app_ctx.profile,
        device,
        mode=app_ctx.channel,
        on_note=render.info if app_ctx.verbose else None,
    )


def _target(app_ctx: AppContext, ref: str) -> tuple[Device, DeviceSpec]:
    device, spec = load_spec(app_ctx, ref)
    if device is None:  # load_spec only returns None when given a urn
        raise UsageError("A specific device is required here, not just a urn")
    return device, spec


def read_current(
    api: DeviceChannel, did: str, props: list[Property]
) -> dict[tuple[int, int], Any]:
    """Read the old values before writing.

    One extra request buys the readability of "old value → new value" and lets a
    mistake be undone by the book. If reading fails, so be it; it does not block the
    write.
    """
    readable = [p for p in props if p.readable]
    if not readable:
        return {}
    try:
        results = api.get_props(
            [{"did": did, "siid": p.siid, "piid": p.piid} for p in readable]
        )
    except MiCliError:
        return {}
    return {
        (item["siid"], item["piid"]): item.get("value")
        for item in results
        if item.get("code") == 0 and "siid" in item and "piid" in item
    }


# Return codes that mean a write was accepted. 0 is a definite success; 1 is
# "accepted, the device is executing" — some devices (e.g. dwdz.switch.sw0a01)
# answer 1 to every write while the operation actually succeeds, so it must not
# be treated as a failure.
ACCEPTED_CODES = frozenset({0, 1})


def describe_action_output(
    spec: DeviceSpec, action: Action, out: Any
) -> dict[str, Any] | Any:
    """Attach property names to an action's return values.

    out only holds values (or {piid, value}); printing a bare array is unreadable —
    a camera's start-rtsp-stream, for instance, returns [address, snapshot address,
    expiry time], which only means something with names attached.
    """
    if not out:
        return "-"
    if not isinstance(out, list):
        return out

    named: dict[str, Any] = {}
    if all(isinstance(item, dict) and "piid" in item for item in out):
        pairs = [(item["piid"], item.get("value")) for item in out]
    elif len(out) == len(action.out_piids):
        pairs = list(zip(action.out_piids, out))
    else:
        # If they do not line up, hand it out as is; do not guess
        return out
    for piid, value in pairs:
        prop = spec.property_at(action.siid, piid)
        key = prop.name if prop else str(piid)
        named[key] = format_value(prop, value) if prop else value
    return named


def _explain_code(code: int) -> str:
    """Turn common return codes into plain language."""
    return {
        0: "OK",
        1: "accepted",
        -704010000: "device is offline",
        -704042011: "the device does not support this property",
        -704220025: "the property is not writable",
        -704053026: "rejected by the device (possibly a child lock or a physical "
                    "switch)",
    }.get(code, f"failed (code={code})")


def verify_after_write(
    api: DeviceChannel,
    did: str,
    expected: list[tuple[Property, Any]],
    *,
    attempts: int = 2,
    delay: float = 0.6,
) -> dict[tuple[int, int], Any]:
    """Read once more after writing and let the device's real state speak.

    The return code is only a receipt for "accepted" and does not mean the change took
    effect; and the cloud's value may lag, so when the expected value is not read back
    we try once more, and if it still differs it is only reported as "possibly delayed",
    not as a failure.
    """
    readable = [(prop, value) for prop, value in expected if prop.readable]
    if not readable:
        return {}
    params = [
        {"did": did, "siid": prop.siid, "piid": prop.piid} for prop, _ in readable
    ]
    actual: dict[tuple[int, int], Any] = {}
    for attempt in range(attempts):
        time.sleep(delay)
        try:
            results = api.get_props(params)
        except MiCliError:
            return actual
        actual = {
            (item["siid"], item["piid"]): item.get("value")
            for item in results
            if item.get("code") == 0 and "siid" in item and "piid" in item
        }
        if all(
            actual.get((prop.siid, prop.piid)) == value for prop, value in readable
        ):
            break
        if attempt == attempts - 1:
            break
    return actual


def get(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    props: Annotated[
        Optional[list[str]], typer.Argument(help="Property, e.g. on / "
                                                 "light.brightness / 2.1")
    ] = None,
    output: OutputOption = None,
) -> None:
    """Read properties. Reads every readable property when none is given."""
    app_ctx = _ctx(ctx)
    target, spec = _target(app_ctx, device)

    if props:
        wanted: list[Property] = [spec.find_property(ref) for ref in props]
        unreadable = [p.full_name for p in wanted if not p.readable]
        if unreadable:
            raise UsageError("These properties are not readable: "
                             f"{', '.join(unreadable)}")
    else:
        wanted = [p for p in spec.properties if p.readable]
        if not wanted:
            raise SpecNotFound(f"{target.label} has no readable properties")

    with app_ctx.session() as session:
        results = _channel(app_ctx, session, target).get_props(
            [{"did": target.did, "siid": p.siid, "piid": p.piid} for p in wanted]
        )

    by_key = {(item.get("siid"), item.get("piid")): item for item in results}
    fmt = pick_output(app_ctx, output)
    if fmt in (OutputFormat.json, OutputFormat.yaml):
        render.output(
            {
                p.full_name: by_key.get((p.siid, p.piid), {}).get("value")
                for p in wanted
            },
            fmt,
        )
        return
    if fmt is OutputFormat.plain and len(wanted) == 1:
        item = by_key.get((wanted[0].siid, wanted[0].piid), {})
        print(item.get("value") if item.get("value") is not None else "")
        return

    rows = []
    for prop in wanted:
        item = by_key.get((prop.siid, prop.piid), {})
        code = item.get("code", -1)
        rows.append(
            {
                "Property": prop.full_name,
                "id": prop.ref,
                "Description": prop.description,
                "Value": format_value(prop, item.get("value"))
                if code == 0
                else _explain_code(int(code)),
            }
        )
    render.output(rows, fmt, title=f"{target.label} ({target.location})")


def set_(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    assignments: Annotated[
        list[str], typer.Argument(help="property=value, repeatable, e.g. on=true "
                                       "brightness=60")
    ],
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
    output: OutputOption = None,
) -> None:
    """Write properties."""
    app_ctx = apply_write_flags(_ctx(ctx), dry_run, verify)
    target, spec = _target(app_ctx, device)

    params: list[dict[str, Any]] = []
    props: list[Property] = []
    for item in assignments:
        if "=" not in item:
            raise UsageError(f"`{item}` is not in property=value form")
        ref, raw = item.split("=", 1)
        prop = spec.find_property(ref)
        if not prop.writable:
            raise InvalidValue(
                f"{prop.full_name} is not writable",
                hint=f"Its access is {prop.access_text()}",
            )
        value = parse_value(prop, raw)
        props.append(prop)
        params.append(
            {"did": target.did, "siid": prop.siid, "piid": prop.piid, "value": value}
        )

    if app_ctx.dry_run:
        render.info("[dim]--dry-run: parsed only, nothing sent:[/dim]")
        render.output(
            [
                {
                    "Property": prop.full_name,
                    "id": prop.ref,
                    "Value to write": param["value"],
                }
                for prop, param in zip(props, params)
            ],
            pick_output(app_ctx, output),
        )
        return

    with app_ctx.session() as session:
        api = _channel(app_ctx, session, target)
        before = read_current(api, target.did, props)
        results = api.set_props(params)
        actual = (
            verify_after_write(
                api, target.did, [(p, q["value"]) for p, q in zip(props, params)]
            )
            if app_ctx.verify
            else {}
        )

    by_key = {(item.get("siid"), item.get("piid")): item for item in results}
    rows = []
    failed = False
    lagging = False
    for prop, param in zip(props, params):
        key = (prop.siid, prop.piid)
        code = int(by_key.get(key, {}).get("code", -1))
        ok = code in ACCEPTED_CODES
        failed = failed or not ok
        result = _explain_code(code)
        if ok and key in actual:
            if actual[key] == param["value"]:
                result = "OK"
            else:
                result = f"sent, still reads back as {format_value(prop, actual[key])}"
                lagging = True
        old = before.get(key)
        rows.append(
            {
                "Property": prop.full_name,
                "Old value": format_value(prop, old) if old is not None else "-",
                "New value": format_value(prop, param["value"]),
                "Result": result,
            }
        )
    render.output(rows, pick_output(app_ctx, output), title=target.label)
    if lagging:
        render.warn("The value read back from the cloud has not caught up yet, "
                    "probably because the device reports with a delay; try `mi get` "
                    "again in a few seconds")
    if failed:
        raise typer.Exit(code=CloudError.exit_code)


def action(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    name: Annotated[
        Optional[str], typer.Argument(help="Action name; lists all actions when omitted")
    ] = None,
    values: Annotated[
        Optional[list[str]], typer.Option("--in", help="Input arguments in order, "
                                                       "repeatable")
    ] = None,
    dry_run: DryRunOption = None,
    output: OutputOption = None,
) -> None:
    """Call an action. Lists the actions the device supports when no name is given."""
    app_ctx = apply_write_flags(_ctx(ctx), dry_run)
    target, spec = _target(app_ctx, device)
    fmt = pick_output(app_ctx, output)

    if not name:
        render.output(
            [
                {
                    "Action": item.full_name,
                    "id": item.ref,
                    "Inputs": describe_action_inputs(spec, item) or "-",
                    "Description": item.description,
                }
                for item in spec.actions
            ],
            fmt,
            title=f"Actions supported by {target.label}",
        )
        return

    target_action = spec.find_action(name)
    raw_values = list(values or [])
    if len(raw_values) != len(target_action.in_piids):
        raise UsageError(
            f"{target_action.full_name} takes {len(target_action.in_piids)} input(s) ("
            f"{describe_action_inputs(spec, target_action) or 'none'}), but "
            f"{len(raw_values)} given",
            hint="Pass them one by one with --in, in the order listed above",
        )
    parsed: list[Any] = []
    for piid, raw in zip(target_action.in_piids, raw_values):
        prop = spec.property_at(target_action.siid, piid)
        parsed.append(parse_value(prop, raw) if prop else raw)

    if app_ctx.dry_run:
        render.info(
            f"[dim]--dry-run: {target.label} {target_action.full_name} ("
            f"{target_action.ref}) inputs {parsed}[/dim]"
        )
        return

    with app_ctx.session() as session:
        result = _channel(app_ctx, session, target).call_action(
            target.did, target_action.siid, target_action.aiid, parsed
        )
    code = int(result.get("code", -1))
    data: dict[str, Any] = {
        "Device": target.label,
        "Action": target_action.full_name,
        "Result": _explain_code(code),
    }
    named = describe_action_output(spec, target_action, result.get("out"))
    if isinstance(named, dict):
        data.update({f"↳ {key}": value for key, value in named.items()})
    else:
        data["Output"] = named
    render.output(data, fmt)
    if code != 0:
        raise typer.Exit(code=CloudError.exit_code)


def _switch(app_ctx: AppContext, device: str, value: bool | None) -> None:
    """Shared by on / off / toggle: find the device's switch property, then write it."""
    target, spec = _target(app_ctx, device)
    candidates = [
        prop
        for prop in spec.properties
        if prop.name == "on" and prop.writable and prop.format == "bool"
    ]
    if not candidates:
        raise SpecNotFound(
            f"{target.label} has no writable on/off property",
            hint="See what it supports with `mi spec show`, then use `mi set`",
        )
    # When several services have on (e.g. a light with a night light), take the main
    # service with the smallest siid
    prop = min(candidates, key=lambda p: (p.siid, p.piid))
    if app_ctx.dry_run:
        # The target value of toggle depends on the current state; a dry run does not
        # read the device and cannot tell, so say so honestly
        target_value = "toggle the current state" if value is None else format_value(prop, value)
        render.info(
            f"[dim]--dry-run: {target.label} ({target.location}) → {prop.full_name} ("
            f"{prop.ref}) = {target_value}[/dim]"
        )
        return
    with app_ctx.session() as session:
        api = _channel(app_ctx, session, target)
        if value is None:
            current = api.get_props(
                [{"did": target.did, "siid": prop.siid, "piid": prop.piid}]
            )
            if not current or current[0].get("code") != 0:
                raise CloudError(f"Cannot read {target.label}'s current on/off state")
            value = not bool(current[0].get("value"))
        results = api.set_props(
            [
                {
                    "did": target.did,
                    "siid": prop.siid,
                    "piid": prop.piid,
                    "value": value,
                }
            ]
        )
        code = int(results[0].get("code", -1)) if results else -1
        actual = (
            verify_after_write(api, target.did, [(prop, value)])
            if app_ctx.verify and code in ACCEPTED_CODES
            else {}
        )
    if code not in ACCEPTED_CODES:
        render.error(
            f"{target.label}: failed to turn {'on' if value else 'off'}: "
            f"{_explain_code(code)}"
        )
        raise typer.Exit(code=CloudError.exit_code)
    readback = actual.get((prop.siid, prop.piid))
    if readback is not None and readback != value:
        render.warn(
            f"{target.label}: command sent, but it still reads back as "
            f"{format_value(prop, readback)}; the report may be delayed"
        )
        return
    render.success(f"{target.label} turned {'on' if value else 'off'}")


def on(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
) -> None:
    """Turn a device on."""
    _switch(apply_write_flags(_ctx(ctx), dry_run, verify), device, True)


def off(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
) -> None:
    """Turn a device off."""
    _switch(apply_write_flags(_ctx(ctx), dry_run, verify), device, False)


def toggle(
    ctx: typer.Context,
    device: Annotated[str, typer.Argument(help="Device name, alias or did")],
    dry_run: DryRunOption = None,
    verify: VerifyOption = None,
) -> None:
    """Toggle a device on/off."""
    _switch(apply_write_flags(_ctx(ctx), dry_run, verify), device, None)
