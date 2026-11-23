# Mi Home CLI — command list

**English** · [简体中文](cli-spec.md)

Executable name: `mi` (alternative alias `mihome`). Design principle: **short for frequent operations, complete for rare ones**.
Everyday operations such as `mi set living-room-light on=true` require remembering neither the did nor siid/piid (for the resolution rules see [design.en.md §4](./design.en.md#4-the-two-keys-to-usability-device-resolution-and-property-resolution)).

## Global options

| Option | Meaning |
| --- | --- |
| `--profile <name>` | isolates account/region configuration, default `default` |
| `--region <cn\|de\|i2\|ru\|sg\|us>` | overrides the region of the current profile |
| `-o, --output <table\|json\|yaml\|plain>` | output format, default `table`; colours are dropped automatically on a non-TTY |
| `--channel <cloud\|auto\|lan>` | control channel, default `cloud`; `auto` means LAN first, falling back to the cloud on failure |
| `--timeout <sec>` | timeout per request, default 15 |
| `--no-cache` / `--refresh` | skip the local cache / force a cache refresh |
| `--dry-run` | parse and validate only, send no real request |
| `-v, --verbose` / `-q, --quiet` | print full requests and responses / print results only |
| `--yes` | skip confirmation of dangerous operations |
| `--all-homes` | ignore the default home and work across all homes |
| `--verify` | read back once after writing and confirm with the device's real state (no read-back by default, only the return code is checked) |
| `--show-secrets` | do not mask sensitive fields such as the device token in output |

---

## 1. Authentication `mi auth`

```bash
mi auth login [--region cn] [--scan] [--manual] [--no-browser] [--no-mdns]
              [--redirect-url URL] [--wait 300] [--skip-confirm]
mi auth login --scan           # QR-code login: draws a QR code in the terminal, scan it with a Xiaomi app, no browser
mi auth status [--check]       # login state, uid, nickname, remaining token validity
mi auth exchange <code|URL>    # exchange an authorization code for a token (retry with the same code after a failed exchange)
mi auth refresh                # refresh the access_token manually
mi auth logout [--purge]       # log out; --purge also deletes the device cache
mi auth whoami                 # print the current account info (queried live)
mi profile list|use|remove|path
```

Xiaomi has an allowlist for `redirect_uri`; the host must be `homeassistant.local:8123`
(for the tests see [design.en.md §3.2](./design.en.md#32-login-flow-the-hard-part-of-the-cli-version)),
so on login the CLI listens on local port 8123 and tries to point this hostname at this
machine via mDNS; if that does not succeed it does not matter, just paste the full
address from the browser's address bar back into the terminal.

- `--scan`: QR-code login. A QR code is drawn in the terminal; scan it with a Xiaomi
  app and confirm on the phone. No browser and no pasting are needed at any point. The
  login page's redirect flow is reproduced with plain API calls (see
  [design.en.md §3.3](./design.en.md#33-qr-code-login---scan)), without introducing a
  headless browser, and it works once installed. A terminal QR code is affected by
  font and line spacing, so in the odd terminal it may not scan; the command also
  prints a QR code image address (visible by opening it in a browser, the same QR
  code) as a fallback, so you never get stuck. `--scan` has nothing to do with
  `--manual` / mDNS / the local callback; once it is set, only the scan path is taken.
- `--manual`: do not listen on a port, only use pasting.
- `--no-mdns`: do not advertise via mDNS (use when there is a real Home Assistant on the LAN).
- `--wait`: seconds to wait for authorization, default 300 (when scanning, the upper limit is also bounded by the QR code's validity).
- `--device-id`: overrides `device_id` (for troubleshooting; generated in HA's shape by default).

Under the Xiaomi account's "logged-in devices", a scan login is shown as
`mi-home-cli/version` by default (repeated scans on the same machine reuse the same
web deviceId, so the list does not keep growing). The display name can be changed:
`mi config set scan_device_name <name>` or the `MI_SCAN_DEVICE_NAME` environment
variable — it is sent as the HTTP User-Agent and can only be ASCII.

The `client_id` / `redirect_uri` / `device_id` of the authorization step and the token
exchange step must be exactly identical, otherwise the server returns
`96002 invalid request`, so these three values are fixed per profile.
Add `-v` to see the request actually sent during the token exchange.

## 2. Homes / rooms / devices

```bash
mi home list                                   # list of homes (including shared ones), the default home is marked *
mi home use [<home>] [--clear]                 # set / show / clear the default home
mi home select                                 # pick the default home interactively (clearing is an option)
mi home unset                                  # clear the default home, back to all homes
mi room list [--home <home>]                   # list of rooms

mi device list [--home H] [--room R] [--model M] [--online|--offline]
               [--search keyword] [--with-sub] [--sort name|room|model]
mi device show <device> [--props]              # details; --props also reads the current property values
mi device sync                                 # re-fetch the device list cache
mi device alias set <device> <alias>
mi device alias list|rm
mi device token <device>                       # print the LAN token (masked by default)
```

Default output of `device list`: alias/name, room, model, online, did (abbreviated).

## 3. Capability queries `mi spec`

```bash
mi spec show <device|urn> [--siid N] [--readable|--writable|--notify]
mi spec search <device> <keyword>      # search this device's properties/actions
mi spec dump <device|urn> [-o json]    # the full spec, to feed scripts or an LLM
mi spec cache clear|info
```

The `spec show` table is where users look up `siid.piid`, value ranges and enum values:

```
SERVICE            PROP                 ID    ACCESS  TYPE    RANGE / VALUES        UNIT
light              on                   2.1   rw n    bool    -                     -
light              brightness           2.2   rw n    uint8   1~100 step 1          %
light              color-temperature    2.3   rw n    uint32  2700~6500 step 1      K
light              mode                 2.4   rw n    uint8   0=Day 1=Night 2=Warm  -
```

## 4. Reading and writing properties

```bash
mi get <device> [prop...]              # without prop, reads all readable properties
mi get living-room-light on brightness
mi get living-room-light 2.1 -o plain  # prints just "true", handy for taking the value in a shell

mi set <device> <prop=value>...        # several at once, sent in one batched request
mi set living-room-light on=true brightness=60
mi set ac mode=cool target-temperature=26

mi watch [device...] [--prop P]... [--events/--no-events] [--state/--no-state]
                     [--all-updates] [--exit-after N] [--duration seconds] [-o json]
```

- Value notations: `on/off/true/false/1/0`, numbers, enum description text, `"strings with spaces"`.
- `watch` uses a long-lived cloud MQTT connection, one line per change, `Ctrl-C` to
  quit. Without a device it watches all devices in the default home.
- `--exit-after N` exits after N messages and `--duration` exits after watching for
  that many seconds, convenient for scripts waiting for some event.
- Property changes are shown as "old value → new value" (the old value comes from the
  previous message seen in this session).
- Devices periodically re-report the same value; these are skipped by default (the
  number skipped is reported at the end), and `--all-updates` shows them all.
- It reconnects automatically after a disconnect, replacing the password with the
  latest access_token before reconnecting.

## 5. Calling actions

```bash
mi action <device> <action> [--in value]... [--param name=value]...
mi action vacuum vacuum.start-sweep
mi action speaker play-control.play --param volume=30
mi action list <device>                # list all callable actions of this device
```

## 6. Semantic shortcut commands

A layer of "plain-language mapping" on top of the spec. It works across models because
the urn names of properties in the MIoT spec are standardised (`on`, `brightness`,
`color-temperature`, `target-temperature`, `fan-level`, `motor-control`…); the semantic
layer only looks at names, not models.

When a device lacks the corresponding property, an error is raised that suggests
checking `mi spec show --writable`; nothing is silently ignored.
Without any option, the current state of the device is shown.

```bash
mi on <device>          # equivalent to setting the device's on property to true
mi off <device>
mi toggle <device>

mi light <device> [--on|--off] [--brightness 60] [--ct 4000] [--color '#ff8800'] [--mode sleep]
mi climate <device> [--on|--off] [--mode cool] [--temp 26] [--fan 2]
mi cover <device> [--open|--close|--stop|--position 50]
mi fan <device> [--on|--off] [--speed 3] [--swing]
```

`--mode` is matched against the enum value names of the device's spec, and those follow
the interface language: with the English interface `mi spec show` lists names such as
`Sleep` or `Cool`, so write `--mode sleep` / `--mode cool`; with the Chinese interface
the same values are listed and written in Chinese. `--color` accepts hex as well as
colour names in English or Chinese (`red` / `红`).

## 7. LAN `mi lan`

```bash
mi lan list                                    # which devices in the list support direct control
mi lan discover [--timeout 3] [--address ...]  # UDP broadcast scan, caches the IPs
mi lan status <device>                         # whether direct control is possible, IP, latency
mi lan raw <device> <method> [--params JSON]   # send a raw miIO request (for troubleshooting)
```

Add `--channel lan` to a control command to go direct; `--channel auto` means "go
direct when possible, silently fall back to the cloud when not". The default is
`cloud` — the cost of LAN probing and fallback should not be borne by the default;
to default to the LAN use `mi config set channel auto`.

## 8. Raw interface `mi raw` (escape hatch)

Sends protocol fields directly without going through spec resolution, for debugging and as a temporary workaround when upstream changes fields:

```bash
mi raw get <did> <siid> <piid>
mi raw set <did> <siid> <piid> <value>
mi raw action <did> <siid> <aiid> [--in JSON]
mi raw api <METHOD> <path> [--data JSON]        # hit the cloud API directly
```

## 9. Miscellaneous

```bash
mi config list|get|set|unset|path   # profile / region / output / home / channel
mi doctor                        # checks login state, clock skew, network connectivity, port usage, file permissions
mi --install-completion     # built into typer, installs completion for the current shell
mi repl                          # interactive mode: get/set directly after selecting a device, with Tab completion (optional)
mi version
```

---

## Commands by implementation phase

| Phase | Commands |
| --- | --- |
| M1 | `auth *`, `profile *`, `home list`, `room list`, `device list/show/sync`, `version` |
| M2 | `spec *`, `get`, `set`, `action`, `raw *`, `-o json` |
| M3 | `on/off/toggle`, `light/climate/cover/fan`, `device alias`, `completion`, `doctor`, `config` |
| M4 | `watch` |
| M5 | `lan *`, `--channel auto` fallback |
| Optional | `repl`, scene-related commands (the APIs need verifying first) |
