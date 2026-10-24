"""Bank deposit SMS parsing and receipt <-> SMS matching rules (pure: no I/O, no framework imports).

The bank SMS is the trust anchor of card-to-card auto verification: a receipt image can be forged, a deposit SMS
delivered by the bank to the store owner's phone cannot. This module only knows how to read such an SMS and how to
decide which pending receipt (if any) it pays for; persistence and wallet crediting live in ``modules.payments``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

try:  # Iran has no DST since 2022; the fixed offset is only a fallback when tzdata is missing.
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # pragma: no cover - depends on the host
    TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = str.maketrans({"٬": ",", "،": ",", "−": "-", "–": "-", "—": "-", "\u200c": "", "\u200f": "", "\u200e": ""})


def normalize_text(text: str) -> str:
    """Persian/Arabic-Indic digits -> ASCII, Arabic separators -> ASCII, invisible direction marks removed."""
    return (text or "").translate(_DIGITS).translate(_SEPARATORS)


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", normalize_text(value or ""))


# --------------------------------------------------------------------------------------------- Jalali calendar
_JALALI_MONTH_DAYS = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)


def _div(a: int, b: int) -> int:
    return a // b


def is_jalali_leap(jy: int) -> bool:
    """33-year arithmetic rule (matches the official calendar for 1206..1473)."""
    return (jy % 33) in (1, 5, 9, 13, 17, 22, 26, 30)


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> dt.date:
    """Convert a Jalali (Solar Hijri) date to a Gregorian ``date``; raises ``ValueError`` on an invalid date."""
    if not (1 <= jm <= 12):
        raise ValueError("invalid jalali month")
    max_day = _JALALI_MONTH_DAYS[jm - 1] + (1 if jm == 12 and is_jalali_leap(jy) else 0)
    if not (1 <= jd <= max_day):
        raise ValueError("invalid jalali day")
    # Algorithm of Kazimierz M. Borkowski / jalaali-js (public domain arithmetic form).
    jy += 1595
    days = -355668 + (365 * jy) + (_div(jy, 33) * 8) + _div((jy % 33) + 3, 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * _div(days, 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * _div(days, 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * _div(days, 1461)
    days %= 1461
    if days > 365:
        gy += _div(days - 1, 365)
        days = (days - 1) % 365
    gd = days + 1
    month_lengths = (31, 29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    gm = 0
    while gm < 12 and gd > month_lengths[gm]:
        gd -= month_lengths[gm]
        gm += 1
    return dt.date(gy, gm + 1, gd)


def jalali_datetime_to_utc(jy: int, jm: int, jd: int, hour: int = 0, minute: int = 0, second: int = 0) -> dt.datetime:
    """A Tehran wall-clock Jalali date-time as a timezone-aware UTC datetime."""
    g = jalali_to_gregorian(jy, jm, jd)
    local = dt.datetime(g.year, g.month, g.day, hour, minute, second, tzinfo=TEHRAN)
    return local.astimezone(dt.timezone.utc)


_DT_RE = re.compile(
    r"(?<!\d)(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[-\s,،]+\s*(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*(\d{2}))?(?!\d)"
)


def parse_datetime_text(value: str | None) -> dt.datetime | None:
    """Parse ``1405/8/2-22:50`` (Jalali, Tehran time) or ``2026-10-24 22:50`` (Gregorian, Tehran time) -> aware UTC."""
    m = _DT_RE.search(normalize_text(value or ""))
    if not m:
        return None
    y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
    sec = int(m.group(6) or 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= sec <= 59):
        return None
    try:
        if y < 1700:
            return jalali_datetime_to_utc(y, mo, d, h, mi, sec)
        return dt.datetime(y, mo, d, h, mi, sec, tzinfo=TEHRAN).astimezone(dt.timezone.utc)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------- SMS parser
@dataclass(frozen=True)
class ParsedSms:
    bank: str
    direction: str  # deposit | withdrawal
    amount_rial: int  # always positive
    occurred_at: dt.datetime  # aware UTC
    serial: str | None = None
    balance_rial: int | None = None
    fingerprint: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


class SmsParseError(ValueError):
    """The text is not a recognizable deposit/withdrawal SMS of the configured bank."""


_AMOUNT_RE = re.compile(
    r"(?<![\d,])((?:\d{1,3}(?:,\d{3})+|\d+))\s*([+\-])(?![\d])|(?<![\w])([+\-])\s*((?:\d{1,3}(?:,\d{3})+|\d+))(?![\d,])"
)
_BALANCE_RE = re.compile(r"(?:مانده|موجودی|balance)\s*[:：]?\s*(-?\d[\d,]*)", re.IGNORECASE)
_SERIAL_RE = re.compile(r"(?<![\d,])(\d{8,})(?![\d,])")


def fingerprint_of(serial: str | None, amount: int, occurred_at: dt.datetime, text: str) -> str:
    """Stable identity of one SMS so a forwarder retry never creates a second row (and never a second credit)."""
    base = f"serial:{serial}" if serial else f"text:{re.sub(r'\s+', ' ', normalize_text(text)).strip()}"
    return hashlib.sha256(f"{base}|{amount}|{occurred_at.isoformat()}".encode()).hexdigest()


def parse_deposit_sms(text: str, *, bank: str = "mehr_iran") -> ParsedSms:
    """Parse the standard Iranian core-banking SMS (also used by Qarz al-Hasaneh Mehr Iran)::

        302570009152325001      <- serial / tracking number
        1,500,000+              <- signed amount (+ deposit, - withdrawal)
        1405/8/2-22:50          <- Jalali date-time, Tehran
        مانده:107,923,032       <- remaining balance

    Digit shape and line order are not relied upon, only the tokens, so reordered or extra promotional lines work.
    """
    raw = normalize_text(text)
    if not raw.strip():
        raise SmsParseError("empty sms")
    occurred_at = parse_datetime_text(raw)
    if occurred_at is None:
        raise SmsParseError("no date-time found")
    without_dt = _DT_RE.sub(" ", raw)
    balance = None
    bm = _BALANCE_RE.search(without_dt)
    if bm:
        balance = int(digits_only(bm.group(1)) or 0) * (-1 if bm.group(1).startswith("-") else 1)
        without_dt = without_dt.replace(bm.group(0), " ")
    am = _AMOUNT_RE.search(without_dt)
    if not am:
        raise SmsParseError("no signed amount found")
    num, sign = (am.group(1), am.group(2)) if am.group(1) else (am.group(4), am.group(3))
    amount = int(digits_only(num))
    if amount <= 0:
        raise SmsParseError("amount must be positive")
    remainder = without_dt.replace(am.group(0), " ")
    sm = _SERIAL_RE.search(remainder)
    serial = sm.group(1) if sm else None
    warnings: list[str] = []
    if serial is None:
        warnings.append("no_serial")
    direction = "deposit" if sign == "+" else "withdrawal"
    return ParsedSms(
        bank=bank,
        direction=direction,
        amount_rial=amount,
        occurred_at=occurred_at,
        serial=serial,
        balance_rial=balance,
        fingerprint=fingerprint_of(serial, amount, occurred_at, raw),
        warnings=tuple(warnings),
    )


# Registry so another bank's format can be plugged in without touching the matcher.
PARSERS = {"mehr_iran": parse_deposit_sms, "generic": parse_deposit_sms}


def parse_sms(text: str, bank: str = "mehr_iran") -> ParsedSms:
    parser = PARSERS.get(bank)
    if parser is None:
        raise SmsParseError(f"unsupported bank parser: {bank}")
    return parser(text, bank=bank)


# --------------------------------------------------------------------------------------------- amount helpers
def to_rial(amount: int, currency: str) -> int | None:
    """Store amount -> Rial (what the bank SMS carries). ``None`` = the currency cannot be paid by card-to-card."""
    if currency == "IRR":
        return amount
    if currency == "IRT":
        return amount * 10
    return None


# ------------------------------------------------------------------------------------------------- matching
@dataclass(frozen=True)
class MatchSettings:
    window_minutes: int = 720  # how long a deposit SMS may lag behind / precede the payment request
    time_tolerance_minutes: int = 2  # |receipt time - SMS time| (both have minute resolution)
    require_claimed_time: bool = True  # the customer must state the time printed on the receipt
    max_auto_amount_rial: int | None = None  # larger deposits are always reviewed by a human
    clock_skew_seconds: int = 120  # an SMS may be stamped slightly before the payment row was created


@dataclass(frozen=True)
class Candidate:
    """A manual-card payment that is waiting for review and carries a receipt."""

    payment_id: str
    amount_rial: int
    created_at: dt.datetime  # aware UTC
    claimed_paid_at: dt.datetime | None = None  # time the customer read off the receipt, aware UTC


@dataclass(frozen=True)
class Decision:
    kind: str  # matched | ambiguous | none
    payment_id: str | None = None
    reason: str = ""
    candidate_ids: tuple[str, ...] = ()


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def eligible(sms: ParsedSms, c: Candidate, s: MatchSettings) -> tuple[bool, str]:
    """Hard rules; every one must hold for a receipt to be paid by this SMS."""
    if sms.direction != "deposit":
        return False, "not_a_deposit"
    if c.amount_rial != sms.amount_rial:
        return False, "amount_mismatch"
    created = _aware(c.created_at)
    occurred = _aware(sms.occurred_at)
    if occurred < created - dt.timedelta(seconds=s.clock_skew_seconds):
        return False, "sms_before_request"
    if occurred > created + dt.timedelta(minutes=s.window_minutes):
        return False, "outside_window"
    if c.claimed_paid_at is None:
        if s.require_claimed_time:
            return False, "claimed_time_required"
    elif abs(_aware(c.claimed_paid_at) - occurred) > dt.timedelta(minutes=s.time_tolerance_minutes, seconds=59):
        return False, "claimed_time_mismatch"
    return True, "ok"


def decide(sms: ParsedSms, candidates: list[Candidate], s: MatchSettings | None = None) -> Decision:
    """Pick the receipt this deposit pays for. Anything not 100% unambiguous goes to a human: never guess with money."""
    s = s or MatchSettings()
    if sms.direction != "deposit":
        return Decision("none", reason="not_a_deposit")
    if s.max_auto_amount_rial is not None and sms.amount_rial > s.max_auto_amount_rial:
        return Decision("none", reason="above_auto_limit")
    ok = [c for c in candidates if eligible(sms, c, s)[0]]
    if not ok:
        return Decision("none", reason="no_candidate")
    if len(ok) > 1:
        # The claimed time (minute precision) is the only tie-breaker we trust; closest must be strictly unique.
        timed = [c for c in ok if c.claimed_paid_at is not None]
        if timed:
            best = min(abs(_aware(c.claimed_paid_at) - _aware(sms.occurred_at)) for c in timed)
            nearest = [c for c in timed if abs(_aware(c.claimed_paid_at) - _aware(sms.occurred_at)) == best]
            if len(nearest) == 1 and len(timed) == len(ok):
                return Decision("matched", nearest[0].payment_id, "unique_closest_time", tuple(c.payment_id for c in ok))
        return Decision("ambiguous", reason="several_candidates", candidate_ids=tuple(c.payment_id for c in ok))
    return Decision("matched", ok[0].payment_id, "unique_candidate", (ok[0].payment_id,))
