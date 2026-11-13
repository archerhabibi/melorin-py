from melorin.domain.notification_dedup import effective_key, notification_key


def test_key_is_event_recipient_channel():
    assert notification_key("e1", "u1", "telegram") == "ev:e1:u1:telegram"
    assert notification_key("e1", "u1", "telegram") != notification_key("e1", "u1", "email")
    assert notification_key("e1", "u1", "telegram") != notification_key("e1", "u2", "telegram")


def test_explicit_key_wins_and_no_event_means_no_key():
    assert effective_key({"dedup_key": "x", "_event_id": "e1"}, "u1", "telegram") == "x"
    assert effective_key({"_event_id": "e1"}, "u1", "telegram") == "ev:e1:u1:telegram"
    assert effective_key({}, "u1", "telegram") is None


def test_key_fits_the_column():
    assert len(notification_key("e" * 300, "u", "telegram")) == 200
