"""Core-driven reseller bots: supervisor reconciliation, connection health, owner experience (Telegram + Core mocked)."""

import asyncio
import importlib.util
import io
import json
import logging
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
TOKEN = "123456789:" + "A" * 35


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def mod(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("MELORIN_RESELLER_BOTS_JSON", "MELORIN_TELEGRAM_RESELLER_TOKEN", "MELORIN_STORE_SLUG", "MELORIN_HEARTBEAT_FILE"):
        monkeypatch.delenv(k, raising=False)
    return load("tg_reseller_s01", "telegram-reseller/runner.py")


# ------------------------------------------------------------------ supervisor
class FakeRunner:
    def __init__(self, cfg):
        self.cfg, self.health, self.health_detail, self.crash, self.cancelled = cfg, "running", None, None, False

    async def run(self):
        try:
            if self.crash:
                raise self.crash
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FakeCore:
    def __init__(self):
        self.bots, self.reports, self.down, self.secrets = [], [], False, set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.secrets.add(request.headers.get("x-bot-secret"))
        if self.down:
            return httpx.Response(503, json={})
        if request.url.path == "/api/v1/internal/reseller-bots":
            return httpx.Response(200, json={"bots": self.bots, "poll_seconds": 30})
        if request.url.path.startswith("/api/v1/internal/reseller-bots/") and request.url.path.endswith("/status"):
            self.reports.append((request.url.path.split("/")[-2], json.loads(request.content)))
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})


def bot(i, fp="fp1"):
    return {
        "store_id": f"store-{i}",
        "slug": f"shop{i}",
        "name": f"S{i}",
        "bot_username": f"b{i}",
        "token": TOKEN,
        "fingerprint": f"{fp}-{i}",
    }


@pytest.fixture
def sup(mod):
    core = FakeCore()
    made = []

    def make(cfg):
        r = FakeRunner(cfg)
        made.append(r)
        return r

    s = mod.Supervisor(client=httpx.AsyncClient(transport=httpx.MockTransport(core.handler)), make_runner=make)
    return s, core, made


async def test_supervisor_starts_one_isolated_runner_per_bot_and_reports_running(sup):
    s, core, made = sup
    core.bots = [bot(1), bot(2)]
    await s.sync()
    await asyncio.sleep(0)
    assert sorted(r.cfg["slug"] for r in made) == ["shop1", "shop2"]
    assert {sid: body["state"] for sid, body in core.reports} == {"store-1": "running", "store-2": "running"}
    assert core.reports[0][1]["fingerprint"].startswith("fp1") and core.secrets == {"sek"}
    await s.sync()
    assert len(made) == 2  # a second sync with nothing changed starts nothing new
    for key in list(s.slots):
        await s._stop(key)


async def test_bot_removed_by_core_is_stopped_and_a_changed_token_restarts_it(sup):
    s, core, made = sup
    core.bots = [bot(1), bot(2)]
    await s.sync()
    await asyncio.sleep(0)  # let both runners reach their first await
    first = {r.cfg["slug"]: r for r in made}
    core.bots = [bot(1, fp="fp2")]  # store 2 suspended / switched off; store 1 got a new token
    await s.sync()
    await asyncio.sleep(0)
    assert first["shop2"].cancelled and first["shop1"].cancelled
    assert [r.cfg["slug"] for r in made[2:]] == ["shop1"] and set(s.slots) == {"store-1"}
    for key in list(s.slots):
        await s._stop(key)


async def test_core_outage_never_kills_running_bots(sup):
    s, core, made = sup
    core.bots = [bot(1)]
    await s.sync()
    core.down = True
    await s.sync()
    assert not made[0].cancelled and set(s.slots) == {"store-1"}
    for key in list(s.slots):
        await s._stop(key)


