"""Telegram button styling: validation, specificity of the matcher, reply-keyboard safety and the Bot API field names."""

from __future__ import annotations

import pytest

from melorin.domain import button_style as bs


def rule(**kw):
    base = {"kind": "inline", "match": "exact", "key": "menu:plans", "style": "success"}
    return {**base, **kw}


def cfg(*rules, enabled=True):
    return bs.normalize({"enabled": enabled, "rules": list(rules)})


def test_normalize_accepts_colours_digits_and_trims():
    out = cfg(rule(style="SUCCESS", icon=" ۵۰۰۰۰۰۰۱ ", prefix="💎 "))
    r = out["rules"][0]
    assert (r["style"], r["icon"], r["prefix"]) == ("success", "50000001", "💎 ")


@pytest.mark.parametrize(
    "bad",
    [
        rule(style="purple"),
        rule(icon="abc"),
        rule(icon="123"),
        rule(prefix="1234567"),
        rule(prefix="a\nb"),
        rule(key=""),
        rule(key="https://example.com/x"),
        rule(kind="weird"),
        rule(match="regex"),
        rule(style=None),  # nothing to apply
        rule(key=bs.URL_KEY, match="prefix"),
    ],
)
def test_invalid_rules_are_refused_in_persian(bad):
    with pytest.raises(bs.ButtonStyleError) as e:
        cfg(bad)
    assert "قانون 1" in str(e.value)


def test_duplicate_rule_and_rule_limit():
    with pytest.raises(bs.ButtonStyleError):
        cfg(rule(), rule(style="danger"))
    many = [rule(key=f"k{i}:", match="prefix") for i in range(bs.MAX_RULES + 1)]
    with pytest.raises(bs.ButtonStyleError):
        bs.normalize({"enabled": True, "rules": many})


def test_reply_rules_ignore_decoration_and_match_exactly():
    out = cfg({"kind": "reply", "key": "🛒 خرید اکانت", "match": "prefix", "style": "primary", "prefix": "X", "suffix": "Y"})
    r = out["rules"][0]
    assert (r["match"], r["prefix"], r["suffix"]) == ("exact", "", "")


def test_exact_beats_prefix_and_longer_prefix_beats_shorter():
    proj = bs.public_projection(
        cfg(
            rule(key="menu:", match="prefix", style="primary"),
            rule(key="menu:plans", style="success"),
            rule(key="menu:wa", match="prefix", style="danger"),
        )
    )
    assert bs.apply_inline(proj, "menu:plans", "t")["style"] == "success"
    assert bs.apply_inline(proj, "menu:wallet", "t")["style"] == "danger"
    assert bs.apply_inline(proj, "menu:orders", "t")["style"] == "primary"
    assert bs.apply_inline(proj, "other:1", "t") == {"text": "t"}


def test_disabled_config_and_disabled_rule_change_nothing():
    assert bs.public_projection(cfg(rule(), enabled=False)) == {"enabled": False, "inline": [], "reply": []}
    proj = bs.public_projection(cfg(rule(enabled=False)))
    assert bs.apply_inline(proj, "menu:plans", "t") == {"text": "t"}


def test_inline_gets_style_icon_and_decoration_with_real_bot_api_field_names():
    proj = bs.public_projection(cfg(rule(icon="5368324170671202286", prefix="💎 ", suffix=" ✨")))
    assert bs.apply_inline(proj, "menu:plans", "خرید") == {
        "text": "💎 خرید ✨",
        "style": "success",
        "icon_custom_emoji_id": "5368324170671202286",
    }


def test_decoration_never_pushes_a_label_past_the_limit():
    proj = bs.public_projection(cfg(rule(prefix="💎💎 ")))
    long = "x" * bs.MAX_BUTTON_TEXT
    assert bs.apply_inline(proj, "menu:plans", long)["text"] == long


def test_reply_keyboard_text_is_never_changed():
    proj = bs.public_projection(cfg({"kind": "reply", "key": "🛒 خرید اکانت", "style": "success", "icon": "12345678"}))
    assert bs.apply_reply(proj, "🛒 خرید اکانت") == {"text": "🛒 خرید اکانت", "style": "success", "icon_custom_emoji_id": "12345678"}
    assert bs.apply_reply(proj, "🎧 پشتیبانی") == {"text": "🎧 پشتیبانی"}


def test_url_buttons_are_styled_through_the_pseudo_key():
    proj = bs.public_projection(cfg(rule(key=bs.URL_KEY, style="primary")))
    assert bs.apply_inline(proj, bs.URL_KEY, "🌐 حساب من در سایت")["style"] == "primary"


def test_strip_styling_removes_only_the_new_fields():
    markup = {"inline_keyboard": [[{"text": "a", "callback_data": "x", "style": "danger", "icon_custom_emoji_id": "1"}]]}
    assert bs.strip_styling(markup) == {"inline_keyboard": [[{"text": "a", "callback_data": "x"}]]}
    assert bs.strip_styling(None) is None
    assert "style" in markup["inline_keyboard"][0][0]  # the original is untouched


def test_stored_tolerates_garbage():
    assert bs.stored(None) == bs.default_config()
    assert bs.stored({"enabled": True, "rules": [{"key": "x", "style": "pink"}]}) == bs.default_config()


def test_every_preset_and_catalog_key_is_valid():
    for preset in bs.PRESETS:
        assert bs.normalize({"enabled": True, "rules": preset["rules"]})["rules"], preset["id"]
    for item in bs.CATALOG:
        bs.normalize_rule({**item, "style": "primary"}, 0)


def test_sample_markups_use_the_configuration():
    inline, reply = bs.sample_markups(cfg(rule(key="menu:plans", style="success")))
    first = inline["inline_keyboard"][0][0]
    assert first["style"] == "success" and first["callback_data"] == "noop:preview"
    assert reply["keyboard"][0][0]["text"] == "🛒 خرید اکانت"
