"""Telegram button styling (Bot API 9.4): colour, Premium custom emoji and text decoration.

Pure logic, no I/O: validation of the admin-edited configuration, the catalogue of the bots' real buttons, ready-made
presets and the compact projection the bots download. The bots are separate apps and carry a tiny matcher with exactly
the semantics of :func:`resolve` below (an exact rule beats a prefix rule, a longer prefix beats a shorter one).

What Telegram supports (https://core.telegram.org/bots/api, ``InlineKeyboardButton`` / ``KeyboardButton``):

* ``style`` - ``primary`` (blue), ``success`` (green) or ``danger`` (red); omitted = the app's own look;
* ``icon_custom_emoji_id`` - a custom (Premium) emoji shown before the text; it only renders when the bot owner has
  Telegram Premium (or the bot bought extra usernames on Fragment), otherwise Telegram ignores or refuses it.

Decoration (a short prefix/suffix) is plain text and is applied to *inline* buttons only: a reply-keyboard button
sends its own text back to the bot, and the bot recognises the menu by that exact text, so it must never change.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

STYLES: tuple[str, ...] = ("primary", "success", "danger")
STYLE_LABEL = {"primary": "آبی", "success": "سبز", "danger": "قرمز"}
KINDS: tuple[str, ...] = ("inline", "reply")
MATCHES: tuple[str, ...] = ("exact", "prefix")

URL_KEY = "@url"  # pseudo key: every URL button of the inline keyboards (they have no callback_data)
EMOJI_ID_RE = re.compile(r"^[0-9]{5,25}$")
MAX_RULES = 120
MAX_KEY = 64
MAX_REPLY_TEXT = 100
MAX_NOTE = 60
MAX_DECOR = 6
MAX_BUTTON_TEXT = 64  # longer labels are shown truncated by the apps; a decoration never pushes a label past this

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class ButtonStyleError(ValueError):
    """The submitted configuration is invalid; the message is Persian and shown to the admin as is."""


# ---------------------------------------------------------------------------------------------------------------------
# Catalogue of the bots' real buttons (what the admin can style without typing raw callback strings)
# ---------------------------------------------------------------------------------------------------------------------

def _inline(key: str, label: str, group: str, match: str = "exact") -> dict[str, Any]:
    return {"kind": "inline", "key": key, "match": match, "label": label, "group": group}


def _reply(text: str, group: str = "منوی اصلی (کیبورد پایین)") -> dict[str, Any]:
    return {"kind": "reply", "key": text, "match": "exact", "label": text, "group": group}


CATALOG: tuple[dict[str, Any], ...] = (
    _inline("menu:home", "🏠 خانه / بازگشت به منو", "ناوبری"),
    _inline("menu:plans", "🛒 خرید اکانت", "ناوبری"),
    _inline("menu:wallet", "💰 کیف پول", "ناوبری"),
    _inline("menu:orders", "📦 سفارش‌ها", "ناوبری"),
    _inline("menu:accounts", "🔑 اکانت‌ها", "ناوبری"),
    _inline("menu:tickets", "🎫 تیکت‌ها", "ناوبری"),
    _inline("menu:notifications", "🔔 اعلان‌ها", "ناوبری"),
    _inline("menu:club", "🏅 باشگاه مشتریان", "ناوبری"),
    _inline("menu:test", "🧪 دریافت اکانت تست", "ناوبری"),
    _inline("menu:devices", "🔐 مرورگرهای مطمئن", "ناوبری"),
    _inline("menu:", "همهٔ دکمه‌های منو (menu:*)", "ناوبری", "prefix"),
    _inline("plan:", "انتخاب پلن", "خرید و پرداخت", "prefix"),
    _inline("buy:", "✅ خرید / پرداخت", "خرید و پرداخت", "prefix"),
    _inline("qt:", "استعلام قیمت", "خرید و پرداخت", "prefix"),
    _inline("cpn:", "🎟 کد تخفیف", "خرید و پرداخت", "prefix"),
    _inline("wallet:", "مبلغ شارژ کیف پول", "خرید و پرداخت", "prefix"),
    _inline("rnw:", "🔄 تمدید اکانت", "تمدید", "prefix"),
    _inline("rnq:", "استعلام تمدید", "تمدید", "prefix"),
    _inline("rnb:", "✅ تأیید و تمدید", "تمدید", "prefix"),
    _inline("account:", "جزئیات اکانت", "اکانت", "prefix"),
    _inline("acl:", "لیست اکانت‌ها / صفحه‌بندی", "اکانت", "prefix"),
    _inline("qr:", "QR و لینک اشتراک", "اکانت", "prefix"),
    _inline("an:", "🔄 نام خودکار", "اکانت", "prefix"),
    _inline("atl:", "ابزارهای اکانت", "اکانت", "prefix"),
    _inline("ticket:", "📂 مشاهدهٔ تیکت", "تیکت", "prefix"),
    _inline("tnew:", "➕ تیکت جدید", "تیکت", "prefix"),
    _inline("reply:", "✍️ پاسخ", "تیکت", "prefix"),
    _inline("tclose:", "🔒 بستن تیکت", "تیکت", "prefix"),
    _inline("treopen:", "🔓 بازگشایی تیکت", "تیکت", "prefix"),
    _inline("rsc:", "❌ لغو درخواست نمایندگی", "هشدار و انصراف", "prefix"),
    _inline("wla:", "✅ تأیید ورود به سایت", "هشدار و انصراف", "prefix"),
    _inline("wld:", "⛔ این من نبودم", "هشدار و انصراف", "prefix"),
    _inline("wdr:", "⛔ حذف مرورگر مطمئن", "هشدار و انصراف", "prefix"),
    _inline("rtn:", "↩️ مرجوعی اکانت", "هشدار و انصراف", "prefix"),
    _inline("rtc:", "✅ بله، مرجوع کن", "هشدار و انصراف", "prefix"),
    _inline("loy:", "🎁 پاداش باشگاه مشتریان", "باشگاه و دعوت", "prefix"),
    _inline("mg:", "منوی مدیریت نماینده", "ربات نماینده", "prefix"),
    _inline("rv:", "تأیید / رد پرداخت (نماینده)", "ربات نماینده", "prefix"),
    _inline("osp:", "⏸ تعلیق اکانت (نماینده)", "ربات نماینده", "prefix"),
    _inline("ors:", "▶️ فعال‌سازی مجدد (نماینده)", "ربات نماینده", "prefix"),
    _inline(URL_KEY, "همهٔ دکمه‌های لینک (مثلاً «حساب من در سایت»)", "لینک‌ها"),
    _reply("🛒 خرید اکانت"),
    _reply("🔍 استعلام و تمدید اکانت"),
    _reply("💰 کیف پول و شارژ حساب"),
    _reply("🌐 حساب من در سایت"),
    _reply("🎁 دعوت از دوستان"),
    _reply("🧪 دریافت اکانت تست"),
    _reply("📜 قوانین خرید و آموزش"),
    _reply("🎧 پشتیبانی"),
    _reply("🤖 درخواست ربات نماینده و همکاری"),
)


# ---------------------------------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------------------------------

def default_config() -> dict[str, Any]:
    return {"enabled": False, "rules": []}


def _decor(value: Any, field: str, where: str) -> str:
    text = "" if value is None else str(value)
    if len(text) > MAX_DECOR:
        raise ButtonStyleError(f"{where}: «{field}» حداکثر {MAX_DECOR} نویسه است.")
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        raise ButtonStyleError(f"{where}: «{field}» نباید خط جدید یا نویسهٔ کنترلی داشته باشد.")
    return text


def _style(value: Any, where: str) -> str | None:
    text = "" if value is None else str(value).strip().lower()
    if text in ("", "default", "none"):
        return None
    if text not in STYLES:
        raise ButtonStyleError(f"{where}: رنگ باید یکی از آبی، سبز یا قرمز باشد.")
    return text


def _icon(value: Any, where: str) -> str | None:
    text = ("" if value is None else str(value)).translate(_DIGITS).strip()
    if not text:
        return None
    if not EMOJI_ID_RE.match(text):
        raise ButtonStyleError(f"{where}: شناسهٔ ایموجی پریمیوم باید فقط عدد باشد (۵ تا ۲۵ رقم).")
    return text


def normalize_rule(raw: Any, index: int) -> dict[str, Any]:
    where = f"قانون {index + 1}"
    if not isinstance(raw, dict):
        raise ButtonStyleError(f"{where}: ساختار نامعتبر است.")
    kind = str(raw.get("kind") or "inline")
    if kind not in KINDS:
        raise ButtonStyleError(f"{where}: نوع دکمه نامعتبر است.")
    match = "exact" if kind == "reply" else str(raw.get("match") or "exact")
    if match not in MATCHES:
        raise ButtonStyleError(f"{where}: نوع تطبیق باید دقیق یا پیشوندی باشد.")
    key = str(raw.get("key") or "").strip()
    limit = MAX_REPLY_TEXT if kind == "reply" else MAX_KEY
    if not key or len(key) > limit:
        raise ButtonStyleError(f"{where}: کلید دکمه خالی است یا از {limit} نویسه بیشتر است.")
    if kind == "inline" and (key.startswith(("http://", "https://")) or any(unicodedata.category(c) == "Cc" for c in key)):
        raise ButtonStyleError(f"{where}: کلید باید callback دکمه باشد، نه لینک. برای دکمه‌های لینک از «{URL_KEY}» استفاده کنید.")
    if key == URL_KEY and match == "prefix":
        raise ButtonStyleError(f"{where}: «{URL_KEY}» فقط تطبیق دقیق دارد.")
    rule = {
        "kind": kind,
        "match": match,
        "key": key,
        "note": str(raw.get("note") or "").strip()[:MAX_NOTE],
        "style": _style(raw.get("style"), where),
        "icon": _icon(raw.get("icon"), where),
        "prefix": _decor(raw.get("prefix"), "پیشوند", where) if kind == "inline" else "",
        "suffix": _decor(raw.get("suffix"), "پسوند", where) if kind == "inline" else "",
        "enabled": bool(raw.get("enabled", True)),
    }
    if not (rule["style"] or rule["icon"] or rule["prefix"] or rule["suffix"]):
        raise ButtonStyleError(f"{where}: حداقل یکی از رنگ، ایموجی پریمیوم یا تزئین را مشخص کنید.")
    return rule


def normalize(raw: Any) -> dict[str, Any]:
    """Validate an admin submission and return the canonical config (raises :class:`ButtonStyleError`)."""
    if not isinstance(raw, dict):
        raise ButtonStyleError("ساختار تنظیمات نامعتبر است.")
    rules_raw = raw.get("rules") or []
    if not isinstance(rules_raw, list):
        raise ButtonStyleError("فهرست قانون‌ها باید آرایه باشد.")
    if len(rules_raw) > MAX_RULES:
        raise ButtonStyleError(f"حداکثر {MAX_RULES} قانون مجاز است.")
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for i, item in enumerate(rules_raw):
        rule = normalize_rule(item, i)
        ident = (rule["kind"], rule["match"], rule["key"])
        if ident in seen:
            raise ButtonStyleError(f"قانون {i + 1}: برای این دکمه قانون تکراری وجود دارد.")
        seen.add(ident)
        rules.append(rule)
    return {"enabled": bool(raw.get("enabled", False)), "rules": rules}


def stored(value: Any) -> dict[str, Any]:
    """The saved config, tolerant of a missing/old/corrupt value (a bad row must never break the bots)."""
    if not isinstance(value, dict):
        return default_config()
    try:
        return normalize(value)
    except ButtonStyleError:
        return default_config()


# ---------------------------------------------------------------------------------------------------------------------
# Projection for the bots and the matcher (kept identical to the one in apps/telegram-main/tgmain/ui.py)
# ---------------------------------------------------------------------------------------------------------------------

def _order(rule: dict[str, Any]) -> tuple[int, int]:
    return (0 if rule["match"] == "exact" else 1, -len(rule["key"]))


def public_projection(cfg: dict[str, Any]) -> dict[str, Any]:
    """What ``GET /telegram/button-styles`` returns: nothing when switched off, else the active rules, most specific first."""
    if not cfg.get("enabled"):
        return {"enabled": False, "inline": [], "reply": []}
    active = [r for r in cfg.get("rules", []) if r.get("enabled", True)]

    def view(r: dict[str, Any]) -> dict[str, Any]:
        out = {"key": r["key"], "match": r["match"]}
        for field in ("style", "icon", "prefix", "suffix"):
            if r.get(field):
                out[field] = r[field]
        return out

    return {
        "enabled": True,
        "inline": [view(r) for r in sorted((r for r in active if r["kind"] == "inline"), key=_order)],
        "reply": [view(r) for r in active if r["kind"] == "reply"],
    }


def resolve(rules: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    """First matching rule of a list already ordered by specificity (exact before prefix, longer prefix first)."""
    for r in rules:
        if r["match"] == "exact" and r["key"] == key:
            return r
        if r["match"] == "prefix" and key.startswith(r["key"]):
            return r
    return None


def _decorated(text: str, rule: dict[str, Any]) -> str:
    out = f"{rule.get('prefix', '')}{text}{rule.get('suffix', '')}"
    return out if len(out) <= MAX_BUTTON_TEXT else text


def apply_inline(projection: dict[str, Any], key: str, text: str) -> dict[str, Any]:
    """The fields one inline button gets: ``text`` (possibly decorated) plus ``style`` / ``icon_custom_emoji_id`` when set."""
    rule = resolve(projection.get("inline", []), key) if projection.get("enabled") else None
    if not rule:
        return {"text": text}
    out: dict[str, Any] = {"text": _decorated(text, rule)}
    if rule.get("style"):
        out["style"] = rule["style"]
    if rule.get("icon"):
        out["icon_custom_emoji_id"] = rule["icon"]
    return out


def apply_reply(projection: dict[str, Any], text: str) -> dict[str, Any]:
    """Reply-keyboard button: the text is never touched (the bot recognises the menu by it), only colour and icon."""
    rule = resolve(projection.get("reply", []), text) if projection.get("enabled") else None
    out: dict[str, Any] = {"text": text}
    if rule and rule.get("style"):
        out["style"] = rule["style"]
    if rule and rule.get("icon"):
        out["icon_custom_emoji_id"] = rule["icon"]
    return out


def strip_styling(markup: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy of a reply markup without ``style`` / ``icon_custom_emoji_id`` (the safe retry when Telegram refuses them)."""
    if not markup:
        return markup
    out = dict(markup)
    for rows_key in ("inline_keyboard", "keyboard"):
        if rows_key in out:
            out[rows_key] = [
                [{k: v for k, v in b.items() if k not in ("style", "icon_custom_emoji_id")} for b in row] for row in out[rows_key]
            ]
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Presets and the sample keyboard of the preview
# ---------------------------------------------------------------------------------------------------------------------

