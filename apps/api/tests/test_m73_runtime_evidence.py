"""M7.3: the runtime evidence collector must be fail-closed - skipped is never passed, secrets never leak,
and every probe verifies the behaviour it claims to (Telegram, Zarinpal sandbox, panels, TLS gate, alert delivery)."""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "runtime_evidence.py"
spec = importlib.util.spec_from_file_location("runtime_evidence", SCRIPT)
ev = importlib.util.module_from_spec(spec)
sys.modules["runtime_evidence"] = ev
spec.loader.exec_module(ev)

TOKEN = "123456789:AAH-secret_token_value_0123456789abc"  # pragma: allowlist secret


def make_ctx(tmp_path, env=None, handler=None, **kw):
    transport = httpx.MockTransport(handler or (lambda req: httpx.Response(404)))

    async def no_sleep(_):
        return None

    return ev.Context(
        env=env or {},
        evidence_dir=tmp_path,
        http=lambda: httpx.AsyncClient(transport=transport, follow_redirects=False),
        run=kw.pop("run", lambda cmd, **k: (0, "ok")),
        which=kw.pop("which", lambda name: None),
        sleep=no_sleep,
        **kw,
    )


async def run(ctx, *names):
    return {r.name: r for r in await ev.run_checks(ctx, list(names) or None)}


# ------------------------------------------------------------ fail-closed contract


async def test_every_check_is_skipped_not_passed_when_nothing_is_configured(tmp_path):
    results = await ev.run_checks(make_ctx(tmp_path))
    assert {r.name for r in results} == set(ev.CHECKS)
    assert all(r.status == ev.SKIPPED and r.reason for r in results)
    assert ev.exit_code(results) == 3
    assert ev.exit_code(results, allow_skip=True) == 0


def test_exit_codes_prefer_failure_over_skip():
    ok, sk, bad = ev.Result("a", ev.PASSED), ev.Result("b", ev.SKIPPED), ev.Result("c", ev.FAILED)
    assert ev.exit_code([ok]) == 0
    assert ev.exit_code([ok, sk]) == 3
    assert ev.exit_code([ok, sk, bad]) == 1
    assert ev.exit_code([ok, bad], allow_skip=True) == 1


async def test_a_crashing_check_is_reported_as_failed(tmp_path, monkeypatch):
    async def boom(ctx):
        raise RuntimeError("kaput")

    monkeypatch.setitem(ev.CHECKS, "telegram_main", boom)
    res = (await run(make_ctx(tmp_path), "telegram_main"))["telegram_main"]
    assert res.status == ev.FAILED and "kaput" in res.reason


async def test_secrets_never_reach_results_or_the_bundle(tmp_path):
    def handler(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")  # httpx embeds the bot token in the URL

    ctx = make_ctx(tmp_path, env={"MELORIN_TELEGRAM_TOKEN": TOKEN}, handler=handler)
    results = await ev.run_checks(ctx, ["telegram_main"])
    ev.write_bundle(results, tmp_path, commit="abc")
    blob = (tmp_path / "summary.json").read_text() + (tmp_path / "summary.md").read_text()
    assert TOKEN not in blob and "AAH-secret" not in blob
    assert results[0].status == ev.FAILED


def test_redactor_masks_secret_env_values_and_bot_token_shapes():
    r = ev.Redactor({"MELORIN_PANEL_PASSWORD": "hunter2hunter2", "HOME": "/root"})
    assert r("login hunter2hunter2 ok") == "login *** ok"
    assert r(f"https://api.telegram.org/bot{TOKEN}/getMe") == "https://api.telegram.org/bot***/getMe"
    assert r.deep({"a": ["hunter2hunter2", 1], "b": {"c": "/root"}}) == {"a": ["***", 1], "b": {"c": "/root"}}


def test_bundle_contains_commit_and_one_row_per_check(tmp_path):
    ev.write_bundle([ev.Result("x", ev.PASSED), ev.Result("y", ev.SKIPPED, "no creds")], tmp_path, commit="deadbeef")
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["git_commit"] == "deadbeef" and [r["name"] for r in data["results"]] == ["x", "y"]
    assert "| y | skipped | no creds |" in (tmp_path / "summary.md").read_text()


def test_cli_lists_checks_and_rejects_unknown_names(capsys):
    assert ev.main(["--list"]) == 0
    assert "alert_delivery" in capsys.readouterr().out
    assert ev.main(["--only", "nope"]) == 2


# ------------------------------------------------------------------ Telegram


def telegram_handler(*, is_bot=True, webhook=""):
    def handler(req):
        if req.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 7, "is_bot": is_bot, "username": "melorin_bot"}})
        return httpx.Response(200, json={"ok": True, "result": {"url": webhook}})

    return handler


