"""Message parsing and client wiring of the cloud MQTT.

A real connection needs access to port 8883; the tests never touch the network and
verify the wiring with a fake client.
"""
import queue

import pytest

from mi_home_cli.core import const
from mi_home_cli.core.mqtt import (
    CloudMqtt,
    broker_host,
    parse_message,
    topic_events,
    topic_props,
    topic_state,
)


def test_broker_host_per_region():
    assert broker_host("cn") == "cn-ha.mqtt.io.mi.com"
    assert broker_host("sg") == "sg-ha.mqtt.io.mi.com"


def test_topic_builders():
    assert topic_props("d1") == "device/d1/up/properties_changed/#"
    assert topic_props("d1", 2, 1) == "device/d1/up/properties_changed/2/1"
    # The server really spells occurred as occured; it must not be "helpfully corrected"
    assert topic_events("d1") == "device/d1/up/event_occured/#"
    assert topic_state("d1") == "device/d1/state/#"


def test_parse_property_change():
    msg = parse_message(
        "device/d1/up/properties_changed/2/1",
        b'{"params":{"siid":2,"piid":1,"value":true}}',
    )
    assert (msg.kind, msg.did, msg.siid, msg.iid, msg.value) == (
        "prop", "d1", 2, 1, True,
    )


def test_parse_event():
    msg = parse_message(
        "device/d1/up/event_occured/5/1",
        b'{"params":{"siid":5,"eiid":1,"arguments":[{"piid":1,"value":3}]}}',
    )
    assert msg.kind == "event" and msg.iid == 1
    assert msg.arguments == [{"piid": 1, "value": 3}]


def test_parse_state_uses_payload_device_id():
    msg = parse_message(
        "device/d1/state/online",
        b'{"device_id":"d1","event":"online","model":"x"}',
    )
    assert (msg.kind, msg.did, msg.state) == ("state", "d1", "online")


@pytest.mark.parametrize(
    "topic,payload",
    [
        ("device/d1/up/properties_changed/#", b"not json"),
        ("device/d1/up/properties_changed/#", b'{"params":{}}'),  # siid missing
        ("device/d1/state/x", b'{"device_id":"d1"}'),  # event missing
        ("other/d1/whatever", b"{}"),
        ("device/d1/up/properties_changed/#", b'"just a string"'),
    ],
)
def test_parse_rejects_garbage(topic, payload):
    assert parse_message(topic, payload) is None


class FakeClient:
    """A good-enough stand-in for paho."""

    def __init__(self, *args, **kwargs):
        self.subscribed: list[str] = []
        self.credentials: list[tuple[str, str]] = []
        self.connected = False
        self.loop_running = False

    def tls_set(self, **kwargs):
        self.tls = kwargs

    def tls_set_context(self, context):
        self.tls_context = context

    def enable_logger(self, logger=None):
        self.logger_enabled = True

    def username_pw_set(self, username, password):
        self.credentials.append((username, password))

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def connect(self, host, port, keepalive):
        self.target = (host, port, keepalive)

    def loop_start(self):
        self.loop_running = True

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.connected = False


@pytest.fixture()
def fake(monkeypatch) -> CloudMqtt:
    import mi_home_cli.core.mqtt as module

    monkeypatch.setattr(module.mqtt, "Client", FakeClient)
    tokens = iter(["AT1", "AT2", "AT3"])
    return CloudMqtt(
        region="cn",
        client_id="ha.abc",
        token_provider=lambda: next(tokens),
    )


def test_connect_subscribes_all_topics(fake: CloudMqtt):
    fake.subscribe(["a", "b", "a"])  # duplicates are kept only once
    client = fake._client
    fake._handle_connect(client, None, None, reason_code=None)
    assert client.subscribed == ["a", "b"]


def test_reconnect_resubscribes(fake: CloudMqtt):
    """After a reconnect the subscriptions must be sent again, or nothing is received even though connected."""
    fake.subscribe(["a"])
    client = fake._client
    fake._handle_connect(client, None, None, reason_code=None)
    fake._handle_disconnect(client, None)
    fake._handle_connect(client, None, None, reason_code=None)
    assert client.subscribed == ["a", "a"]


def test_disconnect_refreshes_password(fake: CloudMqtt):
    """The access_token may be renewed during the long-lived connection; a reconnect must use the new one."""
    client = fake._client
    fake._handle_disconnect(client, None)
    assert client.credentials[-1] == (const.CLIENT_ID, "AT1")
    fake._handle_disconnect(client, None)
    assert client.credentials[-1] == (const.CLIENT_ID, "AT2")


def test_messages_land_in_queue(fake: CloudMqtt):
    class M:
        topic = "device/d1/up/properties_changed/2/1"
        payload = b'{"params":{"siid":2,"piid":1,"value":42}}'

    fake._handle_message(fake._client, None, M())
    assert fake.messages.get_nowait().value == 42

    class Bad:
        topic = "device/d1/up/properties_changed/2/1"
        payload = b"garbage"

    fake._handle_message(fake._client, None, Bad())
    with pytest.raises(queue.Empty):
        fake.messages.get_nowait()


