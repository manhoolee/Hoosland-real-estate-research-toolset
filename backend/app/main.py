from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, AsyncIterator

from fastapi import Body, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from . import __version__
from .admin_auth import AdminAuth
from .capabilities import CapabilityGateway, McpAccessRegistry
from .config import CAPABILITY_NAMES, Settings
from .harness_adapter import (
    CONTROLLER_SKILL_ID,
    HarnessAdapterError,
    HarnessManager,
    build_harness_prompt,
    notification_to_operation_event,
    notification_to_output_write_attempt,
    notification_to_stream_event,
    notification_to_token_retry_attempt,
    notification_to_token_usage_sample,
    output_relative_path_id,
    research_progress_event,
)
from .mcp_protocol import McpProtocol
from .operation_log import OperationLog
from .pdf_runtime import pdf_runtime_status
from .runtime_config import DEFAULT_OUTPUT_FORMATS, RuntimeConfigError, RuntimeConfigStore
from .storage import (
    ConversationNotFound,
    ConversationStore,
    FileNotFound,
    InvalidIdentifier,
    ProjectConflict,
    ProjectNotFound,
    StorageError,
)


LOGGER = logging.getLogger("real_estate_backend")

_OUTPUT_DELIVERY_SKILLS = frozenset(
    {
        "hoosland-pdf-output",
    }
)


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    project_id: str | None = None


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    conversation_id: str | None = None


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=200_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
    retry_of: str | None = Field(default=None, pattern=r"^msg_[0-9a-f]{32}$")
    client_request_id: str | None = Field(
        default=None,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
    )


class AdminLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1_000)


@dataclass(slots=True)
class ActiveRun:
    run_id: str
    cancel_event: asyncio.Event
    task: asyncio.Task[None] | None = None
    project_id: str | None = None
    session_generation: int = 0
    session_rotated: bool = False
    rotate_session_on_exit: bool = False
    user_message_id: str | None = None
    client_request_id: str | None = None


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 404 and "." not in Path(path).name:
            return await super().get_response("index.html", scope)
        return response


def _json_error(status: int, code: str, message: str, **details: Any) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


def _sse(event: dict[str, Any]) -> bytes:
    event_name = str(event.get("type", "message"))
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8")


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    if not value.lower().startswith("bearer "):
        return None
    return value[7:].strip()


def _request_identifier(request: Request) -> str:
    # A client-provided correlation header can itself contain a credential or
    # user text. Use a server-generated opaque id for both the response and log.
    del request
    return uuid.uuid4().hex


def _request_resource_ids(path: str) -> dict[str, str]:
    project_match = re.match(
        r"^/api/projects/([A-Za-z0-9_-]{1,128})(?:/conversations)?$",
        path,
    )
    if project_match is not None:
        return {"project_id": project_match.group(1)}
    match = re.match(
        r"^/api/conversations/([A-Za-z0-9_-]{1,128})(?:/files/([A-Za-z0-9_-]{1,128}))?",
        path,
    )
    if match is None:
        return {}
    result = {"conversation_id": match.group(1)}
    if match.group(2):
        result["file_id"] = match.group(2)
    return result


def _operation_route(path: str) -> str:
    if path in {"/", "/mcp"}:
        return path
    if re.fullmatch(
        r"/api/projects/[A-Za-z0-9_-]{1,128}/conversations",
        path,
    ):
        return "/api/projects/{project_id}/conversations"
    conversation = re.fullmatch(
        r"/api/conversations/[A-Za-z0-9_-]{1,128}"
        r"(?P<suffix>/messages|/run|/usage|/cancel|/files(?:/[A-Za-z0-9_-]{1,128}(?:/open)?)?)?",
        path,
    )
    if conversation is not None:
        suffix = conversation.group("suffix") or ""
        suffix = re.sub(r"/files/[A-Za-z0-9_-]{1,128}", "/files/{file_id}", suffix)
        return f"/api/conversations/{{conversation_id}}{suffix}"
    known = {
        "/api/health/live",
        "/api/health/ready",
        "/api/admin/status",
        "/api/admin/login",
        "/api/admin/logout",
        "/api/admin/config",
        "/api/admin/conversations",
        "/api/admin/projects",
        "/api/capabilities",
        "/api/conversations",
        "/api/projects",
        "/api/docs",
        "/api/openapi.json",
    }
    return path if path in known else "/api/{unmatched}"


def _file_type(value: object) -> str:
    suffix = Path(str(value or "")).suffix.lower().lstrip(".")
    allowed = {
        "csv", "doc", "docx", "gif", "htm", "html", "jpeg", "jpg", "json",
        "md", "pdf", "png", "ppt", "pptx", "svg", "tsv", "txt", "webp",
        "xls", "xlsx",
    }
    return suffix if suffix in allowed else "other"


def _mcp_request_metadata(message: object) -> dict[str, object]:
    if isinstance(message, list):
        return {"mcp_method": "batch", "batch_size": len(message)}
    if not isinstance(message, dict):
        return {"mcp_method": "invalid"}
    method = message.get("method")
    allowed_methods = {"initialize", "ping", "tools/list", "tools/call"}
    safe_method = method if isinstance(method, str) and method in allowed_methods else "unknown"
    result: dict[str, object] = {
        "mcp_method": safe_method
    }
    params = message.get("params")
    if method == "tools/call" and isinstance(params, dict):
        tool_name = params.get("name")
        result["tool_name"] = tool_name if tool_name in CAPABILITY_NAMES else "unknown"
    return result


def _mcp_result_error_code(result: object) -> str | None:
    if isinstance(result, list):
        codes = [_mcp_result_error_code(item) for item in result]
        return "MCP_BATCH_PARTIAL_FAILURE" if any(codes) else None
    if not isinstance(result, dict):
        return None
    protocol_error = result.get("error")
    if isinstance(protocol_error, dict):
        code = protocol_error.get("code")
        return f"MCP_JSONRPC_{code}" if isinstance(code, int) else "MCP_JSONRPC_ERROR"
    payload = result.get("result")
    if not isinstance(payload, dict) or not payload.get("isError"):
        return None
    structured = payload.get("structuredContent")
    if isinstance(structured, dict):
        error = structured.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return str(error["code"])[:120]
    return "CAPABILITY_ERROR"


def _research_assistant_text(value: str) -> str:
    return re.sub(r"deepseek[-_ ]?harness|harness", "研究助手", value, flags=re.I)


def _output_fingerprint(root: Path) -> dict[str, tuple[int, int]]:
    """Return content-free metadata for regular files already in outputs."""

    result: dict[str, tuple[int, int]] = {}
    try:
        candidates = root.rglob("*")
        for path in candidates:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                stat = path.stat()
                result[path.relative_to(root).as_posix()] = (
                    int(stat.st_size),
                    int(stat.st_mtime_ns),
                )
            except (OSError, ValueError):
                continue
    except OSError:
        return {}
    return result


def _has_new_or_updated_output(
    baseline: dict[str, tuple[int, int]],
    current: dict[str, tuple[int, int]],
) -> bool:
    return any(
        metadata[0] > 0 and baseline.get(name) != metadata
        for name, metadata in current.items()
    )


def _new_or_updated_output_formats(
    baseline: dict[str, tuple[int, int]],
    current: dict[str, tuple[int, int]],
) -> list[str]:
    return sorted(
        {
            _file_type(name)
            for name, metadata in current.items()
            if metadata[0] > 0 and baseline.get(name) != metadata
        }
    )


def _public_run_error_message(code: str) -> str:
    if code == "AGENT_CANCELLED":
        return "本次研究已终止，可以继续发送消息"
    if code in {
        "AGENT_DISABLED",
        "AGENT_RUNTIME_UNAVAILABLE",
        "AGENT_CONFIG_MISSING",
        "AGENT_CONTROLLER_SKILL_MISSING",
    }:
        return "研究服务当前不可用，请联系管理员检查配置。"
    if code == "AGENT_BUSY":
        return "上一轮研究仍在进行，请稍后再试。"
    return "本轮研究暂未完成，请重试；详细原因已记录在后台。"


