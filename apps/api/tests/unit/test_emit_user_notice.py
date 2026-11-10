"""T04: emit_user_notice builds the exact notification.send payload the worker expects, with either dedup flavour."""

import uuid

from melorin.core import events


async def test_payload_shape_and_dedup_flavours(monkeypatch):
    calls = []

    async def fake_emit(session, topic, payload, *, dedup_key=None, delay_seconds=0):
        calls.append((topic, payload, dedup_key, delay_seconds))

    monkeypatch.setattr(events, "emit", fake_emit)
    u, st = uuid.uuid4(), uuid.uuid4()

    await events.emit_user_notice(None, u, st, "loyalty", "T", "B", payload_dedup_key="row-key")
    await events.emit_user_notice(None, u, None, "loyalty", "T", "B", dedup_key="outbox-key", delay_seconds=3)

    topic, payload, dedup, delay = calls[0]
    assert topic == events.NOTIFY and dedup is None and delay == 0
    assert payload == {"user_id": u, "store_id": st, "kind": "loyalty", "title": "T", "body": "B", "dedup_key": "row-key"}
    _, payload2, dedup2, delay2 = calls[1]
    assert "dedup_key" not in payload2 and dedup2 == "outbox-key" and delay2 == 3