def _r(key: str, *, style: str | None = None, match: str = "exact", prefix: str = "", suffix: str = "", kind: str = "inline") -> dict[str, Any]:
    return {"kind": kind, "match": match, "key": key, "style": style, "prefix": prefix, "suffix": suffix, "icon": None, "enabled": True}


_CLASSIC = [
    _r("buy:", style="success", match="prefix"),
    _r("rnb:", style="success", match="prefix"),
    _r("wla:", style="success", match="prefix"),
    _r("rtc:", style="danger", match="prefix"),
    _r("rsc:", style="danger", match="prefix"),
    _r("wld:", style="danger", match="prefix"),
    _r("wdr:", style="danger", match="prefix"),
    _r("tclose:", style="danger", match="prefix"),
    _r("menu:plans", style="success"),
    _r("menu:wallet", style="primary"),
    _r("menu:accounts", style="primary"),
    _r("menu:orders", style="primary"),
    _r("menu:tickets", style="primary"),
    _r("menu:club", style="primary"),
    _r("reply:", style="primary", match="prefix"),
    _r("tnew:", style="primary", match="prefix"),
    _r(URL_KEY, style="primary"),
]

PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "classic",
        "name": "رنگی کلاسیک",
        "description": "خرید و تأیید سبز، لغو و حذف قرمز، ناوبری و گفتگو آبی.",
        "rules": _CLASSIC,
    },
    {
        "id": "premium",
        "name": "پریمیوم",
        "description": "رنگ‌های کلاسیک به‌همراه تزئین نشان‌دار روی خرید و کیف پول؛ شناسهٔ ایموجی پریمیوم را خودتان اضافه کنید.",
        "rules": [
            *[r for r in _CLASSIC if r["key"] not in ("buy:", "menu:plans", "menu:wallet")],
            _r("buy:", style="success", match="prefix", prefix="💎 "),
            _r("menu:plans", style="success", prefix="💎 "),
            _r("menu:wallet", style="primary", prefix="✦ "),
        ],
    },
    {
        "id": "calm",
        "name": "آبی یکدست",
        "description": "همهٔ دکمه‌های منو آبی؛ فقط عملیات خطرناک قرمز.",
        "rules": [
            _r("menu:", style="primary", match="prefix"),
            _r("rtc:", style="danger", match="prefix"),
            _r("rsc:", style="danger", match="prefix"),
            _r("wld:", style="danger", match="prefix"),
            _r("wdr:", style="danger", match="prefix"),
        ],
    },
)