async def test_telegram_passes_for_a_bot_without_a_webhook(tmp_path):
    ctx = make_ctx(tmp_path, env={"MELORIN_TELEGRAM_TOKEN": TOKEN}, handler=telegram_handler())
    res = (await run(ctx, "telegram_main"))["telegram_main"]
    assert res.status == ev.PASSED and res.details["bot_username"] == "melorin_bot"


async def test_telegram_fails_when_a_webhook_would_break_long_polling(tmp_path):
    ctx = make_ctx(tmp_path, env={"MELORIN_TELEGRAM_TOKEN": TOKEN}, handler=telegram_handler(webhook="https://x.example/hook"))
    assert (await run(ctx, "telegram_main"))["telegram_main"].status == ev.FAILED


async def test_telegram_fails_for_a_non_bot_account_and_reseller_uses_its_own_variable(tmp_path):
    ctx = make_ctx(tmp_path, env={"MELORIN_TELEGRAM_TOKEN": TOKEN}, handler=telegram_handler(is_bot=False))
    assert (await run(ctx, "telegram_main"))["telegram_main"].status == ev.FAILED
    only_main = make_ctx(tmp_path, env={"MELORIN_TELEGRAM_TOKEN": TOKEN}, handler=telegram_handler())
    assert (await run(only_main, "telegram_reseller"))["telegram_reseller"].status == ev.SKIPPED
    both = make_ctx(tmp_path, env={"MELORIN_TELEGRAM_RESELLER_BOT_TOKEN": TOKEN}, handler=telegram_handler())
    assert (await run(both, "telegram_reseller"))["telegram_reseller"].status == ev.PASSED


# ------------------------------------------------------------ Zarinpal sandbox


