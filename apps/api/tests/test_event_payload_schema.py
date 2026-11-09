"""Audit T50: every ``emit()`` call in the code base matches the declared payload schema of its topic."""

import ast
import pathlib

from melorin.core import events

ROOT = pathlib.Path(__file__).resolve().parents[1] / "melorin"


def _emit_sites():
    for p in ROOT.rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not (isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == "emit" and len(n.args) >= 3):
                continue
            topic_node, payload = n.args[1], n.args[2]
            if isinstance(topic_node, ast.Attribute) and getattr(topic_node.value, "id", None) == "events":
                yield p.relative_to(ROOT), n.lineno, getattr(events, topic_node.attr), payload


def test_every_emit_site_matches_schema():
    sites = list(_emit_sites())
    assert len(sites) >= 25  # the audit counted 54 direct sites; T04 moved the user-notice ones behind emit_user_notice. Guards against the scan silently finding nothing
    bad = []
    for path, line, topic, payload in sites:
        if not isinstance(payload, ast.Dict):
            bad.append(f"{path}:{line} payload must be a dict literal so it can be checked")
            continue
        keys = {k.value for k in payload.keys if isinstance(k, ast.Constant)}
        problems = events.validate_payload(topic, dict.fromkeys(keys))
        if problems:
            bad.append(f"{path}:{line} {topic}: {problems}")
    assert not bad, "\n".join(bad)


def test_every_topic_constant_has_a_schema():
    topics = {v for k, v in vars(events).items() if k.isupper() and isinstance(v, str)}
    assert topics == set(events.PAYLOAD_SCHEMA)


def test_validate_payload():
    assert events.validate_payload(events.ORDER_PAID, {"order_id": "1"}) == []
    assert events.validate_payload(events.ORDER_PAID, {}) == ["missing:order_id"]
    assert events.validate_payload(events.ORDER_PAID, {"order_id": 1, "x": 1}) == ["unexpected:x"]
    assert events.validate_payload("nope", {}) == ["unknown_topic"]
    assert events.validate_payload(events.VPN_EXPIRED, {"anything": 1}) == []
