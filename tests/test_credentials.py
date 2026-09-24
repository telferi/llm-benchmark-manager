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

class MemoryKeyring:
    class Backend:
        priority = 1
    def __init__(self): self.values={}
    def get_keyring(self): return self.Backend()
    def set_password(self,service,user,password): self.values[(service,user)]=password
    def get_password(self,service,user): return self.values.get((service,user))
    def delete_password(self,service,user): self.values.pop((service,user),None)

class FailingKeyring:
    class Backend:
        priority = 0
    def get_keyring(self): return self.Backend()

def test_secure_store_prefers_os_keyring(tmp_path):
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore
    kr=MemoryKeyring()
    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=kr,fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    source,ref=manager.store('provider:nvidia','nv-secret')
    assert (source,ref)==('keyring','provider:nvidia')
    assert manager.resolve(ref,source)=='nv-secret'
    assert manager.availability(ref,source) is True

def test_secure_store_falls_back_to_encrypted_file_without_keyring(tmp_path):
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore
    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=FailingKeyring(),fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    source,ref=manager.store('provider:nvidia','nv-secret')
    assert source=='encrypted-file'
    assert manager.resolve(ref,source)=='nv-secret'
    combined=b''.join(p.read_bytes() for p in (tmp_path/'vault').iterdir() if p.is_file())
    assert b'nv-secret' not in combined
    assert all((p.stat().st_mode & 0o077)==0 for p in (tmp_path/'vault').iterdir() if p.is_file())

def test_env_credentials_remain_supported(monkeypatch,tmp_path):
    from llmbench.credentials import CredentialManager, SecureCredentialStore, EncryptedFileCredentialStore
    monkeypatch.setenv('EXISTING_KEY','env-secret')
    manager=CredentialManager(secure_store=SecureCredentialStore(keyring_module=FailingKeyring(),fallback=EncryptedFileCredentialStore(tmp_path/'vault')))
    assert manager.resolve('EXISTING_KEY','env')=='env-secret'
