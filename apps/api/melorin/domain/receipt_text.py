"""Reading the facts printed on a card-to-card receipt (pure: no I/O, no framework imports).

Two inputs end up in the same :class:`ReceiptFacts`: raw OCR text (:func:`parse_receipt_text`) or the structured answer of
a vision model (:func:`facts_from_mapping`). Nothing here is trusted with money: the bank deposit SMS is the proof, the
receipt facts only help to pick between candidates and to flag receipts whose amount disagrees with the request.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from melorin.domain.bank_sms import digits_only, jalali_datetime_to_utc, normalize_text, parse_datetime_text

_MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "ابان": 8,
    "آذر": 9,
    "اذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}
_UNIFY = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ؤ": "و", "ً": "", "َ": ""})


def _clean(text: str) -> str:
    return normalize_text(text or "").translate(_UNIFY)


@dataclass(frozen=True)
class ReceiptFacts:
    amount_rial: int | None = None
    paid_at: dt.datetime | None = None  # aware UTC
    source_last4: str | None = None
    reference: str | None = None

    @property
    def found(self) -> bool:
        return any((self.amount_rial, self.paid_at, self.source_last4, self.reference))

    def to_claim(self) -> dict:
        """Same shape as ``modules.payments.bank_sms.parse_claim`` (+ the amount, used only as a cross-check)."""
        out: dict = {}
        if self.paid_at:
            out["paid_at"] = self.paid_at.isoformat()
        if self.reference:
            out["reference"] = self.reference
        if self.source_last4:
            out["source_card_last4"] = self.source_last4
        if self.amount_rial:
            out["amount_rial"] = self.amount_rial
        return out


# ----------------------------------------------------------------------------------------------------------- time
_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*[:：.]\s*([0-5]\d)(?:\s*[:：]\s*[0-5]\d)?(?!\d)")
_YMD_RE = re.compile(r"(?<!\d)(1[34]\d{2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)")
_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})\s+([^\W\d_]{2,10})\s+(1[34]\d{2})(?!\d)")


def _find_time(text: str) -> dt.datetime | None:
    """Jalali date + clock time in any layout the bank apps use (``2 آبان 1405``, ``1405/08/02``), Tehran time."""
    t = _TIME_RE.search(text)
    if not t:
        return None
    hour, minute = int(t.group(1)), int(t.group(2))
    ymd = _YMD_RE.search(text)
    year = month = day = None
    if ymd:
        year, month, day = (int(x) for x in ymd.groups())
    else:
        for m in _DMY_RE.finditer(text):
            name = m.group(2)
            if name in _MONTHS:
                day, month, year = int(m.group(1)), _MONTHS[name], int(m.group(3))
                break
    if year is None:
        return None
    try:
        return jalali_datetime_to_utc(year, month, day, hour, minute)
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------------------- amount
_NUM = r"((?:\d{1,3}(?:[,٬]\d{3})+|\d{4,15}))"
_AMOUNT_UNIT_RE = re.compile(rf"{_NUM}\s*(ریال|تومان|rial|irr|toman)|(ریال|تومان|rial|irr|toman)\s*{_NUM}", re.IGNORECASE)


def _find_amount(text: str) -> int | None:
    for m in _AMOUNT_UNIT_RE.finditer(text):
        raw = m.group(1) or m.group(4)
        unit = (m.group(2) or m.group(3) or "").lower()
        value = int(digits_only(raw) or 0)
        if value <= 0:
            continue
        return value * (10 if unit in ("تومان", "toman") else 1)
    return None


# -------------------------------------------------------------------------------------------------------- reference
_REF_LABEL = re.compile(r"(مرجع|پیگیری|رهگیری|ref)", re.IGNORECASE)


def _find_reference(lines: list[str]) -> str | None:
    for line in lines:
        if not _REF_LABEL.search(line):
            continue
        runs = [r for r in re.findall(r"\d{6,30}", re.sub(r"(?<=\d)\s(?=\d)", "", line))]
        if runs:
            return max(runs, key=len)
    return None


# ------------------------------------------------------------------------------------------------------ source card
_CARD_LABEL = re.compile(r"(کارت\s*مبد|از\s*کارت|source\s*card)", re.IGNORECASE)
_GROUP = re.compile(r"[\d*•xX]{4}")


def _luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _last4_from_groups(groups: list[str]) -> str | None:
    """Receipts print the card right-to-left, OCR may return the groups in either order: never guess, decide by structure.

    Masked card (``6219 86** **** 7931``): the group that mixes digits and stars sits next to the BIN, so the *other* end
    is the tail. Unmasked card: whichever order passes the Luhn check. Anything else -> ``None``.
    """
    if len(groups) != 4:
        return None
    pure = [g.isdigit() for g in groups]
    if all(pure):
        for cand in (groups, groups[::-1]):
            if _luhn("".join(cand)):
                return cand[-1]
        return None
    mixed = [i for i, g in enumerate(groups) if not g.isdigit() and re.search(r"\d", g)]
    if len(mixed) != 1:
        return None
    i = mixed[0]
    if i in (1,):  # logical order: BIN first, tail last
        return groups[3] if groups[3].isdigit() else None
    if i == 2:  # visual order: tail first, BIN last
        return groups[0] if groups[0].isdigit() else None
    return None


def _find_source_last4(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        if not _CARD_LABEL.search(line):
            continue
        for chunk in (line, *(lines[i + 1 : i + 2])):
            groups = _GROUP.findall(re.sub(r"[\s‌]+", " ", chunk))
            last4 = _last4_from_groups(groups)
            if last4:
                return last4
    return None


# --------------------------------------------------------------------------------------------------------- entry
def parse_receipt_text(text: str) -> ReceiptFacts:
    """Facts from the raw text of a receipt screenshot (any bank app; Persian or Latin digits)."""
    clean = _clean(text)
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    return ReceiptFacts(
        amount_rial=_find_amount(clean),
        paid_at=_find_time(clean),
        source_last4=_find_source_last4(lines),
        reference=_find_reference(lines),
    )


def facts_from_mapping(data: dict) -> ReceiptFacts:
    """Facts from a vision model's JSON answer; every field is re-validated, a malformed one is simply dropped."""

    def as_int(v) -> int | None:
        if v in (None, "") or str(v).strip().startswith(("-", "−")):
            return None
        try:
            n = int(digits_only(str(v)))
        except ValueError:
            return None
        return n if n and n > 0 else None

    amount = as_int(data.get("amount_rial"))
    if amount is None:
        toman = as_int(data.get("amount_toman"))
        amount = toman * 10 if toman else None
    paid_at = parse_datetime_text(str(data.get("paid_at") or "")) if data.get("paid_at") else None
    last4 = digits_only(str(data.get("source_card_last4") or ""))
    ref = digits_only(str(data.get("reference") or ""))
    return ReceiptFacts(
        amount_rial=amount,
        paid_at=paid_at,
        source_last4=last4 if len(last4) == 4 else None,
        reference=ref if 6 <= len(ref) <= 30 else None,
    )
