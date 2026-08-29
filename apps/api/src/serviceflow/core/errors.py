"""Centralised error codes and the single error envelope (PRD 37, 38).

Route handlers raise AppError subclasses; the handlers registered in main.py turn
them into the documented JSON shape. Raw exception text never reaches the client.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for every error the API deliberately returns."""

    status_code: int = 500
    code: str = ErrorCode.INTERNAL_ERROR
    message: str = "Something went wrong on our end. Please try again."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class ValidationFailed(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_FAILED
    message = "Some of the information provided isn't valid."


class Unauthorized(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    message = "You need to sign in to continue."


class Forbidden(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    message = "You don't have access to this."


class NotFound(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    message = "We couldn't find what you were looking for."


class ScheduleConflict(AppError):
    status_code = 409
    code = ErrorCode.SCHEDULE_CONFLICT
    message = "This employee is already assigned during the selected time."


class InvalidStateTransition(AppError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION
    message = "That change isn't allowed from the current status."


class IdempotencyConflict(AppError):
    status_code = 409
    code = ErrorCode.IDEMPOTENCY_CONFLICT
    message = "This request was already submitted with different details."


class RateLimited(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    message = "Too many requests. Please wait a moment and try again."


class UploadFailed(AppError):
    status_code = 400
    code = ErrorCode.UPLOAD_FAILED
    message = "We couldn't upload that file."


class DependencyUnavailable(AppError):
    status_code = 503
    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    message = "A service we depend on is temporarily unavailable."
