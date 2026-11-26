"""Mandatory channel membership: the pure rules (config validation, membership decision, public projection)."""

import pytest

from melorin.domain import channel_join as cj


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("@melorin_news", "@melorin_news"),
        ("melorin_news", "@melorin_news"),
        ("https://t.me/melorin_news", "@melorin_news"),
        ("t.me/melorin_news/", "@melorin_news"),
        ("telegram.me/melorin_news?start=1", "@melorin_news"),
        ("-1001234567890", "-1001234567890"),
        ("-۱۰۰۱۲۳۴۵۶۷۸۹۰", "-1001234567890"),  # Persian digits typed on a Persian keyboard
        (-1001234567890, "-1001234567890"),
    ],
)
def test_parse_chat_accepts_usernames_links_and_numeric_ids(raw, expected):
    assert cj.parse_chat(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "@abc", "@1abc_def", "https://t.me/+AbCdEfGh123", "t.me/joinchat/AbCdEfGh123", "12345", "@bad-name", None]
)
def test_parse_chat_refuses_what_cannot_identify_a_channel(raw):
    with pytest.raises(cj.ChannelJoinError):
        cj.parse_chat(raw)


def test_public_channel_gets_its_link_and_title_defaults_to_the_handle():
    cfg = cj.normalize({"enabled": True, "channels": [{"chat": "melorin_news"}]})
    assert cfg["channels"] == [{"chat": "@melorin_news", "title": "@melorin_news", "url": "https://t.me/melorin_news"}]
    assert cfg["message"] == cj.DEFAULT_MESSAGE and cfg["cache_seconds"] == 300


def test_private_channel_needs_an_invite_link():
    with pytest.raises(cj.ChannelJoinError, match="لینک دعوت"):
        cj.normalize({"channels": [{"chat": "-1001234567890"}]})
    cfg = cj.normalize({"channels": [{"chat": "-1001234567890", "title": "VIP", "url": "t.me/+AbCdEfGh123"}]})
    assert cfg["channels"][0] == {"chat": "-1001234567890", "title": "VIP", "url": "https://t.me/+AbCdEfGh123"}


@pytest.mark.parametrize(
    "raw,match",
    [
        ({"enabled": True, "channels": []}, "دست‌کم یک کانال"),
        ({"channels": [{"chat": "@melorin_news"}, {"chat": "@Melorin_News"}]}, "دو بار"),
        ({"channels": [{"chat": f"@channel_{i:02d}"} for i in range(cj.MAX_CHANNELS + 1)]}, "حداکثر"),
        ({"channels": [{"chat": "@melorin_news", "url": "https://evil.example/x"}]}, "t.me"),
        ({"enabled": "yes"}, "درست/نادرست"),
        ({"cache_seconds": 99999}, "ثانیه"),
        ({"cache_seconds": True}, "ثانیه"),
        ({"message": "x" * (cj.MAX_MESSAGE + 1)}, "حداکثر"),
        ({"channels": ["@melorin_news"]}, "شیء"),
    ],
)
def test_invalid_submissions_are_refused_with_a_persian_reason(raw, match):
    with pytest.raises(cj.ChannelJoinError, match=match):
        cj.normalize(raw)


def test_disabled_config_may_keep_its_channels_and_an_unreadable_row_reads_as_off():
    cfg = cj.normalize({"enabled": False, "channels": [{"chat": "@melorin_news"}]})
    assert cfg["enabled"] is False and len(cfg["channels"]) == 1
    assert cj.stored(None)["enabled"] is False
    assert cj.stored({"enabled": True, "channels": []}) == {**cj.DEFAULT, "channels": []}


@pytest.mark.parametrize(
    "member,joined",
    [
        ({"status": "creator"}, True),
        ({"status": "administrator"}, True),
        ({"status": "member"}, True),
        ({"status": "restricted", "is_member": True}, True),
        ({"status": "restricted", "is_member": False}, False),
        ({"status": "left"}, False),
        ({"status": "kicked"}, False),
        ({}, False),
    ],
)
def test_membership_rule(member, joined):
    assert cj.is_member(member) is joined


def test_fingerprint_follows_the_set_of_channels_not_titles_or_order():
    a = cj.normalize({"channels": [{"chat": "@alpha_news"}, {"chat": "@beta_news", "title": "B"}]})
    b = cj.normalize({"channels": [{"chat": "@beta_news"}, {"chat": "@alpha_news", "title": "A"}]})
    c = cj.normalize({"channels": [{"chat": "@alpha_news"}]})
    assert cj.fingerprint(a) == cj.fingerprint(b) != cj.fingerprint(c)


def test_public_projection_never_leaks_the_numeric_id():
    ch = cj.normalize_channel({"chat": "-1001234567890", "title": "VIP", "url": "https://t.me/+AbCdEfGh123"})
    assert cj.public_channel(ch) == {"title": "VIP", "url": "https://t.me/+AbCdEfGh123"}
