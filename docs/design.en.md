# Mi Home control CLI — implementation design

**English** · [简体中文](design.md)

> Reference: [XiaoMi/ha_xiaomi_home](https://github.com/XiaoMi/ha_xiaomi_home) (the Home Assistant Xiaomi Home integration)
> This document only describes **how it is implemented**; for the command list see [cli-spec.en.md](./cli-spec.en.md).

---

## 0. Prerequisite: the license boundary (must be clear first)

The license header of `ha_xiaomi_home` states explicitly that the grant only covers copying, modifying and distributing "for non-commercial use in Home Assistant", and that it **does not grant the right to develop apps, web services or other forms of software**.

The constraints for this project are therefore:

- **Do not copy or port** the source code, the `specs/` resource files or the translation resources of `ha_xiaomi_home`.
- Treat it only as **reference material for protocol and API behaviour** (which URL, which fields, which sequence) and implement everything independently.
- If a ready-made implementation of the LAN miIO protocol is needed, depend on the MIT-licensed [`python-miio`](https://github.com/rytilahti/python-miio) rather than copying upstream code.
- State in the README that this project is not affiliated with Xiaomi and that account data is only stored locally.

---

## 1. How upstream makes it work (findings from reading the code)

The key facts read out of `custom_components/xiaomi_home/miot/`, which this CLI's implementation is based on:

### 1.1 Authentication: OAuth2 authorization code flow

| Item | Value |
| --- | --- |
| Authorization page | `https://account.xiaomi.com/oauth2/authorize` |
| `client_id` | `2882303761520251711` (the ID the HA integration uses publicly) |
| Token exchange | `GET https://{host}/app/v2/ha/oauth/get_token?data={json}` |
| API host | `ha.api.io.mi.com` (`cn`) / `{region}.ha.api.io.mi.com` (other regions) |
| Parameters | `redirect_uri` / `client_id` / `response_type=code` / `device_id` / `state` / `skip_confirm` |
| `device_id` | upstream uses `ha.{uuid}`; this project uses `cli.{uuid}` |
| Returns | `access_token` / `refresh_token` / `expires_in` |

There is no client_secret; refreshing uses the `refresh_token` against the same `get_token` endpoint.

### 1.2 Cloud HTTP API

Request headers: `Authorization: Bearer{access_token}` (**note that upstream really has no space there**), `X-Client-BizId: haapi`, `X-Client-AppId: {client_id}`, `Content-Type: application/json`. Responses are uniformly `{"code":0,"result":...}`.

| Purpose | Endpoint |
| --- | --- |
| Homes / rooms / device membership | `POST /app/v2/homeroom/gethome` (paginated) |
| Device details | `POST /app/v2/home/device_list_page` (`limit:200`, paged by `start_did`) |
| Read properties | `POST /app/v2/miotspec/prop/get`, body `{datasource:1, params:[{did,siid,piid}]}` |
| Write properties | `POST /app/v2/miotspec/prop/set`, body `{params:[{did,siid,piid,value}]}` |
| Call an action | `POST /app/v2/miotspec/action`, body `{params:{did,siid,aiid,in:[values...]}}` |
| User info | `GET https://open.account.xiaomi.com/user/profile` |
| Central hub certificate | `POST /app/v2/ha/oauth/get_central_crt` |

Fields available in a device entry: `did`, `name`, `model`, `spec_type` (urn), `isOnline`, `token` (the LAN key), `local_ip`, `pid` (connect_type), `rssi`, `parent_id`, `extra.fw_version`.

Engineering notes: upstream gives `prop/get` **0.2s aggregation + at most 150 entries per request**; a `did` shaped like `600xxxxxx.s2` is a sub-device.

### 1.3 spec (device capability description)

- Instance: `https://miot-spec.org/miot-spec-v2/instance?type={urn}`
- Multi-language: `https://miot-spec.org/instance/v2/multiLanguage`
- Standard library templates: `https://miot-spec.org/miot-spec-v2/template/list/...`

These are **public endpoints that need no token**, so they can be used directly without worry. The spec determines `siid/piid/aiid`, `format`, `access` (read/write/notify), `value-range`, `value-list` (enums) and units.

### 1.4 Real-time push

> The TLS root certificates are taken in the order "`MI_CA_BUNDLE` → system default
> (including `SSL_CERT_FILE`) → certifi as a fallback". Using only certifi would lock
> out users who have configured a corporate CA; using only the system default leaves
> some Pythons on macOS without a single root certificate. In addition, a proxy's
> fake-IP (`198.18.x.x`) acts as a man in the middle, so certificate verification is
> bound to fail; `mi doctor` points this situation out.


Cloud MQTT: `{region}-ha.mqtt.io.mi.com:8883`, TLS + MQTT v5,
**the username is the OAuth client_id and the password is the access_token**,
and the client_id is the same `ha.{32 hex chars}` used for OAuth. Subscriptions:

- Property changes: `device/{did}/up/properties_changed/{siid}/{piid}` (or `#`)
- Events: `device/{did}/up/event_occured/{siid}/{eiid}` (upstream really spells it `occured` here)
- Online state: `device/{did}/state/#`

### 1.5 LAN control

The miIO protocol: UDP `54321`, packet header `0x2131`, key = `md5(token)`, IV = `md5(md5(token)+token)`, AES-128-CBC + PKCS7, bytes `[16:32]` are an MD5 checksum that includes the token. The payload is JSON-RPC: `get_properties` / `set_properties` / `action`, with the same parameters as the cloud.

Limitations (stated explicitly in the upstream docs): it can only control **WiFi/wired devices that are on the same subnet as this machine and connected to the network directly**; devices that join through a gateway, such as Bluetooth Mesh and ZigBee, cannot be reached over the LAN. Central hub gateway control (mDNS discovery + certificates) is only supported in the `cn` region and is highly complex.

---

## 2. Technology choices

**Recommended: Python 3.11+**

- Same language as the reference implementation, so comparing protocols costs the least; the ecosystem has `python-miio` (LAN), `paho-mqtt`, `httpx` and `cryptography`.
- CLI framework `typer` (built on click, generates completions itself); output uses `rich` (tables / colours / progress).
- Dependencies and packaging all go through `uv`: `uv sync` creates the environment, `uv lock` pins versions (`uv.lock` is committed),
  `uv run mi ...` for invoking during development, `uv tool install` to install it as a global command; the entry point command is `mi`.

Alternative: Go (single binary, fast startup, easy distribution, but miIO and spec parsing would all have to be written by hand). If the goal were "a tool distributed to others" rather than "a script for my own use", Go would be an option; this design is laid out for Python, and the layering applies to both.

---

## 3. Architecture layers

```
mi_home_cli/
├── cli/                     # command layer: only argument parsing + calling core + rendering
│   ├── main.py              # root command, global options, exceptions → exit codes
│   ├── auth.py device.py home.py spec.py prop.py action.py
│   ├── watch.py lan.py scene.py config.py doctor.py repl.py
│   └── render.py            # the four outputs: table / json / yaml / plain
├── core/
│   ├── auth.py              # OAuth2: authorization URL, local loopback callback, token refresh
│   ├── cloud.py             # HTTP API wrapper (get aggregation, pagination, retries)
│   ├── mqtt.py              # cloud MQTT subscription (used by watch)
│   ├── lan.py               # direct miIO over UDP (optional dependency python-miio)
│   ├── spec.py              # spec fetching / caching / indexing / value conversion
│   ├── registry.py          # device list cache + name / alias resolution
│   ├── channel.py           # channel routing: auto / cloud / lan
│   └── errors.py            # error codes → plain language + exit codes
├── store.py                 # reads and writes ~/.config/mi-home-cli (isolated per profile)
└── tests/                   # fully offline, replayed with httpx.MockTransport
```

**The key abstraction `Channel`**: three methods, `get_props / set_props / call_action`.
`CloudChannel` and `LanChannel` both implement it, and `AutoChannel` prefers the LAN
when "this machine has the token + the device is on the same subnet + the LAN is
reachable", falling back to the cloud on failure. The CLI layer is completely unaware
of which path is taken.

**The default is `cloud`**: the first LAN hit pays for a liveness probe (unicast hello)
plus a call that may fail, and that wait should not be borne by the default; those who
want low latency pass `--channel lan` explicitly, or make it the default with
`mi config set channel auto`.

### 3.1 Local storage

```
~/.config/mi-home-cli/
├── config.toml                 # default profile, region, output format, timeout, lan switch
└── profiles/<name>/
    ├── auth.json               # access/refresh token, uid, expiry time   (chmod 600)
    ├── devices.json            # device list cache (includes LAN tokens)   (chmod 600)
    ├── aliases.json            # user-defined short names
    └── spec/<urn>.json         # spec cache (14 days by default, same as upstream)
```

- Files containing secrets are always `0600` and directories `0700`; permissions are checked at startup and a warning is issued if they are wrong.
- LAN tokens are masked by default in all output; only `--show-secrets` shows them in plain text.
- LAN addresses are cached in `lan.json` (did → IP + discovery time). On a hit a
  unicast hello is sent first to confirm (tens of milliseconds); only on failure is a
  broadcast scan repeated.
- The `MI_HOME_CONFIG_DIR` environment variable overrides the location; `--profile` manages multiple accounts / regions.

### 3.2 Login flow (the hard part of the CLI version)

**The redirect_uri is locked down by a server-side allowlist**, and this is the hardest constraint of the whole CLI.

Upstream `miot/const.py` says:

```python
# Registered in Xiaomi OAuth 2.0 Service
# DO NOT CHANGE UNLESS YOU HAVE AN ADMINISTRATOR PERMISSION
OAUTH_REDIRECT_URL: str = 'http://homeassistant.local:8123'
```

HA then appends its own webhook path, ending up with
`http://homeassistant.local:8123/api/webhook/{virtual_did}`.

How the authorization endpoint reacted to various redirect_uri values when tested:

| redirect_uri | Result |
| --- | --- |
| `http://homeassistant.local:8123/api/webhook/123456` | 302 → login page ✅ |
| `http://homeassistant.local:8123/mi-home-cli/callback` | 302 ✅ |
| `http://homeassistant.local:8123/x?foo=bar` | 302 ✅ |
| `https://homeassistant.local:8123/x` | 302 ✅ |
| `http://homeassistant.local:9527/x` | `invalid redirect uri` ❌ |
| `http://localhost:8123/x` | `invalid redirect uri` ❌ |
| `http://127.0.0.1:9527` | `invalid redirect uri` ❌ |

**Conclusion for the authorization step: the host must be `homeassistant.local:8123`;
the scheme, path and query are not checked.**

But **the token exchange step compares once more**. With a real authorization code
obtained using a custom path (`/mi-home-cli/callback`) and a custom `device_id`
(`cli.xxx`), the token exchange returns `96002 invalid request`; testing the same
parameters with a fake authorization code gives `96013 invalid authorization code`
instead — which shows that the server looks up the authorization code first and only
checks the bound information after finding it, so 96002 means "the code itself is
valid, but the parameters are not what was expected".

So the identity triple is generated exactly in Home Assistant's shape:

| Item | Value |
| --- | --- |
| `redirect_uri` | `http://homeassistant.local:8123/api/webhook/{webhook_id}`, `webhook_id` = a random 64-bit integer |
| `device_id` | `ha.` + 32 hex chars (`sha256(install_id.webhook_id.region)[:32]`) |
| `state` | `sha1("d=" + device_id)`, the same algorithm as upstream |

These three values are persisted per profile in `identity.json`; authorization and
token exchange must use the same set, so every `mi auth login` writes them together
with `state` into `pending.json`. Should the token exchange fail, it can be retried
with the same authorization code via `mi auth exchange <code>`, without going through
the browser again.

To receive the code automatically, two things must therefore hold at once: the browser
resolves `homeassistant.local` to the machine running the CLI, and port 8123 on that
machine is listened on by us. The implementation makes a best effort in the following
order, and no failed step blocks the flow:

1. Port 8123 can be bound → start a local HTTP server (accepts any path, only cares
   about `code`/`state`). If Home Assistant is running on this machine the port is
   taken, and we jump straight to pasting.
2. `homeassistant.local` already resolves to this machine (hosts file or mDNS on the
   LAN) → usable as is.
3. Otherwise, if `zeroconf` is installed, advertise an mDNS record ourselves pointing
   `homeassistant.local` at this machine's IP. If there is a real HA on the LAN the
   name collides; on a collision we give up.
4. **The paste fallback, always available**: after the browser is redirected to an
   address that will not load, the address bar still contains
   `?code=...&state=...`; the user pastes the whole thing back into the terminal. The
   local server and the paste prompt wait at the same time, and whichever arrives
   first is used; `--manual` only uses pasting.

On security: the `state` of a local callback must match exactly to be accepted (a
mismatch means someone else sent a request to this port); a warning is issued when
pasted content lacks `state`. `state` is derived from `device_id` (same algorithm as
upstream) rather than being random each time — the callback only listens briefly on
this machine, and what this trade-off buys is parameters fully identical to upstream,
one variable fewer to troubleshoot.

The token is renewed automatically before it expires (once 70% of its lifetime is
used up); if renewal fails, the user is told to run `mi auth login` again, with exit
code `10`.

### 3.3 QR-code login (`--scan`)

All the pain of browser login lies in the `redirect_uri` allowlist (see 3.2). QR-code
login takes a different approach: **the authorization code is still the very `code`
that the browser login page produces; only "a person typing account and password into
a browser" is replaced by "a person scanning and confirming with a Xiaomi app"**. The
second half (`code` → `get_token`) shares the same code and the same identity triple
with browser login; scanning is merely another way of doing the first half, "getting
the code".

**A headless browser is deliberately not introduced**; the login page's redirect flow
is reproduced with plain API calls. The findings from analysing the authorization
page's redirects are as follows (`core/qrlogin.py`):

1. `GET oauth2/authorize` (`skip_confirm=true`) → `302` to
   `pass/serviceLogin?...&sid=oauth2.0&callback=...&_ssign=...`. The serviceLogin
   address is not hard-coded; we follow this 302, one changeable constant fewer.
2. `GET serviceLogin?_json=true` → returns JSON, from which the login parameters
   `_sign` / `sid` / `qs` / `callback` / `serviceParam` are taken. When not logged in
   the response carries `code=70016 登录验证失败` ("login verification failed"), which
   is the **normal state** (what we want are the parameters inside, not a login
   result); at the same time the server sets cookies such as `deviceId`, which must
   be carried along in every later step.
3. `GET longPolling/loginUrl` (with the parameters from the previous step) → returns:
   - `loginUrl`: the address encoded into the QR code for the user to scan;
   - `lp`: the long-polling address;
   - `qr`: the address of a server-rendered QR code image (the fallback when `segno`
     is not installed);
   - `timeout`: the validity of the QR code (about 300 seconds).
4. `loginUrl` is drawn as a QR code in the terminal. Rendering uses "the upper half
   block `▀` + the foreground colour for the upper module and the background colour
   for the lower module": the background colour also fills the line-spacing gap,
   which keeps half blocks from splitting into stripes in terminals with a
   line-height; foreground/background are explicitly black and white, so neither dark
   nor light themes invert it. The QR code is encoded with `segno` (pure Python, zero
   dependencies, a direct dependency, works once installed). The aspect ratio of a
   terminal character cell varies with terminal and font, so a plain-text QR code
   cannot be square in every terminal; therefore **the server's `qr` image address is
   always printed as well** (a PNG, visible by opening it in a browser), plus
   `loginUrl` itself as a fallback — so that failing to scan in the terminal never
   leaves you stuck.
5. Long-poll `lp`: it hangs until the phone confirms. A single request is re-sent once
   it has hung up to the limit (30s); the overall time limit is the smaller of
   `--wait` and the QR code's validity. When the phone has scanned but not confirmed
   yet, the server may first return an intermediate response without `location`; in
   that case we keep waiting.
6. After confirmation `lp` returns a `location`. Its redirect chain
   (`sts` → `oauth2/authorize` → `redirect_uri`) is followed **carrying the cookies
   collected along the way**. On reaching the hop whose host is
   `homeassistant.local` — a machine that is most likely unreachable — the URL is
   **only parsed, not actually requested**, and `code` and `state` are taken straight
   from its query (reusing the parsing of the paste path, including the `state`
   check).
7. `code` is handed to `OAuthClient.exchange_code`, joining the browser login path.

The region (`--region`) only affects the API host used later for the token exchange;
the account login page itself is independent of the region, and
`longPolling/loginUrl` picks an access point automatically based on your egress (the
`dc` in the response).

**Do not register one more device on every scan**: on first access the login page
issues a random `deviceId` cookie, and Xiaomi registers a web device under the
account's "logged-in devices" according to it (shown as Chrome, based on the browser
UA). Creating a fresh empty cookie jar for each scan would keep adding more. So a
stable `deviceId` is generated and persisted per profile (`scan_device.json`, shaped
like `wb_{uuid}`) and sent as a cookie on every scan — testing shows the server reuses
it as is (`Set-Cookie` echoes the same value), so Xiaomi treats it as the same device
and adds no new one.

**What name that device is shown under** depends on the `User-Agent` of the login
request (Xiaomi parses the UA). The default is `mi-home-cli/{version}` rather than a
browser UA, so that the account is not full of "Chrome" entries; it can be customised
with `mi config set scan_device_name <name>` or the `MI_SCAN_DEVICE_NAME` environment
variable. Testing shows the account page issues a QR code normally for any UA, so
there is no need to impersonate a browser; but the UA is an HTTP header and can only
be ASCII, so the device name cannot contain Chinese (this is validated and rejected
when it is set).

**Fallback for the first authorization**: for a first authorization Xiaomi requires
one manual tap on "同意并关联 / Agree and link" (the OAuth consent, the same as for
browser login); `skip_confirm=true` can only skip logins that were already authorized
**afterwards**. If the first scan therefore fails to get a code or the token exchange
fails, the scan flow falls back to giving the **original authorization link**
(`oauth2/authorize`, `skip_confirm=false`) — open it in a browser, or scan its QR code
with a phone, then log in and authorize once. When done, you can either paste the
browser callback address back to exchange the token directly, or just press Enter to
scan again (the authorization is remembered by then, `skip_confirm` takes effect, and
the page no longer appears). The authorization link is rather long; when its QR code
is wider than the terminal's columns, only the link is given and no code is drawn (a
drawn one would wrap and break, making it unscannable).

