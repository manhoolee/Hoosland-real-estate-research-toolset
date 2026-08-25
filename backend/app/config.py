from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


CAPABILITY_NAMES = (
    "vision_analyze",
    "image_generate",
    "web_search",
    "document_extract",
    "delegate_text",
)


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int, *, minimum: int = 1) -> int:
    if value is None or value.strip() == "":
        return default
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"expected an integer >= {minimum}, got {parsed}")
    return parsed


def _float(value: str | None, default: float, *, minimum: float = 0.1) -> float:
    if value is None or value.strip() == "":
        return default
    parsed = float(value)
    if parsed < minimum:
        raise ValueError(f"expected a number >= {minimum}, got {parsed}")
    return parsed


def _deployment_label(value: str | None, default: str, name: str) -> str:
    normalized = value.strip() if value is not None else default
    if not normalized:
        normalized = default
    if len(normalized) > 128 or any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{name} must be a printable string no longer than 128 characters")
    return normalized


def _path(value: str | None, default: Path, base: Path) -> Path:
    candidate = Path(value).expanduser() if value else default
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _optional_url(value: str | None, name: str) -> str | None:
    if value is None or value.strip() == "":
        return None
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not contain credentials")
    return normalized


def _launch_args(value: str | None) -> tuple[str, ...] | None:
    if value is None or value.strip() == "":
        return None
    decoded = json.loads(value)
    if not isinstance(decoded, list) or not decoded or not all(isinstance(item, str) for item in decoded):
        raise ValueError("HARNESS_LAUNCH_ARGS_JSON must be a non-empty JSON string array")
    return tuple(decoded)


def _skill_dirs(value: str | None, base: Path) -> tuple[Path, ...]:
    if value is None or value.strip() == "":
        return ()
    result: list[Path] = []
    for item in value.split(os.pathsep):
        if not item.strip():
            continue
        result.append(_path(item.strip(), Path(item.strip()), base))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class CapabilitySettings:
    name: str
    base_url: str | None
    endpoint: str
    api_key: str | None
    auth_header: str
    auth_prefix: str
    model: str | None

    @property
    def configured(self) -> bool:
        return self.base_url is not None

    @property
    def target_url(self) -> str | None:
        if self.base_url is None:
            return None
        return f"{self.base_url}/{self.endpoint.lstrip('/')}"

    def public_status(self) -> dict[str, object]:
        return {
            "name": self.name,
            "configured": self.configured,
            "status": "configured" if self.configured else "not_configured",
            "endpoint": self.endpoint,
            "model": self.model,
            "auth_configured": bool(self.api_key),
            "error_code": None if self.configured else "CAPABILITY_NOT_CONFIGURED",
        }


