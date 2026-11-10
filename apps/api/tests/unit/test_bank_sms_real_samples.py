"""Regression: eleven real card-to-card receipts of the store owner and the deposit SMS each one produced.

Only amounts, times and layouts are kept (no names, no card numbers). Receipt side = what the receipt screen prints
(``parse_receipt_text``); SMS side = the bank SMS. Every pair must be paid automatically, and the negative cases below prove
that the extra tolerance (3-minute SMS lag, 12-hour clock) never turns a wrong receipt into a payment.
"""

from __future__ import annotations

import datetime as dt

import pytest

from melorin.domain import bank_sms as b
from melorin.domain.receipt_text import parse_receipt_text

ACCOUNT = "302570009152325001"

# (id, bank, receipt text as printed, SMS amount, SMS Jalali time)
SAMPLES = [
    (
        "blu-dark",
        "1,500,000 ریال\nمبلغ انتقال\nزمان ۲۲:۵۰ شنبه، ۲ آبان ۱۴۰۵\nکارت به کارت\nشماره مرجع ۲۸۶۹۶۱۱۲۲۷۶۲",
        "1,500,000",
        "1405/8/2-22:50",
    ),
    ("melli-seconds-free", "1,500,000 ریال\nتاریخ ۱۴۰۵/۰۸/۰۲ ۱۸:۳۸\nاز کارت ۶۰۳۷۹۹۷۴۳۸۲۰۶۶۸۳", "1,500,000", "1405/8/2-18:38"),
    ("blu-750k", "750,000 ریال\nزمان ۲۲:۰۶ جمعه، ۱ آبان ۱۴۰۵\nکارت مبدا ۶۲۱۹ ۸۶** **** ۰۷۸۳", "750,000", "1405/8/1-22:06"),
    (
        "mellat-hamrah",
        "مبلغ: 1,500,000 ریال\nکارمزد: 11,000 ریال\nتاریخ تراکنش: 1405/07/29\nزمان تراکنش: 15:35:15",
        "1,500,000",
        "1405/7/29-15:35",
    ),
    ("mellat-sms-lag-3min", "1,500,000 ریال\n1405/07/28 21:07:09\nشماره پیگیری 185889812785", "1,500,000", "1405/7/28-21:10"),
    ("wepod-toman", "مبلغ\n1,000,000 تومان\nحداکثر کارمزد: 1,100 تومان\nتاریخ و ساعت 1405/07/28 12:09:10", "10,000,000", "1405/7/28-12:09"),
    ("wepod-3m", "مبلغ\n3,000,000 ریال\nحداکثر کارمزد: 11,000 ریال\nتاریخ و ساعت 1405/07/26 21:53:21", "3,000,000", "1405/7/26-21:53"),
    ("melli-month-name", "پرداخت موفق\n1,500,000 ریال\nتاریخ ۲۶ مهر ۱۴۰۵، ساعت 17:25:52", "1,500,000", "1405/7/26-17:25"),
    ("blu-light", "1,500,000 ریال\nزمان ۱۷:۲۰ یکشنبه، ۲۶ مهر ۱۴۰۵", "1,500,000", "1405/7/26-17:20"),
    ("asan-12h-clock", "انتقال وجه کارت به کارت\nتاریخ 1405/07/26 03:44\nمبلغ 1,500,000 ریال", "1,500,000", "1405/7/26-15:44"),
    ("refah", "مبلغ 3,000,000 ریال\nتاریخ تراکنش 1405/7/25 - 15:54:27", "3,000,000", "1405/7/25-15:54"),
]


def _sms(amount: str, when: str, balance: str = "100,000,000") -> b.ParsedSms:
    return b.parse_sms(f"{ACCOUNT}\n{amount}+\n{when}\nمانده:{balance}")


