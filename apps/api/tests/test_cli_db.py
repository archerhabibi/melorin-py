"""Phase 4: the first-install / break-glass CLI (bootstrap, outbox replay, key rotation, admin recovery, dispatch)."""

from __future__ import annotations

import sys
import types
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, open_schema_engine
from melorin import cli
from melorin.core import integrations, settings_store
from melorin.core.crypto import decrypt, encrypt
from melorin.core.security import verify_password
from melorin.kernel.models.catalog import Product, StoreProduct
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.stores import Store, StoreMembership, StorePaymentConfiguration
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import Panel
from melorin.kernel.models.webhooks import WebhookEndpoint

STRONG = "a-very-long-one-time-password-123"
TOTP = "JBSWY3DPEHPK3PXP"


def _settings(**over):
    base = dict(
        bootstrap_admin_email="Admin@Example.com ",
        bootstrap_admin_password=STRONG,
        bootstrap_admin_totp_secret=TOTP.lower(),
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


# --- bootstrap: refusals -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "over, fragment",
    [
        ({"bootstrap_admin_email": ""}, "are required"),
        ({"bootstrap_admin_password": ""}, "are required"),
        ({"bootstrap_admin_password": "short"}, "strong one-time"),
        ({"bootstrap_admin_totp_secret": ""}, "TOTP_SECRET is required"),
        ({"bootstrap_admin_totp_secret": "TOOSHORT"}, "TOTP_SECRET is required"),
        ({"bootstrap_admin_totp_secret": "1" * 16}, "TOTP_SECRET is required"),  # not valid base32
    ],
)
async def test_bootstrap_refuses_missing_or_weak_credentials(maker, use_settings, over, fragment):
    use_settings(**over)
    with pytest.raises(SystemExit) as exc:
        await cli.bootstrap()
    assert fragment in str(exc.value)
    async with maker() as s:
        assert (await s.scalars(select(User))).all() == []  # nothing is written on refusal


# --- bootstrap: success --------------------------------------------------------------------------------------------


async def test_bootstrap_creates_admin_main_store_membership_defaults_and_totp(maker, use_settings, capsys):
    await cli.bootstrap()
    async with maker() as s:
        user = await s.scalar(select(User))
        assert user.email == "admin@example.com" and user.is_super_admin and user.is_active and user.locale == "fa"
        assert await verify_password(STRONG, user.password_hash)
        assert user.totp_enabled and decrypt(user.totp_secret_enc) == TOTP  # normalised to upper-case, stored encrypted
        assert (await s.scalar(select(Identity))).subject == "admin@example.com"
        store = await s.scalar(select(Store))
        assert (store.kind, store.slug, store.currency, store.status) == ("main", "main", "IRT", "active")
        member = await s.scalar(select(StoreMembership))
        assert (member.user_id, member.store_id, member.role, member.status) == (user.id, store.id, "owner", "active")
        for key, value in settings_store.DEFAULTS.items():
            assert await settings_store.get(s, key) == value
        assert (await s.scalars(select(Product))).all() == []  # demo data off by default
    assert "bootstrap complete: admin=admin@example.com main_store=main demo_seeded=False" in capsys.readouterr().out


async def test_bootstrap_is_idempotent_and_repairs_an_existing_user(maker, use_settings):
    async with maker() as s:  # a pre-existing, demoted, inactive, password-less account with the same e-mail
        s.add(User(email="admin@example.com", display_name="old", is_super_admin=False, is_active=False))
        await s.commit()
    await cli.bootstrap()
    await cli.bootstrap()
    async with maker() as s:
        users = (await s.scalars(select(User))).all()
        assert len(users) == 1 and users[0].is_super_admin and users[0].is_active and users[0].password_hash
        assert len((await s.scalars(select(Store))).all()) == 1
        assert len((await s.scalars(select(Identity))).all()) == 1
        assert len((await s.scalars(select(StoreMembership))).all()) == 1


async def test_bootstrap_keeps_an_existing_password_and_promotes_membership(maker, use_settings):
    async with maker() as s:
        store = await make_store(s)
        user = User(email="admin@example.com", display_name="x", password_hash="existing-hash")
        s.add(user)
        await s.flush()
        s.add(StoreMembership(store_id=store.id, user_id=user.id, role="staff", status="disabled"))
        await s.commit()
    await cli.bootstrap()
    async with maker() as s:
        assert (await s.scalar(select(User))).password_hash == "existing-hash"
        member = await s.scalar(select(StoreMembership))
        assert (member.role, member.status) == ("owner", "active")


