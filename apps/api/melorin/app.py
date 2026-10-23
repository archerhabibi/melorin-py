import hmac
import logging
import time
import asyncio

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from melorin.core.config import get_settings
from melorin.core.db import configure
from melorin.core.errors import install
from melorin.core.health import build_checks, probe_database, probe_worker, publish_signals
from melorin.core.logging import setup_logging
from melorin.core.middleware import CorrelationMiddleware, SecurityHeadersMiddleware
from melorin.core.metrics import render, set_alert, set_gauge
from melorin.modules.eventcenter.routes import admin_router as event_center_admin_router, reseller_router as event_center_reseller_router
from melorin.modules.admin.router import router as admin_router
from melorin.modules.catalog.router import public as catalog_router
from melorin.modules.identity.router import auth as auth_router, me as me_router
from melorin.channels.telegram.oidc_router import tgoidc as telegram_oidc_router
from melorin.channels.telegram.web_router import tgweb as telegram_web_router
from melorin.modules.notifications.router import router as notifications_router
from melorin.modules.orders.router import router as orders_router
from melorin.modules.payments.router import router as payments_router
from melorin.modules.reseller.bots import internal as internal_router
from melorin.modules.reseller.router import api_router as reseller_api_router, router as reseller_router
from melorin.modules.reports.router import router as reports_router
from melorin.modules.referral.router import router as referral_router
from melorin.modules.tickets.router import router as tickets_router
from melorin.modules.vpn.router import router as vpn_router
from melorin.modules.wallet.router import router as wallet_router

setup_logging()
s = get_settings()
health_log = logging.getLogger("melorin.health")
configure()

app = FastAPI(
    title=s.app_name,
    version="1.0.0",
    description="Melorin Core API",
    docs_url="/docs" if s.is_dev else None,
    redoc_url="/redoc" if s.is_dev else None,
    openapi_url="/openapi.json" if s.is_dev else None,
)
app.add_middleware(CorrelationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origins,
    allow_credentials=True,
    allow_methods=s.cors_allow_methods,
    allow_headers=s.cors_allow_headers,
    expose_headers=["X-Total-Count"],
)
# Outermost (added last) so CORS preflights and error responses carry the security headers too.
app.add_middleware(SecurityHeadersMiddleware)
install(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(telegram_web_router, prefix="/api/v1")
app.include_router(telegram_oidc_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(wallet_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(vpn_router, prefix="/api/v1")
app.include_router(reseller_router, prefix="/api/v1")
app.include_router(internal_router, prefix="/api/v1")
app.include_router(reseller_api_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(referral_router, prefix="/api/v1")
app.include_router(tickets_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(event_center_admin_router, prefix="/api/v1")
app.include_router(event_center_reseller_router, prefix="/api/v1")


@app.get("/health/live", tags=["health"])
async def live():
    return {"status": "ok", "service": "core"}


# Many uptime monitors probe with HEAD. A separate hidden route keeps one OpenAPI operation per method (no duplicate operationId).
@app.head("/health/live", include_in_schema=False)
async def live_head():
    return Response(status_code=200)


@app.get("/healthz", tags=["health"], include_in_schema=False)
async def healthz():
    return await live()


@app.head("/healthz", include_in_schema=False)
async def healthz_head():
    return Response(status_code=200)


@app.get("/health/ready", tags=["health"])
async def ready(request: Request):
    db = await probe_database()
    worker = await probe_worker()
    publish_signals(db, worker)
    ready_ok = db.ok and worker.redis_ok and worker.worker_ok
    detailed = s.is_dev or hmac.compare_digest(request.headers.get("X-Melorin-Health-Token", ""), s.health_token)
    payload = {"status": "ready" if ready_ok else "not_ready"}
    if detailed:
        payload.update(build_checks(db, worker))
    return JSONResponse(payload, status_code=200 if ready_ok else 503)


@app.get("/health", tags=["health"])
async def health(request: Request):
    return await ready(request)


@app.get("/openapi-version", include_in_schema=False)
async def openapi_version():
    return {"version": app.version}


@app.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
async def metrics(request: Request):
    if not s.is_dev and not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {s.metrics_token}"):
        return PlainTextResponse("unauthorized\n", status_code=401)
    # Prometheus scrapes this endpoint directly, so refresh dependency and
    # worker freshness gauges here instead of waiting for a separate
    # readiness request to happen.
    from melorin.core.redis import get_redis

    redis = get_redis()
    redis_ok = worker_ok = False
    worker_last_tick = None
    if redis is not None:
        try:
            redis_ok = True
            worker_last_tick = await asyncio.wait_for(redis.get("melorin:worker:last_tick"), timeout=2.5)
            worker_age = time.time() - float(worker_last_tick) if worker_last_tick else None
            worker_ok = worker_age is not None and 0 <= worker_age <= 15
        except Exception as exc:
            redis_ok = False
            health_log.warning("redis health check failed: %s", type(exc).__name__)
    set_alert("MelorinRedisUnavailable", not redis_ok, summary="Redis unavailable", severity="critical")
    set_alert(
        "MelorinWorkerStale",
        not worker_ok,
        summary="Worker heartbeat stale",
        severity="critical",
        details=str(worker_last_tick or "missing"),
    )
    set_gauge("melorin_worker_last_tick", float(worker_last_tick or 0))
    # M7.6: payment / provisioning / reseller-bot / backup signals come from the database. A database outage must
    # not break the scrape (the MelorinDatabaseUnavailable alert covers it), so failures are swallowed here.
    try:
        from melorin.modules.reports.business_metrics import collect
        from melorin.core.db import session_factory

        async with session_factory()() as session:
            await collect(session)
    except Exception:
        logging.getLogger("melorin.metrics").warning("business metrics unavailable", exc_info=True)
    return PlainTextResponse(render(), media_type="text/plain; version=0.0.4")
