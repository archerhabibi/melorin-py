"""T-R10: the wallet projection of a purchase is computed once, in Core's domain, never in a channel."""

import pytest

from melorin.domain.pricing import project_wallet


@pytest.mark.parametrize(
    ("balance", "total", "sufficient", "after", "short"),
    [(350_000, 100_000, True, 250_000, 0), (100_000, 100_000, True, 0, 0), (30_000, 100_000, False, None, 70_000), (0, 1, False, None, 1)],
)
def test_projection(balance, total, sufficient, after, short):
    p = project_wallet(balance, total)
    assert (p.sufficient, p.balance_after, p.shortfall) == (sufficient, after, short)


def test_bots_never_subtract_amounts_themselves():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "telegram-main" / "tgmain" / "handlers" / "plans.py").read_text(encoding="utf-8")
    assert "balance - " not in src and "- balance" not in src
