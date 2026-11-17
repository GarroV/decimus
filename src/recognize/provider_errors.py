"""Allowlisted provider error metadata for operational diagnostics.

Messages, bodies, request URLs and exception causes may contain external input.
They are not part of the diagnostic contract.
"""

from __future__ import annotations

_ERROR_TYPES = frozenset(
    {
        "OpenAIError",
        "APIError",
        "APIStatusError",
        "APIResponseValidationError",
        "APIConnectionError",
        "APITimeoutError",
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "ConflictError",
        "UnprocessableEntityError",
        "RateLimitError",
        "InternalServerError",
    }
)
_ERROR_CODES = frozenset(
    {
        "invalid_api_key",
        "insufficient_quota",
        "rate_limit_exceeded",
        "context_length_exceeded",
        "model_not_found",
        "content_policy_violation",
        "server_error",
        "invalid_request_error",
        "unsupported_parameter",
    }
)


def safe_provider_error(error: Exception) -> str:
    """Type, numeric HTTP status and known machine code; never the external message."""
    name = type(error).__name__
    parts = [name if name in _ERROR_TYPES else "OpenAIError"]
    status = getattr(error, "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        parts.append(f"HTTP {status}")
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in _ERROR_CODES:
        parts.append(code)
    return ", ".join(parts)
