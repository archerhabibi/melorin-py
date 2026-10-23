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
    "/tickets پشتیبانی و تیکت‌ها\n/me حساب من در سایت\n/referral دعوت از دوستان\n"
    "/reseller درخواست نمایندگی\n/cancel انصراف از مرحلهٔ جاری"
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
    ("reseller", "🤖 درخواست نمایندگی"),
    ("help", "راهنما"),
]

# Shown when the main admin's own Telegram account opens the bot: it is the address of the admin alerts, not a customer account.
ADMIN_NOTICE = (
    "👋 سلام مدیر عزیز\n"
    "✅ اعلان‌های مدیریتی (خطای ساخت اکانت، درخواست نمایندگی جدید، کارهای دستیِ نماینده‌ها و …) از همین ربات به همین چت ارسال می‌شود.\n\n"
    "مدیریت فروشگاه فقط از پنل مدیریت انجام می‌شود؛ این ربات مخصوص مشتریان است."
)

# Core error codes of the reseller details step that mean "send the domain again" / "send the token again".
RESELLER_DOMAIN_ERRORS = {"INVALID_DOMAIN", "DOMAIN_RESERVED", "DOMAIN_TAKEN", "IDENTITY_TAKEN"}

RESELLER_TOKEN_ERRORS = {"INVALID_BOT_TOKEN", "BOT_TOKEN_REJECTED", "BOT_TAKEN", "TELEGRAM_UNREACHABLE"}

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
ACC_FILTERS = [("-", None, "همه"), ("a", "active", "🟢 فعال"), ("x", "expiring", "🟡 رو‌به‌اتمام"), ("e", "expired", "🔴 منقضی")]

HEALTH_BADGE = {"active": "🟢", "expiring": "🟡", "expired": "🔴", "depleted": "🟠", "disabled": "⚫"}

HEALTH_LABEL = {"active": "فعال", "expiring": "رو‌به‌اتمام", "expired": "منقضی", "depleted": "حجم تمام‌شده", "disabled": "غیرفعال"}

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


def gb(b) -> str:
    return f"{(b or 0) / 1073741824:.1f}"


def _button(text, data):
    """callback_data button, or a URL button when ``data`` is an absolute http(s) link (opens in the user's browser)."""
    if str(data).startswith(("https://", "http://")):
        return {"text": text, "url": data}
    return {"text": text, "callback_data": data}


def keyboard(rows):
    return {"inline_keyboard": [[_button(t, d) for t, d in row] for row in rows]}


def reply_keyboard(rows):
    return {"keyboard": [[{"text": text} for text in row] for row in rows], "resize_keyboard": True}


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
    except ImportError:  # optional dependency: the bot still works, just without the QR image
        return None
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()
