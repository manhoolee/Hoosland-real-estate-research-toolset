from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from .config import CAPABILITY_NAMES, CapabilitySettings, Settings


HEADER_RE = re.compile(r"^[A-Za-z0-9-]{1,80}$")
DEFAULT_NATIVE_SEARCH_BASE_URL = "https://api.deepseek.com/anthropic/v1"
DEFAULT_OUTPUT_FORMATS = ("md", "html")


class RuntimeConfigError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _url(value: object, field: str, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise RuntimeConfigError("CONFIG_INVALID", f"{field} must be an http(s) URL or null")
    normalized = value.strip().rstrip("/")
    if not normalized and allow_none:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeConfigError("CONFIG_INVALID", f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise RuntimeConfigError("CONFIG_INVALID", f"{field} must not contain credentials")
    return normalized


def _text(value: object, field: str, *, maximum: int = 300, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise RuntimeConfigError("CONFIG_INVALID", f"{field} must be a string")
    normalized = value.strip()
    if not normalized and allow_none:
        return None
    if not normalized:
        raise RuntimeConfigError("CONFIG_INVALID", f"{field} must not be blank")
    if len(normalized) > maximum:
        raise RuntimeConfigError("CONFIG_INVALID", f"{field} is too long")
    return normalized


class RuntimeConfigStore:
    """Encrypted, process-local runtime configuration with safe public projection."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.data_dir / "config" / "runtime-config.enc"
        self._lock = threading.RLock()
        self._fernet = self._build_fernet(settings)
        self._config = self._initial(settings)
        self._load()

    @staticmethod
    def _build_fernet(settings: Settings) -> Fernet | None:
        raw = settings.config_encryption_key
        if raw:
            try:
                return Fernet(raw.encode("ascii"))
            except (ValueError, TypeError) as exc:
                raise RuntimeConfigError(
                    "CONFIG_ENCRYPTION_INVALID",
                    "CONFIG_ENCRYPTION_KEY must be a Fernet key",
                ) from exc
        if settings.admin_session_secret:
            digest = hashlib.sha256(settings.admin_session_secret.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
        return None

    @staticmethod
    def _initial(settings: Settings) -> dict[str, Any]:
        capabilities: dict[str, dict[str, Any]] = {}
        for name in CAPABILITY_NAMES:
            value = settings.capabilities[name]
            capabilities[name] = {
                "base_url": value.base_url,
                "endpoint": value.endpoint,
                "api_key": value.api_key,
                "auth_header": value.auth_header,
                "auth_prefix": value.auth_prefix,
                "model": value.model,
            }
        return {
            "version": 1,
            "updated_at": None,
            "main_agent": {
                "base_url": settings.harness_base_url,
                "model": settings.harness_model,
                "api_key": settings.harness_api_key,
            },
            "native_search": {
                "base_url": settings.harness_search_base_url,
                "model": settings.harness_search_model,
                "api_key": settings.harness_search_api_key,
            },
            "capabilities": capabilities,
            "output": {
                "directory_name": "outputs",
                "policy": "conversation_isolated",
                "default_formats": list(DEFAULT_OUTPUT_FORMATS),
            },
        }

    @property
    def writable(self) -> bool:
        return self._fernet is not None

    def _load(self) -> None:
        if not self.path.is_file():
            return
        if self._fernet is None:
            raise RuntimeConfigError(
                "CONFIG_ENCRYPTION_REQUIRED",
                "encrypted runtime configuration exists but no encryption secret is configured",
            )
        try:
            encrypted = self.path.read_bytes()
            decoded = self._fernet.decrypt(encrypted)
            value = json.loads(decoded)
        except (OSError, InvalidToken, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeConfigError(
                "CONFIG_DECRYPT_FAILED", "runtime configuration could not be decrypted"
            ) from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise RuntimeConfigError("CONFIG_INVALID", "runtime configuration has an unsupported format")
        # Re-validate stored data through the same update path while preserving
        # environment defaults for fields introduced by future releases.
        stored = copy.deepcopy(value)
        self._config = self._initial(self.settings)
        self._apply(stored, allow_metadata=True)

    def public(self) -> dict[str, Any]:
        with self._lock:
            value = copy.deepcopy(self._config)
        for section in (value["main_agent"], value["native_search"]):
            section["api_key_set"] = bool(section.pop("api_key", None))
        for section in value["capabilities"].values():
            section["api_key_set"] = bool(section.pop("api_key", None))
            section["configured"] = bool(section.get("base_url"))
        value["encryption_ready"] = self.writable
        return value

    def update(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        if self._fernet is None:
            raise RuntimeConfigError(
                "CONFIG_ENCRYPTION_REQUIRED",
                "configure ADMIN_SESSION_SECRET or CONFIG_ENCRYPTION_KEY before saving API settings",
            )
        with self._lock:
            original = copy.deepcopy(self._config)
            candidate = copy.deepcopy(original)
            self._config = candidate
            try:
                self._apply(changes, allow_metadata=False)
                self._config["updated_at"] = _now()
                self._persist_locked()
            except Exception:
                self._config = original
                raise
        return self.public()

    def _apply(self, changes: Mapping[str, Any], *, allow_metadata: bool) -> None:
        # Read-only projection fields are accepted and ignored on update so a
        # settings UI can safely round-trip the GET response without sending
        # secrets or reconstructing the entire shape.
        allowed = {
            "main_agent",
            "native_search",
            "capabilities",
            "output",
            "version",
            "updated_at",
            "encryption_ready",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise RuntimeConfigError("CONFIG_INVALID", f"unknown configuration fields: {', '.join(sorted(unknown))}")

        for name in ("main_agent", "native_search"):
            if name not in changes:
                continue
            incoming = changes[name]
            if not isinstance(incoming, Mapping):
                raise RuntimeConfigError("CONFIG_INVALID", f"{name} must be an object")
            unknown_fields = set(incoming) - {"base_url", "model", "api_key", "api_key_set"}
            if unknown_fields:
                raise RuntimeConfigError("CONFIG_INVALID", f"unknown {name} fields: {', '.join(sorted(unknown_fields))}")
            section = self._config[name]
            if "base_url" in incoming:
                base_url = _url(incoming["base_url"], f"{name}.base_url")
                section["base_url"] = (
                    base_url
                    if name == "main_agent" or base_url is not None
                    else DEFAULT_NATIVE_SEARCH_BASE_URL
                )
            if "model" in incoming:
                section["model"] = _text(incoming["model"], f"{name}.model", allow_none=False)
            if "api_key" in incoming:
                section["api_key"] = _text(incoming["api_key"], f"{name}.api_key", maximum=10_000)

        if "capabilities" in changes:
            incoming_caps = changes["capabilities"]
            if not isinstance(incoming_caps, Mapping):
                raise RuntimeConfigError("CONFIG_INVALID", "capabilities must be an object")
            unknown_caps = set(incoming_caps) - set(CAPABILITY_NAMES)
            if unknown_caps:
                raise RuntimeConfigError("CONFIG_INVALID", f"unknown capabilities: {', '.join(sorted(unknown_caps))}")
            for name, incoming in incoming_caps.items():
                if not isinstance(incoming, Mapping):
                    raise RuntimeConfigError("CONFIG_INVALID", f"capabilities.{name} must be an object")
                allowed_fields = {
                    "base_url", "endpoint", "model", "api_key", "api_key_set",
                    "auth_header", "auth_prefix", "configured",
                }
                unknown_fields = set(incoming) - allowed_fields
                if unknown_fields:
                    raise RuntimeConfigError("CONFIG_INVALID", f"unknown capabilities.{name} fields: {', '.join(sorted(unknown_fields))}")
                section = self._config["capabilities"][name]
                if "base_url" in incoming:
                    section["base_url"] = _url(incoming["base_url"], f"capabilities.{name}.base_url")
                if "endpoint" in incoming:
                    endpoint = _text(incoming["endpoint"], f"capabilities.{name}.endpoint", allow_none=False)
                    if not endpoint.startswith("/") or "://" in endpoint or ".." in endpoint.split("/"):
                        raise RuntimeConfigError("CONFIG_INVALID", f"capabilities.{name}.endpoint must be a safe absolute path")
                    section["endpoint"] = endpoint
                if "model" in incoming:
                    section["model"] = _text(incoming["model"], f"capabilities.{name}.model")
                if "api_key" in incoming:
                    section["api_key"] = _text(incoming["api_key"], f"capabilities.{name}.api_key", maximum=10_000)
                if "auth_header" in incoming:
                    header = _text(incoming["auth_header"], f"capabilities.{name}.auth_header", maximum=80, allow_none=False)
                    if not HEADER_RE.fullmatch(header):
                        raise RuntimeConfigError("CONFIG_INVALID", f"capabilities.{name}.auth_header is invalid")
                    section["auth_header"] = header
                if "auth_prefix" in incoming:
                    prefix = _text(
                        incoming["auth_prefix"],
                        f"capabilities.{name}.auth_prefix",
                        maximum=80,
                    ) or ""
                    if "\r" in prefix or "\n" in prefix:
                        raise RuntimeConfigError(
                            "CONFIG_INVALID",
                            f"capabilities.{name}.auth_prefix is invalid",
                        )
                    section["auth_prefix"] = prefix

        if "output" in changes:
            output = changes["output"]
            if not isinstance(output, Mapping):
                raise RuntimeConfigError("CONFIG_INVALID", "output must be an object")
            if set(output) - {"directory_name", "policy", "default_formats"}:
                raise RuntimeConfigError("CONFIG_INVALID", "output contains unknown fields")
            default_formats = output.get("default_formats", list(DEFAULT_OUTPUT_FORMATS))
            if (
                output.get("directory_name", "outputs") != "outputs"
                or output.get("policy", "conversation_isolated") != "conversation_isolated"
                or not isinstance(default_formats, list)
                or default_formats != list(DEFAULT_OUTPUT_FORMATS)
            ):
                raise RuntimeConfigError(
                    "OUTPUT_POLICY_FIXED",
                    "output files are isolated per conversation and default to Markdown plus HTML",
                )

        if allow_metadata:
            if changes.get("version", 1) != 1:
                raise RuntimeConfigError("CONFIG_INVALID", "unsupported runtime configuration version")
            updated_at = changes.get("updated_at")
            if updated_at is None or isinstance(updated_at, str):
                self._config["updated_at"] = updated_at

    def _persist_locked(self) -> None:
        assert self._fernet is not None
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        payload = json.dumps(self._config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink()

    def main_agent(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config["main_agent"])

    def native_search(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config["native_search"])

    def capability(self, name: str) -> CapabilitySettings:
        if name not in CAPABILITY_NAMES:
            raise KeyError(name)
        with self._lock:
            value = copy.deepcopy(self._config["capabilities"][name])
        return CapabilitySettings(name=name, **value)
