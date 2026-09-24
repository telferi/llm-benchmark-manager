import pytest
from llmbench.credentials import EnvCredentialResolver, CredentialUnavailable, redact_mapping

def test_env_resolver_reads_runtime_value(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY","secret-value")
    r=EnvCredentialResolver()
    assert r.resolve("TEST_PROVIDER_KEY") == "secret-value"
    assert r.availability("TEST_PROVIDER_KEY") is True

def test_missing_env_never_contains_secret(monkeypatch):
    monkeypatch.delenv("NO_SUCH_KEY",raising=False)
    with pytest.raises(CredentialUnavailable, match="NO_SUCH_KEY"):
        EnvCredentialResolver().resolve("NO_SUCH_KEY")

def test_redaction_removes_sensitive_values():
    d=redact_mapping({"Authorization":"Bearer ABC", "api_key":"XYZ", "normal":"ok", "nested":{"token":"T"}})
    assert d["Authorization"] == "<redacted>"
    assert d["api_key"] == "<redacted>"
    assert d["nested"]["token"] == "<redacted>"
    assert d["normal"] == "ok"
