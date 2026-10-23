"""Telegram Event Center (SRS §17): destination settings, fan-out and delivery.

* One destination per Admin (``store_id`` NULL) and per reseller store: a Telegram supergroup (with Topics) plus a map of
  topic -> ``message_thread_id``.
* ``publish`` runs inside the caller's transaction and only writes one ``eventcenter.deliver`` outbox row per destination
  (dedup key = source event + destination), so Telegram is never called in a money-path transaction and a retry resends
  only the destination that failed.
* ``deliver`` runs in the worker. A permanent Telegram error (bot removed, wrong chat) is recorded on the destination and
  not retried; a transient one (429/5xx/network) is raised so the outbox backs off and retries.
* A reseller's destination is served ONLY by that reseller's own bot token; the main bot is never used for a reseller group.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.channels.telegram.bot_api import TelegramApiError, TelegramChannel
from melorin.core import audit, events
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.notifications import TelegramEventDestination
from melorin.kernel.models.stores import Store
from melorin.modules.eventcenter.topics import ADMIN_COPY_TOPICS, TOPICS

CHAT_ID = re.compile(r"^-100[0-9]{5,15}$")
MAX_THREAD_ID = 2**31 - 1
TEXT_MAX = 3900


def parse_chat_id(raw: object) -> str:
    """A supergroup id looks like ``-1001234567890``; ``@username`` or a private id is refused."""
    value = str(raw if raw is not None else "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).strip()
    if not CHAT_ID.match(value):
        raise AppError(
            "INVALID_CHAT_ID",
            "شناسهٔ گروه معتبر نیست؛ باید سوپرگروه باشد و با -100 شروع شود (مثلاً -1001234567890).",
            422,
        )
    return value


def parse_topics(raw: object) -> dict[str, int]:
    """Keep only known topics with a positive integer thread id; an empty value means 'use General'."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise AppError("INVALID_TOPICS", "قالب Topicها نامعتبر است.", 422)
    out: dict[str, int] = {}
    for key, value in raw.items():
        if key not in TOPICS:
            raise AppError("INVALID_TOPICS", f"Topic ناشناخته: {key}", 422)
        if value in (None, ""):
            continue
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise AppError("INVALID_TOPICS", f"شناسهٔ Topic «{TOPICS[key]}» باید عدد باشد.", 422) from None
        if not 1 <= n <= MAX_THREAD_ID:
            raise AppError("INVALID_TOPICS", f"شناسهٔ Topic «{TOPICS[key]}» نامعتبر است.", 422)
        out[key] = n
    return out


async def get_destination(session: AsyncSession, store_id: uuid.UUID | None) -> TelegramEventDestination | None:
    cond = TelegramEventDestination.store_id.is_(None) if store_id is None else TelegramEventDestination.store_id == store_id
    return await session.scalar(select(TelegramEventDestination).where(cond))


def view(dest: TelegramEventDestination | None, *, bot_ready: bool) -> dict:
    topics = [{"key": k, "label": label, "thread_id": ((dest.topics or {}).get(k) if dest else None)} for k, label in TOPICS.items()]
    return {
        "configured": dest is not None,
        "bot_ready": bot_ready,
        "chat_id": dest.chat_id if dest else None,
        "is_enabled": dest.is_enabled if dest else False,
        "note": dest.note if dest else None,
        "topics": topics,
        "last_sent_at": dest.last_sent_at if dest else None,
        "last_error": dest.last_error if dest else None,
        "last_error_at": dest.last_error_at if dest else None,
    }


def _store_token(store: Store | None) -> str | None:
    """Admin group -> main bot; reseller group -> that reseller's own bot only."""
    if store is not None and store.kind == "reseller":
        return decrypt(store.bot_token_enc) if store.bot_token_enc else None
    return get_settings().main_bot_token or None


async def bot_ready(session: AsyncSession, store: Store | None) -> bool:
    return bool(_store_token(store))


