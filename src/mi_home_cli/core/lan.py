"""Direct LAN control (the miIO protocol).

UDP 54321, packet layout:

    0-1    magic 0x2131
    2-3    total packet length
    4-7    unknown (0 when sending; not necessarily 0 in device replies, one
           device was seen to put 16 there)
    8-11   did
    12-15  the device's own timestamp
    16-31  md5 checksum (these 16 bytes hold the token while it is computed)
    32-    JSON-RPC encrypted with AES-128-CBC, PKCS7 padding

key = md5(token), IV = md5(md5(token) + token). The handshake (hello) packet is 32
bytes of ff; the device replies with a packet of the same format that carries its
current timestamp — every later request has to carry a value derived from that
timestamp, or the device drops it.

Only WiFi/wired devices connected directly to the router can be controlled;
devices behind a gateway (Bluetooth Mesh, ZigBee) cannot.
"""
from __future__ import annotations

import hashlib
import json
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..errors import DeviceOffline, MiCliError, NetworkError

PORT = 54321
# Devices handle miot-spec requests far more slowly than the handshake: tens of
# milliseconds for the handshake, possibly seconds for property reads/writes
CALL_TIMEOUT = 3.0
MAGIC = 0x2131
HEADER_LEN = 32
HELLO = bytes.fromhex("21310020" + "ffffffff" * 7)
BROADCAST = "255.255.255.255"


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


@dataclass
class Endpoint:
    """A device's location on the LAN, and its clock."""

    did: str
    ip: str
    stamp: int  # the timestamp the device itself reports
    offset: float  # local time - device timestamp, used to work out what later requests must carry
    elapsed_ms: float = 0.0  # time from sending the probe to receiving this device's reply
    port: int = PORT
    # In a broadcast scan this time includes queueing and is not round-trip
    # latency; only a unicast probe (ping) measures real latency
    is_rtt: bool = False

    def current_stamp(self) -> int:
        return int(time.time() - self.offset)


def _parse_hello(
    data: bytes,
    elapsed_ms: float,
    ip: str,
    port: int = PORT,
    is_rtt: bool = False,
) -> Endpoint | None:
    if len(data) < HEADER_LEN or data[:2] != b"\x21\x31":
        return None
    # did is 4 bytes. The 4 bytes before it (unknown) are not necessarily 0 in a
    # reply — one device was seen to put 16 there — so the 8 bytes must not be read
    # as one integer, or the did becomes astronomically large and never matches
    # the cloud's list.
    did = struct.unpack(">I", data[8:12])[0]
    stamp = struct.unpack(">I", data[12:16])[0]
    return Endpoint(
        did=str(did),
        ip=ip,
        stamp=stamp,
        offset=time.time() - stamp,
        elapsed_ms=elapsed_ms,
        port=port,
        is_rtt=is_rtt,
    )


def discover(timeout: float = 3.0, address: str = BROADCAST) -> dict[str, Endpoint]:
    """Broadcast hello and collect the replies. Returns did → Endpoint."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    found: dict[str, Endpoint] = {}
    try:
        started = time.time()
        try:
            sock.sendto(HELLO, (address, PORT))
        except OSError as err:
            raise NetworkError(f"Broadcast failed: {err}") from err
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            endpoint = _parse_hello(data, (time.time() - started) * 1000, addr[0])
            if endpoint:
                found.setdefault(endpoint.did, endpoint)
    finally:
        sock.close()
    return found


def ping(ip: str, timeout: float = 0.6, port: int = PORT) -> Endpoint | None:
    """Send hello to a known IP, to confirm that a cached address is still valid."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        started = time.time()
        sock.sendto(HELLO, (ip, port))
        data, _ = sock.recvfrom(1024)
        return _parse_hello(
                data, (time.time() - started) * 1000, ip, port, is_rtt=True
            )
    except (socket.timeout, OSError):
        return None
    finally:
        sock.close()


