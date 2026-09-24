from __future__ import annotations
from dataclasses import dataclass
from .domain import ModelStatus


@dataclass(frozen=True)
class ErrorClassification:
    error_type: str
    retryable: bool
    model_status: ModelStatus | None
    diagnostic_code: str


def _is_capability_mismatch(message: str) -> bool:
    text = (message or "").lower()
    markers = (
        "does not support text input",
        "content cannot be a plain string",
        "use the embeddings endpoint",
        "requires image input",
        "requires multimodal input",
    )
    return any(marker in text for marker in markers)


def classify_http_error(status_code: int | None, message: str = "") -> ErrorClassification:
    if status_code in (401, 403):
        return ErrorClassification("AUTH_ERROR", False, None, "auth_error")
    if status_code == 404:
        return ErrorClassification("MODEL_NOT_FOUND", False, ModelStatus.NOT_AVAILABLE, "not_available")
    if status_code == 429:
        return ErrorClassification("RATE_LIMITED", True, None, "rate_limited")
    if status_code == 503:
        return ErrorClassification("OVERLOADED", True, None, "overloaded")
    if status_code in (500, 502, 504):
        return ErrorClassification("PROVIDER_ERROR", True, None, "provider_error")
    if status_code == 400 and _is_capability_mismatch(message):
        return ErrorClassification("CAPABILITY_MISMATCH", False, ModelStatus.INCOMPATIBLE, "capability_mismatch")
    if status_code == 400:
        return ErrorClassification("PAYLOAD_ERROR", False, None, "payload_error")
    if status_code is None:
        return ErrorClassification("TIMEOUT", True, None, "timeout")
    return ErrorClassification("HTTP_ERROR", bool(status_code >= 500), None, "http_error")


_RETRY_DELAYS = {
    "RATE_LIMITED": (1, 2, 5, 10),
    "OVERLOADED": (1, 2, 5, 10),
    "PROVIDER_ERROR": (1, 3),
    "TIMEOUT": (1, 3),
    "NETWORK_ERROR": (1, 3),
}


def retry_delays_for(error_type: str) -> tuple[int, ...]:
    return _RETRY_DELAYS.get(str(error_type or "").upper(), ())
