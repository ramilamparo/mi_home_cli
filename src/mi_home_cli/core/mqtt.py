"""Cloud MQTT: subscribe to device property changes, events and online/offline state.

The connection parameters are taken from the behaviour of the Home Assistant Xiaomi
Home integration:
  broker     {region}-ha.mqtt.io.mi.com:8883 (TLS, MQTT v5)
  username   the OAuth client_id
  password   the access_token
  client id  same as the OAuth device_id, i.e. ha.{32 hex chars}
"""
from __future__ import annotations

import json
import os
import queue
import ssl
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import paho.mqtt.client as mqtt

from ..errors import NetworkError
from . import const

BROKER_SUFFIX = "ha.mqtt.io.mi.com"
BROKER_PORT = 8883
KEEPALIVE = 60


CA_BUNDLE_ENV = "MI_CA_BUNDLE"


def _certifi_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def ssl_contexts() -> list[ssl.SSLContext]:
    """The TLS contexts to try, in order.

    If `MI_CA_BUNDLE` is set, only it is used — that is the user's explicit wish (a
    corporate proxy's self-signed CA mostly depends on it). Otherwise the system default
    goes first (it also honours SSL_CERT_FILE, so a corporate root certificate in the
    system keychain takes effect), and certifi is the fallback on failure.

    Note that "is the system store empty" cannot decide whether to fall back to certifi:
    a store that has certificates does not necessarily have the root this chain needs;
    in testing there was a machine whose system store was not empty yet could not verify
    Xiaomi's broker. So the criterion is "verification fails", not "the store is empty".
    """
    override = os.environ.get(CA_BUNDLE_ENV)
    if override:
        return [ssl.create_default_context(cafile=override)]
    contexts = [ssl.create_default_context()]
    fallback = _certifi_context()
    if fallback is not None:
        contexts.append(fallback)
    return contexts


def _ssl_context() -> ssl.SSLContext:
    return ssl_contexts()[0]


def broker_host(region: str) -> str:
    return f"{region}-{BROKER_SUFFIX}"


def topic_props(did: str, siid: int | None = None, piid: int | None = None) -> str:
    tail = "#" if siid is None or piid is None else f"{siid}/{piid}"
    return f"device/{did}/up/properties_changed/{tail}"


def topic_events(did: str) -> str:
    # Upstream misspells occurred as occured and the server really sends it that way, so
    # we have to follow the mistake
    return f"device/{did}/up/event_occured/#"


def topic_state(did: str) -> str:
    return f"device/{did}/state/#"


@dataclass
class Message:
    """One pushed message, already parsed."""

    kind: str  # "prop" | "event" | "state"
    did: str
    siid: int | None = None
    iid: int | None = None  # piid or eiid
    value: Any = None
    arguments: list[Any] | None = None
    state: str | None = None
    raw: dict[str, Any] | None = None


def parse_message(topic: str, payload: bytes) -> Message | None:
    """Parse an MQTT message into a Message; returns None if it cannot be parsed."""
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "device":
        return None
    did = parts[1]
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None

    if "properties_changed" in topic:
        params = body.get("params")
        if not isinstance(params, dict) or "siid" not in params:
            return None
        return Message(
            kind="prop",
            did=did,
            siid=params.get("siid"),
            iid=params.get("piid"),
            value=params.get("value"),
            raw=body,
        )
    if "event_occured" in topic:
        params = body.get("params")
        if not isinstance(params, dict) or "siid" not in params:
            return None
        return Message(
            kind="event",
            did=did,
            siid=params.get("siid"),
            iid=params.get("eiid"),
            arguments=params.get("arguments") or [],
            raw=body,
        )
    if parts[2] == "state":
        event = body.get("event")
        if not event:
            return None
        return Message(
            kind="state", did=body.get("device_id", did), state=event, raw=body
        )
    return None


