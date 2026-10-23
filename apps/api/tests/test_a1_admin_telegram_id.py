"""A1-1: the installer takes the main admin's numeric Telegram ID and Core links it as the admin's alert address."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from melorin import cli
from melorin.core import admin_telegram
from melorin.core.errors import AppError
from melorin.kernel.models.identity import Identity, User

ROOT = Path(__file__).parents[3]
STRONG = "a-very-long-one-time-password-123"
TOTP = "JBSWY3DPEHPK3PXP"


def _settings(**over):
    base = dict(
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password=STRONG,
        bootstrap_admin_totp_secret=TOTP,
        bootstrap_admin_telegram_id="123456789",
        default_currency="IRT",
        seed_demo_data=False,
        encryption_key="configured",
    )
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.fixture
async def maker(monkeypatch):
    async with open_schema_engine() as engine:
        m = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(cli, "session_factory", lambda: m)
        yield m


@pytest.fixture
def use_settings(monkeypatch):
    def apply(**over):
        monkeypatch.setattr(cli, "get_settings", lambda: _settings(**over))

    apply()
    return apply


# ---------------------------------------------------------------- the ID itself
@pytest.mark.parametrize(
    "raw, expected", [("123456789", "123456789"), (" ۱۲۳۴۵۶۷۸۹ ", "123456789"), ("٥٤٣٢١", "54321"), (987654321, "987654321")]
)
def test_parse_telegram_id_accepts_digits_in_any_script(raw, expected):
    assert admin_telegram.parse_telegram_id(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "1234", "@username", "12ab45678", "0123456789", "1" * 16, "-123456789", "123 456 789"])
def test_parse_telegram_id_rejects_everything_else(raw):
    with pytest.raises(AppError) as exc:
        admin_telegram.parse_telegram_id(raw)
    assert exc.value.code == "INVALID_TELEGRAM_ID" and exc.value.status == 422


# ---------------------------------------------------------------- linking
async def test_bootstrap_links_the_telegram_id_to_the_admin(maker, use_settings, capsys):
    await cli.bootstrap()
    async with maker() as s:
        admin = await s.scalar(select(User))
        idents = {(i.provider, i.subject) for i in (await s.scalars(select(Identity))).all()}
        assert idents == {("email", "admin@example.com"), ("telegram", "123456789")}
        assert await admin_telegram.current(s, admin.id) == "123456789"
    assert "telegram_id=123456789" in capsys.readouterr().out


async def test_bootstrap_without_a_telegram_id_creates_no_telegram_identity(maker, use_settings):
    use_settings(bootstrap_admin_telegram_id="")
    await cli.bootstrap()
    async with maker() as s:
        assert [i.provider for i in (await s.scalars(select(Identity))).all()] == ["email"]


async def test_bootstrap_survives_a_bad_telegram_id_and_says_so(maker, use_settings, capsys):
    use_settings(bootstrap_admin_telegram_id="@not_a_number")
    await cli.bootstrap()  # the first install must never be stopped by this optional value
    out = capsys.readouterr().out
    assert "was not linked" in out and "bootstrap complete" in out
    async with maker() as s:
        assert (await s.scalar(select(User))).is_super_admin


async def test_bootstrap_is_idempotent_for_the_telegram_identity(maker, use_settings):
    await cli.bootstrap()
    await cli.bootstrap()
    async with maker() as s:
        assert len((await s.scalars(select(Identity).where(Identity.provider == "telegram"))).all()) == 1


async def test_link_replaces_the_previous_address_and_refuses_someone_elses_id(maker, use_settings):
    await cli.bootstrap()
    async with maker() as s:
        admin = await s.scalar(select(User).where(User.is_super_admin.is_(True)))
        customer = User(display_name="c")
        s.add(customer)
        await s.flush()
        s.add(Identity(user_id=customer.id, provider="telegram", subject="555555555"))
        await s.commit()
        assert await admin_telegram.link(s, admin, "777777777") == "777777777"
        await s.commit()
        assert await admin_telegram.current(s, admin.id) == "777777777"
        assert len((await s.scalars(select(Identity).where(Identity.user_id == admin.id, Identity.provider == "telegram"))).all()) == 1
        with pytest.raises(AppError) as exc:
            await admin_telegram.link(s, admin, "555555555")  # belongs to a customer: never merged
        assert exc.value.code == "TELEGRAM_ID_IN_USE" and exc.value.status == 409
        assert await admin_telegram.current(s, admin.id) == "777777777"


async def test_set_admin_telegram_cli_links_and_reports(maker, use_settings, capsys):
    use_settings(bootstrap_admin_telegram_id="")
    await cli.bootstrap()
    await cli.set_admin_telegram(" Admin@Example.com ", "۴۴۴۴۴۴۴۴۴")
    assert "admin Telegram ID set" in capsys.readouterr().out
    async with maker() as s:
        assert await admin_telegram.current(s, (await s.scalar(select(User))).id) == "444444444"
    with pytest.raises(SystemExit, match="super-admin not found"):
        await cli.set_admin_telegram("nobody@example.com", "444444444")
    with pytest.raises(SystemExit, match="آیدی عددی"):
        await cli.set_admin_telegram("admin@example.com", "@name")


def test_cli_dispatch_knows_set_admin_telegram(monkeypatch):
    calls = []

    async def fake(*args):
        calls.append(args)

    monkeypatch.setattr(cli, "set_admin_telegram", fake)
    monkeypatch.setattr(sys, "argv", ["melorin.cli", "set-admin-telegram", "a@b.co", "123456789"])
    cli.main()
    assert calls == [("a@b.co", "123456789")]
    monkeypatch.setattr(sys, "argv", ["melorin.cli", "set-admin-telegram", "a@b.co"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


# ---------------------------------------------------------------- the installer and the menu
def _bash(script: str) -> str:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout


def _function(path: str, name: str) -> str:
    src = (ROOT / path).read_text()
    m = re.search(rf"^{name}\(\) \{{.*?^\}}\n", src, re.S | re.M) or re.search(rf"^{name}\(\) \{{.*\}}\n", src, re.M)
    assert m, f"{name} not found in {path}"
    return m.group(0)


def test_installer_scripts_are_valid_bash():
    for script in ("scripts/install_server.sh", "melorin.sh"):
        subprocess.run(["bash", "-n", str(ROOT / script)], check=True)


@pytest.mark.parametrize(
    "raw, expected",
    [("123456789", "123456789"), (" ۱۲۳۴۵۶۷۸۹ ", "123456789"), ("@name", ""), ("1234", ""), ("0123456789", ""), ("", "")],
)
def test_installer_normalises_the_id_like_core(raw, expected):
    fn = _function("scripts/install_server.sh", "normalize_tg_id")
    assert _bash(f"{fn}\nnormalize_tg_id '{raw}'") == expected


def test_installer_stores_the_id_in_env_and_tells_the_admin_to_press_start():
    installer = (ROOT / "scripts/install_server.sh").read_text()
    assert "ADMIN_TELEGRAM_ID" in installer and 'set_kv MELORIN_BOOTSTRAP_ADMIN_TELEGRAM_ID "$ADMIN_TG"' in installer
    assert "press Start" in installer
    assert "MELORIN_BOOTSTRAP_ADMIN_TELEGRAM_ID=" in (ROOT / ".env.example").read_text()


def test_menu_asks_for_the_id_and_passes_it_to_the_installer():
    menu = (ROOT / "melorin.sh").read_text()
    assert "ask_admin_tg" in menu and 'ADMIN_TELEGRAM_ID="$ADMIN_TG"' in menu
    assert "set-admin-telegram" in menu  # menu 3 -> "Admin Telegram ID" works on a running install
    fold = _function("melorin.sh", "fold_digits")
    assert _bash(f"{fold}\nfold_digits ' ۱۲۳۴۵ '") == "12345"


# ---------------------------------------------------------------- the bot answers the admin instead of staying silent
def _load_bot(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_TELEGRAM_TOKEN": "tok",
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("tg_main_a1", ROOT / "apps/telegram-main/runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bot_tells_the_admin_that_alerts_arrive_here(tmp_path, monkeypatch):
    mod = _load_bot(tmp_path, monkeypatch)
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.telegram.org" in url:
            if url.endswith("/sendMessage"):
                sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})
        if request.url.path == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if request.url.path == "/api/v1/auth/telegram/bot":
            return httpx.Response(403, json={"error": {"code": "ADMIN_USE_PANEL", "message": "ورود مدیران فقط از پنل مدیریت انجام می‌شود."}})
        return httpx.Response(404, json={})

    bot = mod.TelegramRunner()
    bot.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    update = {"update_id": 1, "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "A"}, "text": "/start"}}
    asyncio.run(bot.handle(update))
    assert len(sent) == 1 and "اعلان‌های مدیریتی" in sent[0]["text"] and sent[0]["chat_id"] == 9