async def test_crashed_runner_is_restarted_but_a_revoked_token_is_not(sup, mod):
    s, core, made = sup
    core.bots = [bot(1), bot(2)]
    await s.sync()
    made[0].crash, made[1].crash = RuntimeError("boom"), mod.BotRevoked("shop2")
    for slot in s.slots.values():
        slot.task.cancel()
    await asyncio.gather(*(sl.task for sl in s.slots.values()), return_exceptions=True)
    # re-create the tasks the way a crash would have finished them
    for r, key in ((made[0], "store-1"), (made[1], "store-2")):
        s.slots[key].task = asyncio.create_task(r.run())
    await asyncio.sleep(0.01)
    core.reports.clear()
    await s.sync()
    await asyncio.sleep(0)
    assert len(made) == 3 and made[2].cfg["slug"] == "shop1"  # shop1 restarted
    state = {sid: body for sid, body in core.reports}
    assert state["store-2"]["state"] == "error"  # shop2 stays down until the admin supplies a different token
    await s.sync()
    assert len(made) == 3
    for key in list(s.slots):
        await s._stop(key)


async def test_a_store_whose_runner_cannot_be_built_does_not_stop_the_others(mod):
    core = FakeCore()
    core.bots = [bot(1), bot(2)]

    def make(cfg):
        if cfg["slug"] == "shop1":
            raise ValueError("bad")
        return FakeRunner(cfg)

    s = mod.Supervisor(client=httpx.AsyncClient(transport=httpx.MockTransport(core.handler)), make_runner=make)
    await s.sync()
    assert set(s.slots) == {"store-2"}
    for key in list(s.slots):
        await s._stop(key)