class LanDevice:
    """A device that can be controlled directly."""

    def __init__(self, did: str, token: str, endpoint: Endpoint) -> None:
        if len(token) != 32:
            raise MiCliError("Wrong token length (expected 32 hex characters): "
                             f"{token!r}")
        self.did = did
        self.endpoint = endpoint
        self._token = bytes.fromhex(token)
        key = _md5(self._token)
        iv = _md5(key + self._token)
        self._cipher = Cipher(
            algorithms.AES128(key), modes.CBC(iv), default_backend()
        )
        self._msg_id = int(time.time()) % 10000

    # ---------- packing / unpacking ----------

    def _build(self, payload: dict[str, Any]) -> bytes:
        clear = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        padder = padding.PKCS7(algorithms.AES128.block_size).padder()
        encryptor = self._cipher.encryptor()
        body = encryptor.update(padder.update(clear) + padder.finalize())
        body += encryptor.finalize()
        total = len(body) + HEADER_LEN
        packet = bytearray(total)
        packet[:HEADER_LEN] = struct.pack(
            ">HHQI16s",
            MAGIC,
            total,
            int(self.did),
            self.endpoint.current_stamp(),
            self._token,
        )
        packet[HEADER_LEN:] = body
        # The checksum is "the md5 of the whole packet with the token placed at [16:32]"
        packet[16:32] = _md5(bytes(packet))
        return bytes(packet)

    def _parse(self, data: bytes) -> dict[str, Any]:
        if len(data) < HEADER_LEN or data[:2] != b"\x21\x31":
            raise MiCliError("Received something that is not a miIO packet")
        total = struct.unpack(">H", data[2:4])[0]
        buffer = bytearray(data[:total])
        checksum = bytes(buffer[16:32])
        buffer[16:32] = self._token
        if _md5(bytes(buffer)) != checksum:
            raise MiCliError(
                "Checksum mismatch: wrong token",
                hint="Refresh the device list with `mi device sync`; the token "
                     "changes when a device is re-paired",
            )
        decryptor = self._cipher.decryptor()
        padded = decryptor.update(bytes(buffer[HEADER_LEN:total])) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES128.block_size).unpadder()
        clear = unpadder.update(padded) + unpadder.finalize()
        # Some devices append an extra \0 to the JSON
        return json.loads(clear.rstrip(b"\x00"))

    # ---------- calls ----------

    def call(
        self,
        method: str,
        params: Any,
        *,
        timeout: float = CALL_TIMEOUT,
        retries: int = 2,
    ) -> Any:
        self._msg_id = (self._msg_id + 1) % 10000
        payload = {"id": self._msg_id, "method": method, "params": params}
        packet = self._build(payload)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            for attempt in range(retries):
                try:
                    sock.sendto(packet, (self.endpoint.ip, self.endpoint.port))
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError as err:
                    raise NetworkError(f"Sending to {self.endpoint.ip} failed: {err}") from err
                response = self._parse(data)
                if response.get("id") != payload["id"]:
                    # A late response to the previous timed-out request; drop it and
                    # keep waiting
                    continue
                if "error" in response:
                    error = response["error"]
                    raise MiCliError(
                        f"The device returned an error: {error.get('message', error)}"
                    )
                return response.get("result")
            raise DeviceOffline(
                f"{self.endpoint.ip} did not respond within {timeout * retries:.0f} "
                "seconds",
                hint=(
                    "A device does not reply to a packet it cannot accept: wrong "
                    "token (it changes after re-pairing; refresh with `mi device "
                    "sync`), the device just went offline, or its IP changed (rescan "
                    "with `mi lan discover`)"
                ),
            )
        finally:
            sock.close()

    # ---------- the same interface as the cloud ----------

    def get_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self.call(
            "get_properties",
            [
                {"did": self.did, "siid": item["siid"], "piid": item["piid"]}
                for item in params
            ],
        )
        return result if isinstance(result, list) else []

    def set_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self.call(
            "set_properties",
            [
                {
                    "did": self.did,
                    "siid": item["siid"],
                    "piid": item["piid"],
                    "value": item["value"],
                }
                for item in params
            ],
        )
        return result if isinstance(result, list) else []

    def call_action(
        self, did: str, siid: int, aiid: int, values: list[Any]
    ) -> dict[str, Any]:
        result = self.call(
            "action", {"did": self.did, "siid": siid, "aiid": aiid, "in": values}
        )
        return result if isinstance(result, dict) else {"code": 0, "out": result}
