"""Audit T02/T12 guard: adapter close and money formatting each have exactly one implementation."""

import pathlib
import re

import pytest

from melorin.core.fmt import format_amount, format_totals
from melorin.modules.vpn.adapters.lifecycle import close_adapter

ROOT = pathlib.Path(__file__).resolve().parents[1] / "melorin"


def test_no_private_close_or_money_copies():
    bad = []
    for p in ROOT.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if re.search(r"^(async )?def (_close|_close_adapter|_money)\(", text, re.M) and p.name != "web.py":
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, f"use adapters.lifecycle.close_adapter / core.fmt instead: {bad}"


def test_format_helpers():
    assert format_amount(1200000) == "1,200,000"
    assert format_amount(None, "IRT") == "0 IRT"
    assert format_totals([("IRT", 1200000), ("USD", 0), ("EUR", 5)]) == "1,200,000 IRT + 5 EUR"
    assert format_totals([]) == "۰"


class _Sync:
    closed = False

    def close(self):
        self.closed = True


class _Boom:
    async def close(self):
        raise RuntimeError("x")


async def test_close_adapter_variants():
    s = _Sync()
    await close_adapter(s)
    assert s.closed
    await close_adapter(object())  # no close() -> no-op
    await close_adapter(_Boom())  # swallowed by default
    with pytest.raises(RuntimeError):
        await close_adapter(_Boom(), strict=True)