# One representative button per look, in the order a customer meets them; used by the admin's "send a test to Telegram".
SAMPLE_INLINE: tuple[tuple[str, str], ...] = (
    ("🛒 خرید اکانت", "menu:plans"),
    ("💰 کیف پول", "menu:wallet"),
    ("✅ خرید و پرداخت", "buy:sample"),
    ("🎫 تیکت‌ها", "menu:tickets"),
    ("⛔ این من نبودم", "wld:sample"),
    ("🏠 خانه", "menu:home"),
)
SAMPLE_REPLY: tuple[str, ...] = ("🛒 خرید اکانت", "💰 کیف پول و شارژ حساب", "🎧 پشتیبانی")


def sample_markups(cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(inline markup, reply markup) built from ``cfg`` exactly as the bots would build the real ones."""
    proj = public_projection(cfg)
    inline = [[{**apply_inline(proj, key, text), "callback_data": "noop:preview"}] for text, key in SAMPLE_INLINE]
    inline_rows = [inline[0] + inline[1], inline[2], inline[3] + inline[4], inline[5]]
    reply = [[apply_reply(proj, t) for t in SAMPLE_REPLY[:2]], [apply_reply(proj, SAMPLE_REPLY[2])]]
    return {"inline_keyboard": inline_rows}, {"keyboard": reply, "resize_keyboard": True, "one_time_keyboard": True}
