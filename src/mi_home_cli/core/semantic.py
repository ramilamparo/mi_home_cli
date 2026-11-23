"""The mapping used by the semantic commands: `--brightness 60` → which property to write.

This is possible because the urn names of properties in the MIoT spec are
standardised (on, brightness, color-temperature, target-temperature, fan-level,
motor-control…); devices of the same kind from different vendors use the same set
of names. So the semantic layer only looks at names, not models.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidValue, SpecNotFound
from .spec import DeviceSpec, Property, parse_value

# Names of common colours → RGB
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 105, 180),
    "cyan": (0, 255, 255),
    "warm": (255, 170, 100),
}

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_color(text: str) -> int:
    """`#ff8800` / `ff8800` / `red` → the uint32 RGB the spec uses."""
    value = text.strip()
    match = _HEX_RE.match(value)
    if match:
        red, green, blue = (int(match[1][i:i + 2], 16) for i in (0, 2, 4))
    elif value.lower() in NAMED_COLORS:
        red, green, blue = NAMED_COLORS[value.lower()]
    else:
        raise InvalidValue(
            f"Unrecognized color `{text}`",
            hint="Use hex such as #ff8800, or one of " + ", ".join(
                list(NAMED_COLORS)[:6]
            ),
        )
    return (red << 16) | (green << 8) | blue


def format_color(value: Any) -> str:
    if not isinstance(value, int):
        return str(value)
    return f"#{value & 0xFFFFFF:06x}"


def enum_value(prop: Property, *keywords: str) -> Any | None:
    """Find the semantically matching value in an enum, e.g. "open" for a curtain."""
    for item in prop.value_list:
        text = f"{item.description} {item.raw}".lower()
        if any(keyword.lower() in text for keyword in keywords):
            return item.value
    return None


@dataclass
class Change:
    """One pending property write."""

    prop: Property
    value: Any

    def param(self, did: str) -> dict[str, Any]:
        return {
            "did": did,
            "siid": self.prop.siid,
            "piid": self.prop.piid,
            "value": self.value,
        }


class Planner:
    """Translates semantic options into a set of property writes.

    When no matching property is found, an error is raised that says clearly what the
    device does support — better than silently ignoring it.
    """

    def __init__(self, spec: DeviceSpec, label: str) -> None:
        self.spec = spec
        self.label = label
        self.changes: list[Change] = []

    def _require(self, option: str, *names: str) -> Property:
        prop = self.spec.by_name(*names, writable=True)
        if prop is None:
            raise SpecNotFound(
                f"{self.label} does not support {option} (the spec has no writable "
                f"{' / '.join(names)})",
                hint=f"See what is supported with `mi spec show {self.label} "
                     "--writable`",
            )
        return prop

    def add_raw(self, option: str, names: tuple[str, ...], value: Any) -> None:
        self.changes.append(Change(self._require(option, *names), value))

    def add_parsed(self, option: str, names: tuple[str, ...], raw: str) -> None:
        prop = self._require(option, *names)
        self.changes.append(Change(prop, parse_value(prop, raw)))

    def add_enum(
        self, option: str, names: tuple[str, ...], *keywords: str
    ) -> None:
        prop = self._require(option, *names)
        value = enum_value(prop, *keywords)
        if value is None:
            raise SpecNotFound(
                f"{self.label}: {prop.full_name} has no \"{keywords[0]}\" value",
                hint="Allowed values: " + prop.range_text(),
            )
        self.changes.append(Change(prop, value))

    def params(self, did: str) -> list[dict[str, Any]]:
        # on goes first: power up before adjusting parameters, most devices behave
        # better that way
        ordered = sorted(self.changes, key=lambda c: c.prop.name != "on")
        return [change.param(did) for change in ordered]


# The properties worth showing when "looking at the state" of each kind of device, in
# this order
STATUS_PROPERTIES: dict[str, tuple[str, ...]] = {
    "light": ("on", "brightness", "color-temperature", "color", "mode"),
    "climate": (
        "on", "mode", "target-temperature", "temperature",
        "relative-humidity", "fan-level", "status",
    ),
    "cover": ("motor-control", "status", "current-position", "target-position"),
    "fan": ("on", "fan-level", "speed-level", "mode", "horizontal-swing", "status"),
}