def test_connect_failure_does_not_mark_connected(fake: CloudMqtt):
    class Failure:
        is_failure = True

    fake._handle_connect(fake._client, None, None, reason_code=Failure())
    assert not fake._connected.is_set()
    assert fake._client.subscribed == []


def test_uses_certifi_ca_bundle():
    """paho uses the system CA by default, and Python on macOS often finds no root certificates — on the same machine

    httpx works while MQTT cannot connect, and this is most likely why. Using certifi
    explicitly is more robust.
    """
    import certifi

    from mi_home_cli.core.mqtt import _ssl_context

    context = _ssl_context()
    assert context.get_ca_certs(), "the TLS context has not a single root certificate"
    assert certifi.where()  # make sure the dependency is installed


def test_tls_context_is_verifying():
    import ssl as _ssl

    from mi_home_cli.core.mqtt import _ssl_context

    context = _ssl_context()
    assert context.verify_mode == _ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_ca_bundle_env_overrides(monkeypatch, tmp_path):
    """Behind a man-in-the-middle proxy it must be possible to specify the proxy's own root certificate, or connecting fails."""
    import certifi

    from mi_home_cli.core.mqtt import CA_BUNDLE_ENV, _ssl_context

    bundle = tmp_path / "ca.pem"
    bundle.write_text(open(certifi.where(), encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setenv(CA_BUNDLE_ENV, str(bundle))
    assert _ssl_context().get_ca_certs()


def test_system_store_is_tried_first_then_certifi(monkeypatch):
    """System first, then certifi.

    "Is the system store empty" cannot decide whether to fall back to certifi: a store
    with certificates does not necessarily have the root this chain needs; in testing
    there was a machine whose system store was not empty yet could not verify Xiaomi's
    broker. So both go into the candidates and are tried in order.
    """
    import certifi

    from mi_home_cli.core import mqtt as module

    monkeypatch.delenv(module.CA_BUNDLE_ENV, raising=False)
    contexts = module.ssl_contexts()
    assert len(contexts) == 2
    # the second one is certifi's
    assert certifi.where()


def test_explicit_bundle_is_the_only_candidate(monkeypatch, tmp_path):
    """When the user specifies one explicitly, use only that and do not quietly fall back — that would make

    a problem like "the certificate I specified has no effect" impossible to troubleshoot.
    """
    import certifi

    from mi_home_cli.core import mqtt as module

    bundle = tmp_path / "ca.pem"
    bundle.write_text(open(certifi.where(), encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setenv(module.CA_BUNDLE_ENV, str(bundle))
    assert len(module.ssl_contexts()) == 1


def test_new_client_per_ca_attempt(monkeypatch):
    """Switching CA bundles requires a new client: paho's tls_set_context can only be called once;

    the second call raises ValueError('SSL/TLS has already been configured.'), so
    retrying on the same client is pointless.
    """
    import ssl as _ssl

    from mi_home_cli.core.mqtt import CloudMqtt

    built: list[FakeClient] = []

    class Tracking(FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.tls_calls = 0
            built.append(self)

        def tls_set_context(self, context):
            self.tls_calls += 1
            if self.tls_calls > 1:
                raise ValueError("SSL/TLS has already been configured.")

        def connect(self, host, port, keepalive):
            # the first client (system CA) fails verification, the second (certifi)
            # succeeds
            if len(built) == 1:
                raise _ssl.SSLCertVerificationError("certificate verify failed")
            self.on_connect(self, None, None, None)

    import mi_home_cli.core.mqtt as module

    monkeypatch.setattr(module.mqtt, "Client", Tracking)
    notes: list[str] = []
    client = CloudMqtt(
        region="cn",
        client_id="ha.abc",
        token_provider=lambda: "AT",
        on_note=notes.append,
    )
    client.subscribe(["device/d1/state/#"])
    client.start(timeout=2)
    assert len(built) == 2, "the second attempt did not create a new client"
    assert all(item.tls_calls == 1 for item in built)
    assert "certifi" in notes[0]
    # the new client must get the subscriptions as well
    assert built[1].subscribed == ["device/d1/state/#"]


def test_stop_does_not_report_reconnecting(fake: CloudMqtt):
    """A deliberate Ctrl-C stop triggers on_disconnect too and must not announce "reconnecting"."""
    states: list[bool] = []
    fake._on_state_change = states.append
    client = fake._client
    fake._handle_connect(client, None, None, reason_code=None)
    assert states == [True]

    fake.stop()
    fake._handle_disconnect(client, None)
    assert states == [True]  # no extra False was added

    # a real drop must still be reported
    fake._stopping = False
    fake._handle_disconnect(client, None)
    assert states == [True, False]
