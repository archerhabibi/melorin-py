"""upstream_bot contract: validation of the Telethon credentials and the purchase-safety config. Pure functions, no I/O,
and no Telethon import (the adapter loads it lazily only when a call is made)."""

from __future__ import annotations

import math


def validate_settings(cred: dict, cfg: dict) -> None:
    # Like the other kinds: credentials are validated only when they are sent (an edit may keep the stored secret);
    # create_panel itself refuses a new upstream_bot panel without them.
    if cred and not (cred.get("api_id") and cred.get("api_hash") and cred.get("session")):
        raise ValueError("upstream_bot: credentials need api_id, api_hash and session (Telethon StringSession)")
    if cred:
        try:
            if int(cred["api_id"]) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("upstream_bot: credentials.api_id must be a positive number") from exc
    try:
        max_price = int(cfg.get("max_price") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("upstream_bot: config.max_price must be a number (toman)") from exc
    if max_price <= 0:
        raise ValueError("upstream_bot: config.max_price (toman, safety cap per purchase) is required")
    if "plans" in cfg:
        if not (isinstance(cfg["plans"], list) and all(isinstance(p, dict) for p in cfg["plans"])):
            raise ValueError("upstream_bot: config.plans must be a list of {traffic_gb, months, label}")
        for plan in cfg["plans"]:
            try:
                gb, months = float(plan["traffic_gb"]), int(plan.get("months", 1))
                if not (math.isfinite(gb) and gb > 0 and months >= 1):
                    raise ValueError
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("upstream_bot: each plan needs traffic_gb > 0 and an integer months >= 1") from exc
    if "renew" in cfg and not isinstance(cfg["renew"], dict):
        raise ValueError("upstream_bot: config.renew must be an object")
    for key in ("status_ttl", "step_timeout", "delivery_timeout", "poll_interval", "lock_ttl"):
        if key in cfg:
            try:
                if not (math.isfinite(float(cfg[key])) and float(cfg[key]) > 0):
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError(f"upstream_bot: config.{key} must be a positive number") from exc