async def save(
    session: AsyncSession,
    *,
    store: Store | None,
    actor_id: uuid.UUID,
    chat_id: object,
    topics: object,
    is_enabled: bool,
    note: str | None,
) -> TelegramEventDestination:
    """Create or replace the destination. The caller commits."""
    if store is not None and store.kind == "reseller" and not store.bot_token_enc:
        raise AppError("EVENT_CENTER_NO_BOT", "ابتدا ربات فروشگاه را متصل کنید؛ پیام‌ها فقط با ربات خود نماینده ارسال می‌شود.", 409)
    cid, tps = parse_chat_id(chat_id), parse_topics(topics)
    dest = await get_destination(session, store.id if store is not None and store.kind == "reseller" else None)
    owner_id = store.id if store is not None and store.kind == "reseller" else None
    before = None
    if dest is None:
        dest = TelegramEventDestination(store_id=owner_id, chat_id=cid, topics=tps, is_enabled=is_enabled, note=(note or None))
        session.add(dest)
    else:
        before = {"chat_id": dest.chat_id, "topics": dest.topics, "is_enabled": dest.is_enabled}
        if dest.chat_id != cid:  # a new group starts with a clean health record
            dest.last_sent_at = dest.last_error = dest.last_error_at = None
        dest.chat_id, dest.topics, dest.is_enabled, dest.note = cid, tps, is_enabled, (note or None)
    await session.flush()
    audit.record(
        session,
        "event_center.saved",
        actor_id=actor_id,
        actor_type="admin" if owner_id is None else "reseller",
        entity_type="telegram_event_destination",
        entity_id=dest.id,
        store_id=owner_id,
        data={"before": before, "after": {"chat_id": cid, "topics": tps, "is_enabled": is_enabled}},
    )
    return dest


async def remove(session: AsyncSession, *, store: Store | None, actor_id: uuid.UUID) -> bool:
    owner_id = store.id if store is not None and store.kind == "reseller" else None
    dest = await get_destination(session, owner_id)
    if dest is None:
        return False
    audit.record(
        session,
        "event_center.removed",
        actor_id=actor_id,
        actor_type="admin" if owner_id is None else "reseller",
        entity_type="telegram_event_destination",
        entity_id=dest.id,
        store_id=owner_id,
        data={"chat_id": dest.chat_id},
    )
    await session.delete(dest)
    return True


def _clip(text: str) -> str:
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1] + "…"


def _plain(text: str) -> str:
    """Customer-written text (ticket subject, error detail) must not ping people in the group: ``@name`` is broken with a
    zero-width space so Telegram no longer treats it as a mention."""
    return text.replace("@", "@\u200b")


async def _send(token: str, dest: TelegramEventDestination, topic: str, text: str) -> None:
    """One send into the topic. A topic deleted in Telegram falls back once to the group's General."""
    channel = TelegramChannel(token, get_settings().store_web_url or "https://core.invalid", "main")
    thread = (dest.topics or {}).get(topic)
    try:
        await channel.send_to_topic(dest.chat_id, _clip(_plain(text)), thread_id=thread)
    except TelegramApiError as exc:
        if thread and exc.code == 400 and "thread" in exc.description.lower():
            await channel.send_to_topic(dest.chat_id, _clip(_plain(text)), thread_id=None)
            return
        raise


def _record_ok(dest: TelegramEventDestination) -> None:
    dest.last_sent_at, dest.last_error, dest.last_error_at = utcnow(), None, None


def _record_error(dest: TelegramEventDestination, exc: Exception) -> None:
    desc = exc.description if isinstance(exc, TelegramApiError) else type(exc).__name__
    code = f"{exc.code} " if isinstance(exc, TelegramApiError) else ""
    dest.last_error, dest.last_error_at = f"{code}{desc}"[:300], utcnow()


async def send_test(session: AsyncSession, *, store: Store | None) -> list[dict]:
    """Synchronous test so the panel shows the real outcome: one message per configured topic (General when none)."""
    owner_id = store.id if store is not None and store.kind == "reseller" else None
    dest = await get_destination(session, owner_id)
    if dest is None:
        raise AppError("EVENT_CENTER_NOT_SET", "ابتدا گروه رویدادها را تنظیم کنید.", 404)
    token = _store_token(store)
    if not token:
        raise AppError("EVENT_CENTER_NO_BOT", "ربات این گروه متصل نیست.", 409)
    topics = [k for k in TOPICS if (dest.topics or {}).get(k)] or [""]
    results: list[dict] = []
    for key in topics:
        label = TOPICS.get(key, "General")
        try:
            await _send(token, dest, key, f"✅ تست مرکز رویداد ملورین\nتاپیک: {label}")
            _record_ok(dest)
            results.append({"topic": key or "general", "label": label, "ok": True})
        except Exception as exc:
            _record_error(dest, exc)
            results.append({"topic": key or "general", "label": label, "ok": False, "error": dest.last_error})
    await session.commit()
    return results


