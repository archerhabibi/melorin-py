#!/usr/bin/env python3
"""One-time login of the dedicated Telegram *user* account that drives a parent VPN bot (upstream_bot panel).

    pip install telethon
    python scripts/upstream_bot_login.py            # asks api_id / api_hash (https://my.telegram.org), phone, code, 2FA

Prints a StringSession. Paste it as ``session`` in the panel credentials (Admin -> Panels -> kind upstream_bot).
Treat it like a password: it is full access to that Telegram account. Use a separate number, not your personal one.
"""

import asyncio
import getpass


async def main() -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = int(input("api_id: ").strip())
    api_hash = getpass.getpass("api_hash (hidden): ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:  # prompts for phone, code and 2FA
        me = await client.get_me()
        print(f"\nLogged in as {me.first_name} (id {me.id}). Session string (keep secret):\n")
        print(client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
