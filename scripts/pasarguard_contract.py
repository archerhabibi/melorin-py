#!/usr/bin/env python3
"""PasarGuard API contract fixture: build it from a panel's OpenAPI, and diff a newer panel against it.

Why: Melorin talks to PasarGuard over a hand-written adapter. When the panel is upgraded, a renamed field or a removed route
must be noticed by CI/ops, not by a customer. The full OpenAPI of a panel is ~800 KB; this script keeps only what the contract
tests need (stdlib only, no network):

* every operation: ``"METHOD /path"`` -> query parameter names, request-body schema, 2xx response schema;
* the *tracked* schemas (users, admins, nodes, ...) -> property names, required names;
* every enum schema (user status, node status, ...) -> its values.

Get a panel's OpenAPI without enabling its public docs (run inside the panel container)::

    docker exec -w /code <panel-container> python export_openapi.py /tmp/openapi.json
    docker cp <panel-container>:/tmp/openapi.json ./openapi.json

Usage::

    python scripts/pasarguard_contract.py slim openapi.json --panel-version 5.6.0 \
        --out apps/api/tests/fixtures/pasarguard-openapi-5.6.0.contract.json
    python scripts/pasarguard_contract.py diff openapi.json \
        --fixture apps/api/tests/fixtures/pasarguard-openapi-5.6.0.contract.json   # exit 1 when a USED route/field changed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Schemas the adapter reads or writes today, plus the ones the Phase 1+ roadmap (docs/PASARGUARD-MANAGEMENT) will need.
TRACKED_SCHEMAS = (
    "UserResponse", "UserCreate", "UserModify", "UserTemplateResponse", "NextPlanModel",
    "AdminDetails", "AdminCreate", "AdminModify", "RoleResponse",
    "GroupResponse", "NodeResponse", "SystemStats", "SystemUsersStats", "SettingsSchema", "NotificationSettings",
    "HWIDSettings", "CleanupSettings", "NodeHealthSettings",
)  # fmt: skip

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head")


def _first_ref(node) -> str | None:
    """Name of the first ``$ref`` found anywhere in ``node`` (handles anyOf/allOf/array items); ``[Name]`` for arrays."""
    if isinstance(node, dict):
        if "$ref" in node:
            return node["$ref"].rsplit("/", 1)[-1]
        if node.get("type") == "array" and "items" in node:
            inner = _first_ref(node["items"])
            return f"[{inner}]" if inner else "[]"
        for key in ("anyOf", "allOf", "oneOf"):
            for part in node.get(key, []):
                ref = _first_ref(part)
                if ref:
                    return ref
    return None


def _body(op: dict) -> str | None:
    content = (op.get("requestBody") or {}).get("content") or {}
    if "application/json" in content:
        return _first_ref(content["application/json"].get("schema")) or "json"
    if content:
        return "form"
    return None


def _ok(op: dict) -> str | None:
    for code, resp in (op.get("responses") or {}).items():
        if str(code).startswith("2"):
            content = (resp or {}).get("content") or {}
            if "application/json" in content:
                return _first_ref(content["application/json"].get("schema")) or "json"
            return None
    return None


def slim(openapi: dict, panel_version: str) -> dict:
    operations: dict[str, dict] = {}
    for path, item in sorted(openapi["paths"].items()):
        for method in HTTP_METHODS:
            op = item.get(method)
            if op is None:
                continue
            query = sorted(p["name"] for p in op.get("parameters", []) if p.get("in") == "query")
            operations[f"{method.upper()} {path}"] = {"query": query, "body": _body(op), "ok": _ok(op)}
    components = (openapi.get("components") or {}).get("schemas") or {}
    schemas = {}
    for name in TRACKED_SCHEMAS:
        spec = components.get(name)
        if spec is not None:
            schemas[name] = {"props": sorted(spec.get("properties", {})), "required": sorted(spec.get("required", []))}
    enums = {name: spec["enum"] for name, spec in sorted(components.items()) if isinstance(spec.get("enum"), list)}
    return {"panel_version": panel_version, "operations": operations, "schemas": schemas, "enums": enums}


def dump(fixture: dict) -> str:
    """Stable, diff-friendly text: one operation / schema / enum per line."""
    lines = ["{", f'  "panel_version": {json.dumps(fixture["panel_version"])},']
    for section in ("operations", "schemas", "enums"):
        lines.append(f'  "{section}": {{')
        items = list(fixture[section].items())
        for i, (key, value) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            lines.append(f"    {json.dumps(key)}: {json.dumps(value, sort_keys=True, ensure_ascii=False)}{comma}")
        lines.append("  }" + ("," if section != "enums" else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def diff(old: dict, new: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in ("removed_operations", "added_operations", "changed_operations", "schema_changes", "enum_changes")}
    old_ops, new_ops = old["operations"], new["operations"]
    out["removed_operations"] = sorted(set(old_ops) - set(new_ops))
    out["added_operations"] = sorted(set(new_ops) - set(old_ops))
    for key in sorted(set(old_ops) & set(new_ops)):
        if old_ops[key] != new_ops[key]:
            out["changed_operations"].append(f"{key}: {old_ops[key]} -> {new_ops[key]}")
    for name in sorted(set(old["schemas"]) | set(new["schemas"])):
        a, b = old["schemas"].get(name), new["schemas"].get(name)
        if a == b:
            continue
        if a is None or b is None:
            out["schema_changes"].append(f"{name}: {'added' if a is None else 'removed'}")
            continue
        gone, came = sorted(set(a["props"]) - set(b["props"])), sorted(set(b["props"]) - set(a["props"]))
        req = sorted(set(b["required"]) - set(a["required"]))
        out["schema_changes"].append(f"{name}: removed={gone} added={came} newly_required={req}")
    for name in sorted(set(old["enums"]) | set(new["enums"])):
        if old["enums"].get(name) != new["enums"].get(name):
            out["enum_changes"].append(f"{name}: {old['enums'].get(name)} -> {new['enums'].get(name)}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("slim", help="build the committed contract fixture from a full OpenAPI json")
    s.add_argument("openapi")
    s.add_argument("--panel-version", required=True)
    s.add_argument("--out", required=True)
    d = sub.add_parser("diff", help="compare a (newer) OpenAPI json with the committed fixture")
    d.add_argument("openapi")
    d.add_argument("--fixture", required=True)
    d.add_argument("--panel-version", default="new")
    args = parser.parse_args(argv)

    openapi = json.loads(Path(args.openapi).read_text(encoding="utf-8"))
    if args.cmd == "slim":
        fixture = slim(openapi, args.panel_version)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(dump(fixture), encoding="utf-8")
        print(f"wrote {args.out}: {len(fixture['operations'])} operations, {len(fixture['schemas'])} schemas, {len(fixture['enums'])} enums")
        return 0

    old = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    changes = diff(old, slim(openapi, args.panel_version))
    for title, rows in changes.items():
        if rows:
            print(f"## {title} ({len(rows)})")
            print("\n".join(f"  - {r}" for r in rows))
    # Added routes are information; anything else may break the adapter -> the contract tests tell which one.
    breaking = any(changes[k] for k in ("removed_operations", "changed_operations", "schema_changes", "enum_changes"))
    print("RESULT:", "CHANGED (run the contract tests)" if breaking else "compatible")
    return 1 if breaking else 0


if __name__ == "__main__":
    sys.exit(main())