def _channel(token: str) -> TelegramChannel:
    return TelegramChannel(token, get_settings().store_web_url or "https://core.invalid", "main")


def tg_error(exc: TelegramApiError) -> AppError:
    """Translate a Telegram failure into a message the panel owner can act on."""
    d = exc.description.lower()
    if exc.code == 401:
        return AppError("EVENT_CENTER_BAD_TOKEN", "توکن ربات نامعتبر است.", 409)
    if "not a forum" in d or ("forum" in d and "not" in d):
        return AppError("EVENT_CENTER_NOT_FORUM", "قابلیت Topics در گروه فعال نیست؛ از تنظیمات گروه «Topics» را روشن کنید.", 409)
    if "not enough rights" in d or "manage topics" in d or "can_manage_topics" in d:
        return AppError("EVENT_CENTER_NO_RIGHTS", "ربات باید ادمین گروه با دسترسی «Manage Topics» باشد.", 409)
    if "chat not found" in d:
        return AppError("EVENT_CENTER_CHAT_NOT_FOUND", "گروه پیدا نشد؛ شناسه را بررسی کنید و ربات را به گروه اضافه کنید.", 409)
    if exc.code in (403, 404) or "kicked" in d:
        return AppError("EVENT_CENTER_BOT_REMOVED", "ربات از گروه حذف شده یا اجازهٔ ارسال ندارد.", 409)
    if exc.permanent:
        return AppError("EVENT_CENTER_TELEGRAM_REJECTED", f"تلگرام درخواست را رد کرد: {exc.description[:150]}", 409)
    return AppError("EVENT_CENTER_TELEGRAM_UNAVAILABLE", "تلگرام موقتاً در دسترس نیست؛ کمی بعد دوباره تلاش کنید.", 503)


async def _require_ready(session: AsyncSession, store: Store | None) -> tuple[TelegramEventDestination, str]:
    owner_id = store.id if store is not None and store.kind == "reseller" else None
    dest = await get_destination(session, owner_id)
    if dest is None:
        raise AppError("EVENT_CENTER_NOT_SET", "ابتدا گروه رویدادها را تنظیم کنید.", 404)
    token = _store_token(store)
    if not token:
        raise AppError("EVENT_CENTER_NO_BOT", "ربات این گروه متصل نیست.", 409)
    return dest, token


async def _probe(token: str, chat_id: str) -> dict:
    """Ask Telegram who the bot is and what it may do in the group. Raises :class:`TelegramApiError`."""
    ch = _channel(token)
    me = await ch.get_me()
    chat = await ch.get_chat(chat_id)
    member = await ch.get_chat_member(chat_id, int(me["id"]))
    status = str(member.get("status") or "")
    admin = status in ("administrator", "creator")
    return {
        "title": chat.get("title"),
        "type": chat.get("type"),
        "is_forum": bool(chat.get("is_forum")),
        "bot_username": me.get("username"),
        "bot_status": status,
        "can_post": status in ("administrator", "creator", "member") or (status == "restricted" and bool(member.get("can_send_messages"))),
        "can_manage_topics": status == "creator" or (admin and bool(member.get("can_manage_topics"))),
    }


def _problems(info: dict) -> list[str]:
    out: list[str] = []
    if info["type"] != "supergroup":
        out.append("گروه باید سوپرگروه باشد (در تنظیمات گروه آن را به سوپرگروه تبدیل کنید).")
    if not info["can_post"]:
        out.append("ربات عضو گروه نیست یا اجازهٔ ارسال پیام ندارد.")
    if not info["is_forum"]:
        out.append("قابلیت Topics گروه خاموش است؛ پیام‌ها فقط در General می‌آید.")
    elif not info["can_manage_topics"]:
        out.append("برای ساخت خودکار Topic، ربات باید ادمین با دسترسی «Manage Topics» باشد.")
    return out


async def inspect(session: AsyncSession, *, store: Store | None) -> dict:
    """Read-only health check of the configured group: bot membership, Topics switch and rights."""
    dest, token = await _require_ready(session, store)
    try:
        info = await _probe(token, dest.chat_id)
    except TelegramApiError as exc:
        raise tg_error(exc) from exc
    configured = {k: bool((dest.topics or {}).get(k)) for k in TOPICS}
    problems = _problems(info)
    return {
        **info,
        "problems": problems,
        "ok": not problems,
        "missing_topics": [k for k, has in configured.items() if not has],
    }


