"""M7.6: HTTP latency/error metrics, business gauges from the database, and the alert rules that use them."""

import datetime as dt
import re
from pathlib import Path

import pytest
import yaml

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core import business_metrics, metrics
from melorin.core.middleware import route_label
from melorin.modules.payments.models import Payment
from melorin.modules.stores.models import Store
from melorin.modules.system.models import BackupRun

ROOT = Path(__file__).resolve().parents[3]
NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


# ---- metrics.py -----------------------------------------------------------------------------------------


def test_render_declares_types_and_escapes_label_values():
    metrics.inc("melorin_demo_total", path='/a"b\\c')
    metrics.set_gauge("melorin_demo_gauge", 2.5, kind="x")
    text = metrics.render()
    assert "# TYPE melorin_demo_total counter" in text
    assert "# TYPE melorin_demo_gauge gauge" in text
    assert 'melorin_demo_total{path="/a\\"b\\\\c"} 1' in text
    assert 'melorin_demo_gauge{kind="x"} 2.5' in text


def test_histogram_buckets_are_cumulative_with_sum_and_count():
    metrics.observe("melorin_demo_seconds", 0.03, buckets=(0.05, 1.0), path="/p")
    metrics.observe("melorin_demo_seconds", 0.5, buckets=(0.05, 1.0), path="/p")
    metrics.observe("melorin_demo_seconds", 3.0, buckets=(0.05, 1.0), path="/p")
    text = metrics.render()
    assert "# TYPE melorin_demo_seconds histogram" in text
    assert 'melorin_demo_seconds_bucket{path="/p",le="0.05"} 1' in text
    assert 'melorin_demo_seconds_bucket{path="/p",le="1.0"} 2' in text
    assert 'melorin_demo_seconds_bucket{path="/p",le="+Inf"} 3' in text
    assert 'melorin_demo_seconds_count{path="/p"} 3' in text
    assert 'melorin_demo_seconds_sum{path="/p"} 3.53' in text


def test_alert_state_changes_and_is_rendered_once_per_alert():
    metrics.set_alert("MelorinDemo", True, summary="s", severity="critical")
    first = metrics.alert_snapshot()["MelorinDemo"]["changed_at"]
    metrics.set_alert("MelorinDemo", True, summary="s", severity="critical")
    assert metrics.alert_snapshot()["MelorinDemo"]["changed_at"] == first  # unchanged state keeps its timestamp
    metrics.set_alert("MelorinDemo", False, summary="s")
    assert metrics.alert_snapshot()["MelorinDemo"]["state"] == "resolved"
    assert metrics.render().count('melorin_alert{alertname="MelorinDemo"') == 1


def test_route_label_cardinality_is_bounded():
    assert route_label("/api/v1/orders/123") == "/api/v1/*"
    assert route_label("/health") == "/health"
    assert route_label("/wp-admin/setup.php") == "other"
    assert route_label("/random-" + "x" * 50) == "other"


# ---- business metrics (database) ----------------------------------------------------------------------


def _payment(store, user, status, created=NOW):
    return Payment(
        user_id=user.id,
        store_id=store.id,
        purpose="wallet_topup",
        provider="zarinpal",
        amount=1,
        currency="IRT",
        status=status,
        created_at=created,
    )


async def test_payment_failure_ratio_needs_a_meaningful_sample():
    async with open_session() as s:
        store, user = await make_store(s), await make_user(s)
        s.add_all([_payment(store, user, "failed") for _ in range(3)])
        s.add(_payment(store, user, "failed", created=NOW - dt.timedelta(hours=3)))  # outside the 15 min window
        await s.flush()
        values = await business_metrics.collect(s, NOW)
        assert values["melorin_payments_recent_total"] == 3 and values["melorin_payments_recent_failure_ratio"] == 1.0
        assert metrics.alert_snapshot()["MelorinPaymentFailureRateHigh"]["state"] == "resolved"  # only 3 samples
        s.add_all([_payment(store, user, "failed") for _ in range(3)] + [_payment(store, user, "succeeded")])
        await s.flush()
        await business_metrics.collect(s, NOW)
        assert metrics.alert_snapshot()["MelorinPaymentFailureRateHigh"]["state"] == "firing"


