"""Reseller Telegram runner.

Same Core-authenticated transport as the main runner, bound to one reseller Store
(``MELORIN_STORE_SLUG``). Customers get the full storefront; Store owners get extra
commands (/report, /customers, /payments). Authorization is enforced by Core (403 for
non-owners); this process never holds panel/server credentials or other stores' data.
"""
import os
import asyncio
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_here = Path(__file__).parent
_path = next(p for p in (_here / "telegram-main" / "runner.py", _here.parent / "telegram-main" / "runner.py") if p.exists())
_spec = spec_from_file_location("melorin_telegram_main_runner", _path)
_module = module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)
money, keyboard = _module.money, _module.keyboard

OWNER_HELP = "\n\nبخش نماینده:\n/report گزارش فروش\n/customers مشتریان\n/payments پرداخت‌های در انتظار تأیید"


class ResellerTelegramRunner(_module.TelegramRunner):
    channel = "reseller"

    def __init__(self, *, token: str | None = None, slug: str | None = None, state_suffix: str | None = None):
        os.environ["MELORIN_TELEGRAM_TOKEN"] = token or os.environ["MELORIN_TELEGRAM_RESELLER_TOKEN"]
        self.slug = slug or os.environ["MELORIN_STORE_SLUG"]
        if state_suffix:
            os.environ["MELORIN_TELEGRAM_OFFSET_FILE"] = f"/var/lib/melorin/reseller-{state_suffix}-offset.json"
        super().__init__()
        self.commands.update({"/report": self.cmd_report, "/customers": self.cmd_customers, "/payments": self.cmd_payments})
        self.callbacks["rv"] = self.cb_review

    async def store_info(self) -> dict:
        if self.store is None:
            r = await self.client.get(f"{self.core}/api/v1/stores/by-slug/{self.slug}")
            r.raise_for_status()
            self.store = r.json()
        return self.store

    async def cmd_help(self, ctx, arg):
        await self.send(ctx.chat_id, _module.HELP + OWNER_HELP, _module.MENU)

    async def cmd_report(self, ctx, arg):
        s = await self.store_info()
        rep = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/reports")
        lines = [f"{o['status']}: {o['count']} سفارش · فروش {money(o['total'])} · بها {money(o['reseller_cost'])}" for o in rep["orders"]]
        await self.send(ctx.chat_id, f"گزارش ({rep['currency']}):\n" + ("\n".join(lines) or "—"))

    async def cmd_customers(self, ctx, arg):
        s = await self.store_info()
        cs = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/customers")
        lines = [f"{c.get('display_name') or c.get('email') or c['user_id'][:8]} · {c['status']}" for c in cs[:30]]
        await self.send(ctx.chat_id, f"مشتریان ({len(cs)}):\n" + ("\n".join(lines) or "—"))

    async def cmd_payments(self, ctx, arg):
        s = await self.store_info()
        ps = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/payments")
        todo = [p for p in ps if p["status"] not in ("succeeded", "failed") and p.get("has_receipt")][:10]
        if not todo:
            return await self.send(ctx.chat_id, "پرداخت در انتظار تأییدی نیست.")
        for p in todo:
            await self.send(ctx.chat_id, f"پرداخت {money(p['amount'])} {p['currency']} · {p['provider']}",
                            [[("✅ تأیید", f"rv:{p['id']}:1"), ("❌ رد", f"rv:{p['id']}:0")]])

    async def cb_review(self, ctx, rest):
        pid, _, flag = rest.partition(":")
        s = await self.store_info()
        await self.api(ctx, "POST", f"/api/v1/stores/{s['id']}/reseller/payments/{pid}/review", json={"approve": flag == "1", "note": None if flag == "1" else "رد از طریق ربات"})
        await self.send(ctx.chat_id, "پرداخت تأیید شد ✅" if flag == "1" else "پرداخت رد شد ❌")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    raw = os.getenv("MELORIN_RESELLER_BOTS_JSON", "").strip()
    if raw:
        try:
            configs = json.loads(raw)
            if not isinstance(configs, list) or not configs:
                raise ValueError
            bots = []
            for i, cfg in enumerate(configs):
                if not isinstance(cfg, dict) or not cfg.get("token") or not cfg.get("store_slug"):
                    raise ValueError("each bot needs token and store_slug")
                slug = str(cfg["store_slug"])
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)[:60]
                bots.append(ResellerTelegramRunner(token=str(cfg["token"]), slug=slug, state_suffix=f"{i}-{safe}"))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"MELORIN_RESELLER_BOTS_JSON is invalid: {exc}") from exc
        async def run_all():
            await asyncio.gather(*(bot.run() for bot in bots))

        asyncio.run(run_all())
    else:
        asyncio.run(ResellerTelegramRunner().run())
