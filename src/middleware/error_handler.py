from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from src.auth.oauth_client_credentials import AuthenticationError
from src.integrations.salesforce import SalesforceAPIError
from src.middleware.input_validator import InputValidationError

logger = logging.getLogger(__name__)


class ErrorCategory:
    CLIENT = "client_error"       # bad input from Claude/user
    AUTH = "auth_error"           # token expired or revoked
    RATE_LIMIT = "rate_limit"     # too many requests
    EXTERNAL = "external_error"   # Salesforce is down or failing
    SERVER = "server_error"       # bug in our code


@dataclass
class ErrorResponse:
    category: str
    code: str
    message: str
    retry_after: Optional[int] = None  # seconds, for rate limit errors
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error": True,
            "category": self.category,
            "code": self.code,
            "message": self.message,
        }
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        if self.details:
            result["details"] = self.details
        return result


def handle_error(exc: Exception) -> ErrorResponse:
    """
    Convert any exception into a structured ErrorResponse.
    Never exposes raw stack traces to the client.
    """

    # ── Input validation errors ──
    if isinstance(exc, InputValidationError):
        return ErrorResponse(
            category=ErrorCategory.CLIENT,
            code="INVALID_INPUT",
            message=str(exc),
        )

    # ── Authentication errors ──
    if isinstance(exc, AuthenticationError):
        return ErrorResponse(
            category=ErrorCategory.AUTH,
            code="AUTH_FAILED",
            message="Authentication failed. Please re-authenticate.",
        )

    # ── Salesforce API errors ──
    if isinstance(exc, SalesforceAPIError):
        status = exc.status_code

        if status == 401:
            return ErrorResponse(
                category=ErrorCategory.AUTH,
                code="TOKEN_EXPIRED",
                message="Salesforce session expired. Re-authentication required.",
            )

        if status == 403:
            return ErrorResponse(
                category=ErrorCategory.AUTH,
                code="INSUFFICIENT_PERMISSIONS",
                message="You don't have permission to perform this action in Salesforce.",
            )

        if status == 429:
            return ErrorResponse(
                category=ErrorCategory.RATE_LIMIT,
                code="SF_RATE_LIMIT",
                message="Salesforce rate limit reached. Please wait and try again.",
                retry_after=60,
            )

        if status in (500, 502, 503):
            return ErrorResponse(
                category=ErrorCategory.EXTERNAL,
                code="SF_UNAVAILABLE",
                message="Salesforce is temporarily unavailable. Please try again shortly.",
                retry_after=30,
            )

        if 400 <= status < 500:
            return ErrorResponse(
                category=ErrorCategory.CLIENT,
                code="SF_CLIENT_ERROR",
                message=str(exc),
            )

        return ErrorResponse(
            category=ErrorCategory.EXTERNAL,
            code="SF_ERROR",
            message=f"Salesforce returned an unexpected error (HTTP {status}).",
        )

    # ── Anything else = server error ──
    logger.error("Unhandled exception: %s\n%s", exc, traceback.format_exc())
    return ErrorResponse(
        category=ErrorCategory.SERVER,
        code="INTERNAL_ERROR",
        message="An internal error occurred. Please try again or contact support.",
    )