def _public_message(message: dict[str, Any]) -> dict[str, Any]:
    result = dict(message)
    if result.get("role") == "assistant" and isinstance(result.get("content"), str):
        result["content"] = _research_assistant_text(result["content"])
    # Message metadata is an internal persistence contract used to pair
    # successful turns and diagnose the runtime.  The chat UI does not need
    # session ids, reply ids, generation counters, or injection flags.
    metadata = result.pop("metadata", None)
    stored_status = str(result.get("status") or "completed").lower()
    result["status"] = {
        "completed": "complete",
        "succeeded": "complete",
        "failed": "error",
        "cancelled": "stopped",
    }.get(stored_status, stored_status)
    if result.get("role") == "assistant" and isinstance(metadata, dict):
        reply_to = metadata.get("reply_to")
        if isinstance(reply_to, str) and re.fullmatch(r"msg_[0-9a-f]{32}", reply_to):
            result["reply_to"] = reply_to
        public_error = metadata.get("public_error")
        if result["status"] in {"error", "stopped"} and isinstance(public_error, str):
            result["error_message"] = _research_assistant_text(public_error)[:500]
            result["retryable"] = True
    return result


def _public_run_state(record: dict[str, Any], *, active: bool) -> dict[str, Any]:
    status = str(record.get("status") or "idle")
    result: dict[str, Any] = {
        "status": status,
        "active": active,
        "retryable": bool(record.get("retryable", False)),
    }
    for field in (
        "client_request_id",
        "user_message_id",
        "started_at",
        "updated_at",
        "completed_at",
    ):
        value = record.get(field)
        if isinstance(value, str):
            result[field] = value
    return result


def _public_token_usage(record: dict[str, Any]) -> dict[str, Any]:
    totals = record.get("totals")
    if not isinstance(totals, dict):
        totals = {}

    def bucket(name: str) -> int:
        value = totals.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    uncached_input_tokens = bucket("uncached_input_tokens")
    output_tokens = bucket("output_tokens")
    reasoning_tokens = bucket("reasoning_tokens")
    cache_read_tokens = bucket("cache_read_tokens")
    cache_write_tokens = bucket("cache_write_tokens")
    return {
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        # reasoning_tokens is an output subdivision and is intentionally not
        # added again here.
        "total_tokens": (
            uncached_input_tokens
            + output_tokens
            + cache_read_tokens
            + cache_write_tokens
        ),
        "updated_at": record.get("updated_at"),
        "includes_subagents": True,
        "source": "provider_reported",
    }


def _token_usage_event(
    conversation_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "usage",
        "conversation_id": conversation_id,
        "usage": _public_token_usage(record),
    }


def _assistant_reply_for(
    messages: list[dict[str, Any]],
    user_message_id: str,
) -> dict[str, Any] | None:
    for item in reversed(messages):
        metadata = item.get("metadata")
        if (
            item.get("role") == "assistant"
            and isinstance(metadata, dict)
            and metadata.get("reply_to") == user_message_id
        ):
            return item
    return None


