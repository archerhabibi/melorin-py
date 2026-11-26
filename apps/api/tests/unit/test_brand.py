"""ADR-R3: ``Melorin`` is the platform's name, never a store's. One validation of a store name; customer text uses the store's."""

from __future__ import annotations

import pytest

from melorin.core import brand
from melorin.core.errors import AppError


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Paris VPN", "Paris VPN"),
        ("  فروشگاه   پارس \n", "فروشگاه پارس"),
        ("multi\nline\tname", "multi line name"),
        ("نیم\u200cفاصله", "نیم\u200cفاصله"),  # ZWNJ is a format character, not a control character: Persian needs it
        ("Melorin", "Melorin"),  # a store MAY be called Melorin; it just is not assumed to be
    ],
)
def test_normalize_store_name_cleans_whitespace_and_keeps_persian(raw, expected):
    assert brand.normalize_store_name(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\t", "a\x00b", "x" * 201])
def test_normalize_store_name_refuses_empty_control_characters_and_overlong_names(raw):
    with pytest.raises(ValueError):
        brand.normalize_store_name(raw)


def test_normalize_store_name_allows_exactly_the_column_width():
    assert len(brand.normalize_store_name("x" * brand.STORE_NAME_MAX)) == brand.STORE_NAME_MAX


def test_the_default_main_store_name_is_neutral_and_valid():
    assert brand.DEFAULT_MAIN_STORE_NAME.casefold() != brand.PRODUCT_NAME.casefold()
    assert brand.normalize_store_name(brand.DEFAULT_MAIN_STORE_NAME) == brand.DEFAULT_MAIN_STORE_NAME


@pytest.mark.parametrize(
    "name, expected", [("Paris VPN", "Paris VPN"), ("  Paris   VPN ", "Paris VPN"), ("", "Melorin"), (None, "Melorin"), ("  ", "Melorin")]
)
def test_brand_or_product_uses_the_store_name_and_falls_back_only_when_there_is_none(name, expected):
    assert brand.brand_or_product(name) == expected


async def test_store_brand_without_a_store_is_the_product_name():
    assert await brand.store_brand(object(), None) == brand.PRODUCT_NAME


async def test_site_brand_never_raises_when_the_host_is_unknown(monkeypatch):
    """``site_channel`` refuses an unknown host in production; a mail subject must not turn that into an error."""
    from melorin.core import channel

    async def refuse(session, request, **kw):
        raise AppError("CHANNEL_UNKNOWN", "x", 403)

    monkeypatch.setattr(channel, "site_channel", refuse)
    assert await brand.site_brand(object(), object()) == brand.PRODUCT_NAME
