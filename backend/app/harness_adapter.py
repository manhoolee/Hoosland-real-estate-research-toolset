from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from .config import Settings
from .capabilities import McpAccessRegistry
from .runtime_config import RuntimeConfigStore
from .storage import ConversationStore

_RESEARCH_PROGRESS = {
    "brief": {
        "label": "正在确认研究目标与交付要求",
        "current_step": 1,
        "remaining_steps": 4,
        "eta_label": "复杂任务通常还需 5–12 分钟",
    },
    "evidence": {
        "label": "正在研读与核查项目资料",
        "current_step": 2,
        "remaining_steps": 3,
        "eta_label": "复杂任务通常还需 3–10 分钟",
    },
    "analysis": {
        "label": "正在归纳结论与关键判断",
        "current_step": 3,
        "remaining_steps": 2,
        "eta_label": "复杂任务通常还需 2–6 分钟",
    },
    "delivery": {
        "label": "正在整理可交付成果",
        "current_step": 4,
        "remaining_steps": 1,
        "eta_label": "通常还需 1–5 分钟",
    },
}


def research_progress_event(stage: str) -> dict[str, Any]:
    """Return the only process-level event allowed in the customer UI."""

    safe_stage = stage if stage in _RESEARCH_PROGRESS else "brief"
    return {
        "type": "progress",
        "stage": safe_stage,
        "total_steps": 4,
        **_RESEARCH_PROGRESS[safe_stage],
    }


class HarnessAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class HarnessRunResult:
    final_response: str
    finish_reason: str | None
    session_id: str


