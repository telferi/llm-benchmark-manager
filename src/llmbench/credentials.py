from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_data_path

try:
    import keyring as _keyring
except Exception:  # pragma: no cover - optional platform integration failure
    _keyring = None


class CredentialUnavailable(RuntimeError):
    pass


class CredentialStorageError(RuntimeError):
    pass


class EnvCredentialResolver:
    def resolve(self, ref: str) -> str:
        value = os.environ.get(ref)
        if not value:
            raise CredentialUnavailable(f"Credential environment variable is unavailable: {ref}")
        return value

    def availability(self, ref: str) -> bool:
        return bool(os.environ.get(ref))


class EncryptedFileCredentialStore:
    """Headless-safe encrypted credential fallback.

    The vault is encrypted with Fernet. The vault and its local master key are
    both mode 0600 inside a mode 0700 directory. This protects the raw provider
    key from accidental disclosure in the DB/logs/artifacts and encrypts it at
    rest; OS account isolation remains the trust boundary for the master key.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.key_path = self.root / "master.key"
        self.vault_path = self.root / "credentials.json"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except PermissionError:
            pass

    def _key(self, create: bool) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        if not create:
            raise CredentialUnavailable("Encrypted credential master key is unavailable")
        self._ensure_root()
        key = Fernet.generate_key()
        try:
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, key + b"\n")
            finally:
                os.close(fd)
        except FileExistsError:
            return self.key_path.read_bytes().strip()
        return key

    def _vault(self) -> dict[str, str]:
        if not self.vault_path.exists():
            return {}
        try:
            data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialStorageError("Encrypted credential vault is unreadable") from exc
        if not isinstance(data, dict):
            raise CredentialStorageError("Encrypted credential vault has invalid format")
        return {str(k): str(v) for k, v in data.items()}

    def _write_vault(self, data: dict[str, str]) -> None:
        self._ensure_root()
        tmp = self.vault_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.vault_path)
        os.chmod(self.vault_path, 0o600)

    def store(self, ref: str, secret: str) -> None:
        if not secret:
            raise ValueError("API key cannot be empty")
        token = Fernet(self._key(create=True)).encrypt(secret.encode("utf-8")).decode("ascii")
        data = self._vault()
        data[ref] = token
        self._write_vault(data)

    def resolve(self, ref: str) -> str:
        token = self._vault().get(ref)
        if not token:
            raise CredentialUnavailable(f"Encrypted credential is unavailable: {ref}")
        try:
            return Fernet(self._key(create=False)).decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise CredentialStorageError(f"Encrypted credential cannot be decrypted: {ref}") from exc

    def availability(self, ref: str) -> bool:
        try:
            self.resolve(ref)
            return True
        except (CredentialUnavailable, CredentialStorageError):
            return False

    def delete(self, ref: str) -> None:
        data = self._vault()
        if ref in data:
            data.pop(ref)
            self._write_vault(data)


class SecureCredentialStore:
    SERVICE_NAME = "llm-benchmark-manager"

    def __init__(self, keyring_module: Any = None, fallback: EncryptedFileCredentialStore | None = None):
        self.keyring = _keyring if keyring_module is None else keyring_module
        default_root = user_data_path("llmbench") / "credentials"
        self.fallback = fallback or EncryptedFileCredentialStore(default_root)

    def _keyring_usable(self) -> bool:
        if self.keyring is None:
            return False
        try:
            backend = self.keyring.get_keyring()
            return float(getattr(backend, "priority", 0)) > 0
        except Exception:
            return False

    def store(self, ref: str, secret: str) -> tuple[str, str]:
        if not secret:
            raise ValueError("API key cannot be empty")
        if self._keyring_usable():
            try:
                self.keyring.set_password(self.SERVICE_NAME, ref, secret)
                return "keyring", ref
            except Exception:
                pass
        self.fallback.store(ref, secret)
        return "encrypted-file", ref

    def resolve(self, source: str, ref: str) -> str:
        if source == "keyring":
            if not self._keyring_usable():
                raise CredentialUnavailable(f"OS keyring is unavailable for credential: {ref}")
            try:
                value = self.keyring.get_password(self.SERVICE_NAME, ref)
            except Exception as exc:
                raise CredentialUnavailable(f"OS keyring credential is unavailable: {ref}") from exc
            if not value:
                raise CredentialUnavailable(f"OS keyring credential is unavailable: {ref}")
            return value
        if source == "encrypted-file":
            return self.fallback.resolve(ref)
        raise CredentialUnavailable(f"Unsupported secure credential source: {source}")

    def availability(self, source: str, ref: str) -> bool:
        try:
            self.resolve(source, ref)
            return True
        except CredentialUnavailable:
            return False

    def delete(self, source: str, ref: str) -> None:
        if source == "keyring" and self._keyring_usable():
            try:
                self.keyring.delete_password(self.SERVICE_NAME, ref)
            except Exception:
                pass
        elif source == "encrypted-file":
            self.fallback.delete(ref)


class CredentialManager:
    def __init__(self, secure_store: SecureCredentialStore | None = None, env_resolver: EnvCredentialResolver | None = None, data_dir: str | Path | None = None):
        if secure_store is None:
            root = Path(data_dir) if data_dir is not None else user_data_path("llmbench") / "credentials"
            secure_store = SecureCredentialStore(fallback=EncryptedFileCredentialStore(root))
        self.secure = secure_store
        self.env = env_resolver or EnvCredentialResolver()

    def store(self, ref: str, secret: str) -> tuple[str, str]:
        return self.secure.store(ref, secret)

    def resolve(self, ref: str, source: str = "env") -> str:
        if source == "env":
            return self.env.resolve(ref)
        return self.secure.resolve(source, ref)

    def availability(self, ref: str, source: str = "env") -> bool:
        if source == "env":
            return self.env.availability(ref)
        return self.secure.availability(source, ref)

    def delete(self, source: str, ref: str) -> None:
        if source != "env":
            self.secure.delete(source, ref)


def redact_mapping(value):
    sensitive = ("authorization", "api_key", "apikey", "token", "secret", "password")
    if isinstance(value, dict):
        return {k: ("<redacted>" if any(s in k.lower() for s in sensitive) else redact_mapping(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_mapping(x) for x in value]
    return value


def redact_text(value, secrets=()):
    text = "" if value is None else str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "<redacted>")
    return text


def sanitize_provider_message(value, secrets=(), max_length=512):
    """Redact secrets and provider-specific identifiers before persistence."""
    import re

    text = "" if value is None else str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "<redacted>")
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "<authorization>", text)
    uuid_re = r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    text = re.sub(uuid_re, "<uuid>", text)
    text = re.sub(r"(?i)(account(?:_id)?\s*(?:=|:|\bis\b)?\s*)['\"]?[A-Za-z0-9_-]{20,}['\"]?", r"\1'<account_id>'", text)
    text = re.sub(r"(?i)(for account\s+)['\"]?[^'\"\s]{20,}['\"]?", r"\1'<account_id>'", text)
    return text[: max(0, int(max_length))]