async def test_bootstrap_does_not_overwrite_an_operator_changed_setting(maker, use_settings):
    key = next(iter(settings_store.DEFAULTS))
    async with maker() as s:
        await settings_store.set_value(s, key, "operator-choice")
        await s.commit()
    await cli.bootstrap()
    async with maker() as s:
        assert await settings_store.get(s, key) == "operator-choice"


async def test_bootstrap_seeds_one_unlisted_free_test_product_only_when_demo_data_is_on(maker, use_settings):
    use_settings(seed_demo_data=True)
    await cli.bootstrap()
    await cli.bootstrap()
    async with maker() as s:
        (product,) = (await s.scalars(select(Product))).all()
        assert (product.code, product.main_price, product.is_test) == ("TEST", 0, True)
        (link,) = (await s.scalars(select(StoreProduct))).all()
        assert link.is_enabled and not link.is_listed


# --- outbox replay -------------------------------------------------------------------------------------------------


async def test_outbox_replay_requeues_a_failed_event_and_clears_its_error(maker, capsys):
    async with maker() as s:
        e = OutboxEvent(topic="t", payload={}, status="processing", locked_at=None, last_error="boom", attempts=5)
        s.add(e)
        await s.commit()
    await cli.outbox_replay(str(e.id))
    async with maker() as s:
        row = await s.get(OutboxEvent, e.id)
        assert (row.status, row.locked_at, row.last_error) == ("pending", None, None)
    assert f"outbox replay queued: {e.id}" in capsys.readouterr().out


async def test_outbox_replay_unknown_event_exits_and_malformed_id_is_rejected(maker):
    with pytest.raises(SystemExit, match="not found"):
        await cli.outbox_replay(str(uuid.uuid4()))
    with pytest.raises(ValueError):
        await cli.outbox_replay("not-a-uuid")


# --- encryption key rotation ---------------------------------------------------------------------------------------


async def test_rotate_encryption_key_reencrypts_known_columns_and_skips_empty_ones(maker, use_settings, capsys):
    new_key = Fernet.generate_key().decode()
    async with maker() as s:
        store = await make_store(s)
        store.bot_token_enc = encrypt("bot-token")
        s.add(Panel(name="p", kind="mock", base_url="http://p", credentials_enc=encrypt('{"u":"x"}')))
        s.add(Panel(name="no-creds", kind="mock", base_url="http://q"))
        s.add(StorePaymentConfiguration(store_id=store.id, provider="zarinpal", secret_enc=encrypt("merchant")))
        s.add(User(display_name="a", totp_secret_enc=encrypt(TOTP), totp_enabled=True))
        s.add(WebhookEndpoint(store_id=store.id, url="https://h", secret_enc=encrypt("cur"), previous_secret_enc=encrypt("prev")))
        await s.commit()
    await cli.rotate_encryption_key(new_key)
    f = Fernet(new_key.encode())
    async with maker() as s:
        assert f.decrypt((await s.scalar(select(Store))).bot_token_enc.encode()).decode() == "bot-token"
        panels = {p.name: p for p in (await s.scalars(select(Panel))).all()}
        assert f.decrypt(panels["p"].credentials_enc.encode()).decode() == '{"u":"x"}'
        assert panels["no-creds"].credentials_enc is None
        # every encrypted column the platform owns must follow the key, otherwise 2FA / payments / webhooks break
        assert f.decrypt((await s.scalar(select(StorePaymentConfiguration))).secret_enc.encode()).decode() == "merchant"
        assert f.decrypt((await s.scalar(select(User))).totp_secret_enc.encode()).decode() == TOTP
        hook = await s.scalar(select(WebhookEndpoint))
        assert (f.decrypt(hook.secret_enc.encode()).decode(), f.decrypt(hook.previous_secret_enc.encode()).decode()) == ("cur", "prev")
    assert "encryption rotation completed" in capsys.readouterr().out


