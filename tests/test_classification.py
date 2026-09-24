from llmbench.classification import classify_http_error, retry_delays_for
from llmbench.domain import ModelStatus


def test_404_is_not_available_and_never_retried():
    c = classify_http_error(404, "not found")
    assert c.error_type == "MODEL_NOT_FOUND"
    assert c.model_status is ModelStatus.NOT_AVAILABLE
    assert c.retryable is False
    assert retry_delays_for(c.error_type) == ()


def test_retry_schedules_are_error_specific():
    assert retry_delays_for("RATE_LIMITED") == (1, 2, 5, 10)
    assert retry_delays_for("OVERLOADED") == (1, 2, 5, 10)
    assert retry_delays_for("PROVIDER_ERROR") == (1, 3)
    assert retry_delays_for("TIMEOUT") == (1, 3)
    assert retry_delays_for("NETWORK_ERROR") == (1, 3)
    assert retry_delays_for("AUTH_ERROR") == ()


def test_capability_mismatch_400_is_incompatible_without_retry():
    c = classify_http_error(400, "Content cannot be a plain string. The model does not support text input.")
    assert c.error_type == "CAPABILITY_MISMATCH"
    assert c.model_status is ModelStatus.INCOMPATIBLE
    assert c.retryable is False
    assert retry_delays_for(c.error_type) == ()


def test_auth_error_does_not_classify_model_health():
    c = classify_http_error(401, "unauthorized")
    assert c.error_type == "AUTH_ERROR"
    assert c.model_status is None


def test_transient_http_errors_are_retryable():
    assert classify_http_error(429, "busy").retryable is True
    assert classify_http_error(503, "overloaded").error_type == "OVERLOADED"
    assert classify_http_error(500, "internal").error_type == "PROVIDER_ERROR"
