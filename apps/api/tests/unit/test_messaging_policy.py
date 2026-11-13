from melorin.domain import messaging_policy as m


def test_technical_alerts_never_reach_customers():
    for kind in ("provisioning_failed", "panel_down", "backup_failed", "infra_disk"):
        assert not m.allowed(kind, m.CUSTOMER, m.DM)
        assert m.route_for(kind).audience == m.ADMINS


def test_commercial_notices_stay_off_technical_topics_and_unknown_defaults_to_customer_dm():
    assert m.allowed("vpn_expired", m.CUSTOMER, m.DM)
    assert not m.allowed("vpn_expired", m.CUSTOMER, m.EVENT_CENTER)
    assert m.route_for("something_new") == m.route_for(None)
    assert m.route_for("something_new").family == m.COMMERCIAL


def test_longest_prefix_wins():
    assert m.route_for("vpn_near_expiry").severity == m.INFO
    assert m.route_for("store_volume_80").audience == m.STORE_OWNER


def test_dm_allowed_only_for_kinds_routed_to_dm():
    assert m.dm_allowed("vpn_expired") and m.dm_allowed("provisioning_failed") and m.dm_allowed(None)
    assert not m.dm_allowed("panel_down") and not m.dm_allowed("backup_failed") and not m.dm_allowed("outbox_failure")