async def test_rotate_encryption_key_requires_a_configured_current_key_and_a_valid_new_one(maker, use_settings):
    use_settings(encryption_key="")
    with pytest.raises(SystemExit, match="current MELORIN_ENCRYPTION_KEY"):
        await cli.rotate_encryption_key(Fernet.generate_key().decode())
    use_settings()
    with pytest.raises(ValueError):
        await cli.rotate_encryption_key("not-a-fernet-key")


# --- admin recovery ------------------------------------------------------------------------------------------------


def _passwords(monkeypatch, first, second):
    answers = iter([first, second])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))


async def _admin(maker, *, super_admin=True):
    async with maker() as s:
        u = User(email="root@example.com", display_name="r", is_super_admin=super_admin, password_hash="old", totp_enabled=True)
        s.add(u)
        await s.commit()
        return u


async def test_reset_admin_password_sets_a_new_hash_and_keeps_totp(maker, monkeypatch, capsys):
    await _admin(maker)
    _passwords(monkeypatch, STRONG, STRONG)
    await cli.reset_admin_password(" ROOT@example.com ")
    async with maker() as s:
        user = await s.scalar(select(User))
        assert await verify_password(STRONG, user.password_hash) and user.totp_enabled
    assert "TOTP remains unchanged" in capsys.readouterr().out


@pytest.mark.parametrize("first, second", [(STRONG, STRONG + "x"), ("short", "short")])
async def test_reset_admin_password_rejects_mismatch_or_short_passwords(maker, monkeypatch, first, second):
    await _admin(maker)
    _passwords(monkeypatch, first, second)
    with pytest.raises(SystemExit, match="at least 24"):
        await cli.reset_admin_password("root@example.com")
    async with maker() as s:
        assert (await s.scalar(select(User))).password_hash == "old"


async def test_reset_admin_password_only_works_for_existing_super_admins(maker, monkeypatch):
    await _admin(maker, super_admin=False)
    _passwords(monkeypatch, STRONG, STRONG)
    with pytest.raises(SystemExit, match="super-admin not found"):
        await cli.reset_admin_password("root@example.com")
    with pytest.raises(SystemExit, match="super-admin not found"):
        await cli.reset_admin_password("nobody@example.com")


async def test_disable_admin_ip_allowlist_turns_the_allowlist_off(maker, capsys):
    async with maker() as s:
        await integrations.save(s, integrations.ADMIN_ACCESS_KEY, {"enabled": True, "ips": ["203.0.113.9"]})
        await s.commit()
    await cli.disable_admin_ip_allowlist()
    async with maker() as s:
        cfg = await integrations.get_admin_access(s)
    assert cfg["enabled"] is False and cfg["ips"] == []
    assert "admin IP allowlist disabled" in capsys.readouterr().out


# --- argument dispatch ---------------------------------------------------------------------------------------------


@pytest.fixture
def dispatched(monkeypatch):
    calls = []
    for name in ("bootstrap", "outbox_replay", "rotate_encryption_key", "reset_admin_password", "disable_admin_ip_allowlist"):

        def make(n):
            async def fake(*args):
                calls.append((n, *args))

            return fake

        monkeypatch.setattr(cli, name, make(name))
    return calls


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["bootstrap"], ("bootstrap",)),
        (["outbox-replay", "abc"], ("outbox_replay", "abc")),
        (["rotate-encryption-key", "KEY"], ("rotate_encryption_key", "KEY")),
        (["reset-admin-password", "a@b.c"], ("reset_admin_password", "a@b.c")),
        (["disable-admin-ip-allowlist"], ("disable_admin_ip_allowlist",)),
    ],
)
def test_main_routes_each_command(monkeypatch, dispatched, argv, expected):
    monkeypatch.setattr(sys, "argv", ["melorin.cli", *argv])
    cli.main()
    assert dispatched == [expected]


@pytest.mark.parametrize("command", ["outbox-replay", "rotate-encryption-key", "reset-admin-password"])
def test_main_requires_a_value_for_commands_that_need_one(monkeypatch, dispatched, command, capsys):
    monkeypatch.setattr(sys, "argv", ["melorin.cli", command])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2 and "requires" in capsys.readouterr().err and dispatched == []


def test_main_rejects_unknown_commands(monkeypatch, dispatched):
    monkeypatch.setattr(sys, "argv", ["melorin.cli", "drop-database"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2 and dispatched == []
