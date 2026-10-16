"""Small operational CLI for first-install administration."""
import argparse
import datetime as dt
import asyncio
import uuid
import base64
import binascii
import getpass

from sqlalchemy import select

from melorin.core.config import get_settings
from melorin.core.db import session_factory
from melorin.core.security import hash_password
from melorin.core.crypto import encrypt
from melorin.core import settings_store
from melorin import models  # noqa: F401
from melorin.modules.catalog.models import Product, StoreProduct
from melorin.modules.identity.models import Identity, User
from melorin.modules.stores.models import Store, StoreMembership
from melorin.modules.system.models import OutboxEvent


async def bootstrap() -> None:
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        raise SystemExit("MELORIN_BOOTSTRAP_ADMIN_EMAIL and MELORIN_BOOTSTRAP_ADMIN_PASSWORD are required")
    if len(settings.bootstrap_admin_password) < 24 or settings.bootstrap_admin_password in {"change-me-now", "password"}:
        raise SystemExit("MELORIN_BOOTSTRAP_ADMIN_PASSWORD must be a strong one-time credential")
    totp_secret = (settings.bootstrap_admin_totp_secret or "").strip().upper()
    try:
        if len(totp_secret) < 16:
            raise ValueError
        base64.b32decode(totp_secret + "=" * (-len(totp_secret) % 8), casefold=True)
    except (binascii.Error, ValueError):
        raise SystemExit("MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET is required for the first admin bootstrap")
    async with session_factory()() as session:
        email = settings.bootstrap_admin_email.strip().lower()
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name="Melorin Admin",
                password_hash=await hash_password(settings.bootstrap_admin_password),
                is_super_admin=True,
                is_active=True,
                locale="fa",
            )
            session.add(user)
            await session.flush()
        else:
            user.is_super_admin = True
            user.is_active = True
            if not user.password_hash:
                user.password_hash = await hash_password(settings.bootstrap_admin_password)
        if settings.bootstrap_admin_totp_secret:
            user.totp_secret_enc = encrypt(totp_secret)
            user.totp_enabled = True
            user.totp_last_counter = None
        if await session.scalar(select(Identity).where(Identity.provider == "email", Identity.subject == email)) is None:
            session.add(Identity(user_id=user.id, provider="email", subject=email, verified_at=dt.datetime.now(dt.timezone.utc)))

        store = await session.scalar(select(Store).where(Store.kind == "main"))
        if store is None:
            store = Store(kind="main", name="Melorin Main Store", slug="main", currency=settings.default_currency, status="active")
            session.add(store)
            await session.flush()
        membership = await session.scalar(
            select(StoreMembership).where(StoreMembership.store_id == store.id, StoreMembership.user_id == user.id)
        )
        if membership is None:
            session.add(StoreMembership(store_id=store.id, user_id=user.id, role="owner", status="active"))
        else:
            membership.role, membership.status = "owner", "active"
        for key, value in settings_store.DEFAULTS.items():
            if await session.scalar(select(settings_store.SystemSetting).where(settings_store.SystemSetting.key == key)) is None:
                await settings_store.set_value(session, key, value)
        if settings.seed_demo_data:
            product = await session.scalar(select(Product).where(Product.code == "TEST"))
            if product is None:
                product = Product(
                    code="TEST", name="Test VPN", description="Development-only test plan",
                    category="test", duration_days=1, traffic_gb=1, max_devices=1,
                    main_price=0, reseller_price=0, currency=store.currency, is_active=True, is_test=True, sort=999,
                )
                session.add(product)
                await session.flush()
            link = await session.scalar(
                select(StoreProduct).where(StoreProduct.store_id == store.id, StoreProduct.product_id == product.id)
            )
            if link is None:
                session.add(StoreProduct(store_id=store.id, product_id=product.id, is_enabled=True, is_listed=False))
        await session.commit()
        print(f"bootstrap complete: admin={email} main_store={store.slug} demo_seeded={settings.seed_demo_data}")


async def outbox_replay(event_id: str) -> None:
    async with session_factory()() as session:
        event = await session.get(OutboxEvent, uuid.UUID(event_id))
        if event is None:
            raise SystemExit("outbox event not found")
        event.status, event.locked_at, event.available_at = "pending", None, __import__("datetime").datetime.now(__import__("datetime").UTC)
        event.last_error = None
        await session.commit()
        print(f"outbox replay queued: {event.id}")


async def rotate_encryption_key(new_key: str) -> None:
    # Rotate only fields known to contain encrypted values. Keep this explicit
    # and transactional rather than attempting a dangerous blind JSON rewrite.
    from melorin.modules.stores.models import ResellerApplication, Store
    from melorin.modules.vpn.models import Panel
    from melorin.modules.payments.models import StorePaymentConfiguration
    from sqlalchemy import select
    from melorin.core.crypto import decrypt
    from cryptography.fernet import Fernet
    async with session_factory()() as session:
        if not get_settings().encryption_key:
            raise SystemExit("current MELORIN_ENCRYPTION_KEY is required")
        new_fernet = Fernet(new_key.encode())
        rows = [
            (Store, "bot_token_enc"), (ResellerApplication, "bot_token_enc"), (Panel, "credentials_enc"), (StorePaymentConfiguration, "secret_enc"),
        ]
        for model, field in rows:
            for row in (await session.scalars(select(model))).all():
                value = getattr(row, field, None)
                if value:
                    plain = decrypt(value)
                    setattr(row, field, new_fernet.encrypt(plain.encode()).decode())
        await session.commit()
        print("encryption rotation completed; set MELORIN_ENCRYPTION_KEY to the reviewed new key")


async def reset_admin_password(email: str) -> None:
    async with session_factory()() as session:
        user = await session.scalar(select(User).where(User.email == email.strip().lower(), User.is_super_admin.is_(True)))
        if not user:
            raise SystemExit("super-admin not found")
        password = getpass.getpass("New admin password (hidden): ")
        confirm = getpass.getpass("Repeat new admin password: ")
        if len(password) < 24 or password != confirm:
            raise SystemExit("password must match and be at least 24 characters")
        user.password_hash = await hash_password(password)
        await session.commit()
        print(f"admin password reset for {user.email}; existing TOTP remains unchanged")


async def disable_admin_ip_allowlist() -> None:
    """Break-glass: turn the admin IP allowlist off if an admin locked themselves out."""
    from melorin.core import integrations
    async with session_factory()() as session:
        await integrations.save(session, integrations.ADMIN_ACCESS_KEY, {"enabled": False, "ips": []})
        await session.commit()
    print("admin IP allowlist disabled")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m melorin.cli")
    parser.add_argument("command", choices=("bootstrap", "outbox-replay", "rotate-encryption-key", "reset-admin-password", "disable-admin-ip-allowlist"))
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    if args.command == "bootstrap":
        asyncio.run(bootstrap())
    elif args.command == "outbox-replay":
        if not args.value:
            parser.error("outbox-replay requires an event UUID")
        asyncio.run(outbox_replay(args.value))
    elif args.command == "rotate-encryption-key":
        if not args.value:
            parser.error("rotate-encryption-key requires a Fernet key")
        asyncio.run(rotate_encryption_key(args.value))
    elif args.command == "disable-admin-ip-allowlist":
        asyncio.run(disable_admin_ip_allowlist())
    else:
        if not args.value:
            parser.error("reset-admin-password requires the admin email")
        asyncio.run(reset_admin_password(args.value))


if __name__ == "__main__":
    main()
