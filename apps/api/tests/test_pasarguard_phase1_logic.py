"""PasarGuard Phase 1 (PG-01 / PG-02 / PG-05 / PG-06): the pure decision logic, without a database or a network."""

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from melorin.domain.order_state import VpnStatus
from melorin.domain.panel_health import DEGRADED, HEALTHY, SELLABLE_STATES, UNHEALTHY
from melorin.modules.admin.panel_ops import allowed_actions
from melorin.modules.vpn import capabilities as caps
from melorin.modules.vpn import health, issues, notices, sync
from melorin.modules.vpn.adapters.base import Capabilities
from melorin.modules.vpn.adapters.pasarguard.capabilities import build_report

NOW = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.UTC)


def node(i, status, message=None):
    return {"id": i, "name": f"n{i}", "status": status, "message": message}


# ------------------------------------------------------------------------------------------------ PG-01 node health
def test_the_live_vps_case_is_degraded_not_healthy():
    """4 nodes failing with a self-signed certificate, 2 disabled, 1 connected (the evidence in the roadmap document)."""
    nodes = [node(i, "error", "CERTIFICATE_VERIFY_FAILED (self-signed)") for i in range(4)]
    nodes += [node(4, "disabled"), node(5, "disabled"), node(6, "connected")]
    summary = health.summarize(nodes)
    assert (summary.total, summary.connected, summary.disabled, summary.error) == (7, 1, 2, 4)
    state, reason = health.classify(summary)
    assert state == DEGRADED and "4 از 5" in reason
    assert state in SELLABLE_STATES  # customers can still be served by the one connected node
    assert summary.reasons[0]["hint"] and "server_ca" in summary.reasons[0]["hint"]


@pytest.mark.parametrize(
    ("nodes", "expected"),
    [
        ([], HEALTHY),  # no node data is not a verdict
        ([node(1, "connected"), node(2, "connected")], HEALTHY),
        ([node(1, "connected"), node(2, "disabled")], HEALTHY),  # a disabled node is the admin's choice
        ([node(1, "connected"), node(2, "error")], DEGRADED),
        ([node(1, "error"), node(2, "connecting")], UNHEALTHY),  # nobody can be served
        ([node(1, "disabled")], UNHEALTHY),
        ([node(1, "limited"), node(2, "unknown")], UNHEALTHY),
    ],
)
def test_classify(nodes, expected):
    assert health.classify(health.summarize(nodes))[0] == expected


def test_unhealthy_is_the_only_unsellable_state():
    assert UNHEALTHY not in SELLABLE_STATES and HEALTHY in SELLABLE_STATES and DEGRADED in SELLABLE_STATES


def test_reasons_are_capped_and_messages_truncated():
    summary = health.summarize([node(i, "error", "x" * 900) for i in range(health.MAX_REASONS + 15)])
    assert summary.error == health.MAX_REASONS + 15 and len(summary.reasons) == health.MAX_REASONS
    assert len(summary.reasons[0]["message"]) == 300


@pytest.mark.parametrize(
    ("message", "needle"),
    [
        ("CERTIFICATE_VERIFY_FAILED", "server_ca"),
        ("connection timed out", "پاسخ نمی‌دهد"),
        ("Connection refused", "پورت"),
        ("Name or service not known", "DNS"),
    ],
)
def test_node_error_hints(message, needle):
    assert needle in health.node_error_hint(message)


def test_unknown_or_empty_node_messages_have_no_hint():
    assert health.node_error_hint(None) is None and health.node_error_hint("weird failure") is None


# --------------------------------------------------------------------------------------------- PG-02 status mapping
@pytest.mark.parametrize(
    ("local", "remote", "expected"),
    [
        (VpnStatus.ACTIVE, "limited", VpnStatus.LIMITED),
        (VpnStatus.ACTIVE, "expired", VpnStatus.EXPIRED),
        (VpnStatus.ACTIVE, "disabled", VpnStatus.SUSPENDED),
        (VpnStatus.SUSPENDED, "active", VpnStatus.ACTIVE),  # re-enabled from the panel side
        (VpnStatus.LIMITED, "active", VpnStatus.ACTIVE),  # traffic reset on the panel
        (VpnStatus.ACTIVE, "on_hold", VpnStatus.ACTIVE),  # waiting for the first connection is usable
        (VpnStatus.ACTIVE, "something_new", VpnStatus.ACTIVE),  # an unknown panel value never changes anything
    ],
)
def test_status_from_remote(local, remote, expected):
    assert sync.status_from_remote(local, NS(remote_status=remote)) == expected


@pytest.mark.parametrize("local", [VpnStatus.PENDING, VpnStatus.REVOKED, VpnStatus.ARCHIVED])
def test_melorin_only_states_are_never_overwritten_by_the_panel(local):
    assert sync.status_from_remote(local, NS(remote_status="active")) == local


def test_freshness_window():
    account = NS(last_synced_at=NOW - dt.timedelta(minutes=29))
    assert sync.is_fresh(account, NOW)
    assert not sync.is_fresh(NS(last_synced_at=NOW - dt.timedelta(minutes=31)), NOW)
    assert not sync.is_fresh(NS(last_synced_at=None), NOW)


def account(**kw):
    base = {
        "last_synced_at": NOW,
        "sold_expires_at": NOW + dt.timedelta(days=30),
        "sold_traffic_bytes": 10 * 2**30,
    }
    return NS(**{**base, **kw})


