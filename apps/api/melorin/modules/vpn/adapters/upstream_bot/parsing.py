"""Pure parsers for the upstream (parent) VPN bot's Persian messages. No I/O, fully unit-testable.

Verified against the real flow of a parent bot (purchase screens):
  plan button : "🔥 10 گیگ یک ماهه 60,000 تومان"
  confirm     : "... مبلغ 60,000 تومان از حسابت کم خواهم کرد ..." + [تایید خرید] [انصراف]
  result      : "نام اکانت: eg1_1068 / نوع اکانت / توضیحات / تاریخ خرید / لینک اکانت: https://.../sub/...?name=eg1_1068"
  balance     : "موجودی حساب شما: 505,000 تومان"
"""

import re
from dataclasses import dataclass

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
    """Return the account only when the message really is the delivery message (has a name AND a link)."""
    t = digits(text)
    name = _NAME.search(t)
    if not name:
        return None
    after = t[name.end() :]
    link = _LINK.search(after[after.find("لینک") :] if "لینک" in after else after)
    return PurchaseResult(name.group(1), link.group(1).rstrip(".,)") if link else None, text)


def is_confirm_prompt(text: str) -> bool:
    return "تایید خرید" in text or "تأیید خرید" in text or "کم خواهم کرد" in text


def confirm_amount(text: str) -> int | None:
    m = re.search(r"مبلغ\s*([\d,]+)\s*تومان", digits(text))
    return int(m.group(1).replace(",", "")) if m else None


def is_insufficient_balance(text: str) -> bool:
    return any(k in text for k in ("موجودی کافی نیست", "موجودی شما کافی", "موجودی ناکافی", "شارژ کنید"))