class CloudMqtt:
    """The subscriber. Messages go into a queue and are consumed by the caller on the main thread."""

    def __init__(
        self,
        *,
        region: str,
        client_id: str,
        token_provider: Callable[[], str],
        on_state_change: Callable[[bool], None] | None = None,
        on_note: Callable[[str], None] | None = None,
        debug: bool = False,
    ) -> None:
        self.region = region
        self._token_provider = token_provider
        self._on_state_change = on_state_change
        self._on_note = on_note
        self.messages: "queue.Queue[Message]" = queue.Queue()
        self._topics: list[str] = []
        self._connected = threading.Event()
        # When connecting fails, record the real reason: TCP unreachable, TLS handshake
        # failed, authentication refused — these three are troubleshot in completely
        # different directions, and squashing them into "timeout" says nothing
        self._failure: str | None = None
        # A deliberate stop() triggers on_disconnect too; do not treat it as a dropped
        # connection
        self._stopping = False
        self._contexts = ssl_contexts()
        self._client_id = client_id
        self._debug = debug
        self._client = self._build_client(self._contexts[0])

    def _build_client(self, context: ssl.SSLContext) -> mqtt.Client:
        """Create a new client with TLS and callbacks configured.

        A new one is needed for every CA bundle: paho's tls_set_context can only be called
        once; the second call raises ValueError.
        """
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            protocol=mqtt.MQTTv5,
        )
        client.tls_set_context(context)
        if self._debug:
            # paho's own log shows the details of the TLS handshake and CONNACK
            client.enable_logger()
        client.on_connect = self._handle_connect
        client.on_connect_fail = self._handle_connect_fail
        client.on_disconnect = self._handle_disconnect
        client.on_message = self._handle_message
        return client

    # ---------- callbacks ----------

    def _handle_connect_fail(self, client, userdata=None):
        """Failed already at the TCP/TLS stage — usually the port is unreachable or certificate verification failed."""
        self._failure = "cannot reach the broker (failed at the TCP or TLS stage)"

    def _handle_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            # Getting here means TCP/TLS worked and the broker refused the connection
            self._failure = f"the broker refused the connection: {reason_code}"
            self._connected.clear()
            return
        # After a reconnect the subscriptions have to be sent again
        for topic in self._topics:
            client.subscribe(topic, qos=0)
        self._connected.set()
        if self._on_state_change:
            self._on_state_change(True)

    def _handle_disconnect(
        self, client, userdata, disconnect_flags=None, reason_code=None, properties=None
    ):
        self._connected.clear()
        if self._stopping:
            return
        if self._on_state_change:
            self._on_state_change(False)
        # The access_token may have been renewed; replace the password with the latest
        # one before reconnecting
        try:
            client.username_pw_set(const.CLIENT_ID, self._token_provider())
        except Exception:
            pass

    def _handle_message(self, client, userdata, message):
        parsed = parse_message(message.topic, message.payload)
        if parsed is not None:
            self.messages.put(parsed)

    # ---------- lifecycle ----------

    def subscribe(self, topics: Iterable[str]) -> None:
        for topic in topics:
            if topic not in self._topics:
                self._topics.append(topic)
        if self._connected.is_set():
            for topic in self._topics:
                self._client.subscribe(topic, qos=0)

    def start(self, timeout: float = 15.0) -> None:
        self._client.username_pw_set(const.CLIENT_ID, self._token_provider())
        host = broker_host(self.region)
        # Use the synchronous connect: the async version swallows handshake exceptions
        # in a background thread and leaves only a timeout, while problems such as a
        # failed certificate verification must be shown to the user verbatim
        last_error: ssl.SSLCertVerificationError | None = None
        for index, context in enumerate(self._contexts):
            if index:
                # Switching CA bundles requires a new client; paho's TLS configuration
                # is one-shot
                self._client = self._build_client(context)
                self._client.username_pw_set(
                    const.CLIENT_ID, self._token_provider()
                )
            try:
                self._client.connect(host, BROKER_PORT, KEEPALIVE)
                if index and self._on_note:
                    self._on_note("The system root certificates failed to verify; "
                                  "switched to certifi's CA bundle")
                break
            except ssl.SSLCertVerificationError as err:
                last_error = err
                continue
            except (OSError, ssl.SSLError) as err:
                raise NetworkError(
                    f"Connecting to {host}:{BROKER_PORT} failed: {type(err).__name__}"
                    f": {err}"
                ) from err
        else:
            raise NetworkError(
                f"{host}:{BROKER_PORT} failed certificate verification: {last_error}",
                hint=(
                    "Neither the system root certificates nor certifi could verify "
                    "it. If you use a proxy such as Clash/Surge, add a direct rule "
                    "for mqtt.io.mi.com; if you really need a man-in-the-middle "
                    f"certificate, set {CA_BUNDLE_ENV}=/path/to/ca.pem"
                ),
            )
        self._client.loop_start()
        if not self._connected.wait(timeout):
            failure = self._failure
            self.stop()
            if failure:
                raise NetworkError(
                    f"Connecting to {broker_host(self.region)}:{BROKER_PORT} failed: "
                    f"{failure}",
                    hint=(
                        "A refused connection is usually a credential problem: run "
                        "`mi auth status --check` first. A failure at the TCP/TLS "
                        "stage means the network blocks port 8883"
                    ),
                )
            raise NetworkError(
                f"Connecting to {broker_host(self.region)}:{BROKER_PORT} timed out "
                f"(no response within {timeout:.0f} seconds)",
                hint=(
                    "Port 8883 is probably blocked outbound. Check with `mi doctor`, "
                    "or test directly with `nc -vz " + broker_host(self.region) + " 8883`"
                ),
            )

    def stop(self) -> None:
        self._stopping = True
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def __enter__(self) -> "CloudMqtt":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