---

## 4. The two keys to usability: device resolution and property resolution

Whether the CLI experience succeeds does not depend on the protocol but on **not
making people memorise dids and siid/piid**.

### 4.1 Device references (the `<device>` argument)

Matched in order; the first unique hit is used:

1. `did` (purely numeric, or with a `.sN` sub-device suffix)
2. User alias (`mi device alias set living-room-light xxx`)
3. Exact device name match (case-insensitive)
4. `room/device name`, e.g. `Living Room/Ceiling Light`
5. Fuzzy substring match on the device name
6. `model` match (e.g. `yeelink.light.lamp4`)

Multiple candidates → an error listing the candidates (with did, room, model), exit
code `4`. `--home` / `--room` / `--model` narrow the scope.

When there is more than one home, `mi home use <home>` sets a default home, after
which resolution only happens within that home — the most effective way to eliminate
ambiguity from duplicate names. The default home is matched by `home_id` (renaming
the home does not affect it). When a device is in another home, the CLI does not
silently operate across homes but reports an error stating which home it is in;
`--all-homes` crosses homes temporarily.

### 4.2 Property / action references

`<prop>` supports three notations, resolved from the spec index:

- Numeric: `2.1`
- Full name: `light.brightness` (service instance name.property instance name)
- Short name: `brightness` (only allowed if unique within the device; otherwise an error suggests using the full name)