def build_harness_prompt(
    content: str,
    attachments: list[dict[str, Any]],
    *,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    sections: list[str] = []
    sections.append(
        "[总控激活]\n"
        "- 当前阶段：意图识别与任务执行\n"
        "- 路由模式：自动 Skill 路由\n"
        "- 预选 Skill：无；由运行时根据当前请求和可用 Skill 描述按需选择\n"
        "- 本轮已有授权能力：无额外授权"
    )

    if conversation_history:
        sections.append(
            "[已完成历史]\n"
            "- 以下 JSON 仅包含已成功完成的对话轮次，用于恢复连续上下文：\n"
            + json.dumps(conversation_history, ensure_ascii=False, separators=(",", ":"))
        )
    else:
        sections.append("[已完成历史]\n- 无")

    attachment_rows = ["[附件清单]"]
    if attachments:
        for item in attachments:
            record = {
                "id": item.get("id") or "无",
                "文件名": item.get("name") or "未命名文件",
                "类型": item.get("content_type") or "application/octet-stream",
                "可用状态": "可用" if item.get("workspace_path") else "路径缺失",
                "工作区路径": item.get("workspace_path") or "无",
                "与本轮任务的关系": "用户在本轮明确附加，按当前请求需要读取",
            }
            attachment_rows.append(
                "- " + json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            )
    else:
        attachment_rows.append("- 无")
    sections.append("\n".join(attachment_rows))

    sections.append("[当前请求]\n" + content)
    return "\n\n".join(sections)


def notification_to_stream_event(notification: object) -> dict[str, Any] | None:
    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    if not isinstance(method, str) or not isinstance(payload, dict):
        return None

    if method == "session.status":
        status = payload.get("status")
        return research_progress_event("brief") if status == "running" else None
    if method == "subagent.started":
        return research_progress_event("evidence")
    if method == "subagent.finished":
        return research_progress_event("analysis")
    if method != "session.event":
        return None

    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    data = event.get("data")
    if isinstance(data, dict):
        chunk = data.get("chunk")
        if isinstance(chunk, dict) and chunk.get("type") == "text-delta":
            text = chunk.get("text")
            if isinstance(text, str) and text:
                # The customer receives the committed final response in one
                # piece. Streaming model text can contain early planning or
                # runtime narration, so it is neither exposed nor treated as
                # evidence that the delivery stage has begun.
                return None
    if isinstance(event_type, str) and event_type in {"tool/call", "tool/execute/start"}:
        tool_name = _tool_name(data)
        category = _operation_tool_category(tool_name)
        if category == "skill":
            return research_progress_event("brief")
        if category in {"file_read", "document_extract", "vision_analyze", "web_search"}:
            return research_progress_event("evidence")
        if category in {"delegate_text", "subagent"}:
            return research_progress_event("analysis")
        if category in {"file_write", "image_generate"}:
            # Intermediate drafts and generated assets can live in work/.
            # The API layer advances to delivery only after outputs changes.
            return None
        # Shell commands, installers and unknown runtime tools are recorded in
        # the private operation log but deliberately have no customer event.
        return None
    return None


_OPERATION_EVENT_PHASES = {
    "tool/call": "requested",
    "tool/execute/start": "started",
    "tool/execute/end": "completed",
    "tool/execute/finish": "completed",
    "tool/execute/complete": "completed",
    "tool/result": "completed",
    "tool/execute/error": "failed",
    "tool/error": "failed",
}


def notification_to_operation_event(notification: object) -> dict[str, str] | None:
    """Extract a content-free operation record from a Harness notification.

    This intentionally has a much narrower contract than the UI converter:
    arguments, text chunks, results, labels and messages never leave this
    function. Unknown event types are ignored instead of being serialized.
    """

    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    if not isinstance(method, str) or not isinstance(payload, dict):
        return None

    if method in {"subagent.started", "subagent.finished"}:
        return {
            "operation_type": "specialist",
            "phase": "started" if method.endswith("started") else "completed",
            "source_event": method,
            "tool_name": "subagent",
        }
    if method != "session.event":
        return None

    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type not in _OPERATION_EVENT_PHASES:
        return None
    data = event.get("data")
    raw_tool_name = _safe_operation_identifier(_tool_name(data))
    tool_name = _operation_tool_category(raw_tool_name)
    result = {
        "operation_type": "tool",
        "phase": _OPERATION_EVENT_PHASES[event_type],
        "source_event": event_type,
        "tool_name": tool_name,
    }
    call_id = _operation_call_id(data)
    if call_id:
        result["call_id"] = call_id
    if tool_name == "skill":
        result["operation_type"] = "skill"
        result["skill_id"] = (
            _safe_operation_identifier(_skill_id(data) or "professional-skill")
            or "professional-skill"
        )
    return result


def _safe_operation_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.:/-]+", "-", value.strip())[:160]
    return normalized.strip("-._:/")


def _operation_tool_category(tool_name: str) -> str:
    normalized = tool_name.lower()
    categories = (
        ("skill", "skill"),
        ("vision_analyze", "vision_analyze"),
        ("image_generate", "image_generate"),
        ("document_extract", "document_extract"),
        ("delegate_text", "delegate_text"),
        ("web_search", "web_search"),
        ("search", "web_search"),
        ("read", "file_read"),
        ("glob", "file_read"),
        ("grep", "file_read"),
        ("write", "file_write"),
        ("edit", "file_write"),
        ("patch", "file_write"),
        ("shell", "shell"),
        ("bash", "shell"),
        ("exec", "shell"),
        ("subagent", "subagent"),
    )
    for marker, category in categories:
        if marker in normalized:
            return category
    return "other"


