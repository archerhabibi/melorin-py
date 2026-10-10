import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from melorin.core.context import correlation_id

log = logging.getLogger("melorin.errors")


class AppError(Exception):
    """Stable, client-safe business error."""

    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(code)
        self.code, self.message, self.status, self.details = code, message, status, details


def NotFound(what: str = "resource") -> AppError:  # noqa: N802
    return AppError("NOT_FOUND", f"{what} یافت نشد.", 404)


def Forbidden() -> AppError:  # noqa: N802
    return AppError("FORBIDDEN", "دسترسی مجاز نیست.", 403)


def _body(code: str, message: str, details=None) -> dict:
    err = {"code": code, "message": message, "correlation_id": correlation_id.get()}
    if details:
        err["details"] = details
    return {"error": err}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "ورودی نامعتبر است.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(f"HTTP_{exc.status_code}", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(_body("INTERNAL_ERROR", "خطای داخلی. لطفاً بعداً تلاش کنید."), status_code=500)