Value handling is entirely driven by the spec:

- `bool`: `on/off/true/false/1/0/开/关` (the Chinese words `开` "on" and `关` "off" are accepted as input too)
- `uint8/int32/float`: validated against `min/max/step` of `value-range`; out-of-range values are an error (never silently clamped)
- Enum `value-list`: the description text (`Mode=Sleep` with the English interface, `模式=睡眠` with the Chinese one — spec descriptions follow the interface language) or the number may be written; on output the description is looked up
- `string`: as is
- Writing a read-only property / reading an unreadable property → caught locally with an error before any request is sent

`action` input arguments follow the order of `in` in the spec; both positional passing with `--in a --in b` and named passing with `--param name=value` are supported.

---

## 5. Output and errors

- The default is `table` (rich, adapts to the terminal width automatically); `-o json` outputs a stable schema that is **guaranteed to be consumable by `jq`** (colours are turned off automatically when piped to a non-TTY); there are also `-o yaml` / `-o plain` (values only, handy for `$(...)`).
- Every write operation prints "property → old value → new value → result": the old
  values are read in one batch before writing, one extra request in exchange for
  "being able to roll back by the book after a wrong change".
- **A return code does not mean it took effect.** The `code` of `prop/set` is only a
  receipt: `0` is success, `1` is "accepted, the device is executing" — some devices
  (`dwdz.switch.sw0a01` in testing) answer `1` to every write, and the operation
  actually succeeded. Treating every non-zero code as failure would make every
  command for such devices report an error. So both `0` and `1` count as accepted.
  For a firm conclusion add `--verify`: read back once after writing and let the real
  state speak; when the read-back has not caught up, the hint says "there may be a
  delay" instead of declaring failure. No read-back by default — one more round trip
  per write (about 0.6s) is not worth it for interactive use; ask for it explicitly in
  scenarios that need confirmation. `--dry-run` only parses and sends no request, to check that parsing is right.
