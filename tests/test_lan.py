"""The miIO LAN protocol.

A self-made fake device (independent of the packing logic of the code under test)
runs the full path: handshake, encryption, checksum, timeout. Verification on real
hardware is only possible on the same subnet; here we make sure the protocol layer
is right.
"""
import hashlib
import json
import socket
import struct
import threading

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from mi_home_cli.core.lan import Endpoint, LanDevice, _parse_hello
from mi_home_cli.errors import DeviceOffline, MiCliError

TOKEN = "0123456789abcdef0123456789abcdef"
DID = 123456789
STAMP = 4242


def _cipher(token: bytes):
    key = hashlib.md5(token).digest()
    iv = hashlib.md5(key + token).digest()
    return Cipher(algorithms.AES128(key), modes.CBC(iv), default_backend())


class FakeDevice(threading.Thread):
    """A fake device that speaks miIO, with the packing logic written independently from the protocol."""

    def __init__(self, token: str = TOKEN, *, silent: bool = False, echo_id=None):
        super().__init__(daemon=True)
        self.token = bytes.fromhex(token)
        self.silent = silent
        self.echo_id = echo_id
        self.requests: list[dict] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(3)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()

    def endpoint(self) -> Endpoint:
        import time as _t

        return Endpoint(
            did=str(DID), ip="127.0.0.1", stamp=STAMP,
            offset=_t.time() - STAMP, port=self.port,
        )

    def run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            if self.silent:
                continue
            if data == b"\x21\x31\x00\x20" + b"\xff" * 28:
                self.sock.sendto(self._hello_reply(), addr)
                continue
            try:
                request = self._decrypt(data)
            except AssertionError:
                # checksum mismatch: a real device also just drops the packet and
                # replies nothing
                continue
            self.requests.append(request)
            self.sock.sendto(self._reply(request), addr)

    def stop(self):
        self._stop.set()
        self.sock.close()

    def _hello_reply(self) -> bytes:
        return struct.pack(">HHQI16s", 0x2131, 32, DID, STAMP, b"\x00" * 16)

    def _decrypt(self, data: bytes) -> dict:
        total = struct.unpack(">H", data[2:4])[0]
        buffer = bytearray(data[:total])
        checksum = bytes(buffer[16:32])
        buffer[16:32] = self.token
        assert hashlib.md5(bytes(buffer)).digest() == checksum, "the checksum computed by the client is wrong"
        decryptor = _cipher(self.token).decryptor()
        padded = decryptor.update(bytes(buffer[32:total])) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES128.block_size).unpadder()
        return json.loads(unpadder.update(padded) + unpadder.finalize())

    def _reply(self, request: dict) -> bytes:
        method = request.get("method")
        if method == "get_properties":
            result = [
                {**item, "value": 42, "code": 0} for item in request["params"]
            ]
        elif method == "set_properties":
            result = [
                {k: v for k, v in item.items() if k != "value"} | {"code": 0}
                for item in request["params"]
            ]
        elif method == "action":
            result = {"code": 0, "out": []}
        else:
            result = {"code": -1}
        body = {
            "id": self.echo_id if self.echo_id is not None else request["id"],
            "result": result,
        }
        clear = json.dumps(body).encode()
        padder = padding.PKCS7(algorithms.AES128.block_size).padder()
        encryptor = _cipher(self.token).encryptor()
        encrypted = encryptor.update(padder.update(clear) + padder.finalize())
        encrypted += encryptor.finalize()
        total = len(encrypted) + 32
        packet = bytearray(total)
        packet[:32] = struct.pack(">HHQI16s", 0x2131, total, DID, STAMP, self.token)
        packet[32:] = encrypted
        packet[16:32] = hashlib.md5(bytes(packet)).digest()
        return bytes(packet)


@pytest.fixture()
def device():
    fake = FakeDevice()
    fake.start()
    yield fake
    fake.stop()


def test_get_properties_roundtrip(device: FakeDevice):
    lan = LanDevice(str(DID), TOKEN, device.endpoint())
    result = lan.get_props([{"did": str(DID), "siid": 2, "piid": 1}])
    assert result == [{"did": str(DID), "siid": 2, "piid": 1, "value": 42, "code": 0}]
    assert device.requests[0]["method"] == "get_properties"


def test_set_properties_roundtrip(device: FakeDevice):
    lan = LanDevice(str(DID), TOKEN, device.endpoint())
    result = lan.set_props([{"did": str(DID), "siid": 2, "piid": 1, "value": True}])
    assert result[0]["code"] == 0
    assert device.requests[0]["params"][0]["value"] is True


def test_action_roundtrip(device: FakeDevice):
    lan = LanDevice(str(DID), TOKEN, device.endpoint())
    assert lan.call_action(str(DID), 2, 1, [5])["code"] == 0
    assert device.requests[0]["params"] == {
        "did": str(DID), "siid": 2, "aiid": 1, "in": [5],
    }


def test_request_carries_device_clock(device: FakeDevice):
    """The timestamp in a request must be derived from the device's own clock, not local time."""
    lan = LanDevice(str(DID), TOKEN, device.endpoint())
    lan.get_props([{"did": str(DID), "siid": 2, "piid": 1}])
    packet = lan._build({"id": 1, "method": "x", "params": []})
    stamp = struct.unpack(">I", packet[12:16])[0]
    assert abs(stamp - STAMP) <= 2


