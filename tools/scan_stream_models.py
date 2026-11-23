"""Scan all camera/doorbell models on miot-spec and find those with the official streaming services.

The result changes as Xiaomi publishes new specs, so this script is more useful than
a static table:

    uv run python tools/scan_stream_models.py            # print a table
    uv run python tools/scan_stream_models.py --json     # output JSON
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx

INSTANCES = "https://miot-spec.org/miot-spec-v2/instances"
INSTANCE = "https://miot-spec.org/miot-spec-v2/instance"
DEVICE_TYPES = (":device:camera:", ":device:video-doorbell:")
# These two services were originally meant for Google Home / Alexa, but they
# are ordinary spec services that any client able to call spec actions can use
STREAM_SERVICE_PREFIX = "camera-stream-for-"


def scan(timeout: float = 30.0, workers: int = 16) -> dict[str, dict]:
    client = httpx.Client(timeout=timeout)
    instances = client.get(INSTANCES, params={"status": "released"}).json()["instances"]
    cameras = [
        item
        for item in instances
        if any(kind in item["type"] for kind in DEVICE_TYPES)
    ]

    def check(item: dict) -> tuple[str, dict] | None:
        try:
            spec = client.get(INSTANCE, params={"type": item["type"]}).json()
        except (httpx.HTTPError, ValueError):
            return None
        actions: set[str] = set()
        for service in spec.get("services", []):
            name = service["type"].split(":")[3]
            if not name.startswith(STREAM_SERVICE_PREFIX):
                continue
            actions.update(
                action["type"].split(":")[3] for action in service.get("actions", [])
            )
        if not actions:
            return None
        return item["model"], {"actions": sorted(actions)}

    found: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(check, cameras):
            if result:
                model, info = result
                found.setdefault(model, {"actions": []})
                info["actions"] = sorted(
                    set(found[model]["actions"]) | set(info["actions"])
                )
                found[model] = info
    for info in found.values():
        starts = [a for a in info["actions"] if a.startswith("start-")]
        # Models that hand out an address (start-rtsp/hls-stream) and models that need
        # WebRTC negotiation are used completely differently
        info["kind"] = "url" if starts else "webrtc"
    return dict(sorted(found.items()))


def main() -> None:
    found = scan()
    if "--json" in sys.argv:
        print(json.dumps(found, ensure_ascii=False, indent=2))
        return
    url_models = {k: v for k, v in found.items() if v["kind"] == "url"}
    webrtc = {k: v for k, v in found.items() if v["kind"] == "webrtc"}
    print(f"Models that hand out a stream address directly ({len(url_models)}):")
    for model, info in url_models.items():
        print(f"  {model:30} {', '.join(info['actions'])}")
    print(f"\nModels that only offer WebRTC negotiation ({len(webrtc)}, no ready-made address):")
    for model in webrtc:
        print(f"  {model}")


if __name__ == "__main__":
    main()
