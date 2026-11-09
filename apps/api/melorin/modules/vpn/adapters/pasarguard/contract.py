"""PasarGuard contract: what a valid panel configuration and server target look like. Pure functions, no I/O."""

from __future__ import annotations

LIMITS_FROM = ("product", "template")
TARGET_KEYS = {"group_ids", "user_template_id", "limits_from"}


def _ids(value):
    from melorin.modules.vpn.targets import _ids as ids

    return ids(value)


def validate_settings(cred: dict, cfg: dict) -> None:
    if cred and not (cred.get("api_key") or cred.get("access_token") or (cred.get("username") and cred.get("password"))):
        raise ValueError("pasarguard: credentials need api_key, access_token or username+password")
    template_id = cfg.get("user_template_id")
    if template_id is None and not cfg.get("group_ids"):
        raise ValueError("pasarguard: config.group_ids or config.user_template_id is required")
    if template_id is not None:
        try:
            if int(template_id) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("pasarguard: config.user_template_id must be a positive integer") from exc


def validate_target(target: dict, *, api_style: str | None = None) -> list[str]:
    problems: list[str] = []
    unknown = set(target) - TARGET_KEYS
    if unknown:
        problems.append(f"کلید نامعتبر برای پاسارگارد: {', '.join(sorted(unknown))}")
    has_groups, has_template = "group_ids" in target, "user_template_id" in target
    if has_groups == has_template:
        problems.append("برای پاسارگارد دقیقاً یکی از گروه‌ها (group_ids) یا تمپلیت (user_template_id) لازم است.")
    if has_groups and _ids(target["group_ids"]) is None:
        problems.append("group_ids باید فهرست غیرتهی از عددهای مثبت باشد.")
    if has_template:
        try:
            ok = int(target["user_template_id"]) > 0 and not isinstance(target["user_template_id"], bool)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            problems.append("user_template_id باید عدد مثبت باشد.")
    if "limits_from" in target:
        if not has_template:
            problems.append("limits_from فقط با user_template_id معنی دارد.")
        if target["limits_from"] not in LIMITS_FROM:
            problems.append("limits_from باید product یا template باشد.")
    return problems


def capacity_label(target: dict | None) -> str:
    return "ظرفیت تمپلیت" if target and "user_template_id" in target else "ظرفیت گروه"


def listing_warnings(target: dict, listing: dict) -> list[str]:
    out: list[str] = []
    groups = {g["id"]: g for g in listing.get("groups", [])}
    for gid in target.get("group_ids", []):
        if gid not in groups:
            out.append(f"گروه {gid} روی پنل پیدا نشد.")
        elif groups[gid].get("disabled"):
            out.append(f"گروه {gid} روی پنل غیرفعال است.")
    if "user_template_id" in target:
        tpl = {t["id"]: t for t in listing.get("templates", [])}.get(int(target["user_template_id"]))
        if tpl is None:
            out.append(f"تمپلیت {target['user_template_id']} روی پنل پیدا نشد.")
        elif tpl.get("disabled"):
            out.append(f"تمپلیت {target['user_template_id']} روی پنل غیرفعال است.")
        elif target.get("limits_from") == "template":
            out.append("حجم و مدت از خود تمپلیت می‌آید و با بسته‌ی فروش یکی نیست؛ مطمئن شوید با کدهای محصول همین سرور می‌خواند.")
    return out
