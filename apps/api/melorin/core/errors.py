import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from melorin.core.context import correlation_id

log = logging.getLogger("melorin.errors")


class AppError(Exception):
    """Stable, client-safe business error."""

    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None, headers: dict[str, str] | None = None):
        super().__init__(code)
        self.code, self.message, self.status, self.details, self.headers = code, message, status, details, headers


def DependencyUnavailable(what: str = "service", retry_after: int = 5) -> AppError:  # noqa: N802
    """503 + Retry-After: an infrastructure outage (Redis, database...) is not the client's fault and not a 429/500."""
    return AppError(
        "DEPENDENCY_UNAVAILABLE",
        "سرویس موقتاً در دسترس نیست. چند لحظه بعد دوباره تلاش کنید.",
        503,
        {"dependency": what},
        {"Retry-After": str(retry_after)},
    )


def NotFound(what: str = "resource") -> AppError:  # noqa: N802
    return AppError("NOT_FOUND", f"{what} یافت نشد.", 404)


def Forbidden() -> AppError:  # noqa: N802
    return AppError("FORBIDDEN", "دسترسی مجاز نیست.", 403)


def _body(code: str, message: str, details=None, cid: str | None = None) -> dict:
    err = {"code": code, "message": message, "correlation_id": cid or correlation_id.get()}
    if details:
        err["details"] = details
    return {"error": err}


def _cid(request: Request) -> str | None:
    state = request.scope.get("state") or {}
    return state.get("correlation_id") or None


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "ورودی نامعتبر است.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(f"HTTP_{exc.status_code}", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError):
        # Connection-level failures (database stopped / restarting / pool exhausted) => 503, never a bare 500.
        if exc.connection_invalidated or isinstance(exc, (OperationalError, InterfaceError)):
            log.warning("database unavailable: %s", type(exc.orig).__name__ if exc.orig else type(exc).__name__)
            err = DependencyUnavailable("database")
            return JSONResponse(_body(err.code, err.message, err.details, _cid(request)), status_code=503, headers=err.headers)
        return await _unhandled(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # ServerErrorMiddleware runs OUTSIDE CorrelationMiddleware, so the contextvar is already reset: read the id the
        # middleware stored on the ASGI scope so the error body stays traceable.
        log.exception("unhandled error", extra={"correlation_id": _cid(request)})
        return JSONResponse(_body("INTERNAL_ERROR", "خطای داخلی. لطفاً بعداً تلاش کنید.", None, _cid(request)), status_code=500)
