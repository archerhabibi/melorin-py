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
    assert m.dm_allowed("vpn_expired") and m.dm_allowed("panel_unhealthy") and m.dm_allowed("payment_succeeded") and m.dm_allowed(None)
    for kind in ("panel_recovered", "panel_down", "backup_succeeded", "backup_partial", "admin_reseller_application", "payment_approved"):
        assert not m.dm_allowed(kind), kind


# 2026-11-27: the admin's bot DM is for what is very important: something down or stuck, a customer who paid and got nothing, a
# customer's payment that needs the admin. Everything else is a topic of the supergroup.
DM_KINDS = {
    "panel_unhealthy",
    "node_failed",
    "panel_sell_blocked",
    "outbox_failure",
    "backup_failed",
    "provisioning_failed",
    "payment_succeeded",
    "payment_receipt_review",
    "payment_grace_credited",
    "payment_sms_ambiguous",
}
GROUP_ONLY_KINDS = [
    "panel_recovered",
    "panel_degraded",
    "panel_settings_drift",
    "panel_settings_fixed",
    "panel_capacity",
    "node_recovered",
    "payment_failed",
    "payment_approved",
    "payment_sms_matched",
    "payment_sms_confirmed",
    "payment_sms_balance_gap",
    "payment_provisional_blocked",
    "backup_succeeded",
    "backup_partial",
    "infra_disk",
    "admin_reseller_application",
    "admin_reseller_verified",
    "admin_reseller_auto_approved",
    "admin_reseller_identity_lost",
    "admin_manual_tasks",
    "admin_panel_admin_request",
]


def test_the_admin_dm_set_is_exactly_the_very_important_kinds():
    assert m.ADMIN_DM_KINDS == DM_KINDS
    for kind in DM_KINDS:
        assert m.admin_dm(kind), kind
        assert m.EVENT_CENTER in m.admin_route(kind).channels, kind  # mirrored: the group is the complete journal
    for kind in GROUP_ONLY_KINDS:
        assert not m.admin_dm(kind), kind
        assert m.admin_route(kind).channels == (m.EVENT_CENTER,), kind


def test_only_a_provisioning_failure_reaches_the_admin_for_a_reseller_stores_event():
    assert [k for k in DM_KINDS if m.admin_route(k).all_stores] == ["provisioning_failed"]


def test_a_longer_group_only_kind_is_never_swallowed_by_a_dm_prefix():
    # "payment_provisional_blocked" must not match the DM kind "payment_grace_credited" or any DM prefix.
    assert m.route_for("payment_provisional_blocked").channels == (m.EVENT_CENTER,)
    assert m.route_for("node_recovered").channels == (m.EVENT_CENTER,)
    assert m.route_for("backup_partial").channels == (m.EVENT_CENTER,) and m.route_for("backup_failed").channels == (m.DM, m.EVENT_CENTER)
    assert m.route_for("payment_approved").channels == (m.EVENT_CENTER,)
    assert m.route_for("node_failed").channels == (m.DM, m.EVENT_CENTER)


def test_an_unknown_admin_kind_is_a_quiet_group_notice_and_personal_kinds_are_not_admin_dms():
    for kind in ("something_new", None, "vpn_expired", "payment"):
        r = m.admin_route(kind)
        assert r.channels == (m.EVENT_CENTER,) and r.topic == "admin" and not m.admin_dm(kind), kind


def test_every_topic_of_the_policy_exists_in_the_event_center():
    from melorin.modules.eventcenter.topics import ADMIN_ONLY_TOPICS, TOPICS

    used = {r.topic for r in m._ROUTES.values() if r.topic} | {m._ADMIN_DEFAULT.topic}
    assert used <= set(TOPICS)
    # panel / node / admin-desk notices are platform-level: they must not be routed to a topic a reseller's group has
    assert {m.route_for(k).topic for k in ("panel_unhealthy", "node_failed", "admin_manual_tasks")} <= ADMIN_ONLY_TOPICS
