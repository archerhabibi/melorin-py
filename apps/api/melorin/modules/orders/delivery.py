"""Order delivery: ONE Telegram post with QR image + subscription link + wallet balance.

Runs in the outbox worker after provisioning succeeded (topic ``order.delivery``). The
post is a single photo message: the QR code of the subscription link is the image and
the caption carries the account details, the tap-to-copy subscription link and the
customer's wallet balance right after the payment.

Delivery is at-least-once and deduplicated through the Notification row
(``delivery:<order_id>``): once ``telegram_status == "sent"`` a retry is a no-op.
"""

import html
import io
import logging
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.config import get_settings
from melorin.core.crypto import decrypt
from melorin.core.metrics import inc
from melorin.modules.identity.models import Identity
from melorin.modules.notifications.models import Notification
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import Store
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.wallet.models import LedgerEntry, LedgerTransaction, Wallet

log = logging.getLogger("melorin.delivery")

CAPTION_LIMIT = 1024  # Telegram hard limit for a photo caption
LINK_WAIT = dt.timedelta(hours=1)  # how long a missing link is retried before delivering without it


class LinkNotReady(RuntimeError):
    """The subscription link is not stored yet; raised so the outbox retries instead of sending a post without QR."""


def render_qr_png(data: str) -> bytes:
    """PNG QR code for ``data`` (pure-python, no Pillow needed)."""
    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=4)
    return buf.getvalue()


def _money(n) -> str:
    return f"{int(n or 0):,}"


def _gb(b) -> str:
    return f"{(b or 0) / 1073741824:.1f}"


def build_caption(*, order: Order, account: VpnAccount, link: str | None, balance: int | None, currency: str) -> str:
    """HTML caption (Telegram ``parse_mode=HTML``). Every dynamic value is escaped."""
    e = html.escape
    snap = order.product_snapshot or {}
    if order.kind == "renewal":
        head = "✅ تمدید اکانت شما انجام شد"
    elif order.kind == "test":
        head = "🧪 اکانت تست شما آماده شد"
    else:
        head = "✅ خرید شما با موفقیت انجام شد"
    lines = [f"<b>{head}</b>", ""]
    lines.append(f"📦 سفارش: <code>{e(order.number)}</code>")
    if snap.get("name"):
        lines.append(f"🛍 سرویس: {e(str(snap['name']))}")
    lines.append(f"👤 نام اکانت: <code>{e(account.username)}</code>")
    if account.expires_at:
        lines.append(f"⏳ انقضا: {account.expires_at:%Y-%m-%d}")
    lines.append(f"📊 حجم: {_gb(account.traffic_limit_bytes) + ' GB' if account.traffic_limit_bytes else 'نامحدود'}")
    if link:
        lines += [
            "",
            "🔗 لینک اشتراک (برای کپی لمس کنید):",
            f"<code>{e(link)}</code>",
            "",
            "📷 برای اتصال سریع، QR کد را در برنامه اسکن کنید.",
        ]
    else:
        lines += ["", "🔗 لینک اشتراک در حال آماده‌سازی است؛ از بخش «اکانت‌ها» دریافت کنید."]
    if balance is not None:
        lines += ["", f"💰 موجودی کیف پول: <b>{_money(balance)}</b> {e(currency)}"]
    return "\n".join(lines)


def build_plain_body(*, link: str | None, balance: int | None, currency: str) -> str:
    """Plain-text body stored for the in-app notification (website bell)."""
    parts = ["اکانت شما با موفقیت آماده شد."]
    if link:
        parts.append(f"لینک اشتراک: {link}")
    if balance is not None:
        parts.append(f"موجودی کیف پول: {_money(balance)} {currency}")
    return "\n".join(parts)


async def balance_after_payment(session: AsyncSession, order: Order) -> int | None:
    """Wallet balance right after this order's payment (from the ledger), else the current balance.

    Free orders (test accounts) have no payment, so no balance line is shown.
    """
    if not order.total:
        return None
    after = await session.scalar(
        select(LedgerEntry.balance_after)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .join(Wallet, Wallet.id == LedgerEntry.wallet_id)
        .where(LedgerTransaction.idempotency_key == f"order:{order.id}:payment", Wallet.user_id == order.user_id, Wallet.kind == "customer")
    )
    if after is not None:
        return int(after)
    w = await session.scalar(
        select(Wallet).where(
            Wallet.user_id == order.user_id, Wallet.store_id == order.store_id, Wallet.kind == "customer", Wallet.currency == order.currency
        )
    )
    return int(w.balance) if w else None


def _link_wait_expired(order: Order) -> bool:
    done = order.completed_at
    if done is None:
        return False
    if done.tzinfo is None:
        done = done.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) - done > LINK_WAIT


async def deliver_order(session: AsyncSession, order_id: uuid.UUID) -> str:
    """Send the delivery post. Returns sent | skipped. Raises on transport failure so the outbox retries."""
    order = await session.get(Order, order_id)
    if order is None:
        return "skipped"
    account = (
        await session.get(VpnAccount, order.vpn_account_id)
        if order.vpn_account_id
        else await session.scalar(select(VpnAccount).where(VpnAccount.order_id == order.id))
    )
    if account is None:
        return "skipped"

    link = account.subscription_url or ((account.links or [None])[0] if isinstance(account.links, list) else None)
    if not link and not _link_wait_expired(order):
        raise LinkNotReady(f"order {order.id}: subscription link not ready")
    balance = await balance_after_payment(session, order)
    currency = order.currency

    dedup = f"delivery:{order.id}"
    n = await session.scalar(select(Notification).where(Notification.dedup_key == dedup))
    if n and n.telegram_status == "sent":
        return "skipped"
    if n is None:
        n = Notification(
            user_id=order.user_id,
            store_id=order.store_id,
            kind="vpn_account",
            title="اکانت شما آماده شد",
            body=build_plain_body(link=link, balance=balance, currency=currency),
            dedup_key=dedup,
        )
        session.add(n)
        await session.flush()

    identity = await session.scalar(select(Identity).where(Identity.user_id == order.user_id, Identity.provider == "telegram"))
    store = await session.get(Store, order.store_id)
    token = decrypt(store.bot_token_enc) if store and store.bot_token_enc else get_settings().main_bot_token
    if not identity or not token:
        n.telegram_status = "skipped"
        await session.commit()
        return "skipped"

    from melorin.channels.telegram import TelegramChannel

    channel = TelegramChannel(token, get_settings().store_web_url, "reseller" if store and store.kind == "reseller" else "main")
    caption = build_caption(order=order, account=account, link=link, balance=balance, currency=currency)
    try:
        if link and len(caption) <= CAPTION_LIMIT:
            await channel.send_photo(identity.subject, render_qr_png(link), caption=caption, parse_mode="HTML")
        elif link:
            # Extremely long link: keep the photo post, but never exceed Telegram's caption limit.
            short = build_caption(order=order, account=account, link=None, balance=balance, currency=currency)
            await channel.send_photo(identity.subject, render_qr_png(link), caption=short[:CAPTION_LIMIT], parse_mode="HTML")
            await channel.send_message(identity.subject, f"🔗 {link}")
        else:
            await channel.send_message(identity.subject, caption, parse_mode="HTML")
        n.telegram_status = "sent"
        await session.commit()
        inc("melorin_notifications_total", channel="telegram", result="sent")
        return "sent"
    except Exception:
        n.telegram_status = "failed"
        await session.commit()
        inc("melorin_notifications_total", channel="telegram", result="failed")
        raise
