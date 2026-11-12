"""Presentation helpers for the main Telegram bot: texts, labels, keyboards and formatting (no I/O, no Core calls)."""

import base64
import datetime as dt
import html
import io
import logging
import uuid

from tgmain.errors import CoreError

log = logging.getLogger("melorin.telegram.main")

log = logging.getLogger("melorin.telegram.main")

HELP = (
    "فرمان‌ها:\n"
    "/plans خرید اکانت\n/wallet کیف پول و شارژ حساب\n/topup مبلغ — شارژ کیف پول\n"
    "/accounts استعلام و تمدید اکانت\n/orders سفارش‌ها\n/test دریافت اکانت تست\n"
    "/tickets پشتیبانی و تیکت‌ها\n/me حساب من در سایت\n/referral دعوت از دوستان\n/club باشگاه مشتریان\n"
    "/reseller درخواست نمایندگی\n/devices مرورگرهای مطمئن (ورود خودکار)\n/cancel انصراف از مرحلهٔ جاری"
)

# Registered with Telegram (setMyCommands) so the "Menu" button lists them.
BOT_COMMANDS = [
    ("start", "شروع و منوی اصلی"),
    ("plans", "🛒 خرید اکانت"),
    ("accounts", "🔑 اکانت‌های من"),
    ("wallet", "💰 کیف پول و شارژ"),
    ("orders", "📦 سفارش‌ها"),
    ("test", "🧪 اکانت تست"),
    ("tickets", "🎧 پشتیبانی"),
    ("referral", "🎁 دعوت از دوستان"),
    ("club", "🏅 باشگاه مشتریان"),
    ("reseller", "🤖 درخواست نمایندگی"),
    ("devices", "🔐 مرورگرهای مطمئن"),
    ("help", "راهنما"),
]

# Shown when the main admin's own Telegram account opens the bot: it is the address of the admin alerts, not a customer account.
ADMIN_NOTICE = (
    "👋 سلام مدیر عزیز\n"
    "✅ اعلان‌های مدیریتی (خطای ساخت اکانت، درخواست نمایندگی جدید، کارهای دستیِ نماینده‌ها و …) از همین ربات به همین چت ارسال می‌شود.\n\n"
    "مدیریت فروشگاه فقط از پنل مدیریت انجام می‌شود؛ این ربات مخصوص مشتریان است."
)

# Core error codes of the reseller details step that mean "send the domain again" / "send the token again".
RESELLER_DOMAIN_ERRORS = {
    "INVALID_DOMAIN",
    "DOMAIN_RESERVED",
    "DOMAIN_TAKEN",
    "IDENTITY_TAKEN",
}

RESELLER_TOKEN_ERRORS = {
    "INVALID_BOT_TOKEN",
    "BOT_TOKEN_REJECTED",
    "BOT_TAKEN",
    "TELEGRAM_UNREACHABLE",
}

# The account button opens the user's account on the store website (Telegram/Google login happens there).
ACCOUNT_BUTTON = "🌐 حساب من در سایت"

LEGACY_ACCOUNT_BUTTON = "👤 حساب کاربری"  # cached reply keyboards still send this text

# Must stay in sync with the public bot's Persian reply keyboard.
MAIN_MENU = [
    ["🛒 خرید اکانت", "🔍 استعلام و تمدید اکانت"],
    ["💰 کیف پول و شارژ حساب", ACCOUNT_BUTTON],
    ["🎁 دعوت از دوستان", "🧪 دریافت اکانت تست"],
    ["📜 قوانین خرید و آموزش", "🎧 پشتیبانی"],
    ["🤖 درخواست ربات نماینده و همکاری"],
]

# Inline actions used inside the flows behind the reply keyboard.
MENU = [
    [("🛒 خرید اکانت", "menu:plans"), ("💰 کیف پول", "menu:wallet")],
    [("📦 سفارش‌ها", "menu:orders"), ("🔑 اکانت‌ها", "menu:accounts")],
    [("🎫 تیکت‌ها", "menu:tickets"), ("🔔 اعلان‌ها", "menu:notifications")],
    [("🏅 باشگاه مشتریان", "menu:club")],
]

CURRENCY_LABEL = {"IRT": "تومان", "IRR": "ریال"}

ACCOUNT_STATUS = {
    "active": "🟢 فعال",
    "pending": "⏳ در انتظار",
    "provisioning": "⏳ در حال ساخت",
    "suspended": "🟠 مسدود",
    "expired": "🔴 منقضی",
    "revoked": "⛔ لغوشده",
    "archived": "📁 بایگانی",
}