def _operation_call_id(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    candidates = [data]
    call = data.get("call")
    if isinstance(call, dict):
        candidates.append(call)
    for candidate in candidates:
        for key in ("call_id", "callId", "tool_call_id", "toolCallId", "id"):
            value = candidate.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                safe = _safe_operation_identifier(str(value))
                if safe:
                    return safe
    return None


def _tool_name(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("name", "tool", "tool_name", "toolName"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    call = data.get("call")
    if isinstance(call, dict):
        return _tool_name(call)
    return ""


def _skill_id(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    candidates: list[object] = [data]
    for key in ("arguments", "args", "input", "parameters", "call"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
        elif isinstance(value, str) and len(value) <= 10_000:
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                candidates.append(decoded)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("skill", "skill_id", "skillId", "name"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip() and value.strip() != "skill":
                return value.strip().lstrip("/")[:160]
    return None


class HarnessManager:
    """Owns a bounded cache of SDK runtime subprocesses, one per workspace."""

    def __init__(
        self,
        settings: Settings,
        store: ConversationStore,
        runtime_config: RuntimeConfigStore | None = None,
        mcp_registry: McpAccessRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.runtime_config = runtime_config
        self.mcp_registry = mcp_registry
        self._runners: OrderedDict[str, Any] = OrderedDict()
        self._busy: dict[str, str] = {}
        self._cancel_requested: set[str] = set()
        self._cache_lock = asyncio.Lock()
        self._runner_tokens: dict[int, str] = {}
        self._runner_tokens_lock = threading.Lock()

    @staticmethod
    def sdk_installed() -> bool:
        try:
            return importlib.util.find_spec("deepseek_harness") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def status(self) -> dict[str, Any]:
        enabled = self.settings.harness_enabled
        installed = self.sdk_installed()
        cordis_exists = self.settings.cordis_path.is_file()
        main = self.runtime_config.main_agent() if self.runtime_config else {
            "api_key": self.settings.harness_api_key,
            "model": self.settings.harness_model,
        }
        credential_configured = bool(main.get("api_key"))
        configured = enabled and installed and cordis_exists and credential_configured
        reasons: list[str] = []
        if not enabled:
            reasons.append("研究助手已被服务配置停用")
        if not installed:
            reasons.append("研究助手运行组件未安装")
        if not cordis_exists:
            reasons.append("研究助手运行配置缺失")
        if not credential_configured:
            reasons.append("主模型 API 密钥尚未配置")
        return {
            "name": "research_agent",
            "configured": configured,
            "status": "configured" if configured else "degraded",
            "runtime_installed": installed,
            "runtime_configured": cordis_exists,
            "credential_configured": credential_configured,
            "provider": self.settings.harness_provider,
            "model": main.get("model") or self.settings.harness_model,
            "reasons": reasons,
        }

    async def run(
        self,
        conversation_id: str,
        prompt: str,
        on_notification: Callable[[object], None],
        *,
        run_id: str,
        session_generation: int = 0,
    ) -> HarnessRunResult:
        if not self.settings.harness_enabled:
            raise HarnessAdapterError("AGENT_DISABLED", "研究助手已被服务配置停用")
        if not self.sdk_installed():
            raise HarnessAdapterError(
                "AGENT_RUNTIME_UNAVAILABLE",
                "研究助手运行组件不可用，服务不会伪造回答",
            )
        if not self.settings.cordis_path.is_file():
            raise HarnessAdapterError(
                "AGENT_CONFIG_MISSING", "研究助手运行配置缺失"
            )

        if isinstance(session_generation, bool) or session_generation < 0:
            raise HarnessAdapterError("AGENT_PROTOCOL_ERROR", "研究助手运行会话代际无效")
        runner = await self._runner_for(conversation_id, run_id)
        # A web request is a self-contained SDK session.  Reusing a persisted
        # SDK session id in a fresh runtime can collide after restart, runner
        # eviction, or configuration reset.  The HTTP run id makes the SDK id
        # unique while the application restores continuity from its own
        # successful-message history.
        session_id = f"web-{conversation_id}-g{session_generation}-r{run_id}"
        try:
            result = await asyncio.to_thread(
                runner.run,
                prompt,
                session_id=session_id,
                on_notification=on_notification,
            )
        except Exception as exc:
            if await self._take_cancelled(run_id):
                await self._discard_runner(conversation_id, runner, run_id)
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止") from exc
            await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError("AGENT_RUN_FAILED", self._safe_error_message(exc)) from exc
        if await self._take_cancelled(run_id):
            await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
        finish_reason = getattr(result, "finish_reason", None)
        normalized_finish_reason = (
            finish_reason.strip().lower() if isinstance(finish_reason, str) else None
        )
        if normalized_finish_reason in {"error", "failed", "failure"}:
            await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError(
                "AGENT_RESPONSE_ERROR",
                "研究助手本轮未能完成，请重新发送消息",
            )
        final_response = getattr(result, "final_response", None)
        if not isinstance(final_response, str) or not final_response.strip():
            await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError(
                "AGENT_EMPTY_RESPONSE",
                "研究助手本轮没有返回可显示的内容，请重新发送消息",
            )
        response = HarnessRunResult(
            final_response=final_response,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            session_id=session_id,
        )
        # The next HTTP turn intentionally starts a fresh runtime/session and
        # receives persisted history in its prompt.  Closing here also avoids
        # accumulating per-session SDK state inside a long-lived runner.
        await self._discard_runner(conversation_id, runner, run_id)
        return response

    async def _runner_for(self, conversation_id: str, run_id: str) -> Any:
        async with self._cache_lock:
            if conversation_id in self._busy:
                raise HarnessAdapterError("AGENT_BUSY", "研究助手正在处理这个项目的上一条消息")
            existing = self._runners.pop(conversation_id, None)
            self._busy[conversation_id] = run_id
            if existing is not None:
                self._runners[conversation_id] = existing
                return existing

        try:
            runner = await asyncio.to_thread(self._create_runner, conversation_id)
        except Exception:
            async with self._cache_lock:
                if self._busy.get(conversation_id) == run_id:
                    self._busy.pop(conversation_id, None)
            raise

        async with self._cache_lock:
            cancelled = (
                run_id in self._cancel_requested
                or self._busy.get(conversation_id) != run_id
            )
            if cancelled:
                self._cancel_requested.discard(run_id)
                if self._busy.get(conversation_id) == run_id:
                    self._busy.pop(conversation_id, None)
            else:
                self._runners[conversation_id] = runner
                await self._trim_cache_locked()
        if cancelled:
            await asyncio.to_thread(self._close_runner, runner)
            raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
        return runner

    def _create_runner(self, conversation_id: str) -> Any:
        try:
            from deepseek_harness import DeepSeekHarness
        except ImportError as exc:
            raise HarnessAdapterError(
                "AGENT_RUNTIME_UNAVAILABLE", "研究助手运行组件无法加载"
            ) from exc

        paths = self.store.require(conversation_id)
        session_root = (self.settings.harness_session_root / conversation_id).resolve()
        session_root.mkdir(parents=True, exist_ok=True, mode=0o750)
        main = self.runtime_config.main_agent() if self.runtime_config else {
            "base_url": self.settings.harness_base_url,
            "model": self.settings.harness_model,
            "api_key": self.settings.harness_api_key,
        }
        search = self.runtime_config.native_search() if self.runtime_config else {
            "base_url": self.settings.harness_search_base_url,
            "model": self.settings.harness_search_model,
            "api_key": self.settings.harness_search_api_key,
        }
        mcp_token = self.mcp_registry.issue(conversation_id) if self.mcp_registry else None
        kwargs: dict[str, Any] = {
            "provider": self.settings.harness_provider,
            "model": main.get("model") or self.settings.harness_model,
            "max_tokens": self.settings.harness_max_tokens,
            "cwd": str(paths.workspace),
            "runtime_cwd": str(paths.workspace),
            "session_root": str(session_root),
            "cordis": str(self.settings.cordis_path),
            "env": self.settings.runtime_env(
                model=main.get("model"),
                base_url=main.get("base_url"),
                api_key=main.get("api_key"),
                search_model=search.get("model"),
                search_api_key=search.get("api_key"),
                search_base_url=search.get("base_url"),
                capability_mcp_token=mcp_token,
            ),
            "request_timeout_seconds": self.settings.harness_request_timeout_seconds,
        }
        if main.get("base_url"):
            kwargs["base_url"] = main["base_url"]
        if self.settings.harness_runtime_bin:
            kwargs["runtime_bin"] = self.settings.harness_runtime_bin
        if self.settings.harness_launch_args:
            kwargs["launch_args_override"] = self.settings.harness_launch_args
        try:
            runner = DeepSeekHarness(**kwargs)
        except Exception:
            if mcp_token and self.mcp_registry:
                self.mcp_registry.revoke(mcp_token)
            raise
        if mcp_token:
            with self._runner_tokens_lock:
                self._runner_tokens[id(runner)] = mcp_token
        return runner

    async def _discard_runner(
        self,
        conversation_id: str,
        runner: Any,
        run_id: str,
    ) -> None:
        owns_close = False
        async with self._cache_lock:
            if self._runners.get(conversation_id) is runner:
                self._runners.pop(conversation_id, None)
                owns_close = True
            if self._busy.get(conversation_id) == run_id:
                self._busy.pop(conversation_id, None)
            self._cancel_requested.discard(run_id)
        # cancel(), close(), or cache eviction may already have detached and
        # taken ownership of closing this runtime.  Only the operation that
        # identity-popped the cached runner may close it; DeepSeekHarness.close
        # is not safe to execute concurrently on the same instance.
        if owns_close:
            await asyncio.to_thread(self._close_runner, runner)

    async def _release_runner(
        self,
        conversation_id: str,
        runner: Any,
        run_id: str,
    ) -> None:
        async with self._cache_lock:
            if (
                self._runners.get(conversation_id) is runner
                and self._busy.get(conversation_id) == run_id
            ):
                self._busy.pop(conversation_id, None)
            await self._trim_cache_locked()

    async def _trim_cache_locked(self) -> None:
        while len(self._runners) > self.settings.harness_runner_cache_size:
            victim: tuple[str, Any] | None = None
            for old_id, old_runner in self._runners.items():
                if old_id not in self._busy:
                    victim = (old_id, old_runner)
                    break
            if victim is None:
                return
            old_id, old_runner = victim
            self._runners.pop(old_id, None)
            await asyncio.to_thread(self._close_runner, old_runner)

    async def close(self) -> None:
        async with self._cache_lock:
            runners = list(self._runners.values())
            self._cancel_requested.update(
                self._busy.values()
            )
            self._runners.clear()
            self._busy.clear()
        for runner in runners:
            await asyncio.to_thread(self._close_runner, runner)

    async def cancel(self, conversation_id: str, *, run_id: str) -> bool:
        async with self._cache_lock:
            busy_run_id = self._busy.get(conversation_id)
            active = busy_run_id == run_id
            runner = None
            if active:
                self._busy.pop(conversation_id, None)
                runner = self._runners.pop(conversation_id, None)
            elif busy_run_id is None:
                # The SDK call may have just completed but the web worker has
                # not committed its response yet. Invalidate that cached
                # session so a cancelled turn cannot be resumed as completed.
                runner = self._runners.pop(conversation_id, None)
            if active or runner is not None:
                self._cancel_requested.add(run_id)
        if runner is not None:
            await asyncio.to_thread(self._close_runner, runner)
        return active or runner is not None

    async def reset(self) -> None:
        await self.close()

    async def _take_cancelled(self, run_id: str) -> bool:
        async with self._cache_lock:
            if run_id not in self._cancel_requested:
                return False
            self._cancel_requested.discard(run_id)
            return True

    def _close_runner(self, runner: Any) -> None:
        try:
            runner.close()
        except Exception:
            pass
        finally:
            with self._runner_tokens_lock:
                token = self._runner_tokens.pop(id(runner), None)
            if token and self.mcp_registry:
                self.mcp_registry.revoke(token)

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        # Runtime diagnostics may contain many stderr lines. Keep the API error
        # useful without mirroring logs, prompts, or environment data to clients.
        first_line = message.splitlines()[0]
        sanitized = re.sub(r"deepseek[-_ ]?harness|harness", "研究助手", first_line, flags=re.I)
        return sanitized[:1000]