@pytest.fixture
def zarinpal_gateway(monkeypatch):
    from melorin.modules.payments.adapters import zarinpal

    real = httpx.AsyncClient

    def install(*, verify_code=-54, forged_ok=False):
        def handler(req):
            body = json.loads(req.content)
            if req.url.path.endswith("request.json"):
                return httpx.Response(200, json={"data": {"code": 100, "authority": "S" + "0" * 34 + "1"}})
            return httpx.Response(200, json={"data": {"code": 100 if forged_ok else verify_code}})

        monkeypatch.setattr(zarinpal.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    return install


async def test_zarinpal_sandbox_passes_when_unpaid_and_forged_authorities_do_not_verify(tmp_path, zarinpal_gateway):
    zarinpal_gateway()
    ctx = make_ctx(tmp_path, env={"MELORIN_ZARINPAL_SANDBOX_MERCHANT": "11111111-2222-3333-4444-555555555555"})
    res = (await run(ctx, "zarinpal_sandbox"))["zarinpal_sandbox"]
    assert res.status == ev.PASSED and res.details["unpaid_verify_code"] == -54


async def test_zarinpal_sandbox_fails_if_an_unpaid_authority_verifies_as_paid(tmp_path, zarinpal_gateway):
    zarinpal_gateway(verify_code=100)
    ctx = make_ctx(tmp_path, env={"MELORIN_ZARINPAL_SANDBOX_MERCHANT": "11111111-2222-3333-4444-555555555555"})
    res = (await run(ctx, "zarinpal_sandbox"))["zarinpal_sandbox"]
    assert res.status == ev.FAILED and "unpaid" in res.reason


# --------------------------------------------------------------------- panels


class FakeAdapter:
    def __init__(self, *, healthy=True, leaves_account=False):
        self.healthy, self.leaves_account, self.accounts, self.log = healthy, leaves_account, {}, []

    async def health_check(self):
        return self.healthy

    async def create_account(self, spec):
        from melorin.modules.vpn.adapters.base import PanelAccount

        self.accounts[spec.username] = spec
        self.log.append("create")
        return PanelAccount("1", spec.username, "active", spec.expire_at, spec.traffic_bytes, 0, "https://sub/x")

    async def get_account(self, username):
        from melorin.modules.vpn.adapters.base import PanelAccount

        s = self.accounts.get(username)
        return PanelAccount("1", username, "active", None, 0, 0) if s else None

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        self.log.append("extend")

    async def suspend_account(self, username):
        self.log.append("suspend")

    async def resume_account(self, username):
        self.log.append("resume")

    async def revoke_account(self, username):
        self.log.append("revoke")
        if not self.leaves_account:
            self.accounts.pop(username, None)

    async def close(self):
        self.log.append("close")


def panels_file(tmp_path, *names):
    path = tmp_path / "panels.json"
    path.write_text(json.dumps([{"name": n, "kind": "mock", "base_url": "https://p"} for n in names]))
    return {"MELORIN_EVIDENCE_PANELS": str(path)}


async def test_panel_roundtrip_requires_explicit_permission_to_mutate(tmp_path):
    ctx = make_ctx(tmp_path, env=panels_file(tmp_path, "p1"), adapter_factory=lambda cfg: FakeAdapter())
    res = (await run(ctx, "panel_roundtrip"))["panel_roundtrip"]
    assert res.status == ev.SKIPPED and "--allow-mutation" in res.reason


async def test_panel_roundtrip_passes_and_cleans_up_its_throwaway_account(tmp_path):
    adapters = []

    def factory(cfg):
        adapters.append(FakeAdapter())
        return adapters[-1]

    ctx = make_ctx(tmp_path, env=panels_file(tmp_path, "p1", "p2"), adapter_factory=factory, allow_mutation=True)
    res = (await run(ctx, "panel_roundtrip"))["panel_roundtrip"]
    assert res.status == ev.PASSED and [p["panel"] for p in res.details["panels"]] == ["p1", "p2"]
    for a in adapters:
        assert a.log == ["create", "extend", "suspend", "resume", "revoke", "close"] and a.accounts == {}


async def test_panel_roundtrip_fails_when_the_panel_is_unhealthy_or_leaves_the_account_behind(tmp_path):
    ctx = make_ctx(tmp_path, env=panels_file(tmp_path, "sick"), adapter_factory=lambda cfg: FakeAdapter(healthy=False), allow_mutation=True)
    assert (await run(ctx, "panel_roundtrip"))["panel_roundtrip"].status == ev.FAILED
    ctx = make_ctx(
        tmp_path, env=panels_file(tmp_path, "leaky"), adapter_factory=lambda cfg: FakeAdapter(leaves_account=True), allow_mutation=True
    )
    res = (await run(ctx, "panel_roundtrip"))["panel_roundtrip"]
    assert res.status == ev.FAILED and res.details["panels"][0]["steps"]["gone_after_revoke"] is False


async def test_a_panel_that_raises_is_reported_without_aborting_other_panels(tmp_path):
    def factory(cfg):
        if cfg["name"] == "bad":
            raise ValueError("unknown panel kind")
        return FakeAdapter()

    ctx = make_ctx(tmp_path, env=panels_file(tmp_path, "bad", "good"), adapter_factory=factory, allow_mutation=True)
    res = (await run(ctx, "panel_roundtrip"))["panel_roundtrip"]
    assert res.status == ev.FAILED and [p["ok"] for p in res.details["panels"]] == [False, True]


# --------------------------------------------------- docker / caddy / prometheus


async def test_docker_build_is_skipped_without_docker_and_checks_every_image_with_it(tmp_path):
    assert (await run(make_ctx(tmp_path), "docker_build"))["docker_build"].status == ev.SKIPPED
    seen = []

    def runner(cmd, **kw):
        seen.append(" ".join(cmd))
        return 0, "built"

    ctx = make_ctx(tmp_path, which=lambda n: "/usr/bin/docker", run=runner)
    res = (await run(ctx, "docker_build"))["docker_build"]
    assert res.status == ev.PASSED and len(seen) == 4
    assert any("apps/api/Dockerfile" in s for s in seen) and any("apps/admin-web/Dockerfile" in s for s in seen)
    failing = make_ctx(
        tmp_path, which=lambda n: "/usr/bin/docker", run=lambda cmd, **kw: (1, "boom") if "store-web" in " ".join(cmd) else (0, "")
    )
    res = (await run(failing, "docker_build"))["docker_build"]
    assert res.status == ev.FAILED and "store-web image" in res.reason


async def test_caddy_and_promtool_validation_use_a_local_binary_then_docker_and_report_rejections(tmp_path):
    ctx = make_ctx(tmp_path, which=lambda n: "/bin/" + n if n in {"caddy", "promtool"} else None)
    results = await run(ctx, "caddy_config", "prometheus_rules")
    assert results["caddy_config"].status == ev.PASSED and results["caddy_config"].details["tool"] == "caddy"
    assert results["prometheus_rules"].details["tool"] == "promtool"
    rejecting = make_ctx(tmp_path, which=lambda n: "/bin/docker" if n == "docker" else None, run=lambda cmd, **kw: (1, "syntax error"))
    results = await run(rejecting, "caddy_config", "prometheus_rules")
    assert results["caddy_config"].status == results["prometheus_rules"].status == ev.FAILED
    assert (await run(make_ctx(tmp_path), "caddy_config"))["caddy_config"].status == ev.SKIPPED


def tls_handler(known="shop.example.com", *, leak=False):
    def handler(req):
        domain = req.url.params.get("domain", "")
        return httpx.Response(200 if domain == known or leak else 404, json={})

    return handler


TLS_ENV = {"MELORIN_EVIDENCE_API_URL": "http://api:8000", "MELORIN_EVIDENCE_RESELLER_DOMAIN": "Shop.Example.com"}


async def test_tls_ask_gate_requires_200_for_registered_and_404_for_everything_else(tmp_path):
    res = (await run(make_ctx(tmp_path, env=TLS_ENV, handler=tls_handler()), "tls_ask_gate"))["tls_ask_gate"]
    assert res.status == ev.PASSED and res.details == {
        "registered_status": 200, "unregistered_status": 404, "empty_status": 404, "note": res.details["note"],
    }  # fmt: skip
    leaky = (await run(make_ctx(tmp_path, env=TLS_ENV, handler=tls_handler(leak=True)), "tls_ask_gate"))["tls_ask_gate"]
    assert leaky.status == ev.FAILED  # a gate that approves arbitrary hostnames would let anyone burn certificate quota


# ------------------------------------------------------------------ Prometheus


def prom_handler(*, up="1", groups=("melorin-core",), ready=200):
    def handler(req):
        if req.url.path == "/-/ready":
            return httpx.Response(ready)
        if req.url.path == "/api/v1/query":
            return httpx.Response(200, json={"data": {"result": [{"value": [0, up]}]}})
        return httpx.Response(200, json={"data": {"groups": [{"name": g} for g in groups]}})

    return handler


async def test_prometheus_scrape_requires_up_equal_one_and_the_core_rule_group(tmp_path):
    env = {"MELORIN_PROMETHEUS_URL": "http://prom:9090"}
    assert (await run(make_ctx(tmp_path, env=env, handler=prom_handler()), "prometheus_scrape"))["prometheus_scrape"].status == ev.PASSED
    assert (await run(make_ctx(tmp_path, env=env, handler=prom_handler(up="0")), "prometheus_scrape"))[
        "prometheus_scrape"
    ].status == ev.FAILED
    assert (await run(make_ctx(tmp_path, env=env, handler=prom_handler(groups=())), "prometheus_scrape"))[
        "prometheus_scrape"
    ].status == ev.FAILED


class FakeAlertmanager:
    def __init__(self, *, accept=True, visible=True, receiver_hits=1):
        self.accept, self.visible, self.receiver_hits, self.alerts = accept, visible, receiver_hits, []

    def __call__(self, req):
        if req.method == "POST":
            if not self.accept:
                return httpx.Response(500)
            self.alerts = json.loads(req.content)
            return httpx.Response(200, json={"status": "success"})
        if req.url.path == "/api/v2/alerts":
            return httpx.Response(200, json=self.alerts if self.visible else [])
        return httpx.Response(200, json={"received": self.receiver_hits})


AM_ENV = {"MELORIN_ALERTMANAGER_URL": "http://am:9093"}


async def test_alert_delivery_needs_the_receiver_to_see_the_alert(tmp_path):
    env = {**AM_ENV, "MELORIN_ALERT_RECEIVER_PROBE_URL": "http://receiver/probe"}
    ok = (await run(make_ctx(tmp_path, env=env, handler=FakeAlertmanager()), "alert_delivery"))["alert_delivery"]
    assert ok.status == ev.PASSED and ok.details["delivered_to_receiver"] is True
    lost = (await run(make_ctx(tmp_path, env=env, handler=FakeAlertmanager(receiver_hits=0)), "alert_delivery"))["alert_delivery"]
    assert lost.status == ev.FAILED and "receiver" in lost.reason


async def test_alert_delivery_without_a_receiver_probe_is_skipped_not_green(tmp_path):
    res = (await run(make_ctx(tmp_path, env=AM_ENV, handler=FakeAlertmanager()), "alert_delivery"))["alert_delivery"]
    assert res.status == ev.SKIPPED and res.details["ingested"] is True


async def test_alert_delivery_fails_when_alertmanager_refuses_or_drops_the_alert(tmp_path):
    assert (await run(make_ctx(tmp_path, env=AM_ENV, handler=FakeAlertmanager(accept=False)), "alert_delivery"))[
        "alert_delivery"
    ].status == ev.FAILED
    dropped = await run(make_ctx(tmp_path, env=AM_ENV, handler=FakeAlertmanager(visible=False)), "alert_delivery")
    assert dropped["alert_delivery"].status == ev.FAILED