ORDER_STATUS = {
    "pending": "⏳ در انتظار پرداخت",
    "paid": "💳 پرداخت‌شده",
    "processing": "⚙️ در حال پردازش",
    "provisioning": "⚙️ در حال ساخت اکانت",
    "completed": "✅ تکمیل‌شده",
    "provisioning_failed": "❌ ناموفق",
    "refund_pending": "↩️ در حال بازگشت وجه",
    "refunded": "↩️ بازگشت داده شد",
    "cancelled": "🚫 لغوشده",
    "manual_review": "🔎 در حال بررسی",
}

TX_KIND = {
    "purchase": "🛒 خرید",
    "topup": "💳 شارژ",
    "refund": "↩️ بازگشت وجه",
    "topup_refund": "↩️ برگشت شارژ",
    "referral_first": "🎁 پاداش دعوت",
    "referral_recurring": "🎁 پاداش دعوت",
    "manual_adjustment": "✏️ اصلاح دستی",
}

PAGE_SIZE = 8

# Account inquiry: filter chips (code -> Core `state` value, label) and the badge of each account's `health`.
ACC_FILTERS = [
    ("-", None, "همه"),
    ("a", "active", "🟢 فعال"),
    ("x", "expiring", "🟡 رو‌به‌اتمام"),
    ("e", "expired", "🔴 منقضی"),
]

HEALTH_BADGE = {
    "active": "🟢",
    "expiring": "🟡",
    "expired": "🔴",
    "depleted": "🟠",
    "disabled": "⚫",
}

HEALTH_LABEL = {
    "active": "فعال",
    "expiring": "رو‌به‌اتمام",
    "expired": "منقضی",
    "depleted": "حجم تمام‌شده",
    "disabled": "غیرفعال",
}

TICKET_ICON = {"open": "🟡", "answered": "🟢", "closed": "⚫"}

TICKET_LABEL = {"open": "🟡 باز", "answered": "🟢 پاسخ داده شد", "closed": "⚫ بسته"}

PRIORITY_LABEL = {"low": "کم", "normal": "عادی", "high": "🟠 مهم", "urgent": "🔴 فوری"}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


def money(n) -> str:
    return f"{int(n or 0):,}"


def cur(code) -> str:
    return CURRENCY_LABEL.get(str(code or "").upper(), str(code or ""))


def fmt(n, code) -> str:
    return f"{money(n)} {cur(code)}"


def _reward_line(label: str, plan: dict | None, currency) -> str | None:
    """One line of the store's referral programme, exactly as Core reports it (the bot computes nothing)."""
    if not plan:
        return None
    value = plan.get("value") or 0
    if plan.get("model") == "percent":
        amount = f"{value / 100:g}٪"
        cap = plan.get("max_amount")
        if cap:
            amount += f" (حداکثر {fmt(cap, currency)})"
    else:
        amount = fmt(value, currency)
    return f"• {label}: <b>{amount}</b>"


def referral_text(data: dict, fallback_link: str) -> str:
    """Referral screen of THIS store, built only from ``/me/referrals`` (programme, link, invited count, earnings)."""
    link = ((data.get("links") or {}).get("telegram")) or fallback_link
    program = data.get("program") or {}
    currency = program.get("currency")
    lines = ["🎁 <b>دعوت از دوستان</b>", ""]
    rewards = [
        _reward_line("پاداش ثبت‌نام دوست شما", program.get("signup_reward"), currency),
        _reward_line("کمیسیون هر خرید دوست شما", program.get("commission"), currency),
    ]
    rewards = [r for r in rewards if r]
    if program.get("enabled") and rewards:
        lines += ["این فروشگاه برای دعوت دوستان به شما پاداش می‌دهد:", *rewards, ""]
    else:
        lines += ["فعلاً برنامه‌ی پاداش دعوت در این فروشگاه فعال نیست.", ""]
    lines += [f"لینک اختصاصی شما:\n{esc(link)}", ""]
    count = data.get("referred_count", data.get("count", data.get("total", 0)))
    lines.append(f"تعداد زیرمجموعه‌ها: <b>{count}</b>")
    if data.get("earned") is not None:  # Core sums every commission of this store; the list below is only the latest ones
        if int(data["earned"]) > 0:
            lines.append(f"درآمد ثبت‌شده از دعوت‌ها: <b>{fmt(int(data['earned']), currency)}</b>")
        return "\n".join(lines)
    credited = [
        c for c in data.get("commissions") or [] if c.get("status") == "credited"
    ]
    if credited:  # older Core without ``earned``: best effort from the listed commissions
        earned = sum(
            int(c.get("amount") or 0) - int(c.get("offset_amount") or 0)
            for c in credited
        )
        lines.append(
            f"درآمد ثبت‌شده از دعوت‌ها: <b>{fmt(max(0, earned), credited[0].get('currency') or currency)}</b>"
        )
    return "\n".join(lines)


