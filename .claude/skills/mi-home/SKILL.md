---
name: mi-home
description: Control Xiaomi Home (Mi Home) smart-home devices with this repo's `mi` command-line tool — switch lights, adjust brightness and colour temperature, read temperature, humidity and air quality, check device state, call device actions, subscribe to real-time events. Use this skill whenever the user mentions lights, plugs, air conditioners, fans, curtains, purifiers, robot vacuums, cameras or sensors at home, or says things like "turn on the living room light", "how warm is it inside", "what mode is the purifier in" or "tell me when someone comes home", even if they never mention "Mi Home" or the `mi` command. Controlling real devices has physical effects, and this skill also explains how to do it carefully.
---

# Controlling Mi Home devices with mi

`mi` is a command-line tool for Mi Home devices; it operates real devices through
Xiaomi's cloud OAuth2 API.

## Make sure mi is available

Run `mi --help` first. If the command is not found:

- **Inside this repo**: use `uv run mi ...` (every `mi` below can be replaced with `uv run mi`).
- **For a global command**: install it once from PyPI, then use `mi` directly:

  ```bash
  uv tool install --with zeroconf mi-home-cli   # or pipx install "mi-home-cli[mdns]"
  ```

`zeroconf`/`[mdns]` is an optional extra that improves the chance of receiving the
login callback automatically. Python 3.11+ is required.

## Check that it works first

```bash
mi auth status          # fails with exit code 10 when not logged in
```

If not logged in, stop and tell the user to run `mi auth login` (the authorization is
completed in a browser). Do **not** attempt the login flow on the user's behalf.

## The core loop: locate the device → look up capabilities → operate

```bash
mi device list --search light -o json  # which devices are there
mi spec show <device> --writable       # what can be changed on this device, and the value ranges
mi get <device> [prop...]              # read
mi set <device> <prop=value>...        # write
```

**Do not guess `siid.piid` from memory.** The numbers differ between models, and
`mi spec show` gives the exact ids, value ranges and enum values. Properties can be
referred to by name (`brightness`, `light.on`), which is more robust than numbers.

## Key points for agents

### Parse JSON, not tables

```bash
mi -o json device list             # structured, with stable field names
mi -o plain get lamp brightness    # a single value, prints "60", ready to use
```

The default table output is for people and is truncated to the terminal width; do not
parse it. The field names and types in the JSON are stable:

```json
{"did": "305792037", "name": "Desk Lamp", "alias": null, "model": "yeelink.light.lamp4",
 "home": "Home", "room": "Study", "online": true, "connect_type": 0}
```

`mi get <device> -o json` returns `{"full property name": value}`, for example
`{"light.on": true, "light.brightness": 60}`.

Commands that print a table of rows (`doctor`, `config list`, `home list`, `room list`,
`lan *`, `device alias list`) use the column headers as JSON keys, e.g.
`{"Check": ..., "Result": ..., "Description": ...}` for `mi -o json doctor`.

### Exit codes are the classification; branch on them

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | success | — |
| 3 | device not found | confirm the name with `mi device list` |
| 4 | ambiguous device name | **the error lists the candidates; present them to the user and let them choose**, do not pick yourself |
| 5 | device offline | tell the user the device is offline |
| 6 | property not found | check with `mi spec show` what the device really supports |
| 7 | invalid value (out of range / read-only) | the error contains the correct range; fix accordingly |
| 10 | not logged in | ask the user to run `mi auth login` |

Ambiguity (4) matters most: homes often have several "ceiling lights" or "desk lamps".
**Guessing one for the user and switching it is the easiest way for this tool to cause
real harm** — it may be the light in someone else's bedroom.

### Writes have physical effects

One `mi set` really lights up a room or starts an appliance. So:

- **When unsure, `--dry-run` first**: it only parses and validates and sends nothing;
  use it to confirm which device was resolved, which property is written and what the
  value was converted to.

  ```bash
  mi set lamp brightness=60 --dry-run
  ```
