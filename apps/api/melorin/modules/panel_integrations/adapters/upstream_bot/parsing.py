"""Pure parsers for the upstream (parent) VPN bot's Persian messages. No I/O, fully unit-testable.

Verified against the real flow of a parent bot (purchase screens):
  plan button : "🔥 10 گیگ یک ماهه 60,000 تومان"
  confirm     : "... مبلغ 60,000 تومان از حسابت کم خواهم کرد ..." + [تایید خرید] [انصراف]
  result      : "نام اکانت: eg1_1068 / نوع اکانت / توضیحات / تاریخ خرید / لینک اکانت: https://.../sub/...?name=eg1_1068"
  balance     : "موجودی حساب شما: 505,000 تومان"

Verified against the real renewal flow (screenshots + recording of 24 Oct 2026):
  account screen -> [تمدید اکانت] -> "موجودی حساب شما: 445,000 تومان" + options message
  options     : "تمدید اکانت eg2_1052 / حجم اولیه: 10 گیگ / لطفا حجم تمدید مورد نظرت رو انتخاب کن" with buttons
                "تمدید با حجم اولیه 60000 تومان" (no thousands separator!), "تمدید و افزایش 10 گیگ 110,000 تومان", ..., "انصراف"
  confirm     : "تمدید اکانت eg2_1052 با حجم اولیه 10 گیگ / ... مبلغ 0 تومان از حسابت کم خواهم کرد ..." + [تایید تمدید اکانت] [برگشت]
                NOTE: the parent bot prints "0 تومان" here although it really charges the option price; never trust this amount.
  result      : "اکانت eg2_1052 رو با موفقیت تمدید کردم" + "مبلغ 60,000 تومان از حسابت کم کردم" + the account screen with "تاریخ تمدید"
  stale button: "زمان عملیات منقضی شده از اول باید بری" + [عملیات منقضی شده]
"""

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬٫", "01234567890123456789,.")
_NAME = re.compile(r"نام\s*اکانت\s*[:：]\s*([A-Za-z0-9_.\-]+)")
_LINK = re.compile(r"(https?://[^\s]+)")
_BALANCE = re.compile(r"موجودی[^:：\n]*[:：]\s*([\d,\.]+)\s*تومان")
_PLAN = re.compile(r"(\d+(?:\.\d+)?)\s*گیگ\s*(.*?)\s*([\d,]+)\s*تومان")
_DURATIONS = {"یک": 1, "دو": 2, "سه": 3, "شش": 6, "6": 6, "3": 3, "2": 2, "1": 1, "12": 12, "دوازده": 12}


def digits(text: str) -> str:
    return (text or "").translate(_FA)


@dataclass(frozen=True)
class PlanButton:
    label: str
    traffic_gb: float
    months: int
    price: int


@dataclass(frozen=True)
class PurchaseResult:
    name: str
    subscription_url: str | None
    raw: str


def parse_balance(text: str) -> int | None:
    m = _BALANCE.search(digits(text))
    return int(m.group(1).replace(",", "").split(".")[0]) if m else None


def parse_plan_label(label: str) -> PlanButton | None:
    m = _PLAN.search(digits(label))
    if not m:
        return None
    gb, middle, price = float(m.group(1)), m.group(2), int(m.group(3).replace(",", ""))
    months = 1
    for word, n in _DURATIONS.items():
        if re.search(rf"{word}\s*ماه", middle):
            months = n
            break
    return PlanButton(label.strip(), gb, months, price)


def parse_purchase_result(text: str) -> PurchaseResult | None:
    """Return the account only when the message really is the delivery message (name AND link, no status line)."""
    t = digits(text)
    name = _NAME.search(t)
    if not name or "وضعیت" in t:  # the account detail screen also has a name, but a status line and no link
        return None
    after = t[name.end() :]
    link = _LINK.search(after[after.find("لینک") :] if "لینک" in after else after)
    if not link:
        return None
    return PurchaseResult(name.group(1), link.group(1).rstrip(".,)"), text)


def is_confirm_prompt(text: str) -> bool:
    return "تایید خرید" in text or "تأیید خرید" in text or "کم خواهم کرد" in text


def confirm_amount(text: str) -> int | None:
    m = re.search(r"مبلغ\s*([\d,]+)\s*تومان", digits(text))
    return int(m.group(1).replace(",", "")) if m else None


def is_insufficient_balance(text: str) -> bool:
    return any(k in text for k in ("موجودی کافی نیست", "موجودی شما کافی", "موجودی ناکافی", "شارژ کنید"))


# ----------------------------------------------------------------------------- account detail screen
_TEHRAN = ZoneInfo("Asia/Tehran")
_UNITS = {"ترابایت": 1024**4, "تراببایت": 1024**4, "گیگابایت": 1024**3, "گیگ": 1024**3, "مگابایت": 1024**2, "مگ": 1024**2, "کیلوبایت": 1024}
_VOL = re.compile(r"([\d.,]+)\s*(ترابایت|تراببایت|گیگابایت|گیگ|مگابایت|مگ|کیلوبایت)?")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    jy += 1595
    days = -355668 + (365 * jy) + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    months = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return gy, gm, gd


def parse_jalali(text: str) -> dt.datetime | None:
    """'1405/09/02 03:51' (Tehran wall clock) -> aware UTC datetime."""
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", digits(text))
    if not m:
        return None
    jy, jm, jd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    return dt.datetime(gy, gm, gd, hh, mm, tzinfo=_TEHRAN).astimezone(dt.UTC)