@dataclass(frozen=True, slots=True)
class Settings:
    root_dir: Path
    data_dir: Path
    frontend_dist: Path
    cordis_path: Path
    environment: str
    slot: str
    build_id: str
    host: str
    port: int
    log_level: str
    operation_log_enabled: bool
    operation_log_retention_days: int
    cors_origins: tuple[str, ...]
    max_upload_bytes: int
    max_request_bytes: int
    max_capability_response_bytes: int
    max_capability_file_bytes: int
    capability_timeout_seconds: float
    harness_enabled: bool
    harness_provider: str
    harness_model: str
    harness_max_tokens: int
    harness_base_url: str | None
    harness_api_key: str | None
    harness_search_base_url: str | None
    harness_search_model: str
    harness_search_api_key: str | None
    harness_runtime_bin: str | None
    harness_launch_args: tuple[str, ...] | None
    harness_request_timeout_seconds: float | None
    harness_runner_cache_size: int
    harness_skill_dirs: tuple[Path, ...]
    capability_mcp_url: str
    capability_mcp_token: str | None
    api_token: str | None
    admin_password: str | None
    admin_session_secret: str | None
    admin_session_seconds: int
    admin_cookie_secure: bool
    config_encryption_key: str | None
    capabilities: dict[str, CapabilitySettings]

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        root_dir: Path | None = None,
    ) -> "Settings":
        values = os.environ if env is None else env
        root = (root_dir or Path(__file__).resolve().parents[1]).resolve()
        port = _int(values.get("PORT"), 8080)
        data_dir = _path(values.get("DATA_DIR"), Path("data"), root)
        frontend_dist = _path(values.get("FRONTEND_DIST"), Path("../frontend/dist"), root)
        cordis_path = _path(values.get("HARNESS_CORDIS_PATH"), Path("cordis.yml"), root)

        endpoints = {
            "vision_analyze": "/chat/completions",
            "image_generate": "/images/generations",
            "web_search": "/web-search",
            "document_extract": "/extract",
            "delegate_text": "/chat/completions",
        }
        capabilities: dict[str, CapabilitySettings] = {}
        for name in CAPABILITY_NAMES:
            prefix = name.upper()
            capabilities[name] = CapabilitySettings(
                name=name,
                base_url=_optional_url(values.get(f"{prefix}_API_BASE_URL"), f"{prefix}_API_BASE_URL"),
                endpoint=values.get(f"{prefix}_API_PATH", endpoints[name]),
                api_key=values.get(f"{prefix}_API_KEY") or None,
                auth_header=values.get(f"{prefix}_AUTH_HEADER", "Authorization"),
                auth_prefix=values.get(f"{prefix}_AUTH_PREFIX", "Bearer"),
                model=values.get(f"{prefix}_API_MODEL") or None,
            )

        request_timeout_raw = values.get("HARNESS_REQUEST_TIMEOUT_SECONDS")
        request_timeout = (
            None
            if request_timeout_raw is None or request_timeout_raw.strip() == ""
            else _float(request_timeout_raw, 300.0)
        )
        origins = tuple(item.strip() for item in values.get("CORS_ORIGINS", "").split(",") if item.strip())
        mcp_url = values.get("CAPABILITY_MCP_URL", f"http://127.0.0.1:{port}/mcp").rstrip("/")
        _optional_url(mcp_url, "CAPABILITY_MCP_URL")

        return cls(
            root_dir=root,
            data_dir=data_dir,
            frontend_dist=frontend_dist,
            cordis_path=cordis_path,
            environment=values.get("APP_ENV", "development"),
            slot=_deployment_label(values.get("APP_SLOT"), "slot-b", "APP_SLOT"),
            build_id=_deployment_label(values.get("BUILD_ID"), "development", "BUILD_ID"),
            host=values.get("HOST", "127.0.0.1"),
            port=port,
            log_level=values.get("LOG_LEVEL", "info").lower(),
            operation_log_enabled=_bool(values.get("OPERATION_LOG_ENABLED"), True),
            operation_log_retention_days=_int(
                values.get("OPERATION_LOG_RETENTION_DAYS"), 14
            ),
            cors_origins=origins,
            max_upload_bytes=_int(values.get("MAX_UPLOAD_BYTES"), 25 * 1024 * 1024),
            max_request_bytes=_int(values.get("MAX_REQUEST_BYTES"), 30 * 1024 * 1024),
            max_capability_response_bytes=_int(
                values.get("MAX_CAPABILITY_RESPONSE_BYTES"), 8 * 1024 * 1024
            ),
            max_capability_file_bytes=_int(
                values.get("MAX_CAPABILITY_FILE_BYTES"), 25 * 1024 * 1024
            ),
            capability_timeout_seconds=_float(values.get("CAPABILITY_TIMEOUT_SECONDS"), 120.0),
            harness_enabled=_bool(values.get("HARNESS_ENABLED"), True),
            harness_provider=values.get("HARNESS_PROVIDER", "deepseek-official"),
            harness_model=values.get("HARNESS_MODEL", "deepseek-v4-flash"),
            harness_max_tokens=_int(values.get("HARNESS_MAX_TOKENS"), 49_152),
            harness_base_url=_optional_url(values.get("DEEPSEEK_BASE_URL"), "DEEPSEEK_BASE_URL"),
            harness_api_key=values.get("DEEPSEEK_API_KEY") or None,
            harness_search_base_url=_optional_url(
                values.get("DEEPSEEK_SEARCH_BASE_URL", "https://api.deepseek.com/anthropic/v1"),
                "DEEPSEEK_SEARCH_BASE_URL",
            ),
            harness_search_model=values.get("DSH_SEARCH_MODEL", values.get("HARNESS_MODEL", "deepseek-v4-flash")),
            harness_search_api_key=(
                values.get("DEEPSEEK_SEARCH_API_KEY")
                or values.get("DEEPSEEK_API_KEY")
                or None
            ),
            harness_runtime_bin=values.get("HARNESS_RUNTIME_BIN") or None,
            harness_launch_args=_launch_args(values.get("HARNESS_LAUNCH_ARGS_JSON")),
            harness_request_timeout_seconds=request_timeout,
            harness_runner_cache_size=_int(values.get("HARNESS_RUNNER_CACHE_SIZE"), 4),
            harness_skill_dirs=_skill_dirs(values.get("HARNESS_SKILL_DIRS"), root),
            capability_mcp_url=mcp_url,
            capability_mcp_token=values.get("CAPABILITY_MCP_TOKEN") or None,
            api_token=values.get("APP_API_TOKEN") or None,
            admin_password=values.get("ADMIN_PASSWORD") or None,
            admin_session_secret=values.get("ADMIN_SESSION_SECRET") or None,
            admin_session_seconds=_int(values.get("ADMIN_SESSION_SECONDS"), 8 * 60 * 60),
            admin_cookie_secure=_bool(values.get("ADMIN_COOKIE_SECURE"), False),
            config_encryption_key=values.get("CONFIG_ENCRYPTION_KEY") or None,
            capabilities=capabilities,
        )

    @property
    def conversation_root(self) -> Path:
        return self.data_dir / "conversations"

    @property
    def harness_session_root(self) -> Path:
        return self.data_dir / "harness-sessions"

    @property
    def operation_log_path(self) -> Path:
        """Private, temporary JSONL operation log kept inside DATA_DIR."""

        return self.data_dir / "logs" / "operations.jsonl"

    def runtime_env(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        search_model: str | None = None,
        search_api_key: str | None = None,
        search_base_url: str | None = None,
        capability_mcp_token: str | None = None,
    ) -> dict[str, str]:
        # The SDK launcher starts from os.environ.copy(). Explicitly blank every
        # inherited secret-like variable, then add only credentials that this
        # particular research runtime needs. This keeps admin and specialist API
        # secrets out of the model-controlled subprocess.
        result = {
            name: ""
            for name in os.environ
            if any(
                marker in name.upper()
                for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH", "COOKIE")
            )
        }
        result.update({
            "CAPABILITY_MCP_URL": self.capability_mcp_url,
            "DEEPSEEK_BASE_URL": base_url or "https://api.deepseek.com",
            "DSH_PERMISSION_MODE": "workspace-write",
            "DSH_CUSTOM_SKILL_DIRS_JSON": json.dumps(
                [str(path) for path in self.harness_skill_dirs], ensure_ascii=False
            ),
            "DSH_MODEL": model or self.harness_model,
        })
        if api_key:
            result["DEEPSEEK_API_KEY"] = api_key
        if search_api_key:
            result["DEEPSEEK_SEARCH_API_KEY"] = search_api_key
        if search_model:
            result["DSH_SEARCH_MODEL"] = search_model
        result["DEEPSEEK_SEARCH_BASE_URL"] = (
            search_base_url or "https://api.deepseek.com/anthropic/v1"
        )
        effective_mcp_token = capability_mcp_token or self.capability_mcp_token
        if effective_mcp_token:
            result["CAPABILITY_MCP_TOKEN"] = effective_mcp_token
        return result
