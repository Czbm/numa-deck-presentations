"""Transport-independent tests; no radio or Windows settings are changed."""

import asyncio
import json
import unittest

from direct_connections import DirectConnections, JsonLineBuffer
from mobile_link import MobileLinkServer


class FakeChannel:
    path = ""
    remote_address = "bluetooth:test"

    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def close(self, **kwargs):
        self.closed = True


def envelope(kind, sequence, payload):
    return json.dumps(dict(version=1, type=kind, sequence=sequence, timestamp=1, payload=payload))


class DirectConnectionsTests(unittest.TestCase):
    def test_framing_utf8_and_multiple_messages(self):
        buffer = JsonLineBuffer()
        raw = '{"name":"tel\u00e9fono"}\n{"type":"action"}\n'.encode("utf-8")
        result = []
        for byte in raw:
            result.extend(buffer.feed(bytes([byte])))
        self.assertEqual(len(result), 2)
        self.assertEqual(json.loads(result[0])["name"], "tel\u00e9fono")
        self.assertFalse(buffer.pending)

    def test_framing_rejects_oversized_and_invalid_utf8(self):
        with self.assertRaises(ValueError):
            JsonLineBuffer(4).feed(b"12345")
        with self.assertRaises(ValueError):
            JsonLineBuffer(4).feed(b"12345\n")
        with self.assertRaises(UnicodeDecodeError):
            JsonLineBuffer().feed(b"\xff\n")

    def test_pairing_requires_ready_transport(self):
        manager = DirectConnections(MobileLinkServer(auth_token="secret"))
        self.assertEqual(manager.snapshot("bluetooth")[0], "off")
        with self.assertRaises(RuntimeError):
            manager.pairing_payload("bluetooth")
        manager._publish("bluetooth", "ready", {"service_uuid": "test"})
        self.assertEqual(json.loads(manager.pairing_payload("bluetooth"))["token"], "secret")
        manager.stop_all()

    def test_wifi_requires_live_application_receiver(self):
        manager = DirectConnections(MobileLinkServer(auth_token="secret"))
        self.assertFalse(manager.start("wifi_direct"))
        self.assertEqual(manager.snapshot("wifi_direct")[0], "error")
        self.assertFalse(manager.workers)

    def test_protocol_accepts_authenticated_bluetooth_actions(self):
        receiver = MobileLinkServer(auth_token="secret")
        channel = FakeChannel([
            envelope("hello", 0, dict(token="secret", protocol_version=1, client_name="Android")),
            envelope("action", 1, dict(action="next")),
            envelope("action", 1, dict(action="next")),
        ])
        asyncio.run(receiver._handle_client(channel))
        self.assertEqual(channel.sent[0]["type"], "hello_ack")
        stats = receiver.diagnostics_snapshot()
        self.assertEqual(stats["accepted_messages"], 2)
        self.assertEqual(stats["duplicate_sequences"], 1)
        self.assertEqual(stats["client_count"], 0)

    def test_protocol_rejects_wrong_token_and_missing_hello(self):
        for messages in ([envelope("hello", 0, dict(token="wrong", protocol_version=1, client_name="Android"))],
                         [envelope("action", 0, dict(action="next"))]):
            receiver = MobileLinkServer(auth_token="secret")
            channel = FakeChannel(messages)
            asyncio.run(receiver._handle_client(channel))
            self.assertTrue(channel.closed)
            self.assertEqual(receiver.diagnostics_snapshot()["accepted_messages"], 0)


if __name__ == "__main__":
    unittest.main()