def gb(b) -> str:
    return f"{(b or 0) / 1073741824:.1f}"


# Admin-configured button styling (Bot API 9.4 ``style`` / ``icon_custom_emoji_id`` + a text decoration), downloaded from Core
# by the runner (``TransportMixin.refresh_button_styles``). Same semantics as ``melorin.domain.button_style.resolve``:
# the rule lists arrive ordered most-specific first, an exact key beats a prefix, the first match wins. Disabled = no-op.
URL_STYLE_KEY = "@url"
MAX_BUTTON_TEXT = 64
_STYLES: dict = {"enabled": False, "inline": [], "reply": []}


def set_button_styles(projection) -> None:
    """Install the styling downloaded from Core; anything malformed switches styling off rather than breaking keyboards."""
    global _STYLES
    ok = (
        isinstance(projection, dict)
        and projection.get("enabled") is True
        and isinstance(projection.get("inline"), list)
        and isinstance(projection.get("reply"), list)
    )
    _STYLES = (
        {"enabled": True, "inline": list(projection["inline"]), "reply": list(projection["reply"])}
        if ok
        else {"enabled": False, "inline": [], "reply": []}
    )


def _style_rule(rules, key: str):
    for r in rules:
        k, m = r.get("key"), r.get("match")
        if (m == "exact" and k == key) or (m == "prefix" and isinstance(k, str) and key.startswith(k)):
            return r
    return None


def styled_inline(text, key) -> dict:
    """Text (maybe decorated) plus ``style`` / ``icon_custom_emoji_id`` for the inline button identified by ``key``."""
    rule = _style_rule(_STYLES["inline"], str(key)) if _STYLES["enabled"] else None
    if not rule:
        return {"text": text}
    decorated = f"{rule.get('prefix', '')}{text}{rule.get('suffix', '')}"
    out = {"text": decorated if len(decorated) <= MAX_BUTTON_TEXT else text}
    if rule.get("style"):
        out["style"] = rule["style"]
    if rule.get("icon"):
        out["icon_custom_emoji_id"] = rule["icon"]
    return out


def has_styling(markup) -> bool:
    """True when a reply markup carries any ``style`` / ``icon_custom_emoji_id`` (so a refusal can be retried without them)."""
    if not isinstance(markup, dict):
        return False
    rows = markup.get("inline_keyboard") or markup.get("keyboard") or []
    return any(isinstance(b, dict) and ("style" in b or "icon_custom_emoji_id" in b) for row in rows for b in row)


def strip_styling(markup):
    """Copy of a reply markup without the styling fields (the safe retry when Telegram refuses them)."""
    if not isinstance(markup, dict):
        return markup
    out = dict(markup)
    for rows_key in ("inline_keyboard", "keyboard"):
        if rows_key in out:
            out[rows_key] = [[{k: v for k, v in b.items() if k not in ("style", "icon_custom_emoji_id")} for b in row] for row in out[rows_key]]
    return out


def _button(text, data):
    """callback_data button, or a URL button when ``data`` is an absolute http(s) link (opens in the user's browser)."""
    if str(data).startswith(("https://", "http://")):
        return {**styled_inline(text, URL_STYLE_KEY), "url": data}
    return {**styled_inline(text, data), "callback_data": data}


def keyboard(rows):
    return {"inline_keyboard": [[_button(t, d) for t, d in row] for row in rows]}


def _reply_button(text) -> dict:
    """Reply-keyboard button: only colour/icon may change; the text is what the user sends back and must stay exact."""
    rule = _style_rule(_STYLES["reply"], text) if _STYLES["enabled"] else None
    out = {"text": text}
    if rule and rule.get("style"):
        out["style"] = rule["style"]
    if rule and rule.get("icon"):
        out["icon_custom_emoji_id"] = rule["icon"]
    return out


def reply_keyboard(rows):
    return {
        "keyboard": [[_reply_button(text) for text in row] for row in rows],
        "resize_keyboard": True,
    }