- **After writing, report "old value → new value" to the user**: `mi set` prints it
  anyway, so relay it. If the change was wrong, the user can roll back by it.
- In situations like **late at night, bedrooms, other people's rooms**, confirm once
  before acting. When the user says "turn off the light" and several match, see exit
  code 4 above.
- Do not switch a device back and forth to "verify success". For a firm conclusion add
  `--verify` (one read-back after the write).
- **Some devices turn themselves on when a parameter is written**: a Yeelight desk
  lamp, for example, lights up when `brightness=60` is written while it is off. So for
  an intent like "just change a parameter, do not turn the device on", read the state
  back after writing and tell the user honestly what actually happened.

### Do it in one command, do not split it

```bash
mi set lamp on=true brightness=60 color-temperature=4000    # good: one batched write
```

This is faster than three `mi set` calls in a row and avoids intermediate device states.

### Values can be written in plain words

```bash
mi set purifier mode=sleep     # enum values by their description, as `mi spec show` lists them
mi set lamp on=on              # on/off, true/false, 1/0 and yes/no all work
mi light lamp --color red      # colours: #ff8800 or a common colour name
```

Out-of-range numbers and writes to read-only properties are caught before any request
is sent, with the correct range in the error — no need to validate yourself.

### The semantic commands save effort

```bash
mi on|off|toggle <device>
mi light <device> [--on|--off] [--brightness 60] [--ct 4000] [--color warm]
mi climate <device> [--on|--off] [--mode cool] [--temp 26]
mi fan <device> [--speed 2] [--mode auto]
mi cover <device> [--open|--close|--position 50]
```

Without options they show the current state. When a device does not support an option,
a clear error is raised; nothing is silently ignored.

### Wait for events with watch, do not poll

```bash
mi watch <device> --events --exit-after 1     # blocks until the first event, then returns
mi watch <device> -o json --duration 60       # line-delimited JSON, can be piped
```

It uses a long-lived MQTT connection. **Do not write polling loops like
`while true; do mi get ...; done`** — slow, noisy, and likely to hit rate limits.

### "Offline" does not mean unreadable

For devices with `online: false` in `device list`, `mi get` often still returns **the
last reported value cached in the cloud** — especially for low-power devices such as
Bluetooth temperature/humidity sensors, which are never permanently connected anyway.

So do not skip a device just because it is offline: **read it, but say in your answer
that it is a cached value and may be stale**. When several sources are read,
contradicting values are useful information in themselves (a purifier reporting 60%
humidity and a hygrometer reporting 74.5% means one of them is outdated, or the two
places really differ).

## Common tasks

**"How warm is it inside?" / "How is the air?"**

Such questions are about the **environment**, not one device. Read all relevant sensors
and answer from the combination; reporting a single device's reading easily
generalises from too little:

```bash
mi device list -o json | grep -iE "purif|humid|temp|air|sensor_ht|airp"   # find all the sensors first
mi get <each one> -o json                                                 # read them one by one
```

Purifiers have PM2.5 / formaldehyde / temperature and humidity, hygrometers have
temperature and humidity, and they may be in different rooms. In the answer, say which
device each reading comes from, which room it is in, and whether it is a live value.

**"Turn off all the lights in the living room"**
```bash
mi device list --room "Living Room" --search light -o json     # list them first
mi off <each device>                                           # then turn them off one by one
```
With several devices, **show the list to the user for confirmation first** before acting.

**"When someone comes home…"**
```bash
mi watch "door lock" --events -o json --exit-after 1
```

**When the user has several homes** (visible in `mi home list`), setting a default home
is recommended; it removes a lot of ambiguity:
```bash
mi home use Home
```

## More

- Full commands and options: `docs/cli-spec.md` in this repo
- Design and protocol details, known limitations: `docs/design.md`
- Camera stream address support: `docs/camera-stream.md`
- Known impossible: Mi Home scenes/automations and camera recording playback (they need
  the account-password identity, and this project only uses OAuth2); most cameras
  cannot provide a live picture