def remote(**kw):
    base = {"expire_at": NOW + dt.timedelta(days=30), "traffic_limit_bytes": 10 * 2**30}
    return NS(**{**base, **kw})


def test_no_drift_when_the_panel_matches():
    assert sync.limits_drift(account(), remote()) is None
    assert sync.limits_drift(account(), remote(expire_at=NOW + dt.timedelta(days=30, minutes=20))) is None  # clock noise


def test_manual_panel_edits_are_detected():
    drift = sync.limits_drift(account(), remote(expire_at=NOW + dt.timedelta(days=60), traffic_limit_bytes=2**30))
    assert set(drift) == {"expires_at", "traffic_limit_bytes"}


def test_drift_needs_a_baseline_and_ignores_on_hold():
    assert sync.limits_drift(account(last_synced_at=None), remote(traffic_limit_bytes=1)) is None
    assert sync.limits_drift(account(), remote(remote_status="on_hold", expire_at=None)) is None


# ------------------------------------------------------------------------------------------ PG-06 notices (regression)
def test_a_renewal_starts_a_new_notice_period():
    """purchase -> near expiry -> notice -> renewal -> near expiry again -> a SECOND notice must be possible."""
    acc = NS(near_expiry_notified=True, traffic_notified_level=90, expires_at=NOW + dt.timedelta(days=2))
    before = notices.period_token(acc)
    notices.reset_for_renewal(acc)
    assert acc.near_expiry_notified is False and acc.traffic_notified_level == 0
    acc.sold_expires_at = NOW + dt.timedelta(days=32)
    assert notices.period_token(acc) != before


def test_period_token_ignores_second_level_drift_and_handles_open_accounts():
    a = NS(sold_expires_at=NOW)
    b = NS(sold_expires_at=NOW + dt.timedelta(seconds=40))
    assert notices.period_token(a) == notices.period_token(b)
    assert notices.period_token(NS(sold_expires_at=None)) == "open"
    assert notices.period_token(NS(sold_expires_at=NOW.replace(tzinfo=None))) == notices.period_token(a)


@pytest.mark.parametrize(
    ("used", "limit", "percent", "level"),
    [(0, 100, 0, 0), (79, 100, 79, 0), (80, 100, 80, 80), (89, 100, 89, 80), (90, 100, 90, 90), (150, 100, 150, 90), (5, 0, None, 0)],
)
def test_traffic_levels(used, limit, percent, level):
    assert notices.percent_of(limit, used) == percent  # R4: from two numbers just read from the panel, never from a stored copy
    assert notices.traffic_level(percent) == level


# -------------------------------------------------------------------------------------------- issues (admin actions)
def test_closed_issues_allow_no_action():
    assert allowed_actions(issues.MISSING, "resolved") == []


def test_actions_depend_on_the_issue_kind():
    assert "archive_account" in allowed_actions(issues.MISSING, issues.OPEN)
    assert "fix_owner" in allowed_actions(issues.OWNER_MISMATCH, issues.OPEN)
    other = allowed_actions(issues.LIMITS_MISMATCH, issues.OPEN)
    assert "fix_owner" not in other and "archive_account" not in other
    assert {"resync", "resolve", "ignore"} <= set(other)


# ------------------------------------------------------------------------------------------ PG-05 permission probe
def panel(report=None, kind="pasarguard"):
    stored = report.to_dict() if report else None
    return NS(kind=kind, capabilities=stored, capabilities_checked_at=NOW if stored else None, base_url="https://p.example.com", config={})


FULL = Capabilities(node_ops=True, account_listing=True, bulk_ops=True, admin_ops=True)
SERVICE_ROLE = {
    "users": {"read": 2, "update": 2, "set_owner": 2},
    "nodes": {"read": True},
    "settings": {"read": True},
    "admins": {"read": True, "create": True, "update": True},
}
OPERATOR_ROLE = {"users": {"read": 1, "update": 1, "set_owner": 0}, "nodes": {}, "admins": {}}


def test_owner_credential_is_flagged_as_the_highest_privilege():
    review = caps.access_review(panel(build_report(FULL, role="owner", is_owner=True, permissions=None)))
    assert review["level"] == "owner"
    assert [w["code"] for w in review["warnings"]] == ["owner_credential"]


def test_a_service_role_is_least_privilege_with_no_warnings():
    review = caps.access_review(panel(build_report(FULL, role="melorin-service", is_owner=False, permissions=SERVICE_ROLE)))
    assert review == {"level": "least_privilege", "role": "melorin-service", "warnings": []}


def test_an_operator_role_reports_what_phase1_loses():
    review = caps.access_review(panel(build_report(FULL, role="operator", is_owner=False, permissions=OPERATOR_ROLE)))
    codes = {w["code"] for w in review["warnings"]}
    assert review["level"] == "limited"
    assert {"missing_node_ops", "missing_bulk_ops", "missing_admin_ops", "own_users_only"} <= codes
    node_warning = next(w for w in review["warnings"] if w["code"] == "missing_node_ops")
    assert node_warning["permissions"] == ["nodes.read"]


def test_an_unprobed_panel_is_unknown_not_clean():
    review = caps.access_review(panel(None))
    assert review["level"] == "unknown" and review["warnings"][0]["code"] == "unverified"


def test_other_panel_kinds_are_not_reviewed():
    assert caps.access_review(panel(None, kind="sanaei")) == {"level": "not_applicable", "role": None, "warnings": []}
