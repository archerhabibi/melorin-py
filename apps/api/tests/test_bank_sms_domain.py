"""Pure rules of card-to-card auto verification: SMS parsing, Jalali time and receipt <-> SMS matching."""

import datetime as dt

import pytest

from melorin.domain import bank_sms as b

SAMPLE = "302570009152325001\n1,500,000+\n1405/8/2-22:50\nمانده:107,923,032"
UTC = dt.timezone.utc


def _t(h, m, day=24):
    return dt.datetime(2026, 10, day, h, m, tzinfo=UTC)


def test_sample_mehr_iran_sms_is_parsed_exactly():
    p = b.parse_sms(SAMPLE)
    assert (p.direction, p.amount_rial, p.serial, p.balance_rial) == ("deposit", 1_500_000, "302570009152325001", 107_923_032)
    # 22:50 Tehran (UTC+3:30) on 1405/08/02 == 2026-10-24 19:20 UTC
    assert p.occurred_at == _t(19, 20)


def test_persian_digits_and_withdrawal_sign():
    p = b.parse_sms("۳۰۲۵۷۰۰۰۹۱۵۲۳۲۵۰۰۱\n۱,۵۰۰,۰۰۰-\n۱۴۰۵/۰۸/۰۲-۲۲:۵۰\nمانده:۱۰۶,۴۲۳,۰۳۲")
    assert p.direction == "withdrawal" and p.amount_rial == 1_500_000


def test_sign_before_amount_and_extra_lines():
    p = b.parse_sms("بانک مهر ایران\n+2,000,000\n302570009152325002\n1405/08/02-23:01\nمانده:5,000")
    assert p.direction == "deposit" and p.amount_rial == 2_000_000 and p.serial == "302570009152325002"


@pytest.mark.parametrize("bad", ["", "hello", "1,500,000+", "1405/8/2-22:50", "1405/13/2-22:50 1,000+"])
def test_unrecognizable_text_is_rejected(bad):
    with pytest.raises(b.SmsParseError):
        b.parse_sms(bad)


def test_unknown_bank_parser_is_rejected():
    with pytest.raises(b.SmsParseError):
        b.parse_sms(SAMPLE, bank="nope")


def test_jalali_conversion_known_dates():
    assert b.jalali_to_gregorian(1405, 1, 1) == dt.date(2026, 3, 21)
    assert b.jalali_to_gregorian(1405, 8, 2) == dt.date(2026, 10, 24)
    assert b.jalali_to_gregorian(1403, 12, 30) == dt.date(2025, 3, 20)  # leap year
    with pytest.raises(ValueError):
        b.jalali_to_gregorian(1404, 12, 30)  # 1404 is not leap
    with pytest.raises(ValueError):
        b.jalali_to_gregorian(1405, 7, 31)


def test_fingerprint_is_stable_across_retries_and_digit_shapes():
    a = b.parse_sms(SAMPLE)
    c = b.parse_sms(SAMPLE.replace("1", "۱"))
    assert a.fingerprint == c.fingerprint


def test_to_rial():
    assert b.to_rial(150_000, "IRT") == 1_500_000 and b.to_rial(1_500_000, "IRR") == 1_500_000 and b.to_rial(5, "USD") is None


def _cand(pid, amount=1_500_000, created=None, claimed=None):
    return b.Candidate(pid, amount, created or _t(19, 0), claimed)


def test_single_matching_receipt_is_matched():
    sms = b.parse_sms(SAMPLE)
    d = b.decide(sms, [_cand("p1", claimed=_t(19, 20)), _cand("p2", amount=2_000_000, claimed=_t(19, 20))])
    assert (d.kind, d.payment_id) == ("matched", "p1")


def test_claimed_time_must_agree_with_the_sms():
    sms = b.parse_sms(SAMPLE)
    assert b.decide(sms, [_cand("p1", claimed=_t(19, 40))]).kind == "none"
    assert b.decide(sms, [_cand("p1", claimed=_t(19, 21))]).kind == "matched"  # one-minute rounding tolerated


def test_claimed_time_is_required_by_default_but_can_be_relaxed():
    sms = b.parse_sms(SAMPLE)
    assert b.decide(sms, [_cand("p1")]).kind == "none"
    assert b.decide(sms, [_cand("p1")], b.MatchSettings(require_claimed_time=False)).kind == "matched"


def test_sms_before_request_or_outside_window_never_matches():
    sms = b.parse_sms(SAMPLE)
    assert b.decide(sms, [_cand("p1", created=_t(19, 30), claimed=_t(19, 20))]).kind == "none"  # SMS older than the request
    assert b.decide(sms, [_cand("p1", created=_t(1, 0), claimed=_t(19, 20))], b.MatchSettings(window_minutes=60)).kind == "none"


def test_two_identical_receipts_are_never_guessed():
    sms = b.parse_sms(SAMPLE)
    d = b.decide(sms, [_cand("p1", claimed=_t(19, 20)), _cand("p2", claimed=_t(19, 20))])
    assert d.kind == "ambiguous" and set(d.candidate_ids) == {"p1", "p2"}


def test_closest_claimed_time_breaks_a_tie_only_when_unique():
    sms = b.parse_sms(SAMPLE)
    d = b.decide(sms, [_cand("p1", claimed=_t(19, 20)), _cand("p2", claimed=_t(19, 22))])
    assert (d.kind, d.payment_id) == ("matched", "p1")


def test_withdrawals_and_large_amounts_are_never_auto_matched():
    out = b.parse_sms(SAMPLE.replace("+", "-"))
    assert b.decide(out, [_cand("p1", claimed=_t(19, 20))]).reason == "not_a_deposit"
    sms = b.parse_sms(SAMPLE)
    assert b.decide(sms, [_cand("p1", claimed=_t(19, 20))], b.MatchSettings(max_auto_amount_rial=1_000_000)).reason == "above_auto_limit"