def _candidate(text: str, sms: b.ParsedSms, pid: str = "p1") -> b.Candidate:
    facts = parse_receipt_text(text)
    assert facts.amount_rial is not None and facts.paid_at is not None
    return b.Candidate(pid, facts.amount_rial, sms.occurred_at - dt.timedelta(minutes=6), facts.paid_at)


@pytest.mark.parametrize(("name", "text", "amount", "when"), SAMPLES, ids=[s[0] for s in SAMPLES])
def test_every_real_receipt_is_paid_by_its_sms(name, text, amount, when):
    sms = _sms(amount, when)
    d = b.decide(sms, [_candidate(text, sms)])
    assert d.kind == "matched", (name, d)


def test_receipt_amounts_are_read_in_rial_even_when_printed_in_toman():
    assert parse_receipt_text(SAMPLES[5][1]).amount_rial == 10_000_000


def test_twelve_hour_clock_is_reported_and_can_be_switched_off():
    name, text, amount, when = SAMPLES[9]
    sms = _sms(amount, when)
    c = _candidate(text, sms)
    d = b.decide(sms, [c])
    assert d.reason == "unique_candidate_clock12h"
    off = b.decide(sms, [c], b.MatchSettings(accept_12h_clock=False))
    assert (off.kind, off.reason) == ("none", "no_candidate")


def test_twelve_hour_shift_never_overrides_amount_or_window():
    _, text, _, when = SAMPLES[9]
    sms = _sms("1,500,000", when)
    c = _candidate(text, sms)
    other_amount = b.Candidate("p2", 2_000_000, c.created_at, c.claimed_paid_at)
    assert b.decide(sms, [other_amount]).kind == "none"
    too_old = b.Candidate("p3", c.amount_rial, c.created_at - dt.timedelta(days=2), c.claimed_paid_at)
    assert b.decide(sms, [too_old]).kind == "none"


def test_wrong_time_that_is_not_a_half_day_away_is_still_rejected():
    sms = _sms("1,500,000", "1405/7/26-15:44")
    for hour_shift in (1, 3, 6, 9):
        claimed = sms.occurred_at - dt.timedelta(hours=hour_shift)
        c = b.Candidate("p", 1_500_000, sms.occurred_at - dt.timedelta(hours=10), claimed)
        assert b.decide(sms, [c]).kind == "none", hour_shift


def test_lag_beyond_the_new_tolerance_is_rejected():
    sms = _sms("1,500,000", "1405/7/28-21:10")
    c = b.Candidate("p", 1_500_000, sms.occurred_at - dt.timedelta(minutes=30), sms.occurred_at - dt.timedelta(minutes=9))
    assert b.decide(sms, [c]).kind == "none"


def test_two_equal_amounts_close_in_time_are_still_ambiguous():
    """Same amount, claimed times 2 min apart, SMS exactly between them: the tolerance must not invent a winner."""
    sms = _sms("1,500,000", "1405/7/26-17:21")
    created = sms.occurred_at - dt.timedelta(minutes=10)
    a = b.Candidate("a", 1_500_000, created, sms.occurred_at - dt.timedelta(minutes=1))
    c = b.Candidate("c", 1_500_000, created, sms.occurred_at + dt.timedelta(minutes=1))
    d = b.decide(sms, [a, c])
    assert d.kind == "ambiguous" and set(d.candidate_ids) == {"a", "c"}


def test_receipts_that_differ_only_by_the_half_day_stay_ambiguous():
    """15:44 and 03:44 both fit a 15:44 SMS: a human decides, Core never guesses with money."""
    sms = _sms("1,500,000", "1405/7/26-15:44")
    created = sms.occurred_at - dt.timedelta(minutes=10)
    direct = b.Candidate("direct", 1_500_000, created, sms.occurred_at)
    shifted = b.Candidate("shifted", 1_500_000, created, sms.occurred_at - dt.timedelta(hours=12))
    d = b.decide(sms, [direct, shifted])
    assert d.kind == "ambiguous" and set(d.candidate_ids) == {"direct", "shifted"}