def _visible_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold superseded retry outcomes while retaining the append-only audit log."""

    latest_reply_index: dict[str, int] = {}
    for index, item in enumerate(messages):
        metadata = item.get("metadata")
        reply_to = metadata.get("reply_to") if isinstance(metadata, dict) else None
        if item.get("role") == "assistant" and isinstance(reply_to, str):
            latest_reply_index[reply_to] = index
    return [
        item
        for index, item in enumerate(messages)
        if not (
            item.get("role") == "assistant"
            and isinstance(item.get("metadata"), dict)
            and isinstance(item["metadata"].get("reply_to"), str)
            and latest_reply_index.get(item["metadata"]["reply_to"]) != index
        )
    ]


def _public_conversation_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": summary["id"],
        "project_id": summary["project_id"],
        "created_at": summary["created_at"],
        "updated_at": summary["updated_at"],
        "title": _research_assistant_text(summary["title"]),
        "preview": _research_assistant_text(summary["preview"]),
        "message_count": summary["message_count"],
    }


def _public_project_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": summary["id"],
        "created_at": summary["created_at"],
        "updated_at": summary["updated_at"],
        "title": _research_assistant_text(summary["title"]),
        "preview": _research_assistant_text(summary["preview"]),
        "conversation_count": summary["conversation_count"],
        "message_count": summary["message_count"],
        "conversations": [
            _public_conversation_summary(item)
            for item in summary["conversations"]
        ],
    }


def _metadata_generation(metadata: dict[str, Any], key: str, default: int) -> int:
    value = metadata.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def _completed_conversation_history(
    messages: list[dict[str, Any]],
    *,
    maximum_characters: int = 120_000,
) -> list[dict[str, str]]:
    """Return bounded successful user/assistant pairs for a stateless web turn.

    User turns that were cancelled or failed have no successful assistant reply
    and are deliberately excluded, so a cancelled instruction is not replayed.
    """

    users = {
        item.get("id"): item.get("content")
        for item in messages
        if item.get("role") == "user"
        and isinstance(item.get("id"), str)
        and isinstance(item.get("content"), str)
    }
    pairs: list[list[dict[str, str]]] = []
    for item in messages:
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        metadata = item.get("metadata")
        if not isinstance(content, str) or not content.strip() or not isinstance(metadata, dict):
            continue
        finish_reason = metadata.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason.strip().lower() in {
            "cancelled",
            "canceled",
            "error",
            "failed",
            "failure",
            "stopped",
        }:
            continue
        reply_to = metadata.get("reply_to")
        user_content = users.get(reply_to)
        if not isinstance(user_content, str):
            continue
        pairs.append(
            [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": content},
            ]
        )

    if maximum_characters < 2:
        return []

    selected: list[list[dict[str, str]]] = []
    used = 0
    for pair in reversed(pairs):
        pair_size = sum(len(message["content"]) for message in pair)
        remaining = maximum_characters - used
        if remaining < 2:
            break
        if pair_size > remaining:
            # Keep complete older pairs when possible.  Only the newest pair
            # may be clipped, and both sides share the budget so an oversized
            # user message can never defeat the history limit.
            if selected:
                break
            user_content = pair[0]["content"]
            assistant_content = pair[1]["content"]
            user_budget = min(len(user_content), remaining // 2)
            assistant_budget = min(len(assistant_content), remaining - user_budget)
            spare = remaining - user_budget - assistant_budget
            if spare:
                additional_user = min(len(user_content) - user_budget, spare)
                user_budget += additional_user
                spare -= additional_user
            if spare:
                assistant_budget += min(
                    len(assistant_content) - assistant_budget,
                    spare,
                )
            if user_budget == 0 or assistant_budget == 0:
                break
            pair = [
                {"role": "user", "content": user_content[-user_budget:]},
                {
                    "role": "assistant",
                    "content": assistant_content[-assistant_budget:],
                },
            ]
            pair_size = user_budget + assistant_budget
        selected.append(pair)
        used += pair_size
    return [message for pair in reversed(selected) for message in pair]


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    operation_log = OperationLog(
        app_settings.operation_log_path,
        enabled=app_settings.operation_log_enabled,
        retention_days=app_settings.operation_log_retention_days,
    )
    store = ConversationStore(app_settings.conversation_root)
    runtime_config = RuntimeConfigStore(app_settings)
    gateway = CapabilityGateway(app_settings, runtime_config)
    mcp_registry = McpAccessRegistry()
    mcp = McpProtocol(gateway)
    harness = HarnessManager(app_settings, store, runtime_config, mcp_registry)
    admin_auth = AdminAuth(app_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        app_settings.data_dir.mkdir(parents=True, exist_ok=True)
        app_settings.harness_session_root.mkdir(parents=True, exist_ok=True)
        try:
            operation_log.start()
        except OSError:
            LOGGER.exception("Unable to start the private operation log")
        operation_log.record(
            "service.started",
            source="backend",
            environment=app_settings.environment,
            retention_days=app_settings.operation_log_retention_days,
        )
        LOGGER.info(
            "backend starting env=%s data_dir=%s frontend=%s",
            app_settings.environment,
            app_settings.data_dir,
            app_settings.frontend_dist,
        )
        try:
            yield
        finally:
            for active in application.state.active_runs.values():
                active.cancel_event.set()
            await harness.close()
            tasks = list(application.state.background_tasks)
            if tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
                except TimeoutError:
                    for task in tasks:
                        task.cancel()
            operation_log.record("service.stopped", source="backend")
            operation_log.close()

    app = FastAPI(
        title="Hoosland-real-estate-research-toolset",
        version=__version__,
        docs_url="/api/docs" if app_settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if app_settings.environment != "production" else None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.store = store
    app.state.gateway = gateway
    app.state.mcp_registry = mcp_registry
    app.state.harness = harness
    app.state.runtime_config = runtime_config
    app.state.admin_auth = admin_auth
    app.state.operation_log = operation_log
    app.state.active_runs: dict[str, ActiveRun] = {}
    app.state.active_guard = asyncio.Lock()
    app.state.config_update_in_progress = False
    app.state.background_tasks: set[asyncio.Task[None]] = set()

    def read_token_usage_safely(conversation_id: str) -> dict[str, Any]:
        """Keep optional accounting damage from blocking the research chat."""

        try:
            return store.read_token_usage(conversation_id)
        except Exception:
            operation_log.record(
                "agent.token_usage.failed",
                source="backend",
                conversation_id=conversation_id,
                error_code="TOKEN_USAGE_READ_FAILED",
            )
            LOGGER.exception("Failed to read token usage conversation=%s", conversation_id)
            return {"totals": {}, "updated_at": None}

    def begin_token_usage_run_safely(conversation_id: str, run_id: str) -> None:
        try:
            store.begin_token_usage_run(conversation_id, run_id)
        except Exception:
            operation_log.record(
                "agent.token_usage.failed",
                source="backend",
                conversation_id=conversation_id,
                run_id=run_id,
                error_code="TOKEN_USAGE_BEGIN_FAILED",
            )
            LOGGER.exception(
                "Failed to begin token usage run conversation=%s run=%s",
                conversation_id,
                run_id,
            )

    def rotate_active_session(conversation_id: str, active: ActiveRun) -> None:
        """Persist exactly one new SDK session generation for a disposed run."""

        if active.session_rotated:
            return
        metadata = store.read_meta(conversation_id)
        current = _metadata_generation(metadata, "agent_session_generation", 0)
        next_generation = max(current, active.session_generation) + 1
        store.update_meta(
            conversation_id,
            agent_session_generation=next_generation,
        )
        active.session_rotated = True
        operation_log.record(
            "agent.session.rotated",
            source="backend",
            project_id=metadata["project_id"],
            conversation_id=conversation_id,
            run_id=active.run_id,
            session_generation=next_generation,
        )
        LOGGER.info(
            "Rotated agent session conversation=%s generation=%s",
            conversation_id,
            next_generation,
        )

    def write_run_state(
        conversation_id: str,
        *,
        status: str,
        active: ActiveRun,
        assistant_message_id: str | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        required: bool = False,
    ) -> dict[str, Any] | None:
        """Persist run state without turning a completed model run into an API failure."""

        try:
            return store.write_run(
                conversation_id,
                status=status,
                run_id=active.run_id,
                client_request_id=active.client_request_id,
                user_message_id=active.user_message_id,
                assistant_message_id=assistant_message_id,
                error_code=error_code,
                retryable=retryable,
            )
        except Exception:
            operation_log.record(
                "agent.run_state.failed",
                source="backend",
                conversation_id=conversation_id,
                run_id=active.run_id,
                error_code="RUN_STATE_PERSIST_FAILED",
            )
            LOGGER.exception(
                "Failed to persist agent run state conversation=%s run=%s status=%s",
                conversation_id,
                active.run_id,
                status,
            )
            if required:
                raise
            return None

    def append_terminal_assistant(
        conversation_id: str,
        *,
        active: ActiveRun,
        status: str,
        public_error: str,
        finish_reason: str,
    ) -> dict[str, Any] | None:
        """Persist a safe terminal assistant projection for refresh/retry recovery."""

        if not active.user_message_id:
            return None

        try:
            return store.append_message(
                conversation_id,
                role="assistant",
                content="",
                status=status,
                metadata={
                    "finish_reason": finish_reason,
                    "reply_to": active.user_message_id,
                    "run_id": active.run_id,
                    "public_error": public_error,
                },
            )
        except Exception:
            operation_log.record(
                "agent.terminal_message.failed",
                source="backend",
                conversation_id=conversation_id,
                run_id=active.run_id,
                error_code="TERMINAL_MESSAGE_PERSIST_FAILED",
            )
            LOGGER.exception(
                "Failed to persist terminal assistant state conversation=%s run=%s",
                conversation_id,
                active.run_id,
            )
            return None

    def reconcile_inactive_run(
        conversation_id: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist legacy projections and repair orphaned running records."""

        is_legacy = record.get("legacy") is True
        if not is_legacy and record.get("status") != "running":
            return record
        user_message_id = record.get("user_message_id")
        reply = (
            _assistant_reply_for(store.list_messages(conversation_id), user_message_id)
            if isinstance(user_message_id, str)
            else None
        )
        if reply is not None and not is_legacy:
            reply_metadata = reply.get("metadata")
            reply_run_id = (
                reply_metadata.get("run_id")
                if isinstance(reply_metadata, dict)
                else None
            )
            record_run_id = record.get("run_id")
            reply_created_at = reply.get("created_at")
            run_started_at = record.get("started_at")
            if (
                isinstance(reply_run_id, str)
                and isinstance(record_run_id, str)
                and reply_run_id != record_run_id
            ) or (
                not isinstance(reply_run_id, str)
                and isinstance(reply_created_at, str)
                and isinstance(run_started_at, str)
                and reply_created_at < run_started_at
            ):
                reply = None
        reply_status = str(reply.get("status") or "").lower() if reply else ""
        if is_legacy and record.get("status") == "idle":
            repaired_status, retryable = "idle", False
        elif reply_status in {"complete", "completed", "succeeded"}:
            repaired_status, retryable = "succeeded", False
        elif reply_status in {"error", "failed"}:
            repaired_status, retryable = "failed", True
        elif reply_status in {"stopped", "cancelled", "canceled"}:
            repaired_status, retryable = "cancelled", True
        else:
            repaired_status, retryable = "interrupted", True

        if (
            repaired_status == "interrupted"
            and reply is None
            and isinstance(user_message_id, str)
        ):
            try:
                reply = store.append_message(
                    conversation_id,
                    role="assistant",
                    content="",
                    status="error",
                    metadata={
                        "finish_reason": "interrupted",
                        "reply_to": user_message_id,
                        **(
                            {"run_id": record["run_id"]}
                            if isinstance(record.get("run_id"), str)
                            else {}
                        ),
                        "public_error": (
                            "上次后台任务因服务重启未能完成，可以从原请求继续重试。"
                        ),
                    },
                )
            except Exception:
                LOGGER.exception(
                    "Failed to persist interrupted terminal state conversation=%s",
                    conversation_id,
                )
        return store.write_run(
            conversation_id,
            status=repaired_status,
            run_id=(record.get("run_id") if isinstance(record.get("run_id"), str) else None),
            client_request_id=(
                record.get("client_request_id")
                if isinstance(record.get("client_request_id"), str)
                else None
            ),
            user_message_id=(
                user_message_id if isinstance(user_message_id, str) else None
            ),
            assistant_message_id=(reply.get("id") if isinstance(reply, dict) else None),
            error_code=("RUN_INTERRUPTED" if repaired_status == "interrupted" else None),
            retryable=retryable,
        )

    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(app_settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "mcp-protocol-version", "mcp-session-id"],
        )

    @app.middleware("http")
    async def request_policy(request: Request, call_next: Any) -> Response:
        started_at = perf_counter()
        request_id = _request_identifier(request)
        request.state.request_id = request_id
        tracked = request.url.path.startswith("/api/") or request.url.path in {"/", "/mcp"}
        content_length = request.headers.get("content-length")
        declared_size: int | None = None

        def finish(response: Response, *, error_type: str | None = None) -> Response:
            response.headers["x-request-id"] = request_id
            response.headers["x-content-type-options"] = "nosniff"
            response.headers["referrer-policy"] = "no-referrer"
            if request.url.path.startswith("/api/") or request.url.path == "/mcp":
                response.headers["cache-control"] = "no-store"
            if tracked:
                route = getattr(request.scope.get("route"), "path", None)
                operation_log.record(
                    "http.request",
                    source="api",
                    request_id=request_id,
                    method=request.method,
                    route=route if isinstance(route, str) else _operation_route(request.url.path),
                    status_code=response.status_code,
                    outcome=(
                        "succeeded"
                        if response.status_code < 400
                        else "rejected"
                        if response.status_code < 500
                        else "failed"
                    ),
                    duration_ms=round((perf_counter() - started_at) * 1000, 3),
                    request_bytes=declared_size,
                    error_type=error_type,
                    **_request_resource_ids(request.url.path),
                )
            return response

        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return finish(
                    _json_error(400, "INVALID_CONTENT_LENGTH", "Content-Length must be an integer")
                )
            if declared_size > app_settings.max_request_bytes:
                return finish(
                    _json_error(413, "REQUEST_TOO_LARGE", "request exceeds the configured byte limit")
                )

        if (
            app_settings.api_token
            and request.url.path.startswith("/api/")
            and not request.url.path.startswith("/api/health/")
            and not request.url.path.startswith("/api/admin/")
        ):
            supplied = _bearer(request)
            if supplied is None or not hmac.compare_digest(supplied, app_settings.api_token):
                return finish(
                    _json_error(401, "UNAUTHORIZED", "a valid API bearer token is required")
                )

        try:
            response = await call_next(request)
        except Exception as exc:
            if tracked:
                operation_log.record(
                    "http.request",
                    source="api",
                    request_id=request_id,
                    method=request.method,
                    route=_operation_route(request.url.path),
                    status_code=500,
                    outcome="failed",
                    duration_ms=round((perf_counter() - started_at) * 1000, 3),
                    request_bytes=declared_size,
                    error_type=type(exc).__name__,
                    **_request_resource_ids(request.url.path),
                )
            raise
        return finish(response)

    @app.exception_handler(StorageError)
    async def storage_error_handler(_request: Request, exc: StorageError) -> JSONResponse:
        if isinstance(exc, (ConversationNotFound, FileNotFound, ProjectNotFound)):
            status = 404
        elif isinstance(exc, ProjectConflict):
            status = 409
        elif isinstance(exc, InvalidIdentifier):
            status = 400
        else:
            status = 500
        return _json_error(status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _json_error(422, "VALIDATION_ERROR", "request validation failed", issues=exc.errors())

    @app.exception_handler(RuntimeConfigError)
    async def runtime_config_error_handler(
        _request: Request,
        exc: RuntimeConfigError,
    ) -> JSONResponse:
        status = 503 if exc.code in {"CONFIG_ENCRYPTION_REQUIRED", "CONFIG_DECRYPT_FAILED"} else 422
        return _json_error(status, exc.code, exc.message)

    @app.get("/api/health/live")
    async def live() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "slot": app_settings.slot,
            "build_id": app_settings.build_id,
        }

    @app.get("/api/health/ready")
    async def ready() -> JSONResponse:
        harness_status = harness.status()
        is_ready = bool(harness_status["configured"])
        return JSONResponse(
            {
                "ready": is_ready,
                "version": __version__,
                "slot": app_settings.slot,
                "build_id": app_settings.build_id,
                "agent": harness_status,
                "frontend_built": app_settings.frontend_dist.joinpath("index.html").is_file(),
            },
            status_code=200 if is_ready else 503,
        )

    def require_same_origin(request: Request) -> None:
        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if fetch_site == "cross-site":
            raise HTTPException(status_code=403, detail="管理请求来源不受信任")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="管理请求来源不受信任")

    def require_admin(request: Request) -> None:
        require_same_origin(request)
        if not admin_auth.enabled:
            raise HTTPException(status_code=503, detail="管理后台尚未配置")
        if not admin_auth.authorized(request):
            raise HTTPException(status_code=401, detail="管理会话无效或已过期")

    @app.get("/api/admin/status")
    async def admin_status(request: Request) -> dict[str, Any]:
        return {
            "enabled": admin_auth.enabled,
            "authenticated": admin_auth.authorized(request),
            "encryption_ready": runtime_config.writable,
        }

    @app.post("/api/admin/login")
    async def admin_login(
        request: Request,
        payload: AdminLogin,
        response: Response,
    ) -> dict[str, Any]:
        require_same_origin(request)
        if not admin_auth.enabled:
            raise HTTPException(status_code=503, detail="管理后台尚未配置")
        if not admin_auth.authenticate(payload.password):
            operation_log.record(
                "admin.login",
                source="api",
                request_id=request.state.request_id,
                outcome="rejected",
            )
            raise HTTPException(status_code=401, detail="管理密码错误")
        admin_auth.issue(response)
        operation_log.record(
            "admin.login",
            source="api",
            request_id=request.state.request_id,
            outcome="succeeded",
        )
        return {"authenticated": True}

    @app.post("/api/admin/logout")
    async def admin_logout(request: Request, response: Response) -> dict[str, Any]:
        require_same_origin(request)
        admin_auth.clear(response)
        operation_log.record(
            "admin.logout",
            source="api",
            request_id=request.state.request_id,
            outcome="succeeded",
        )
        return {"authenticated": False}

    @app.get("/api/admin/config")
    async def get_admin_config(request: Request) -> dict[str, Any]:
        require_admin(request)
        return runtime_config.public()

    @app.put("/api/admin/config")
    async def update_admin_config(
        request: Request,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        require_admin(request)
        async with app.state.active_guard:
            if app.state.config_update_in_progress:
                raise HTTPException(status_code=409, detail="配置正在更新，请稍后重试")
            active = [
                run
                for run in app.state.active_runs.values()
                if run.task is None or not run.task.done()
            ]
            if active:
                raise HTTPException(status_code=409, detail="请等待当前研究完成，或先终止正在进行的研究")
            app.state.config_update_in_progress = True
        try:
            value = runtime_config.update(payload)
            allowed_sections = {
                "main_agent",
                "native_search",
                "capabilities",
                "output",
            }
            operation_log.record(
                "admin.configuration.updated",
                source="api",
                request_id=request.state.request_id,
                changed_sections=sorted(set(payload).intersection(allowed_sections)),
            )
            await harness.reset()
            return value
        finally:
            async with app.state.active_guard:
                app.state.config_update_in_progress = False

    @app.get("/api/capabilities")
    async def capabilities() -> dict[str, Any]:
        skill_found = any(
            (path / CONTROLLER_SKILL_ID / "SKILL.md").is_file()
            or (path / f"{CONTROLLER_SKILL_ID}.md").is_file()
            for path in app_settings.harness_skill_dirs
        )
        items: list[dict[str, Any]] = [harness.status()]
        items.append(
            {
                "name": CONTROLLER_SKILL_ID,
                "label": "房地产综合研究总控",
                "configured": skill_found,
                "status": "configured" if skill_found else "not_verified",
                "reason": None if skill_found else "已配置的专业技能目录中未找到房地产综合研究总控",
            }
        )
        search = runtime_config.native_search()
        search_configured = bool(search.get("api_key"))
        items.append(
            {
                "name": "native_web_search",
                "configured": search_configured,
                "status": "configured" if search_configured else "credential_missing",
                "provider": "deepseek",
                "model": search.get("model"),
            }
        )
        items.append(
            {
                "name": "document_workspace_files",
                "configured": True,
                "status": "configured",
                "read": True,
                "write": True,
                "sandbox": "conversation_workspace",
            }
        )
        items.append(pdf_runtime_status())
        items.extend(gateway.status())
        return {
            "items": items,
            "mcp": {
                "configured": True,
                "transport": "streamable-http",
                "path": "/mcp",
                "authentication": "per_conversation_bearer",
                "tools": list(CAPABILITY_NAMES),
            },
        }

    @app.post("/api/conversations", status_code=201)
    async def create_conversation(
        request: Request,
        response: Response,
        payload: ConversationCreate | None = Body(default=None),
    ) -> dict[str, Any]:
        requested_id = payload.id if payload else None
        requested_project_id = payload.project_id if payload else None
        if requested_project_id:
            metadata, created = store.create_conversation_in_project(
                requested_project_id,
                requested_id,
            )
        else:
            metadata, created = store.create_or_reuse(requested_id)
        if not created:
            response.status_code = 200
        operation_log.record(
            "conversation.created" if created else "conversation.reused",
            source="api",
            request_id=request.state.request_id,
            project_id=metadata["project_id"],
            conversation_id=metadata["id"],
        )
        return {
            "id": metadata["id"],
            "project_id": metadata["project_id"],
            "created": created,
            "created_at": metadata["created_at"],
            "updated_at": metadata["updated_at"],
        }

    @app.post("/api/projects", status_code=201)
    async def create_project(
        request: Request,
        payload: ProjectCreate | None = Body(default=None),
    ) -> dict[str, Any]:
        project_id, metadata = store.create_project(
            payload.id if payload else None,
            requested_conversation_id=payload.conversation_id if payload else None,
        )
        operation_log.record(
            "project.created",
            source="api",
            request_id=request.state.request_id,
            project_id=project_id,
            conversation_id=metadata["id"],
        )
        operation_log.record(
            "conversation.created",
            source="api",
            request_id=request.state.request_id,
            project_id=project_id,
            conversation_id=metadata["id"],
        )
        return {
            "id": project_id,
            "project_id": project_id,
            "created": True,
            "created_at": metadata["created_at"],
            "updated_at": metadata["updated_at"],
            "conversation": {
                "id": metadata["id"],
                "project_id": project_id,
                "created_at": metadata["created_at"],
                "updated_at": metadata["updated_at"],
            },
        }

    @app.post("/api/projects/{project_id}/conversations", status_code=201)
    async def create_project_conversation(
        request: Request,
        project_id: str,
        response: Response,
        payload: ConversationCreate | None = Body(default=None),
    ) -> dict[str, Any]:
        if payload and payload.project_id and payload.project_id != project_id:
            raise HTTPException(status_code=409, detail="对话不能同时属于两个项目")
        metadata, created = store.create_conversation_in_project(
            project_id,
            payload.id if payload else None,
        )
        if not created:
            response.status_code = 200
        operation_log.record(
            "conversation.created" if created else "conversation.reused",
            source="api",
            request_id=request.state.request_id,
            project_id=metadata["project_id"],
            conversation_id=metadata["id"],
        )
        return {
            "id": metadata["id"],
            "project_id": metadata["project_id"],
            "created": created,
            "created_at": metadata["created_at"],
            "updated_at": metadata["updated_at"],
        }

    @app.get("/api/admin/conversations")
    async def list_conversations(request: Request) -> dict[str, Any]:
        require_admin(request)
        return {
            "items": [
                _public_conversation_summary(item)
                for item in store.list_conversations()
            ][:200]
        }

    @app.get("/api/admin/projects")
    async def list_projects(request: Request) -> dict[str, Any]:
        require_admin(request)
        return {
            "items": [
                _public_project_summary(item)
                for item in store.list_projects()
            ][:200]
        }

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> dict[str, Any]:
        metadata = store.read_meta(conversation_id)
        return {
            "id": metadata["id"],
            "project_id": metadata["project_id"],
            "created_at": metadata["created_at"],
            "updated_at": metadata["updated_at"],
        }

    @app.get("/api/conversations/{conversation_id}/messages")
    async def list_messages(conversation_id: str) -> dict[str, Any]:
        messages = _visible_messages(store.list_messages(conversation_id))
        return {"items": [_public_message(item) for item in messages]}

    @app.get("/api/conversations/{conversation_id}/run")
    async def get_conversation_run(conversation_id: str) -> dict[str, Any]:
        store.require(conversation_id)
        async with app.state.active_guard:
            active = app.state.active_runs.get(conversation_id)
            if active is not None:
                record = store.read_run(conversation_id)
                record = (
                    dict(record)
                    if record.get("run_id") == active.run_id
                    else {}
                )
                record["status"] = (
                    "termination_requested" if active.cancel_event.is_set() else "running"
                )
                record["retryable"] = False
                active_client_request_id = getattr(active, "client_request_id", None)
                if active_client_request_id:
                    record["client_request_id"] = active_client_request_id
                if active.user_message_id:
                    record["user_message_id"] = active.user_message_id
                return _public_run_state(record, active=True)

            record = store.read_run(conversation_id)
            if record.get("status") == "running" or record.get("legacy") is True:
                record = reconcile_inactive_run(conversation_id, record)
            return _public_run_state(record, active=False)

    @app.get("/api/conversations/{conversation_id}/usage")
    async def get_conversation_usage(conversation_id: str) -> dict[str, Any]:
        store.require(conversation_id)
        return {
            "conversation_id": conversation_id,
            "usage": _public_token_usage(read_token_usage_safely(conversation_id)),
        }

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(
        request: Request,
        conversation_id: str,
        payload: MessageCreate,
    ) -> Response:
        conversation_paths = store.require(conversation_id)
        content = payload.content.strip()
        if not content:
            raise HTTPException(status_code=422, detail="content must not be blank")

        attachment_ids = list(payload.attachment_ids)
        retry_user_message: dict[str, Any] | None = None
        if payload.retry_of:
            messages = store.list_messages(conversation_id)
            retry_user_message = next(
                (
                    item
                    for item in messages
                    if item.get("id") == payload.retry_of and item.get("role") == "user"
                ),
                None,
            )
            if retry_user_message is None:
                return _json_error(404, "RETRY_TURN_NOT_FOUND", "无法找到需要重试的原任务。")
            original_content = retry_user_message.get("content")
            original_attachment_ids = retry_user_message.get("attachment_ids")
            if not isinstance(original_content, str) or not isinstance(
                original_attachment_ids, list
            ):
                return _json_error(409, "RETRY_TURN_INVALID", "原任务记录不完整，无法安全重试。")
            if content != original_content.strip() or attachment_ids != original_attachment_ids:
                return _json_error(
                    409,
                    "RETRY_PAYLOAD_MISMATCH",
                    "重试内容或附件与原任务不一致，请刷新后重新操作。",
                )
            reply = _assistant_reply_for(messages, payload.retry_of)
            if reply is not None and str(reply.get("status") or "completed").lower() in {
                "complete",
                "completed",
                "succeeded",
            }:
                return _json_error(409, "TURN_ALREADY_COMPLETED", "这轮研究已经完成，无需重试。")
            content = original_content.strip()
            attachment_ids = list(original_attachment_ids)

        attachments = store.input_files(conversation_id, attachment_ids)

        active = ActiveRun(
            run_id=uuid.uuid4().hex,
            cancel_event=asyncio.Event(),
            client_request_id=payload.client_request_id,
        )
        async with app.state.active_guard:
            if app.state.config_update_in_progress:
                return _json_error(409, "CONFIG_UPDATE_ACTIVE", "研究助手配置正在更新，请稍后发送")
            previous = app.state.active_runs.get(conversation_id)
            if previous is not None and previous.task is not None and previous.task.done():
                if (
                    previous.cancel_event.is_set() or previous.rotate_session_on_exit
                ) and not previous.session_rotated:
                    return _json_error(
                        503,
                        "RUN_CLEANUP_PENDING",
                        "上一轮研究的运行会话尚未完成清理，请稍后重试",
                    )
                app.state.active_runs.pop(conversation_id, None)
                previous = None
            if previous is not None:
                if previous.cancel_event.is_set():
                    return _json_error(409, "RUN_TERMINATING", "上一轮研究正在终止，请稍后重试")
                return _json_error(
                    409,
                    "RUN_ACTIVE",
                    "上一轮研究仍在后台运行；刷新不会中断任务，请等待完成或先停止。",
                )
            durable = store.read_run(conversation_id)
            if durable.get("status") == "running" or durable.get("legacy") is True:
                reconcile_inactive_run(conversation_id, durable)
            app.state.active_runs[conversation_id] = active

        try:
            metadata = store.read_meta(conversation_id)
            session_generation = _metadata_generation(
                metadata,
                "agent_session_generation",
                0,
            )
            project_id = str(metadata["project_id"])
            active.project_id = project_id
            active.session_generation = session_generation
            # Web turns are deliberately stateless at the SDK-session layer.
            # Each run receives bounded successful persisted history. The API
            # deterministically activates the comprehensive controller; that
            # controller then routes to specialist skills for this request.
            conversation_history = _completed_conversation_history(
                store.list_messages(conversation_id)
            )
            seed_history = bool(conversation_history)
            user_message = retry_user_message or store.append_message(
                conversation_id,
                role="user",
                content=content,
                attachment_ids=attachment_ids,
                metadata={
                    "agent_session_generation": session_generation,
                    "history_seed_applied": seed_history,
                },
            )
            active.user_message_id = str(user_message["id"])
            write_run_state(
                conversation_id,
                status="running",
                active=active,
                required=True,
            )
            begin_token_usage_run_safely(conversation_id, active.run_id)
            prompt = build_harness_prompt(
                content,
                attachments,
                conversation_history=conversation_history,
                workspace_path=conversation_paths.workspace,
            )
            operation_log.record(
                "agent.controller.injection.prepared",
                source="api",
                request_id=request.state.request_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=active.run_id,
                session_generation=session_generation,
                skill_id=CONTROLLER_SKILL_ID,
            )
            operation_log.record(
                "agent.run.accepted",
                source="api",
                request_id=request.state.request_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=active.run_id,
                session_generation=session_generation,
                content_characters=len(content),
                attachment_count=len(attachment_ids),
                history_seeded=seed_history,
                retried=payload.retry_of is not None,
            )
        except Exception:
            if active.user_message_id:
                terminal_message = append_terminal_assistant(
                    conversation_id,
                    active=active,
                    status="error",
                    public_error=_public_run_error_message("RUN_SETUP_FAILED"),
                    finish_reason="setup_failed",
                )
                write_run_state(
                    conversation_id,
                    status="failed",
                    active=active,
                    assistant_message_id=(
                        str(terminal_message["id"]) if terminal_message else None
                    ),
                    error_code="RUN_SETUP_FAILED",
                    retryable=True,
                )
            async with app.state.active_guard:
                if app.state.active_runs.get(conversation_id) is active:
                    app.state.active_runs.pop(conversation_id, None)
            raise

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        last_notification: dict[str, Any] = {}
        usage_attempts: dict[tuple[str, int, int], int] = {}
        output_write_attempt_count = 0
        misplaced_output_write_attempt_count = 0
        attempted_output_formats: set[str] = set()
        attempted_output_target_ids: set[str] = set()
        output_delivery_skill_invoked = False
        highest_progress_step = 1
        output_baseline = _output_fingerprint(conversation_paths.outputs)
        initial_usage_event = _token_usage_event(
            conversation_id,
            read_token_usage_safely(conversation_id),
        )

        def on_notification(notification: object) -> None:
            nonlocal highest_progress_step
            nonlocal misplaced_output_write_attempt_count
            nonlocal output_delivery_skill_invoked
            nonlocal output_write_attempt_count
            output_attempt = notification_to_output_write_attempt(
                notification,
                conversation_paths.workspace,
            )
            if output_attempt is not None:
                output_write_attempt_count += 1
                if not output_attempt.canonical:
                    misplaced_output_write_attempt_count += 1
                if output_attempt.output_format:
                    attempted_output_formats.add(output_attempt.output_format)
                attempted_output_target_ids.add(output_attempt.target_id)
            retry_attempt = notification_to_token_retry_attempt(notification)
            if retry_attempt is not None:
                usage_attempts[
                    (retry_attempt.session_id, retry_attempt.turn, retry_attempt.step)
                ] = retry_attempt.attempt

            usage_sample = notification_to_token_usage_sample(notification)
            if usage_sample is not None:
                attempt = (
                    usage_attempts.get(
                        (usage_sample.session_id, usage_sample.turn, usage_sample.step),
                        0,
                    )
                    if usage_sample.sample_kind == "model_step"
                    else 0
                )
                try:
                    usage_record, usage_changed = store.record_token_usage(
                        conversation_id,
                        run_id=active.run_id,
                        session_id=usage_sample.session_id,
                        event_seq=usage_sample.event_seq,
                        turn=usage_sample.turn,
                        step=usage_sample.step,
                        attempt=attempt,
                        buckets=usage_sample.buckets(),
                        sample_kind=usage_sample.sample_kind,
                    )
                except Exception:
                    operation_log.record(
                        "agent.token_usage.failed",
                        source="backend",
                        request_id=request.state.request_id,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        run_id=active.run_id,
                        error_code="TOKEN_USAGE_PERSIST_FAILED",
                    )
                    LOGGER.exception(
                        "Failed to persist token usage conversation=%s run=%s",
                        conversation_id,
                        active.run_id,
                    )
                else:
                    # Usage can arrive while a cancellation is settling.  It is
                    # still billable work, so persist and surface the final
                    # snapshot before the stream closes.
                    if usage_changed:
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            _token_usage_event(conversation_id, usage_record),
                        )
            if active.cancel_event.is_set():
                return
            operation_event = notification_to_operation_event(notification)
            if operation_event is not None:
                if operation_event.get("skill_id") in _OUTPUT_DELIVERY_SKILLS:
                    output_delivery_skill_invoked = True
                operation_log.record(
                    "agent.operation",
                    source="harness",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    run_id=active.run_id,
                    session_generation=active.session_generation,
                    **operation_event,
                )
            event = notification_to_stream_event(notification)
            if (
                highest_progress_step < 4
                and operation_event is not None
                and operation_event.get("phase") == "completed"
                and _has_new_or_updated_output(
                    output_baseline,
                    _output_fingerprint(conversation_paths.outputs),
                )
            ):
                event = research_progress_event("delivery")
            if event is None:
                return
            # Customer-visible progress is monotonic and replace-only. Detailed
            # operations remain available exclusively in the private log.
            if event.get("type") == "progress":
                current_step = event.get("current_step")
                if not isinstance(current_step, int) or current_step < highest_progress_step:
                    return
                if event == last_notification:
                    return
                highest_progress_step = current_step
                last_notification.clear()
                last_notification.update(event)
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def is_current() -> bool:
            async with app.state.active_guard:
                return (
                    app.state.active_runs.get(conversation_id) is active
                    and not active.cancel_event.is_set()
                )

        async def worker() -> None:
            run_started_at = perf_counter()
            operation_log.record(
                "agent.run.started",
                source="harness",
                request_id=request.state.request_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=active.run_id,
                session_generation=active.session_generation,
            )
            try:
                if active.cancel_event.is_set():
                    raise asyncio.CancelledError
                result = await harness.run(
                    conversation_id,
                    prompt,
                    on_notification,
                    run_id=active.run_id,
                    session_generation=active.session_generation,
                )
                if not await is_current():
                    raise asyncio.CancelledError
                output_current = _output_fingerprint(conversation_paths.outputs)
                run_output_formats = _new_or_updated_output_formats(
                    output_baseline,
                    output_current,
                )
                changed_output_target_ids = {
                    output_relative_path_id(name)
                    for name, metadata in output_current.items()
                    if metadata[0] > 0 and output_baseline.get(name) != metadata
                }
                missing_attempted_target_count = len(
                    attempted_output_target_ids - changed_output_target_ids
                )
                if (output_write_attempt_count or output_delivery_skill_invoked) and (
                    not changed_output_target_ids
                    or missing_attempted_target_count
                ):
                    operation_log.record(
                        "agent.output.persistence_rejected",
                        source="backend",
                        request_id=request.state.request_id,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        run_id=active.run_id,
                        session_generation=active.session_generation,
                        error_code="AGENT_OUTPUT_NOT_PERSISTED",
                        output_write_attempt_count=output_write_attempt_count,
                        misplaced_output_write_attempt_count=(
                            misplaced_output_write_attempt_count
                        ),
                        attempted_output_formats=sorted(attempted_output_formats),
                        run_output_formats=run_output_formats,
                        missing_attempted_target_count=missing_attempted_target_count,
                        output_delivery_skill_invoked=output_delivery_skill_invoked,
                    )
                    raise HarnessAdapterError(
                        "AGENT_OUTPUT_NOT_PERSISTED",
                        "研究助手尝试生成成果，但文件没有完整写入当前会话的正式成果目录",
                    )
                if seed_history:
                    store.update_meta(
                        conversation_id,
                        agent_session_seeded_generation=active.session_generation,
                    )
                final_response = _research_assistant_text(result.final_response)
                assistant_message = store.append_message(
                    conversation_id,
                    role="assistant",
                    content=final_response,
                    metadata={
                        "finish_reason": result.finish_reason,
                        "agent_session_id": result.session_id,
                        "reply_to": user_message["id"],
                        "run_id": active.run_id,
                    },
                )
                write_run_state(
                    conversation_id,
                    status="succeeded",
                    active=active,
                    assistant_message_id=str(assistant_message["id"]),
                )
                await queue.put(
                    {
                        "type": "final",
                        "message": _public_message(assistant_message),
                    }
                )
                outputs = [
                    item for item in store.list_files(conversation_id)
                    if item.get("kind") == "output"
                ]
                operation_log.record(
                    "agent.run.completed",
                    source="harness",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    run_id=active.run_id,
                    session_generation=active.session_generation,
                    outcome="succeeded",
                    duration_ms=round((perf_counter() - run_started_at) * 1000, 3),
                    finish_reason=result.finish_reason,
                    response_characters=len(final_response),
                    output_count=len(outputs),
                    output_formats=sorted(
                        {
                            _file_type(item.get("name"))
                            for item in outputs
                        }
                    ),
                    run_output_formats=run_output_formats,
                    default_output_pair_present_this_run=set(
                        DEFAULT_OUTPUT_FORMATS
                    ).issubset(run_output_formats),
                )
            except asyncio.CancelledError:
                public_error = _public_run_error_message("AGENT_CANCELLED")
                terminal_message = append_terminal_assistant(
                    conversation_id,
                    active=active,
                    status="stopped",
                    public_error=public_error,
                    finish_reason="cancelled",
                )
                write_run_state(
                    conversation_id,
                    status="cancelled",
                    active=active,
                    assistant_message_id=(
                        str(terminal_message["id"]) if terminal_message else None
                    ),
                    error_code="AGENT_CANCELLED",
                    retryable=True,
                )
                operation_log.record(
                    "agent.run.completed",
                    source="harness",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    run_id=active.run_id,
                    session_generation=active.session_generation,
                    outcome="cancelled",
                    error_code="AGENT_CANCELLED",
                    duration_ms=round((perf_counter() - run_started_at) * 1000, 3),
                )
                await queue.put(
                    {
                        "type": "cancelled",
                        "code": "AGENT_CANCELLED",
                        "message": public_error,
                        "reply_to": active.user_message_id,
                    }
                )
            except HarnessAdapterError as exc:
                LOGGER.warning("Agent run failed conversation=%s code=%s", conversation_id, exc.code)
                event_type = "cancelled" if exc.code == "AGENT_CANCELLED" else "error"
                public_error = _public_run_error_message(exc.code)
                terminal_status = "stopped" if exc.code == "AGENT_CANCELLED" else "error"
                durable_status = "cancelled" if exc.code == "AGENT_CANCELLED" else "failed"
                terminal_message = append_terminal_assistant(
                    conversation_id,
                    active=active,
                    status=terminal_status,
                    public_error=public_error,
                    finish_reason=(
                        "cancelled" if exc.code == "AGENT_CANCELLED" else "failed"
                    ),
                )
                write_run_state(
                    conversation_id,
                    status=durable_status,
                    active=active,
                    assistant_message_id=(
                        str(terminal_message["id"]) if terminal_message else None
                    ),
                    error_code=exc.code,
                    retryable=True,
                )
                operation_log.record(
                    "agent.run.completed",
                    source="harness",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    run_id=active.run_id,
                    session_generation=active.session_generation,
                    outcome="cancelled" if exc.code == "AGENT_CANCELLED" else "failed",
                    error_code=exc.code,
                    duration_ms=round((perf_counter() - run_started_at) * 1000, 3),
                )
                if exc.code in {
                    "AGENT_CANCELLED",
                    "AGENT_RUN_FAILED",
                    "AGENT_PROTOCOL_ERROR",
                    "AGENT_RESPONSE_ERROR",
                    "AGENT_EMPTY_RESPONSE",
                }:
                    active.rotate_session_on_exit = True
                await queue.put(
                    {
                        "type": event_type,
                        "code": exc.code,
                        "message": public_error,
                        "reply_to": active.user_message_id,
                    }
                )
            except Exception:
                LOGGER.exception("Unexpected run failure conversation=%s", conversation_id)
                active.rotate_session_on_exit = True
                public_error = _public_run_error_message("INTERNAL_ERROR")
                terminal_message = append_terminal_assistant(
                    conversation_id,
                    active=active,
                    status="error",
                    public_error=public_error,
                    finish_reason="failed",
                )
                write_run_state(
                    conversation_id,
                    status="failed",
                    active=active,
                    assistant_message_id=(
                        str(terminal_message["id"]) if terminal_message else None
                    ),
                    error_code="INTERNAL_ERROR",
                    retryable=True,
                )
                operation_log.record(
                    "agent.run.completed",
                    source="harness",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    run_id=active.run_id,
                    session_generation=active.session_generation,
                    outcome="failed",
                    error_code="INTERNAL_ERROR",
                    duration_ms=round((perf_counter() - run_started_at) * 1000, 3),
                )
                await queue.put(
                    {
                        "type": "error",
                        "code": "INTERNAL_ERROR",
                        "message": public_error,
                        "reply_to": active.user_message_id,
                    }
                )
            finally:
                await queue.put(None)
                async with app.state.active_guard:
                    rotation_succeeded = True
                    if active.cancel_event.is_set() or active.rotate_session_on_exit:
                        try:
                            rotate_active_session(conversation_id, active)
                        except Exception:
                            rotation_succeeded = False
                            operation_log.record(
                                "agent.cleanup.failed",
                                source="backend",
                                request_id=request.state.request_id,
                                project_id=project_id,
                                conversation_id=conversation_id,
                                run_id=active.run_id,
                                error_code="SESSION_ROTATION_FAILED",
                            )
                            LOGGER.exception(
                                "Failed to rotate disposed agent session conversation=%s run=%s",
                                conversation_id,
                                active.run_id,
                            )
                    if (
                        rotation_succeeded
                        and app.state.active_runs.get(conversation_id) is active
                    ):
                        app.state.active_runs.pop(conversation_id, None)

        task = asyncio.create_task(worker(), name=f"research-agent-{conversation_id}-{active.run_id}")
        active.task = task
        app.state.background_tasks.add(task)
        task.add_done_callback(app.state.background_tasks.discard)

        async def event_stream() -> AsyncIterator[bytes]:
            yield _sse(initial_usage_event)
            yield _sse(research_progress_event("brief"))
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                if event is None:
                    yield _sse({"type": "done"})
                    return
                yield _sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/conversations/{conversation_id}/cancel")
    async def cancel_message(request: Request, conversation_id: str) -> dict[str, Any]:
        conversation_metadata = store.read_meta(conversation_id)
        project_id = str(conversation_metadata["project_id"])
        async with app.state.active_guard:
            active = app.state.active_runs.get(conversation_id)
            if active is None:
                operation_log.record(
                    "agent.cancel",
                    source="api",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    outcome="idle",
                )
                return {"cancelled": False, "status": "idle"}
            active.cancel_event.set()
            operation_log.record(
                "agent.cancel",
                source="api",
                request_id=request.state.request_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=active.run_id,
                outcome="requested",
            )

        cancel_completed = True
        try:
            await asyncio.wait_for(
                harness.cancel(conversation_id, run_id=active.run_id),
                timeout=10.0,
            )
        except TimeoutError:
            cancel_completed = False
            operation_log.record(
                "agent.cancel",
                source="api",
                request_id=request.state.request_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=active.run_id,
                outcome="termination_timeout",
                error_code="AGENT_CANCEL_TIMEOUT",
            )
            LOGGER.warning(
                "Timed out closing cancelled agent runtime conversation=%s run=%s",
                conversation_id,
                active.run_id,
            )
        completed = False
        if cancel_completed and active.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(active.task), timeout=10.0)
                completed = True
            except TimeoutError:
                operation_log.record(
                    "agent.cancel",
                    source="api",
                    request_id=request.state.request_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    run_id=active.run_id,
                    outcome="run_wait_timeout",
                    error_code="AGENT_CANCEL_WAIT_TIMEOUT",
                )
                LOGGER.warning(
                    "Timed out waiting for cancelled agent run conversation=%s run=%s",
                    conversation_id,
                    active.run_id,
                )
        if completed:
            async with app.state.active_guard:
                if not active.session_rotated:
                    try:
                        rotate_active_session(conversation_id, active)
                    except Exception as exc:
                        LOGGER.exception(
                            "Failed to persist cancelled session generation conversation=%s run=%s",
                            conversation_id,
                            active.run_id,
                        )
                        raise HTTPException(
                            status_code=503,
                            detail="本轮已停止，但运行会话清理尚未完成，请稍后再次确认",
                        ) from exc
                if app.state.active_runs.get(conversation_id) is active:
                    app.state.active_runs.pop(conversation_id, None)
        operation_log.record(
            "agent.cancel",
            source="api",
            request_id=request.state.request_id,
            project_id=project_id,
            conversation_id=conversation_id,
            run_id=active.run_id,
            outcome="cancelled" if completed else "termination_requested",
        )
        return {
            "cancelled": completed,
            "requested": True,
            "status": "cancelled" if completed else "termination_requested",
            "message": (
                "本次研究已终止，可以继续发送消息"
                if completed
                else "研究助手正在终止上一轮，请稍后继续"
            ),
        }

    @app.get("/api/conversations/{conversation_id}/files")
    async def list_files(conversation_id: str) -> dict[str, Any]:
        return {"items": store.list_files(conversation_id)}

    @app.post("/api/conversations/{conversation_id}/files", status_code=201)
    async def upload_files(conversation_id: str, request: Request) -> dict[str, Any]:
        conversation_metadata = store.read_meta(conversation_id)
        project_id = str(conversation_metadata["project_id"])
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise HTTPException(status_code=415, detail="multipart/form-data is required")
        form = await request.form()
        uploads: list[UploadFile] = []
        for key in ("files", "file"):
            for value in form.getlist(key):
                if isinstance(value, StarletteUploadFile):
                    uploads.append(value)
        if not uploads:
            raise HTTPException(status_code=422, detail="multipart field 'files' or 'file' is required")
        if len(uploads) > 10:
            raise HTTPException(status_code=422, detail="at most 10 files may be uploaded at once")

        saved: list[dict[str, Any]] = []
        for upload in uploads:
            file_id, safe_name, target = store.allocate_upload(conversation_id, upload.filename)
            size = 0
            try:
                with target.open("xb") as handle:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        if size > app_settings.max_upload_bytes:
                            raise HTTPException(
                                status_code=413,
                                detail=f"{safe_name} exceeds the per-file upload limit",
                            )
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                item = store.register_upload(
                    conversation_id,
                    file_id=file_id,
                    original_name=safe_name,
                    stored_path=target,
                    size=size,
                    content_type=upload.content_type,
                )
                saved.append(item)
            except Exception:
                if target.is_file():
                    target.unlink()
                raise
            finally:
                await upload.close()
        operation_log.record(
            "files.uploaded",
            source="api",
            request_id=request.state.request_id,
            project_id=project_id,
            conversation_id=conversation_id,
            file_count=len(saved),
            total_bytes=sum(int(item.get("size") or 0) for item in saved),
            file_types=sorted(
                {
                    _file_type(item.get("name"))
                    for item in saved
                }
            ),
        )
        return {"items": saved}

    @app.get("/api/conversations/{conversation_id}/files/{file_id}")
    async def download_file(
        request: Request,
        conversation_id: str,
        file_id: str,
    ) -> FileResponse:
        path, item = store.resolve_file(conversation_id, file_id)
        project_id = str(store.read_meta(conversation_id)["project_id"])
        operation_log.record(
            "file.downloaded",
            source="api",
            request_id=request.state.request_id,
            project_id=project_id,
            conversation_id=conversation_id,
            file_id=file_id,
            file_kind=item.get("kind"),
            file_type=_file_type(path.name),
            file_bytes=item.get("size"),
        )
        return FileResponse(
            path,
            media_type=str(item.get("content_type") or "application/octet-stream"),
            filename=str(item.get("name") or path.name),
        )

    @app.get("/api/conversations/{conversation_id}/files/{file_id}/open")
    async def open_output_file(
        request: Request,
        conversation_id: str,
        file_id: str,
    ) -> FileResponse:
        path, item = store.resolve_file(conversation_id, file_id)
        project_id = str(store.read_meta(conversation_id)["project_id"])
        suffix = path.suffix.lower()
        media_types = {
            ".md": "text/plain; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".pdf": "application/pdf",
        }
        if item.get("kind") != "output" or suffix not in media_types:
            raise HTTPException(status_code=415, detail="仅支持打开 outputs 目录中的 Markdown、HTML 或 PDF 文件")
        operation_log.record(
            "file.opened",
            source="api",
            request_id=request.state.request_id,
            project_id=project_id,
            conversation_id=conversation_id,
            file_id=file_id,
            file_kind="output",
            file_type=suffix.lstrip("."),
            file_bytes=item.get("size"),
        )
        headers = {
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        }
        if suffix == ".html":
            headers["Content-Security-Policy"] = (
                "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'self'; script-src 'none'; connect-src 'none'; "
                "style-src 'unsafe-inline'; img-src data: blob:; font-src data:"
            )
        return FileResponse(
            path,
            media_type=media_types[suffix],
            filename=str(item.get("name") or path.name),
            content_disposition_type="inline",
            headers=headers,
        )

    def require_mcp_auth(request: Request) -> str | None:
        expected = app_settings.capability_mcp_token
        supplied = _bearer(request)
        if supplied:
            conversation_id = mcp_registry.resolve(supplied)
            if conversation_id is not None:
                return conversation_id
            if expected is not None and hmac.compare_digest(supplied, expected):
                return None
        if supplied is None or expected is None or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid MCP bearer token")
        return None

    @app.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        conversation_id = require_mcp_auth(request)
        try:
            message = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )
        metadata = _mcp_request_metadata(message)
        operation_id = uuid.uuid4().hex
        active = app.state.active_runs.get(conversation_id) if conversation_id else None
        project_id = active.project_id if active else None
        if conversation_id and project_id is None:
            try:
                project_id = str(store.read_meta(conversation_id)["project_id"])
            except StorageError:
                project_id = None
        operation_log.record(
            "mcp.operation.started",
            source="mcp_gateway",
            request_id=request.state.request_id,
            operation_id=operation_id,
            project_id=project_id,
            conversation_id=conversation_id,
            run_id=active.run_id if active else None,
            **metadata,
        )
        started_at = perf_counter()
        try:
            result = await mcp.dispatch(message, conversation_id=conversation_id)
        except Exception as exc:
            operation_log.record(
                "mcp.operation.completed",
                source="mcp_gateway",
                request_id=request.state.request_id,
                operation_id=operation_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=active.run_id if active else None,
                outcome="failed",
                error_code=type(exc).__name__,
                duration_ms=round((perf_counter() - started_at) * 1000, 3),
                **metadata,
            )
            raise
        error_code = _mcp_result_error_code(result)
        operation_log.record(
            "mcp.operation.completed",
            source="mcp_gateway",
            request_id=request.state.request_id,
            operation_id=operation_id,
            project_id=project_id,
            conversation_id=conversation_id,
            run_id=active.run_id if active else None,
            outcome="failed" if error_code else "succeeded",
            error_code=error_code,
            duration_ms=round((perf_counter() - started_at) * 1000, 3),
            **metadata,
        )
        if result is None:
            return Response(status_code=202)
        response = JSONResponse(result)
        if isinstance(message, dict) and message.get("method") == "initialize":
            response.headers["Mcp-Session-Id"] = uuid.uuid4().hex
        return response

    @app.get("/mcp")
    async def mcp_get(request: Request) -> Response:
        require_mcp_auth(request)
        return Response(
            "This MCP server does not publish unsolicited SSE notifications; use POST.",
            status_code=405,
            media_type="text/plain",
            headers={"Allow": "POST, DELETE"},
        )

    @app.delete("/mcp")
    async def mcp_delete(request: Request) -> Response:
        require_mcp_auth(request)
        return Response(status_code=204)

    if app_settings.frontend_dist.joinpath("index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=app_settings.frontend_dist, html=True), name="frontend")
    else:
        @app.get("/")
        async def frontend_missing() -> JSONResponse:
            return JSONResponse(
                {
                    "service": "hoosland-real-estate-research-toolset-backend",
                    "version": __version__,
                    "slot": app_settings.slot,
                    "build_id": app_settings.build_id,
                    "frontend": "not_built",
                },
                status_code=503,
            )

    return app


app = create_app()