async def test_provisioning_failures_and_review_queue_are_counted():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        ok = await make_order(s, user=user, store=store, product=product, status="active")
        bad = await make_order(s, user=user, store=store, product=product, status="provisioning_failed")
        bad.needs_review = True
        await s.flush()
        values = await business_metrics.collect(s, dt.datetime.now(dt.UTC))
        assert ok and values["melorin_orders_provisioning_failed_recent"] == 1.0
        assert values["melorin_orders_needs_review"] == 1.0
        assert metrics.alert_snapshot()["MelorinProvisioningFailures"]["state"] == "firing"


async def test_unhealthy_reseller_bots_are_detected():
    async with open_session() as s:
        owner = await make_user(s)
        healthy = await make_store(s, kind="reseller", owner=owner)
        broken = await make_store(s, kind="reseller", owner=owner)
        silent = await make_store(s, kind="reseller", owner=owner)
        main = await make_store(s)
        for st, state, seen in (
            (healthy, "running", NOW - dt.timedelta(seconds=20)),
            (broken, "error", NOW),
            (silent, "running", NOW - dt.timedelta(hours=2)),  # heartbeat went stale -> offline
        ):
            st.bot_token_enc, st.bot_enabled, st.bot_status, st.bot_seen_at = "enc", True, state, seen
        main.bot_token_enc, main.bot_status = "enc", "error"  # main store is not a reseller bot
        await s.flush()
        values = await business_metrics.collect(s, NOW)
        assert values["melorin_reseller_bots_unhealthy"] == 2.0
        assert metrics.alert_snapshot()["MelorinResellerBotUnhealthy"]["state"] == "firing"
        assert isinstance(healthy, Store)


async def test_backup_age_alert_fires_when_missing_or_old_and_clears_after_a_fresh_run():
    async with open_session() as s:
        values = await business_metrics.collect(s, NOW)
        assert values["melorin_backup_age_seconds"] >= 10**9
        assert metrics.alert_snapshot()["MelorinBackupStale"]["state"] == "firing"
        s.add(BackupRun(status="succeeded", created_at=NOW - dt.timedelta(hours=40)))
        s.add(BackupRun(status="failed", created_at=NOW - dt.timedelta(minutes=5)))  # failures do not count
        await s.flush()
        await business_metrics.collect(s, NOW)
        assert metrics.alert_snapshot()["MelorinBackupStale"]["state"] == "firing"
        s.add(BackupRun(status="succeeded", created_at=NOW - dt.timedelta(hours=2)))
        await s.flush()
        values = await business_metrics.collect(s, NOW)
        assert values["melorin_backup_age_seconds"] == 7200.0
        assert metrics.alert_snapshot()["MelorinBackupStale"]["state"] == "resolved"


# ---- alert rule contract -----------------------------------------------------------------------------


def _alert_rules():
    data = yaml.safe_load((ROOT / "infra" / "alerts.yml").read_text())
    return [r for g in data["groups"] for r in g["rules"]]


def _emitted_metric_names() -> set[str]:
    names: set[str] = {"melorin_alert"}
    for path in (ROOT / "apps" / "api" / "melorin").rglob("*.py"):
        src = path.read_text()
        names |= set(re.findall(r'(?:inc|observe|set_gauge)\(\s*"(melorin_[a-z_]+)"', src))
        if path.name == "business_metrics.py":
            names |= set(re.findall(r'"(melorin_[a-z_]+)"', src))
    return names


def test_every_alert_expression_only_uses_metrics_the_code_emits():
    emitted = _emitted_metric_names()
    for rule in _alert_rules():
        used = {re.sub(r"_(bucket|sum|count)$", "", m) for m in re.findall(r"melorin_[a-z_]+", rule["expr"])}
        assert used <= emitted, f"{rule['alert']} uses unknown metrics: {used - emitted}"


def test_m76_alert_rules_exist_with_severity_and_summary():
    rules = {r["alert"]: r for r in _alert_rules()}
    for name in (
        "MelorinHttpErrorRateHigh",
        "MelorinHttpLatencyHigh",
        "MelorinPaymentFailureRateHigh",
        "MelorinProvisioningFailures",
        "MelorinResellerBotUnhealthy",
        "MelorinBackupStale",
    ):
        assert name in rules, name
        assert rules[name]["labels"]["severity"] in {"warning", "critical"}
        assert rules[name]["annotations"]["summary"]
    assert len(rules) >= 11
