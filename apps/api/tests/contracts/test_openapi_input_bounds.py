"""Contract guard: every integer a client can send is bounded on both sides (see ``melorin.core.limits``).

An unbounded integer reaches a PostgreSQL INTEGER/BIGINT bind (``asyncpg: value out of int64 range``) or later arithmetic
(``timedelta``, GB -> bytes) and used to surface as an HTTP 500 with a traceback in the log (audit finding BE-001).
"""

from __future__ import annotations

from melorin.app import app

# Violations owned by a later audit team (audit/OWNERSHIP-MATRIX.md). Each owner deletes its entries in its own PR; the second
# test fails when an entry is no longer violated, so this list can only shrink.
PENDING: set[str] = {
    # AI-03 (payments/schemas.py, money rules): amounts use ``limits.MAX_MONEY``, minutes/hours use ``MAX_DAYS``-style caps.
    "BankSmsSettingsIn.max_auto_amount_rial",
    "BankSmsSettingsIn.time_tolerance_minutes",
    "BankSmsSettingsIn.window_minutes",
    "GraceSettingsIn.max_amount_rial",
    "GraceSettingsIn.max_exposure_rial",
    "GraceSettingsIn.max_open_per_origin",
    "GraceSettingsIn.max_open_per_user",
    "GraceSettingsIn.min_account_age_hours",
    "GraceSettingsIn.minutes",
    "TopupRequest.amount",
}

_METHODS = {"get", "post", "put", "patch", "delete"}


def _refs(node):
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"].rsplit("/", 1)[-1]
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _int_nodes(node):
    """Every integer schema inside ``node`` (``$ref`` is not followed: components are checked on their own)."""
    if isinstance(node, list):
        for item in node:
            yield from _int_nodes(item)
    elif isinstance(node, dict) and "$ref" not in node:
        if node.get("type") == "integer" and "enum" not in node and "const" not in node:
            yield node
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            yield from _int_nodes(node.get(key, []))
        for key in ("items", "additionalProperties"):
            yield from _int_nodes(node.get(key))


def _bounded(node: dict) -> bool:
    return ("minimum" in node or "exclusiveMinimum" in node) and ("maximum" in node or "exclusiveMaximum" in node)


def _violations() -> set[str]:
    spec = app.openapi()
    comps = spec.get("components", {}).get("schemas", {})
    found: set[str] = set()
    todo: list[str] = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in _METHODS:
                continue
            for prm in op.get("parameters", []):
                if any(not _bounded(n) for n in _int_nodes(prm.get("schema", {}))):
                    found.add(f"{method.upper()} {path} ?{prm['name']}")
            for content in op.get("requestBody", {}).get("content", {}).values():
                todo.extend(_refs(content.get("schema", {})))
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen or name not in comps:
            continue
        seen.add(name)
        todo.extend(_refs(comps[name]))
        for prop, schema in (comps[name].get("properties") or {}).items():
            if any(not _bounded(n) for n in _int_nodes(schema)):
                found.add(f"{name}.{prop}")
    return found


def test_every_request_integer_is_bounded() -> None:
    unbounded = sorted(_violations() - PENDING)
    assert not unbounded, "request integers without a minimum and a maximum (use melorin.core.limits): " + ", ".join(unbounded)


def test_pending_list_only_shrinks() -> None:
    stale = sorted(PENDING - _violations())
    assert not stale, "no longer violated, delete from PENDING: " + ", ".join(stale)
