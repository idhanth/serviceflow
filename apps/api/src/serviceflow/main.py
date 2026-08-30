"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from serviceflow.api.middleware import RequestContextMiddleware
from serviceflow.api.v1 import health
from serviceflow.api.v1.router import api_router
from serviceflow.auth.provider import build_auth_provider
from serviceflow.core import context
from serviceflow.core.config import Settings, get_settings
from serviceflow.core.errors import AppError, ErrorCode
from serviceflow.core.logging import configure_logging
from serviceflow.schemas.envelope import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

_STATUS_TO_CODE = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    429: ErrorCode.RATE_LIMITED,
}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request: Request,
    details: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """The one shape every failure takes (PRD 37).

    `request_id` comes from the context rather than request.state, so it is
    present even for failures raised before a route ever runs.
    """
    request_id = context.request_id() or getattr(request.state, "request_id", None)
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=request_id,
            details=details or None,
        )
    )
    response_headers = dict(headers or {})
    if request_id:
        # Starlette runs ServerErrorMiddleware outside every user middleware, so a
        # 500 rendered here never passes through the one that stamps this header.
        # Setting it on the envelope makes the id reportable on all failures.
        response_headers["X-Request-Id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=response_headers or None,
    )


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        headers: dict[str, str] = {}
        # Rate limits tell the caller when to come back rather than making them guess.
        retry_after = (exc.details or {}).get("retry_after")
        if isinstance(retry_after, int):
            headers["Retry-After"] = str(retry_after)
        return _error_response(
            exc.status_code, exc.code, exc.message, request, exc.details, headers or None
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {
            ".".join(str(p) for p in err["loc"][1:]) or "body": err["msg"] for err in exc.errors()
        }
        return _error_response(
            422,
            ErrorCode.VALIDATION_FAILED,
            "Some of the information provided isn't valid.",
            request,
            {"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error_response(exc.status_code, code, message, request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Anything unforeseen.

        The traceback goes to the log with its request id; the client gets a
        stable code, a safe sentence and that same id. No exception text, SQL,
        stack frame or path ever crosses the boundary (PRD 29, 41).
        """
        logger.exception(
            "unhandled exception",
            extra={
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
            },
        )
        return _error_response(
            500,
            ErrorCode.INTERNAL_ERROR,
            "Something went wrong on our end. Please try again.",
            request,
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.auth_provider = build_auth_provider(settings)
    logger.info(
        "api starting",
        extra={"environment": settings.environment, "auth_provider": settings.auth_provider},
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")

    app = FastAPI(
        title="ServiceFlow API",
        version="0.1.0",
        openapi_url=None if settings.is_production else "/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        lifespan=_lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "Idempotency-Key"],
        expose_headers=["X-Request-Id"],
    )

    _register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
