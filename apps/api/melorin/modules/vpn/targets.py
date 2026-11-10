"""Destination (target) rules: what a server slot may send new accounts to, and how it is merged over the panel config.

A *target* lives on ``Server.target`` (UI word: مقصد). NULL/{} means "inherit ``panel.config``" (the pre-target behaviour).
Pure functions only: no database, no network, so every rule is unit-tested.

    pasarguard   {"group_ids": [2, 3]}                              one of the two keys, never both
                 {"user_template_id": 5}
                 {"user_template_id": 5, "limits_from": "template"}  default "product": the package volume/time are applied after creation
    sanaei       {"inbound_ids": [4, 5]}                            v3: one client on all of them; legacy: exactly one
"""

from __future__ import annotations

from typing import Any

LIMITS_FROM = ("product", "template")  # kept for importers; the owner is adapters/pasarguard/contract.py
# Keys that decide the connection destination; a target replaces ALL of them in the panel config, never just one.
_DESTINATION_KEYS = ("group_ids", "user_template_id", "limits_from", "inbound_ids", "inbound_id")


def _ids(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not value:
        return None
    out: list[int] = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int | str):
            return None
        try:
            n = int(v)
        except ValueError:
            return None
        if n <= 0:
            return None
        out.append(n)
    return list(dict.fromkeys(out))


def normalize_target(target: dict | None) -> dict | None:
    """Canonical stored form (ints, no duplicates). Empty means inherit: returned as None."""
    if not target:
        return None
    out: dict = {}
    for key, value in target.items():
        if key in ("group_ids", "inbound_ids"):
            ids = _ids(value)
            out[key] = ids if ids is not None else value
        elif key == "user_template_id":
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                out[key] = value
        else:
            out[key] = value
    return out


def validate_target(panel_kind: str, target: dict | None, *, api_style: str | None = None) -> list[str]:
    """Human-readable problems with ``target`` for a panel of ``panel_kind``. An empty list means valid (None is always valid).
    The family-specific rules live in the provider's contract (adapters/<kind>/contract.py)."""
    if not target:
        return []
    if not isinstance(target, dict):
        return ["مقصد باید یک شیء باشد."]
    from melorin.modules.vpn.adapters import providers

    return providers.validate_target(panel_kind, target, api_style=api_style)


def merge_config(panel_config: dict | None, target: dict | None) -> dict:
    """Panel config with the server target laid over it. The target replaces every destination key, so a panel that
    defaults to a template never overrides a target that names groups (and vice versa)."""
    cfg = dict(panel_config or {})
    if not target:
        return cfg
    for key in _DESTINATION_KEYS:
        cfg.pop(key, None)
    cfg.update(target)
    return cfg


def effective_destination(panel_kind: str, panel_config: dict | None, target: dict | None) -> dict:
    """The destination keys that will actually be used (for display and the placement snapshot). Never any other config."""
    cfg = merge_config(panel_config, target)
    return {k: cfg[k] for k in _DESTINATION_KEYS if k in cfg and not (k == "inbound_id" and "inbound_ids" in cfg)}


def capacity_label(panel_kind: str, target: dict | None) -> str:
    """The one place that names a server's capacity in the admin UI (D7): گروه / تمپلیت / اینباند / مقصد."""
    from melorin.modules.vpn.adapters import providers

    return providers.capacity_label(panel_kind, target)