# ------------------------------------------------------------------ one bot: health + owner experience
class TgCore:
    def __init__(self, owner=False, getupdates=200):
        self.owner, self.getupdates, self.sent, self.commands = owner, getupdates, [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, path = str(request.url), request.url.path
        body = json.loads(request.content) if request.content else None
        if "api.telegram.org" in url:
            if url.endswith("/getUpdates"):
                return httpx.Response(self.getupdates, json={"ok": self.getupdates == 200, "result": [], "description": "x"})
            if url.endswith("/sendMessage"):
                self.sent.append(body)
            if url.endswith("/setMyCommands"):
                self.commands.append(body)
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path == "/api/v1/stores/by-slug/shop":
            return httpx.Response(
                200,
                json={"id": "s1", "name": "Shop", "bot_messages": {"welcome": "به فروشگاه ما خوش آمدید", "support": "ساعت کاری ۹ تا ۱۸"}},
            )
        if path == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        if path == "/api/v1/stores/s1/reseller/profile":
            if not self.owner:
                return httpx.Response(403, json={"error": {"code": "FORBIDDEN", "message": "no"}})
            return httpx.Response(
                200,
                json={
                    "store_name": "Shop",
                    "debt_limit": 1000,
                    "sales_enabled": True,
                    "main_wallet": {"balance": -200, "currency": "IRT", "debt_state": "near"},
                },
            )
        if path == "/api/v1/stores/s1/reseller/payments":
            return httpx.Response(
                200,
                json=[{"id": "p1", "status": "pending", "has_receipt": True, "amount": 5, "currency": "IRT", "provider": "manual_card"}],
            )
        return httpx.Response(404, json={})


def msg(text, n=1):
    return {"update_id": n, "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "A"}, "text": text}}


def _bot(mod, fake, tmp_path):
    r = mod.ResellerTelegramRunner(token=TOKEN, slug="shop")  # offset file comes from the env (tmp)
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return r


async def test_getupdates_success_marks_the_bot_running(mod, tmp_path):
    fake = TgCore()
    r = _bot(mod, fake, tmp_path)
    await r.tg("getUpdates", {})
    assert r.health == "running" and r.health_detail is None


async def test_telegram_401_means_revoked_token_and_is_not_retried(mod, tmp_path):
    r = _bot(mod, TgCore(getupdates=401), tmp_path)
    with pytest.raises(mod.BotRevoked):
        await r.tg("getUpdates", {})
    assert r.health == "error" and "توکن" in r.health_detail


async def test_telegram_409_is_reported_as_a_conflict_but_still_retried(mod, tmp_path):
    r = _bot(mod, TgCore(getupdates=409), tmp_path)
    with pytest.raises(httpx.HTTPStatusError):
        await r.tg("getUpdates", {})
    assert r.health == "error" and "هم‌زمان" in r.health_detail


async def test_owner_gets_management_button_and_scoped_commands_customer_does_not(mod, tmp_path):
    owner_fake, cust_fake = TgCore(owner=True), TgCore(owner=False)
    owner, cust = _bot(mod, owner_fake, tmp_path), _bot(mod, cust_fake, tmp_path)
    await owner.handle(msg("/start"))
    await cust.handle(msg("/start"))
    assert [mod.OWNER_BUTTON] in owner.main_menu_rows(9)
    assert [mod.OWNER_BUTTON] not in cust.main_menu_rows(9)
    flat = [b for row in cust.main_menu_rows(9) for b in row]
    assert not any("نماینده" in b and "درخواست" in b for b in flat)  # reseller bots offer no "become a reseller"
    scoped = [c for c in owner_fake.commands if c.get("scope", {}).get("type") == "chat"]
    assert scoped and "manage" in [c["command"] for c in scoped[0]["commands"]]
    assert not [c for c in cust_fake.commands if "scope" in c]


async def test_welcome_and_support_texts_come_from_the_store(mod, tmp_path):
    fake = TgCore()
    r = _bot(mod, fake, tmp_path)
    await r.handle(msg("/start"))
    assert fake.sent[0]["text"] == "به فروشگاه ما خوش آمدید"
    await r.handle(msg("🎧 پشتیبانی", 2))
    assert "ساعت کاری ۹ تا ۱۸" in fake.sent[-1]["text"]


async def test_manage_screen_is_owner_only_and_shows_debt_and_pending_payments(mod, tmp_path):
    cust_fake = TgCore(owner=False)
    await _bot(mod, cust_fake, tmp_path).handle(msg("/manage"))
    assert "فقط برای مالک" in cust_fake.sent[-1]["text"]
    fake = TgCore(owner=True)
    r = _bot(mod, fake, tmp_path)
    await r.handle(msg(mod.OWNER_BUTTON))
    text = fake.sent[-1]["text"]
    assert "Shop" in text and "نزدیک به سقف" in text
    labels = [b["text"] for row in fake.sent[-1]["reply_markup"]["inline_keyboard"] for b in row]
    assert any("(1)" in label for label in labels)


# ------------------------------------------------------------------ hosting + safety
def test_token_never_reaches_the_logs(mod):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.addFilter(mod.RedactTokens())
    lg = logging.getLogger("melorin.test.redact")
    lg.addHandler(handler)
    lg.propagate = False
    try:
        raise httpx.ConnectError(f"boom https://api.telegram.org/bot{TOKEN}/getUpdates")
    except httpx.ConnectError:
        lg.exception("telegram cycle failed: %s", f"https://api.telegram.org/bot{TOKEN}/getUpdates")
    assert TOKEN not in buf.getvalue() and "bot<redacted>" in buf.getvalue()


def test_default_mode_is_core_driven_and_env_modes_stay_available(mod, monkeypatch):
    assert mod._static_bots() is None
    monkeypatch.setenv("MELORIN_RESELLER_BOTS_JSON", "not json")
    with pytest.raises(SystemExit):
        mod._static_bots()


def test_healthcheck_uses_the_heartbeat_file(tmp_path):
    hc = load("hc_s01", "../scripts/telegram_healthcheck.py")
    f = tmp_path / "hb"
    assert hc.heartbeat_ok(str(f)) is False
    f.write_text(str(int(time.time())))
    assert hc.heartbeat_ok(str(f)) is True
    f.write_text(str(int(time.time()) - 600))
    assert hc.heartbeat_ok(str(f)) is False


def test_compose_always_runs_the_reseller_supervisor_and_proxies_hide_the_internal_api():
    repo = ROOT.parent
    compose = (repo / "docker-compose.yml").read_text()
    block = compose.split("  telegram_reseller:")[1].split("\n  caddy:")[0]
    assert "profiles" not in block and "MELORIN_HEARTBEAT_FILE" in block and "telegram_healthcheck.py" in block
    assert "/api/v1/internal/*" in (repo / "infra/Caddyfile").read_text()
    for conf in ("apps/admin-web/nginx.conf", "apps/store-web/nginx.conf"):
        assert "location /api/v1/internal/ { return 404; }" in (repo / conf).read_text()