def b64(value) -> str:
    """UUID -> 22 chars so two ids still fit in Telegram's 64-byte callback_data limit."""
    return base64.urlsafe_b64encode(uuid.UUID(str(value)).bytes).decode().rstrip("=")


def unb64(token: str) -> str:
    try:
        return str(uuid.UUID(bytes=base64.urlsafe_b64decode(token + "==")))
    except (ValueError, TypeError) as exc:
        raise CoreError(400, "گزینه نامعتبر است. دوباره از منو انتخاب کنید.") from exc


def usage_bar(used, limit, width: int = 10) -> str:
    if not limit:
        return f"♾ نامحدود · مصرف {gb(used)} GB"
    pct = min(1.0, (used or 0) / limit)
    filled = round(pct * width)
    return f"{'▰' * filled}{'▱' * (width - filled)} {int(pct * 100)}٪\n{gb(used)} / {gb(limit)} GB"


def parse_dt(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def expiry_line(value) -> str:
    d = parse_dt(value)
    if d is None:
        return "⏳ انقضا: نامحدود"
    left = (d - dt.datetime.now(dt.UTC)).days
    tail = f"{left} روز مانده" if left >= 0 else "منقضی شده"
    return f"⏳ انقضا: {d:%Y-%m-%d} ({tail})"


def qr_png(data: str) -> bytes | None:
    try:
        import segno
    except (
        ImportError
    ):  # optional dependency: the bot still works, just without the QR image
        return None
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()


LOYALTY_BLOCKED = {
    "LOYALTY_NOT_ENOUGH_POINTS": "امتیاز کافی نیست",
    "LOYALTY_REWARD_SOLD_OUT": "موجودی تمام شده",
    "LOYALTY_REWARD_LIMIT": "سقف دریافت شما پر شده",
    "LOYALTY_REWARD_INACTIVE": "غیرفعال است",
}


def loyalty_text(data: dict) -> str:
    """The club screen of THIS store, built only from ``/stores/{id}/loyalty`` (the bot computes nothing)."""
    if not data.get("enabled"):
        return "🏅 <b>باشگاه مشتریان</b>\n\nاین فروشگاه فعلاً باشگاه مشتریان ندارد."
    currency = data.get("currency")
    lines = ["🏅 <b>باشگاه مشتریان</b>", "", f"امتیاز شما: <b>{money(data.get('balance'))}</b>"]
    tier = data.get("tier")
    if tier:
        lines.append(f"سطح شما: <b>{esc(tier['name'])}</b> (ضریب {int(tier.get('multiplier_bp') or 10000) / 10000:g}×)")
    nxt = data.get("next_tier")
    lines.append(
        f"تا سطح «{esc(nxt['name'])}»: <b>{money(nxt['points_missing'])}</b> امتیاز مانده"
        if nxt
        else "شما در بالاترین سطح هستید."
    )
    if int(data.get("debt") or 0) > 0:
        lines.append(f"⚠️ {money(data['debt'])} امتیاز بابت بازگشت وجه از امتیازهای بعدی شما کم می‌شود.")
    bonus = int((data.get("program") or {}).get("first_order_bonus") or 0)
    if bonus:
        lines.append(f"✨ هدیهٔ اولین خرید: {money(bonus)} امتیاز")
    rewards = data.get("rewards") or []
    lines.append("")
    if rewards:
        lines.append("🎁 <b>پاداش‌ها</b>")
        for r in rewards:
            why = "" if r.get("available") else f" — {LOYALTY_BLOCKED.get(r.get('blocked_reason'), 'فعلاً قابل دریافت نیست')}"
            lines.append(f"• {esc(r['name'])}: {money(r['cost_points'])} امتیاز ← {fmt(r['value'], currency)}{why}")
    else:
        lines.append("فعلاً پاداشی تعریف نشده است.")
    history = data.get("history") or []
    if history:
        lines += ["", "🕘 <b>آخرین تغییرات</b>"]
        lines += [f"• {'+' if int(t['amount']) > 0 else ''}{money(t['amount'])}" for t in history[:3]]
    return "\n".join(lines)


def loyalty_keyboard_rows(data: dict) -> list:
    """One button per reward the customer can take right now (Core says which), then the way back."""
    rows = [
        [(f"🎁 {r['name']} · {money(r['cost_points'])}", f"loy:r:{r['id']}")]
        for r in (data.get("rewards") or [])
        if r.get("available")
    ][:6]
    return rows + [[("🏠 خانه", "menu:home")]]