- Exit codes: `0` success / `1` generic error / `2` argument error / `3` device not found / `4` ambiguous reference / `5` device offline / `6` property or action not found / `7` invalid value / `8` network error / `9` the cloud returned an error / `10` not logged in or token invalid.
- Error messages append the `code/message` returned by Xiaomi verbatim at the end (with `--verbose` the full request and response are printed).

---

## 6. Implementation phases

| Phase | Content | Outcome |
| --- | --- | --- |
| **M1 Get it working** | ✅ OAuth login (local callback + mDNS + `--manual` fallback), token storage/refresh, `auth *`, `profile *`, `doctor` | can log in |
| **M2 Control** | ✅ `home/room/device list`, device list cache and resolution, spec fetching and caching, `spec show/search/dump`, `get`/`set`/`action`, value conversion, `on/off/toggle`, `-o json`, `--dry-run` | core usable |
| **M3 Convenience** | ✅ the semantic commands `light`/`climate`/`cover`/`fan`, `device alias`, write operations showing old value → new value, shell completion (built into typer) | usable day to day |
| **M4 Real time** | ✅ cloud MQTT `watch` (properties / events / online state), streaming output, line-delimited JSON | can trigger scripts |
| **M5 Local** | ✅ LAN channel (own miIO implementation), `lan list/discover/status`, `--channel auto\|cloud\|lan` fallback | low latency, works offline |
| Optional | `repl` interactive mode, scenes (`/app/v2/scene/*` needs exploring and verifying ourselves, unused upstream), central hub gateway control | — |