async def provision_topics(session: AsyncSession, *, store: Store | None, actor_id: uuid.UUID) -> dict:
    """Create the forum topics that have no thread id yet (Mirza-style "sync topics") and save their ids.

    Existing thread ids are never touched. Each created topic is committed at once, so a failure half-way (or a double
    click) can never create the same topic twice or lose ids that Telegram already handed out.
    """
    dest, token = await _require_ready(session, store)
    owner_id = store.id if store is not None and store.kind == "reseller" else None
    dest = await session.get(TelegramEventDestination, dest.id, with_for_update=True) or dest
    try:
        info = await _probe(token, dest.chat_id)
    except TelegramApiError as exc:
        raise tg_error(exc) from exc
    if not info["is_forum"]:
        raise AppError("EVENT_CENTER_NOT_FORUM", "قابلیت Topics در گروه فعال نیست؛ از تنظیمات گروه «Topics» را روشن کنید.", 409)
    if not info["can_manage_topics"]:
        raise AppError("EVENT_CENTER_NO_RIGHTS", "ربات باید ادمین گروه با دسترسی «Manage Topics» باشد.", 409)
    channel = _channel(token)
    results: list[dict] = []
    for key, label in TOPICS.items():
        if (dest.topics or {}).get(key):
            results.append({"topic": key, "label": label, "status": "kept", "thread_id": dest.topics[key]})
            continue
        try:
            thread_id = await channel.create_forum_topic(dest.chat_id, label)
        except TelegramApiError as exc:
            _record_error(dest, exc)
            results.append({"topic": key, "label": label, "status": "failed", "error": dest.last_error})
            await session.commit()
            break  # rights / rate limit problems hit every remaining topic too
        dest.topics = {**(dest.topics or {}), key: thread_id}
        results.append({"topic": key, "label": label, "status": "created", "thread_id": thread_id})
        audit.record(
            session,
            "event_center.topic_created",
            actor_id=actor_id,
            actor_type="admin" if owner_id is None else "reseller",
            entity_type="telegram_event_destination",
            entity_id=dest.id,
            store_id=owner_id,
            data={"topic": key, "thread_id": thread_id},
        )
        await session.commit()
    await session.commit()
    return {"results": results, "created": sum(r["status"] == "created" for r in results)}


async def publish(
    session: AsyncSession,
    *,
    store_id: uuid.UUID | None,
    topic: str,
    text: str,
    source_key: str,
) -> int:
    """Queue the event for the right destinations. Returns how many deliveries were queued. Never talks to Telegram.

    Routing: an event of a reseller store goes to that store's group only, plus (for ``debt`` / ``errors``) the admin's
    group with the store name in front. An event of the Main Store, or one without a store, goes to the admin's group.
    """
    if topic not in TOPICS:
        raise ValueError(f"unknown event-center topic {topic!r}")
    store = await session.get(Store, store_id) if store_id else None
    queued = 0
    targets: list[tuple[uuid.UUID | None, str]] = []
    if store is not None and store.kind == "reseller":
        targets.append((store.id, text))
        if topic in ADMIN_COPY_TOPICS:
            targets.append((None, f"[{store.name}] {text}"))
    else:
        targets.append((None, text))
    for owner_id, body in targets:
        dest = await get_destination(session, owner_id)
        if dest is None or not dest.is_enabled:
            continue
        await events.emit(
            session,
            events.EVENT_CENTER_DELIVER,
            {"destination_id": dest.id, "topic": topic, "text": body},
            dedup_key=f"ec:{source_key}:{dest.id}",
        )
        queued += 1
    return queued


async def deliver(session: AsyncSession, payload: dict) -> None:
    """Worker side of one queued delivery. Raises only for transient failures, so the outbox retries just this one."""
    dest = await session.get(TelegramEventDestination, uuid.UUID(str(payload["destination_id"])), with_for_update=True)
    if dest is None or not dest.is_enabled:
        return
    store = await session.get(Store, dest.store_id) if dest.store_id else None
    token = _store_token(store)
    if not token:
        _record_error(dest, RuntimeError("bot token missing"))
        return
    try:
        await _send(token, dest, str(payload.get("topic") or ""), str(payload.get("text") or ""))
    except TelegramApiError as exc:
        _record_error(dest, exc)
        if exc.permanent:
            return  # bot removed / wrong group: shown in the panel, retrying cannot help
        await session.commit()  # keep the error visible, then let the outbox back off
        raise
    except Exception as exc:
        _record_error(dest, exc)
        await session.commit()
        raise
    _record_ok(dest)
