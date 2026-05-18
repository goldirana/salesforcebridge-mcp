from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Max length for any single string parameter
MAX_STRING_LENGTH = 10_000

# Max depth for nested objects (prevents deeply nested payloads)
MAX_NESTING_DEPTH = 5

# Characters that should never appear in field names
FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")

# SOQL injection patterns — things that shouldn't be in user-supplied values
SOQL_INJECTION_PATTERNS = [
    re.compile(r";\s*(SELECT|INSERT|UPDATE|DELETE)", re.IGNORECASE),
    re.compile(r"--"),                  # SQL comment
    re.compile(r"/\*.*?\*/", re.DOTALL),  # block comment
    re.compile(r"\\u0027"),             # escaped single quote (unicode)
]


class InputValidationError(Exception):
    """Raised when input fails validation."""


def validate_tool_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitise and validate all parameters before they reach a tool.

    Called by the server before tool execution — acts as a cross-cutting guard.
    Returns cleaned params or raises InputValidationError.
    """
    if not isinstance(params, dict):
        raise InputValidationError("Parameters must be a JSON object.")

    cleaned = {}
    for key, value in params.items():
        _validate_key(key)
        cleaned[key] = _sanitize_value(key, value, depth=0)

    return cleaned


def _validate_key(key: str) -> None:
    """Ensure parameter keys are safe identifiers."""
    if not isinstance(key, str) or len(key) > 200:
        raise InputValidationError(f"Invalid parameter key: '{key[:50]}...'")


def _sanitize_value(key: str, value: Any, depth: int) -> Any:
    """Recursively sanitise a parameter value."""
    if depth > MAX_NESTING_DEPTH:
        raise InputValidationError(
            f"Parameter '{key}' exceeds maximum nesting depth of {MAX_NESTING_DEPTH}."
        )

    if value is None:
        return value

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        return _sanitize_string(key, value)

    if isinstance(value, list):
        return [_sanitize_value(key, item, depth + 1) for item in value]

    if isinstance(value, dict):
        return {
            k: _sanitize_value(k, v, depth + 1)
            for k, v in value.items()
        }

    raise InputValidationError(
        f"Parameter '{key}' has unsupported type: {type(value).__name__}"
    )


def _sanitize_string(key: str, value: str) -> str:
    """Validate and clean a string parameter."""
    if len(value) > MAX_STRING_LENGTH:
        raise InputValidationError(
            f"Parameter '{key}' exceeds maximum length of {MAX_STRING_LENGTH} characters."
        )

    # Check for null bytes
    if "\x00" in value:
        raise InputValidationError(f"Parameter '{key}' contains null bytes.")

    # Check for SOQL injection patterns in values
    for pattern in SOQL_INJECTION_PATTERNS:
        if pattern.search(value):
            logger.warning(
                "Possible SOQL injection detected in parameter '%s': %s",
                key,
                value[:100],
            )
            raise InputValidationError(
                f"Parameter '{key}' contains a disallowed pattern."
            )

    return value.strip()
