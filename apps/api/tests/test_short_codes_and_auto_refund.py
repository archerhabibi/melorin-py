"""Short 6-char codes + provisioning retry/auto-refund policy (migration 0014)."""

import asyncio
import re
from pathlib import Path

from _source import read_source

from melorin.core import codes, settings_store

ROOT = Path(__file__).parents[1]


class _FakeSession:
    def __init__(self, value: int):
        self.value = value

    async def scalar(self, _stmt):
        return self.value


def test_code_is_always_six_unambiguous_chars():
    pattern = re.compile(rf"^[{codes.ALPHABET}]{{6}}$")
    for n in (1, 2, 31, 32, 1023, 123456, codes._MAX_SEQ - 1, codes._MAX_SEQ, codes._MAX_SEQ + 5):
        code = asyncio.run(codes.next_code(_FakeSession(n), codes.ORDER_SEQ))
        assert pattern.match(code), code
        assert len(code) == codes.CODE_LEN == 6


def test_prefix_is_unique_per_sequence_value_before_wrap():
    prefixes = {asyncio.run(codes.next_code(_FakeSession(n), codes.ORDER_SEQ))[: codes.SEQ_WIDTH] for n in range(1, 2000)}
    assert len(prefixes) == 1999


def test_alphabet_has_no_ambiguous_symbols():
    assert len(codes.ALPHABET) == 32
    assert not set("01OIl") & set(codes.ALPHABET)


def test_provisioning_defaults_are_one_initial_plus_three_retries():
    assert settings_store.DEFAULTS["provisioning.max_attempts"] == 4
    assert settings_store.DEFAULTS["provisioning.backoff_seconds"] == [5, 7, 10]


def test_migration_0014_chains_from_0013_and_models_match():
    src = read_source(ROOT / "alembic" / "versions" / "0014_short_codes_and_auto_refund.py")
    assert 'down_revision = "0013_product_default_panel_group"' in src
    assert 'revision = "0014_short_codes"' in src
    # system_settings.id has no server default, the INSERT must provide it
    assert "gen_random_uuid()" in src

    from melorin.modules.orders.models import Order
    from melorin.modules.tickets.models import Ticket

    assert Order.__table__.c.number.type.length == 6
    assert Ticket.__table__.c.number.type.length == 6
    assert Ticket.__table__.c.number.nullable is False
