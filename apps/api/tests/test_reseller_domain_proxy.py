"""Reseller store domains behind the bundled Caddy: on-demand TLS gate + catch-all site + host-based storefront."""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.modules.catalog.router import tls_ask
from melorin.modules.stores.models import Store

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.sorted_tables:  # one by one: a pre-existing duplicate index breaks create_all on SQLite
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        except Exception:
            pass
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def test_tls_ask_only_approves_active_reseller_domains(session):
    main = Store(kind="main", name="Main", slug="main", currency="IRT")
    session.add(main)
    await session.flush()
    session.add_all([
        Store(kind="reseller", name="A", slug="a", domain="shop.example.com", parent_store_id=main.id),
        Store(kind="reseller", name="B", slug="b", domain="off.example.com", parent_store_id=main.id, status="suspended"),
    ])
    await session.commit()
    assert await tls_ask("shop.example.com", session) == {"ok": True}
    assert await tls_ask(" Shop.Example.COM. ", session) == {"ok": True}  # Caddy may send any case / trailing dot
    for host in ("off.example.com", "evil.example.org", "", "   ", "a" * 300):
        with pytest.raises(AppError) as e:
            await tls_ask(host, session)
        assert e.value.status == 404


def test_caddyfile_issues_certificates_on_demand_only_after_core_approval():
    caddy = (REPO / "infra/Caddyfile").read_text()
    assert "on_demand_tls" in caddy and "ask http://api:8000/api/v1/tls/ask" in caddy
    site = caddy.split("https:// {", 1)[1].split("http:// {", 1)[0]
    assert "on_demand" in site                          # catch-all site is only allowed through the ask gate
    assert "reverse_proxy store_web:80" in site and "reverse_proxy api:8000" in site
    assert "admin_web" not in site                      # the admin panel is never exposed on a reseller domain
    assert "@blocked_ops path /metrics /docs /redoc /openapi.json" in site
    assert "redir https://{host}{uri}" in caddy.split("http:// {", 1)[1]


def test_storefront_resolves_the_store_from_the_hostname_with_main_as_fallback():
    app = (REPO / "apps/store-web/src/App.jsx").read_text()
    assert "/api/v1/stores/by-domain/${encodeURIComponent(window.location.hostname" in app
    assert app.index("stores/by-domain/") < app.index("/api/v1/stores/main")
