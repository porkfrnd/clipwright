from __future__ import annotations

from typing import Any


class EngineError(Exception):
    """An error that is safe to show to a user.

    Codes are stable, upper-snake identifiers so the UI can map them to help text.
    Details must never contain secrets; the redaction layer runs over them anyway.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class CancelledError(EngineError):
    def __init__(self, message: str = "Job cancelled.") -> None:
        super().__init__("JOB_CANCELLED", message)


class RateLimited(EngineError):
    def __init__(self, retry_after_s: float, message: str) -> None:
        super().__init__(
            "PROVIDER_RATE_LIMITED",
            message,
            details={"retryAfterSeconds": retry_after_s},
            retryable=True,
        )
        self.retry_after_s = retry_after_s