## 6.5 An explicit non-goal: OAuth2 only

Two parallel identities exist in the Mi Home ecosystem:

| | OAuth2 (this project / the official HA integration) | Account password (the Mi Home app, al-one/hass-xiaomi-miot) |
| --- | --- | --- |
| What you get | `access_token` | `serviceToken` + `ssecurity`; requests need RC4 signing |
| Usable APIs | the `/app/v2/*` set of spec APIs | all of the above, **plus** private APIs such as smartcamera and scenes |
| Cost | login on the authorization page, never touching the user's password | has to handle passwords, two-step verification and the signing algorithm |

**This project only uses OAuth2.** The price is that the following cannot be done, which are known and accepted gaps:

- **Camera alarm recording playback**: `get/eventlist` and `common/app/m3u8` on
  `business.smartcamera.api.io.mi.com` require `serviceToken` + `ssecurity` + RC4
  signing.
- **Mi Home scenes / automations**: likewise under that identity.

Rationale: not touching the user's password is one of this CLI's security baselines —
OAuth2 authorization is completed in the browser, and the CLI only gets a revocable
token valid for 3 days; switching to account passwords would mean handling passwords
and two-step verification locally, and neither the risk nor the maintenance cost is
worth these few features.

Those who need these capabilities are better served by
[al-one/hass-xiaomi-miot](https://github.com/al-one/hass-xiaomi-miot) (Apache-2.0).

To clear up an easily confused point along the way: **the camera live stream address
is not on this dividing line**. The spec of some models carries the
`camera-stream-for-google-home` / `camera-stream-for-amazon-alexa` services;
`start-hls-stream` / `start-rtsp-stream` are ordinary spec actions that OAuth2 can
call, `mi action <device> start-rtsp-stream` just works, and the returned address
comes with the property name. Models without these two services (such as
`chuangmi.camera.039c01` and `chuangmi.camera.079ac1`) only have `p2p-stream`, which
is Xiaomi's private cs2 protocol and not part of miot-spec's data plane. Support is
decided per SKU; different SKUs of the same product may differ, one having it and
the other not — for the full list and the scan script see
[camera-stream.en.md](camera-stream.en.md).

## 7. Testing strategy

- The protocol layer is tested by replaying recorded responses as fixtures (**fixtures must be sanitised**: did, uid, token, ssid/bssid, latitude/longitude).
- The resolution layer (device resolution, property resolution, value conversion, exit codes) is pure unit tests that never touch the network.
- A `--mock` mode: run complete commands against local fixtures, convenient for writing documentation examples and for CI.
- CI only runs offline tests; real-device tests are cases marked `@pytest.mark.live`, run manually and locally.

## 8. Known risks

1. **The APIs are not a public contract**: `app/v2/*` is the API Mi Home provides for the HA integration and may change at any time; URLs and fields are concentrated in the single place `core/cloud.py` to make following changes easy.
2. **The `redirect_uri` allowlist**: testing confirmed the host is locked to
   `homeassistant.local:8123` (see 3.2). If Xiaomi adjusts the allowlist, the
   automatic callback stops working; pasting is unaffected.
3. **Rate limits**: batch property reads must keep to the "aggregation + ≤150 entries per request" strategy, and `watch` uses MQTT rather than polling.
4. **Limited LAN coverage**: only devices with `connect_type ∈ {0,8,12,23}` and a
   token (WiFi/wired devices connected directly to the router) can be reached
   directly; Bluetooth Mesh and ZigBee devices behind a gateway cannot. In testing,
   only 21 of the 72 devices of one account qualified. `--channel auto` silently
   falls back to the cloud whenever any step does not hold, so the limited coverage
   does not affect usability.
5. **Credential security**: a device token is equivalent to LAN control; triple protection through file permissions + masked output + never writing it to logs.
