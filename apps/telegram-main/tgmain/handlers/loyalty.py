"""Customer loyalty club of THIS store: points, tier, rewards. Core decides every number and every rule; the bot shows and asks."""

from tgmain.errors import CoreError
from tgmain.ui import esc, loyalty_keyboard_rows, loyalty_text


class LoyaltyMixin:
    async def _club(self, ctx) -> dict:
        store = await self.store_info()
        return await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/loyalty")

    async def cmd_club(self, ctx, arg):
        await self._show_club(ctx)

    async def _show_club(self, ctx, note: str | None = None):
        data = await self._club(ctx)
        text = loyalty_text(data)
        if note:
            text = f"{note}\n\n{text}"
        await self.screen(ctx, text, loyalty_keyboard_rows(data))

    async def cb_loyalty(self, ctx, rest):
        """``loy:r:<reward id>`` spends points on one reward; anything else just reopens the club."""
        kind, _, arg = rest.partition(":")
        if kind != "r" or not arg:
            return await self._show_club(ctx)
        store = await self.store_info()
        try:
            # The key comes from the callback id, so a replayed tap returns the first result and never spends twice.
            done = await self.api(
                ctx,
                "POST",
                f"/api/v1/stores/{store['id']}/loyalty/rewards/{arg}/redeem",
                headers={"Idempotency-Key": f"{ctx.idem}-loyalty"},
            )
        except CoreError as exc:
            return await self._show_club(ctx, f"⚠️ {esc(exc.message)}")
        await self._show_club(ctx, "✅ پاداش شما به کیف پول اضافه شد." if not done.get("replayed") else "✅ این درخواست قبلاً ثبت شده بود.")
