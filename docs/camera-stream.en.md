# Which cameras can hand out a stream address via OAuth2

**English** · [简体中文](camera-stream.md)

The spec of some models carries the `camera-stream-for-google-home` /
`camera-stream-for-amazon-alexa` services. These two services were originally meant for
Google Home and Alexa, but they are just ordinary spec services — **any client that can
call spec actions can use them**; this project's OAuth2 identity is sufficient, and the
account-password identity is not needed.

```bash
mi action <camera>                        # if start-rtsp-stream is there, you can get an address
mi action <camera> start-rtsp-stream --in 2
# ↳ stream-address    rtsp://...
# ↳ expiration-time   ...
```

The address has an expiry time; remember to `stop-stream` when you are done.

## Support is decided per SKU

Different SKUs of the same product may differ, one having it and the other not, so do
not judge by the product name:

| Model | Official streaming |
| --- | --- |
| `chuangmi.camera.039c01` (Smart Camera 2 PTZ) | ❌ |
| `chuangmi.camera.039c04` (another SKU of the same product) | ✅ |
| `chuangmi.camera.079ac1` (Smart Camera 4 4K) | ❌ |
| `chuangmi.camera.079ae2` (another SKU of the same product) | ✅ |

Models without this service only have `p2p-stream`, and the stream can only be fetched
through projects that implement cs2 themselves, such as
[go2rtc](https://go2rtc.org/internal/xiaomi/); the reasons follow.

## Why no picture can be obtained from `p2p-stream` under OAuth2

Conclusion: **it cannot be obtained**, and not because "the API was not found" but
because the identity boundary decides so. Evidence from testing:

**1. The device side gives no connection parameters.** Calling `start-p2p-stream`
(siid 9 / aiid 1) returns `code: 0` but an empty `out` — the session is opened, yet
there is no address, no session id and no key at all:

```json
{"did":"...","siid":9,"aiid":1,"code":0,"exe_time":99}
```

**2. The key has to be exchanged separately, and that API is under the other
identity.** In go2rtc's (MIT) implementation (`internal/xiaomi/xiaomi.go`), a key is
exchanged with the cloud before every connection:

```go
cloudUserRequest(url.User, "/v2/device/miss_get_vendor", params)
// {"app_pubkey":"<client public key>","did":"...","support_vendors":"TUTK_CS2_MTP"}
// older devices fall back to /device/devicepass
```

These requests are RC4-signed with a `signedNonce` derived from `ssecurity`, and
`ssecurity` comes from **account-password login** (`serviceLogin` → `passToken` +
`serviceToken`).

**3. The OAuth2 gateway does not have this API.**

| Request | Result |
| --- | --- |
| `ha.api.io.mi.com/app/v2/device/miss_get_vendor` | 404 |
| `ha.api.io.mi.com/app/v2/device/devicepass` | 404 |
| `ha.api.io.mi.com/v2/device/miss_get_vendor` | 204 |
| `ha.api.io.mi.com/any-path-that-does-not-exist` | 204 |

**204 is this gateway's catch-all response for every non-`/app/v2/*` request** and does
not mean the API exists — this was cross-checked against made-up paths.

**4. Knocking on the app's API domain with an OAuth token is rejected.**

```
api.io.mi.com/app/v2/device/miss_get_vendor → 401 {"code":0,"message":"auth error"}
```

It only accepts `serviceToken` + RC4 signing.

So: Xiaomi opened the **control plane** (the spec APIs) to OAuth2 and kept the **data
plane** (the p2p key exchange) under the account-password identity. This project only
uses OAuth2, so this road is a dead end — unless Xiaomi one day mounts
`miss_get_vendor` under `/app/v2/*`.

## Snapshot (2026-08-20, 56 models in total)

The list changes as Xiaomi publishes new specs; rescan with `uv run python tools/scan_stream_models.py`.

### An address can be obtained directly (43)

`start-rtsp-stream` / `start-hls-stream` return a URL.

- `chuangmi.camera.021a04`
- `chuangmi.camera.026c02`
- `chuangmi.camera.026c05`
- `chuangmi.camera.029a02`
- `chuangmi.camera.029b06`
- `chuangmi.camera.039a04`
- `chuangmi.camera.039c04`
- `chuangmi.camera.046a01`
- `chuangmi.camera.046c04`
- `chuangmi.camera.055c02`
- `chuangmi.camera.060a02`
- `chuangmi.camera.065ac1`
- `chuangmi.camera.068ac1`
- `chuangmi.camera.072ae2`
- `chuangmi.camera.075ae1`
- `chuangmi.camera.077ac1`
- `chuangmi.camera.079ae2`
- `chuangmi.camera.081ae2`
- `chuangmi.camera.111ae1`
- `chuangmi.camera.112ae1`
- `chuangmi.camera.115ac1`
- `chuangmi.camera.46e01`
- `chuangmi.camera.ipc009`
- `chuangmi.camera.ipc019`
- `chuangmi.camera.ipc019b`
- `chuangmi.camera.ipc021`
- `isa.camera.500dh`
- `isa.camera.hlc6`
- `isa.camera.hlc7`
- `isa.camera.hlc8a`
- `isa.camera.hlc9a`
- `mijia.camera.v1`
- `mijia.camera.v3`
- `mxiang.camera.c301`
- `mxiang.camera.c500os`
- `mxiang.camera.moc006`
- `mxiang.camera.moc008`
- `mxiang.camera.mod13`
- `mxiang.camera.mwc11`
- `xiaomi.camera.080ao1`
- `xiaomi.camera.c01a01`
- `xiaomi.camera.c302o`
- `xiaovv.camera.xvvi01`

### Only WebRTC negotiation is offered (13)

There is only `initiate-webrtc-session`, which requires an SDP offer/answer exchange; no ready-made address can be obtained, and `mi action` cannot help.

- `chuangmi.camera.061a03`
- `chuangmi.camera.120ae1`
- `isa.camera.700sa`
- `madv.cateye.mi3sg`
- `midr.camera.bw300`
- `midr.camera.bw400`
- `midr.camera.bw400b`
- `midr.camera.bw400g`
- `midr.camera.bw400p`
- `xiaomi.camera.083ae2`
- `xiaomi.camera.c201`
- `xiaomi.camera.c302n`
- `xiaomi.camera.c500a`