def _volume_bytes(raw: str) -> int | None:
    m = _VOL.search(digits(raw))
    if not m or not m.group(1).strip(".,"):
        return None
    num = float(m.group(1).replace(",", ""))
    return int(num * _UNITS.get(m.group(2) or "گیگ", 1024**3))


@dataclass(frozen=True)
class AccountDetail:
    name: str
    status: str  # normalized: active | disabled | expired | limited | unknown
    used_bytes: int
    remaining_bytes: int | None
    expire_at: dt.datetime | None
    description: str
    renewed_at: dt.datetime | None = None  # "تاریخ تمدید": only present once the account was renewed


def _status(raw: str) -> str:
    r = raw.strip()
    if any(w in r for w in ("غیرفعال", "غیر فعال", "مسدود", "disabled")):
        return "disabled"
    if "منقضی" in r or ("تمام شد" in r and "زمان" in r):
        return "expired"
    if "اتمام حجم" in r or "حجم تمام" in r or "محدود شد" in r:
        return "limited"
    if "فعال" in r:
        return "active"
    return "unknown"


def _field(t: str, label: str) -> str | None:
    m = re.search(rf"{label}\s*[:：]\s*([^\n]+)", t)
    return m.group(1).strip() if m else None


def parse_account_detail(text: str) -> AccountDetail | None:
    """The 'my purchase' screen: name, type, description, status, used, remaining, end date, time left. None if not that screen."""
    t = digits(text)
    name = _NAME.search(t)
    st = _field(t, "وضعیت")
    if not name or st is None:
        return None
    used = _volume_bytes(_field(t, "حجم مصرف\\s*شده") or "") or 0
    rem_raw = _field(t, "حجم باقی\\s*مانده")
    remaining = _volume_bytes(rem_raw) if rem_raw else None
    return AccountDetail(
        name.group(1),
        _status(st),
        used,
        remaining,
        parse_jalali(_field(t, "تاریخ اتمام") or ""),
        _field(t, "توضیحات") or "",
        parse_jalali(_field(t, "تاریخ تمدید") or ""),
    )


# ----------------------------------------------------------------------------- refund (مرجوعی)
def is_refund_confirm_prompt(text: str) -> bool:
    return ("قابل مرجوع میباشد" in text or "قابل مرجوع می‌باشد" in text) and "تایید" in text


def parse_refund_success(text: str) -> bool:
    return "با موفقیت مرجوع" in text


def parse_refund_amount(text: str) -> int | None:
    m = re.search(r"مبلغ\s*([\d,]+)\s*تومان[^\n]*مرجوعی", digits(text))
    return int(m.group(1).replace(",", "")) if m else None


# ----------------------------------------------------------------------------- renewal (تمدید)
_RENEW_NAME = re.compile(r"تمدید\s*اکانت\s+([A-Za-z0-9_.\-]+)")
_RENEW_INITIAL = re.compile(r"حجم\s*اولیه\s*[:：]?\s*([\d.,]+)\s*گیگ")
_RENEW_PRICE = re.compile(r"([\d,]+)\s*تومان")
_RENEW_INCREASE = re.compile(r"افزایش\s*([\d.]+)\s*گیگ")


@dataclass(frozen=True)
class RenewOption:
    label: str
    kind: str  # "initial" (renew with the original volume) | "increase" (renew and add ``extra_gb``)
    extra_gb: float
    price: int


@dataclass(frozen=True)
class RenewScreen:
    name: str
    initial_gb: float


def parse_renew_option(label: str) -> RenewOption | None:
    """'تمدید با حجم اولیه 60000 تومان' / 'تمدید و افزایش 10 گیگ 110,000 تومان'. Cancel / back buttons -> None."""
    t = digits(label)
    price = _RENEW_PRICE.search(t)
    if not price or "تمدید" not in t:
        return None
    amount = int(price.group(1).replace(",", "") or 0)
    inc = _RENEW_INCREASE.search(t)
    if inc:
        return RenewOption(label.strip(), "increase", float(inc.group(1)), amount)
    if "حجم اولیه" in t:
        return RenewOption(label.strip(), "initial", 0.0, amount)
    return None


def parse_renew_screen(text: str) -> RenewScreen | None:
    """The options message: account name + the original volume. None for any other message."""
    t = digits(text)
    name, initial = _RENEW_NAME.search(t), _RENEW_INITIAL.search(t)
    if not name or not initial or "حجم تمدید" not in t:
        return None
    return RenewScreen(name.group(1), float(initial.group(1).replace(",", "")))


def is_renew_confirm_prompt(text: str, name: str) -> bool:
    """The confirmation message for THIS account (the name must match, so a stale prompt of another account is never confirmed)."""
    t = digits(text)
    m = _RENEW_NAME.search(t)
    return bool(m and m.group(1) == name and "تایید تمدید" in t and "حجم تمدید" not in t)


def renew_confirm_amount(text: str) -> int | None:
    """Amount printed in the renew confirmation. The parent bot prints 0 here (display quirk), so callers accept 0."""
    return confirm_amount(text)


def parse_renew_success(text: str, name: str) -> bool:
    t = digits(text)
    return "با موفقیت تمدید" in t and name in t


def parse_charged_amount(text: str) -> int | None:
    """'مبلغ 60,000 تومان از حسابت کم کردم' (past tense = money really taken; the confirm prompt says 'کم خواهم کرد')."""
    m = re.search(r"مبلغ\s*([\d,]+)\s*تومان\s*از\s*حسابت\s*کم\s*کردم", digits(text))
    return int(m.group(1).replace(",", "")) if m else None


def is_operation_expired(text: str) -> bool:
    """Stale inline buttons: 'زمان عملیات منقضی شده از اول باید بری'."""
    return "عملیات منقضی شده" in text
