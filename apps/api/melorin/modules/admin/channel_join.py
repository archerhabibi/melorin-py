"""Admin API - mandatory channel membership ("force join") of the main Telegram bot.

``GET/PUT /admin/telegram/channel-join`` read and edit the configuration (one switch, up to five channels, the message the
user sees and how long a confirmed membership is remembered). ``POST .../check`` probes the submitted - not necessarily
saved - channels with the main bot (exists? is the bot an admin?) so the admin can fix a channel before turning the gate on.

Enforcement lives in ``melorin.modules.channel_gate`` and runs at bot sign-in; nothing here is ever sent to the bots.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.domain import channel_join as cj
from melorin.modules.channel_gate import service as gate

router = APIRouter(prefix="/admin", tags=["admin"])


class ChannelIn(BaseModel):
    chat: str = Field(max_length=128)  # @username, t.me link or -100... id; the domain canonicalises it
    title: str | None = Field(default=None, max_length=256)
    url: str | None = Field(default=None, max_length=256)


class ChannelJoinIn(BaseModel):
    enabled: bool = False
    channels: list[ChannelIn] = Field(default_factory=list, max_length=cj.MAX_CHANNELS)
    message: str | None = Field(default=None, max_length=4 * cj.MAX_MESSAGE)  # the exact limit is the domain's (Persian error)
    cache_seconds: int = Field(default=cj.DEFAULT["cache_seconds"], ge=cj.MIN_CACHE_SECONDS, le=cj.MAX_CACHE_SECONDS)


class ChannelOut(BaseModel):
    chat: str
    title: str
    url: str


class ChannelJoinConfigOut(BaseModel):
    enabled: bool
    channels: list[ChannelOut]
    message: str
    cache_seconds: int


class ChannelJoinDefaultsOut(BaseModel):
    message: str
    cache_seconds: int


class ChannelJoinLimitsOut(BaseModel):
    max_channels: int
    max_message: int
    max_cache_seconds: int


class ChannelJoinView(BaseModel):
    config: ChannelJoinConfigOut
    defaults: ChannelJoinDefaultsOut
    limits: ChannelJoinLimitsOut


class ChannelCheckOut(ChannelOut):
    ok: bool
    problem: str | None = None
    telegram_title: str | None = None
    type: str | None = None
    bot_status: str | None = None


class ChannelJoinCheck(BaseModel):
    bot_username: str | None = None
    ok: bool
    channels: list[ChannelCheckOut]


def _normalize(body: ChannelJoinIn, **override) -> dict:
    try:
        return cj.normalize({**body.model_dump(), **override})
    except cj.ChannelJoinError as exc:
        raise AppError("CHANNEL_JOIN_INVALID", str(exc), 422) from exc


def _view(cfg: dict) -> dict:
    return {
        "config": cfg,
        "defaults": {"message": cj.DEFAULT_MESSAGE, "cache_seconds": cj.DEFAULT["cache_seconds"]},
        "limits": {"max_channels": cj.MAX_CHANNELS, "max_message": cj.MAX_MESSAGE, "max_cache_seconds": cj.MAX_CACHE_SECONDS},
    }


@router.get("/telegram/channel-join", response_model=ChannelJoinView)
async def get_channel_join(_: AdminUser, session: Session):
    return _view(await gate.load(session))


@router.put("/telegram/channel-join", response_model=ChannelJoinView)
async def put_channel_join(body: ChannelJoinIn, admin: AdminUser, session: Session):
    cfg = _normalize(body)
    before = await gate.load(session)
    await gate.save(session, cfg)
    audit.record(
        session,
        "integration.telegram.channel_join.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="integration",
        entity_id="telegram_channel_join",
        data={"enabled": cfg["enabled"], "was_enabled": before["enabled"], "channels": [c["chat"] for c in cfg["channels"]]},
    )
    await session.commit()
    return _view(cfg)


@router.post("/telegram/channel-join/check", response_model=ChannelJoinCheck)
async def check_channel_join(body: ChannelJoinIn, _: AdminUser, session: Session):
    cfg = _normalize(body, enabled=False)  # checking never requires the switch; an empty list is simply "nothing to check"
    if not cfg["channels"]:
        raise AppError("CHANNEL_JOIN_INVALID", "ابتدا دست‌کم یک کانال اضافه کنید.", 422)
    return await gate.inspect(session, cfg)
