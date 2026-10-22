"""Wallet balance, top-up (card/receipt) and order history."""

import logging
import re

from tgmain.ui import (
    ORDER_STATUS,
    TX_KIND,
    esc,
    fmt,
    money,
)
from tgmain.errors import CoreError

log = logging.getLogger("melorin.telegram.main")


class WalletMixin:
    """Wallet balance, top-up (card/receipt) and order history."""

    # ----- wallet -----
    async def cmd_wallet(self, ctx, arg):
        store = await self.store_info()
        w = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet")
        tx = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/wallet/transactions")
        items = tx if isinstance(tx, list) else tx.get("items", [])
        lines = [f"💰 <b>کیف پول</b>\n\nموجودی: <b>{esc(fmt(w['balance'], w['currency']))}</b>"]
        if items:
            lines.append("\n🕘 آخرین تراکنش‌ها:")
            for t in items[:5]:
                amt = int(t["amount"])
                lines.append(f"{TX_KIND.get(t['kind'], esc(t['kind']))}  {'➕' if amt > 0 else '➖'} {money(abs(amt))}")
        lines.append("\nبرای شارژ، مبلغ را انتخاب کنید:")
        amounts = [
            [("۲۰۰,۰۰۰ تومان", "wallet:amount:200000"), ("۵۰۰,۰۰۰ تومان", "wallet:amount:500000")],
            [("۱,۰۰۰,۰۰۰ تومان", "wallet:amount:1000000"), ("✏️ مبلغ دلخواه", "wallet:amount:custom")],
        ]
        await self.screen(ctx, "\n".join(lines), amounts)

    async def cb_wallet_amount(self, ctx, value):
        # Callback data is split once in handle(), so this receives
        # "amount:200000" or "amount:custom", not just the suffix.
        prefix, _, raw = value.partition(":")
        if prefix != "amount":
            raise CoreError(400, "گزینه شارژ نامعتبر است. دوباره از منوی کیف پول انتخاب کنید.")
        if raw == "custom":
            self._set_state(ctx.chat_id, {"topup_amount": True})
            return await self.send(ctx.chat_id, "مبلغ دلخواه را به تومان وارد کنید (فقط عدد):")
        if not re.fullmatch(r"\d+", raw) or int(raw) <= 0:
            raise CoreError(400, "مبلغ شارژ نامعتبر است.")
        await self.create_topup(ctx, int(raw))

    async def create_topup(self, ctx, amount):
        store = await self.store_info()
        p = await self.api(
            ctx,
            "POST",
            f"/api/v1/stores/{store['id']}/wallet/topups",
            headers={"Idempotency-Key": f"{ctx.idem}-topup"},
            json={"amount": amount, "provider": "manual_card"},
        )
        ins = p.get("instructions") or {}
        lines = [f"💳 <b>درخواست شارژ {esc(fmt(p['amount'], p['currency']))} ثبت شد</b>", ""]
        if ins.get("card_number"):
            lines += [
                "شماره کارت (برای کپی لمس کنید):",
                f"<code>{esc(ins['card_number'])}</code>",
                f"به نام: {esc(ins.get('holder', '-'))}",
                f"بانک: {esc(ins.get('bank', '-'))}",
            ]
        if ins.get("redirect_url"):
            lines.append(f"🌐 پرداخت آنلاین: {esc(ins['redirect_url'])}")
        else:
            lines += ["", "📸 پس از واریز، عکس رسید را همین‌جا بفرستید."]
            self._set_state(ctx.chat_id, {"receipt_payment": p["id"]})
        await self.send(ctx.chat_id, "\n".join(lines), html=True)

    async def cmd_topup(self, ctx, arg):
        digits = "".join(ch for ch in arg.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")) if ch.isdigit())
        if not digits or int(digits) <= 0:
            return await self.send(ctx.chat_id, "مبلغ را وارد کنید. مثال: /topup 100000")
        await self.create_topup(ctx, int(digits))

    async def cmd_orders(self, ctx, arg):
        store = await self.store_info()
        os_ = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/orders")
        lines = [
            f"🧾 <code>{esc(o['number'])}</code> · {esc(fmt(o['total'], o['currency']))} · {ORDER_STATUS.get(o['status'], esc(o['status']))}"
            for o in os_[:10]
        ]
        await self.screen(ctx, "📦 <b>سفارش‌ها</b>\n\n" + ("\n".join(lines) or "هنوز سفارشی ندارید."), [[("🛒 خرید اکانت", "menu:plans")]])
