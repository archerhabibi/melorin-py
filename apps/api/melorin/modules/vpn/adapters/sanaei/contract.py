"""Sanaei (3x-ui) contract: what a valid panel configuration and server target look like. Pure functions, no I/O."""

from __future__ import annotations

from typing import Any

TARGET_KEYS = {"inbound_ids"}


def _ids(value: Any) -> list[int] | None:
    from melorin.modules.vpn.targets import _ids as ids

    return ids(value)


def validate_settings(cred: dict, cfg: dict) -> None:
    # 3x-ui needs a subscription base (served on a separate Sub Port/Path) and a target inbound,
    # otherwise provisioning creates panel clients that can never be delivered.
    if cred and not (cred.get("api_token") or (cred.get("username") and cred.get("password"))):
        raise ValueError("sanaei: credentials need api_token or username+password")
    if not str(cfg.get("sub_base_url") or "").startswith(("http://", "https://")):
        raise ValueError("sanaei: config.sub_base_url is required, e.g. https://sub.example.com:2096/sub")
    if not (cfg.get("inbound_ids") or cfg.get("inbound_id") or cfg.get("template_username")):
        raise ValueError("sanaei: config.inbound_ids or config.template_username is required")
    if cfg.get("api_style", "auto") not in ("auto", "v3", "legacy"):
        raise ValueError("sanaei: config.api_style must be auto, v3 or legacy")


def validate_target(target: dict, *, api_style: str | None = None) -> list[str]:
    problems: list[str] = []
    unknown = set(target) - TARGET_KEYS
    if unknown:
        problems.append(f"کلید نامعتبر برای سنایی: {', '.join(sorted(unknown))}")
    ids = _ids(target.get("inbound_ids"))
    if ids is None:
        problems.append("inbound_ids باید فهرست غیرتهی از عددهای مثبت باشد.")
    elif api_style == "legacy" and len(ids) != 1:
        problems.append("سنایی نسخه‌ی قدیمی (legacy) فقط یک اینباند را پشتیبانی می‌کند.")
    return problems


def capacity_label(target: dict | None) -> str:
    return "ظرفیت اینباند"


def listing_warnings(target: dict, listing: dict) -> list[str]:
    out: list[str] = []
    inbounds = {i["id"]: i for i in listing.get("inbounds", [])}
    for iid in target.get("inbound_ids", []):
        if iid not in inbounds:
            out.append(f"اینباند {iid} روی پنل پیدا نشد.")
        elif not inbounds[iid].get("enabled", True):
            out.append(f"اینباند {iid} روی پنل غیرفعال است.")
    return out