def test_wrong_token_times_out_with_token_hint(device: FakeDevice):
    """With a wrong token the device does not reply at all, so it looks like a timeout — the hint must mention the token,

    or the user will keep investigating the network.
    """
    lan = LanDevice(str(DID), "f" * 32, device.endpoint())
    with pytest.raises(DeviceOffline) as excinfo:
        lan.get_props([{"did": str(DID), "siid": 2, "piid": 1}])
    assert not device.requests  # the device side really dropped it
    assert "token" in (excinfo.value.hint or "")


def test_timeout_reports_offline():
    fake = FakeDevice(silent=True)
    fake.start()
    try:
        lan = LanDevice(str(DID), TOKEN, fake.endpoint())
        with pytest.raises(DeviceOffline) as excinfo:
            lan.get_props(
                [{"did": str(DID), "siid": 2, "piid": 1}]
            )
        assert excinfo.value.exit_code == 5
    finally:
        fake.stop()


def test_stale_response_id_is_ignored():
    """A late response to the previous timed-out request must not be taken as this call's result."""
    fake = FakeDevice(echo_id=99999)
    fake.start()
    try:
        lan = LanDevice(str(DID), TOKEN, fake.endpoint())
        with pytest.raises(DeviceOffline):
            lan.get_props([{"did": str(DID), "siid": 2, "piid": 1}])
    finally:
        fake.stop()


def test_parse_hello():
    payload = struct.pack(">HHQI16s", 0x2131, 32, DID, STAMP, b"\xff" * 16)
    endpoint = _parse_hello(payload, 12.0, "192.168.1.9")
    assert endpoint.did == str(DID)
    assert endpoint.stamp == STAMP
    assert endpoint.ip == "192.168.1.9"
    assert _parse_hello(b"nope", 0, "1.2.3.4") is None


def test_bad_token_length_rejected_early():
    with pytest.raises(MiCliError):
        LanDevice("1", "abc", Endpoint("1", "127.0.0.1", 0, 0.0))


def test_hello_did_is_four_bytes_not_eight():
    """did only takes 4 bytes; the unknown field before it is not necessarily 0 in replies.

    One device was seen to put 16 into unknown; reading 8 bytes then gives an absurd
    did like 70044981670, which never matches the cloud's list and makes direct control
    impossible.
    """
    payload = (
        struct.pack(">HH", 0x2131, 32)
        + struct.pack(">I", 16)  # unknown ≠ 0
        + struct.pack(">I", 1325504934)  # did, still within 32 bits
        + struct.pack(">I", STAMP)
        + b"\xff" * 16
    )
    endpoint = _parse_hello(payload, 0, "192.0.2.9")
    assert endpoint.did == "1325504934"


def test_broadcast_elapsed_is_not_labelled_as_rtt():
    """The time measured by a broadcast scan includes queueing and must not be treated as round-trip latency."""
    payload = struct.pack(">HHQI16s", 0x2131, 32, DID, STAMP, b"\xff" * 16)
    assert _parse_hello(payload, 654.0, "1.2.3.4").is_rtt is False
    assert _parse_hello(payload, 5.0, "1.2.3.4", is_rtt=True).is_rtt is True


def test_auto_channel_falls_back_when_lan_call_fails():
    """A successful handshake does not mean the device is willing to work over the LAN — some devices answer get_properties

    with user ack timeout. The fallback has to happen on every call; falling back only
    at the locating stage is not enough.
    """
    from mi_home_cli.core.channel import AutoChannel
    from mi_home_cli.errors import MiCliError as _Err

    class FailingLan:
        name = "lan"

        def get_props(self, params):
            raise _Err("The device returned an error: user ack timeout")

        def set_props(self, params):
            raise _Err("timeout")

        def call_action(self, did, siid, aiid, values):
            raise _Err("timeout")

    class Cloud:
        name = "cloud"
        calls = 0

        def get_props(self, params):
            Cloud.calls += 1
            return [{"siid": 2, "piid": 1, "value": True, "code": 0}]

        def set_props(self, params):
            Cloud.calls += 1
            return [{"code": 0}]

        def call_action(self, did, siid, aiid, values):
            Cloud.calls += 1
            return {"code": 0}

    notes: list[str] = []
    channel = AutoChannel(FailingLan(), Cloud(), on_note=notes.append)
    assert channel.get_props([{"siid": 2, "piid": 1}])[0]["value"] is True
    assert "user ack timeout" in notes[0]
    # after one failure the LAN is not retried, so not every command waits in vain
    channel.set_props([{"siid": 2, "piid": 1, "value": False}])
    channel.call_action("d", 2, 1, [])
    assert Cloud.calls == 3
    assert len(notes) == 1


def test_lan_failure_is_remembered_across_runs(tmp_path):
    """Not retrying within one session is not enough — the next command must not try in vain again either."""
    import time as _t

    from mi_home_cli.core.channel import (
        clear_lan_failures,
        lan_failure,
        record_lan_failure,
    )
    from mi_home_cli.store import Profile

    profile = Profile("default", root=tmp_path)
    assert lan_failure(profile, "d1") is None

    record_lan_failure(profile, "d1", "user ack timeout")
    failed_at, reason = lan_failure(profile, "d1")
    assert reason == "user ack timeout"
    assert abs(failed_at - int(_t.time())) < 5

    # a rescan is new evidence, so the mark must be cleared (a firmware upgrade may have
    # added support)
    clear_lan_failures(profile)
    assert lan_failure(profile, "d1") is None


def test_lan_failure_expires(tmp_path, monkeypatch):
    from mi_home_cli.core import channel as channel_module
    from mi_home_cli.store import Profile

    profile = Profile("default", root=tmp_path)
    profile.write_lan({"d1": {"failed_at": 1, "reason": "old"}})
    assert channel_module.lan_failure(profile, "d1") is None
