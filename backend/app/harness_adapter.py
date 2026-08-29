from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
import threading
from collections import OrderedDict
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .capabilities import McpAccessRegistry
from .runtime_config import DEFAULT_OUTPUT_FORMATS, RuntimeConfigStore
from .storage import (
    CHECKLIST_MAX_CONTENT_CHARACTERS,
    CHECKLIST_MAX_ITEMS,
    CHECKLIST_MODEL_STATUSES,
    ConversationStore,
)

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

SKILL_COMMAND = "/comprehensive-real-estate-expert"
CONTROLLER_SKILL_ID = SKILL_COMMAND.lstrip("/")


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


@dataclass(frozen=True, slots=True)
class HarnessFollowup:
    """A bounded server instruction appended to the currently active session."""

    content: str
    # The pinned SDK exposes only a next-turn queue for ``session/prompt``;
    # it cannot interrupt a model step that is already executing.  Recovery
    # instructions therefore may request a fresh runtime/session so queued
    # sibling tools cannot run ahead of the correction.
    restart_session: bool = False


class _HarnessSessionRestart(RuntimeError):
    """Internal signal asking the manager to rotate the live SDK session."""

    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.content = content


class _HarnessStartGate:
    """Linearize cancellation with the beginning of an SDK turn.

    ``HarnessManager.cancel`` can otherwise detach a freshly-installed runner
    in the small interval between an async ownership check and the worker
    thread's ``start_session``/``run`` call.  The gate gives cancellation a
    single ordering point: it either marks the run before the worker claims
    the start, or waits until the initial prompt has been submitted.
    """

    def __init__(self, lock: threading.Lock, cancelled: threading.Event) -> None:
        self._lock = lock
        self._cancelled = cancelled

    def claim(self) -> None:
        """Claim a compatibility-path turn without holding the lock in it."""

        with self._lock:
            if self._cancelled.is_set():
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")

    @contextmanager
    def setup(self):
        """Hold the gate through ``start_session`` and initial prompt submit."""

        self._lock.acquire()
        try:
            if self._cancelled.is_set():
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
            yield
        finally:
            self._lock.release()


@dataclass(frozen=True, slots=True)
class ChecklistTodo:
    content: str
    status: str

    def as_dict(self) -> dict[str, str]:
        return {"content": self.content, "status": self.status}


@dataclass(frozen=True, slots=True)
class ChecklistSnapshot:
    session_id: str
    event_seq: int
    event_time_ms: int
    todos: tuple[ChecklistTodo, ...]

    def todo_dicts(self) -> list[dict[str, str]]:
        return [todo.as_dict() for todo in self.todos]


@dataclass(frozen=True, slots=True)
class TokenUsageSample:
    """One provider-reported usage sample for a Harness model step.

    Harness emits an early usage chunk and may later emit a finalized
    assistant message for the same ``(session, turn, step)``.  Consumers must
    replace the earlier sample with the latter instead of adding both.
    ``reasoningTokens`` is retained as a detail bucket but is already a
    subdivision of ``outputTokens`` and must not be added to the total.
    """

    session_id: str
    sample_kind: str
    event_seq: int
    turn: int
    step: int
    uncached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int

    def buckets(self) -> dict[str, int]:
        return {
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass(frozen=True, slots=True)
class TokenRetryAttempt:
    """A provider retry attempt that has actually started for one model step."""

    session_id: str
    turn: int
    step: int
    attempt: int


@dataclass(frozen=True, slots=True)
class OutputWriteAttempt:
    """Content-free classification of one file-tool write target.

    The raw path is deliberately not retained because it can contain customer
    filenames.  The API only needs to know whether the agent intended to write
    a deliverable and whether that target was inside the one canonical outputs
    directory for this conversation.
    """

    canonical: bool
    output_format: str | None
    target_id: str


@dataclass(frozen=True, slots=True)
class _OwnedHarnessRunResult:
    final_response: str
    finish_reason: str | None


def _notification_method_payload(
    notification: object,
) -> tuple[object, object]:
    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    return method, payload


def _owned_root_event(
    notification: object,
    session_id: str,
) -> dict[str, Any] | None:
    method, payload = _notification_method_payload(notification)
    if (
        method != "session.event"
        or not isinstance(payload, dict)
        or payload.get("sessionId") != session_id
    ):
        return None
    event = payload.get("event")
    return event if isinstance(event, dict) else None


def _owned_inbox_message_ids(
    notification: object,
    session_id: str,
) -> set[str]:
    event = _owned_root_event(notification, session_id)
    if event is None or event.get("type") != "agent/inbox/spliced":
        return set()
    data = event.get("data")
    inserted = data.get("inserted") if isinstance(data, dict) else None
    if not isinstance(inserted, list):
        return set()
    return {
        message_id
        for message in inserted
        if isinstance(message, dict)
        and isinstance((message_id := message.get("id")), str)
    }


def _owned_final_response(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") != "assistant/message":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        message = data.get("message")
        content_owner = message if isinstance(message, dict) else data
        content = content_owner.get("content")
        if not isinstance(content, list):
            continue
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _owned_finish_reason(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("type") != "turn/end":
            continue
        data = event.get("data")
        reason = data.get("reason") if isinstance(data, dict) else None
        kind = reason.get("kind") if isinstance(reason, dict) else None
        if not isinstance(kind, str):
            raise HarnessAdapterError(
                "AGENT_PROTOCOL_ERROR",
                "研究助手结束状态无效",
            )
        return kind
    return None


def _run_owned_harness_session(
    runner: Any,
    prompt: str,
    *,
    session_id: str,
    on_notification: Callable[[object], HarnessFollowup | None],
    start_guard: _HarnessStartGate | None = None,
) -> _OwnedHarnessRunResult:
    """Own every injected prompt from its inbox receipt through the next idle."""

    events: list[dict[str, Any]] = []
    # Keep cancellation from detaching the runner between the ownership check
    # in ``HarnessManager`` and the SDK's initial session/prompt submission.
    # The lock is released before waiting for notifications, so cancellation
    # remains responsive once the turn has genuinely started.
    with ExitStack() as stack:
        # Keep cancellation from detaching the runner between the ownership
        # check and the initial SDK prompt, but release the gate while waiting
        # for the turn's notifications so cancel() remains responsive.
        setup_context = start_guard.setup() if start_guard is not None else nullcontext()
        with setup_context:
            runner.start_session(session_id)
            client = runner.client
            subscription = stack.enter_context(
                client.subscribe_session_notifications(session_id)
            )
            initial_message_id = client.session_prompt(
                session_id,
                [{"type": "text", "text": prompt}],
                notification_subscription=subscription,
            )
        if not isinstance(initial_message_id, str) or not initial_message_id:
            raise HarnessAdapterError(
                "AGENT_PROTOCOL_ERROR",
                "研究助手消息回执无效",
            )
        awaiting_receipts = {initial_message_id}
        initial_received = False
        while True:
            notification = subscription.next()
            receipt_ids = _owned_inbox_message_ids(notification, session_id)
            if not initial_received:
                if initial_message_id not in receipt_ids:
                    continue
                initial_received = True
            awaiting_receipts.difference_update(receipt_ids)

            followup = on_notification(notification)
            event = _owned_root_event(notification, session_id)
            if event is not None:
                events.append(event)
            if followup is not None:
                if followup.restart_session:
                    # ``session/prompt`` is a next-turn enqueue in the pinned
                    # SDK, not a cancel/steer operation.  Continuing this
                    # live turn could dispatch sibling tools after the server
                    # rejected a checklist snapshot.  Let the manager close
                    # this runtime and replay the bounded instruction in a
                    # new session instead.
                    raise _HarnessSessionRestart(followup.content)
                try:
                    followup_message_id = client.session_prompt(
                        session_id,
                        [{"type": "text", "text": followup.content}],
                        notification_subscription=subscription,
                    )
                except Exception as exc:
                    raise HarnessAdapterError(
                        "AGENT_CHECKLIST_RECOVERY_FAILED",
                        "研究助手无法接收任务清单纠正指令",
                    ) from exc
                if not isinstance(followup_message_id, str) or not followup_message_id:
                    raise HarnessAdapterError(
                        "AGENT_PROTOCOL_ERROR",
                        "研究助手清单纠正回执无效",
                    )
                awaiting_receipts.add(followup_message_id)

            method, payload = _notification_method_payload(notification)
            if (
                method == "session.status"
                and isinstance(payload, dict)
                and payload.get("sessionId") == session_id
                and payload.get("status") == "idle"
                and not awaiting_receipts
            ):
                break

    return _OwnedHarnessRunResult(
        final_response=_owned_final_response(events),
        finish_reason=_owned_finish_reason(events),
    )


def notification_to_token_retry_attempt(
    notification: object,
) -> TokenRetryAttempt | None:
    """Extract ``llm/retry-started`` so separately billed attempts stay distinct."""

    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    if method != "session.event" or not isinstance(payload, dict):
        return None
    event = payload.get("event")
    if not isinstance(event, dict) or event.get("type") != "llm/retry-started":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    turn = _nonnegative_token_integer(data.get("turn"))
    step = _nonnegative_token_integer(data.get("step"))
    attempt = _nonnegative_token_integer(data.get("retry"))
    if turn is None or step is None or attempt is None:
        return None
    session_id = payload.get("sessionId", payload.get("session_id"))
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    return TokenRetryAttempt(
        session_id=session_id,
        turn=turn,
        step=step,
        attempt=attempt,
    )


def notification_to_token_usage_sample(
    notification: object,
) -> TokenUsageSample | None:
    """Extract a validated provider usage sample from a Harness notification."""

    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    if method != "session.event" or not isinstance(payload, dict):
        return None

    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    event_seq = _nonnegative_token_integer(event.get("seq"))
    data = event.get("data")
    if event_seq is None or not isinstance(data, dict):
        return None

    usage: object = None
    sample_kind = "model_step"
    if event_type == "assistant/chunk":
        chunk = data.get("chunk")
        if isinstance(chunk, dict) and chunk.get("type") == "usage":
            usage = chunk.get("usage")
    elif event_type == "assistant/message":
        usage = data.get("usage")
    elif event_type == "compaction/summary":
        usage = data.get("usage")
        sample_kind = "compaction"
    if not isinstance(usage, dict):
        return None

    if sample_kind == "compaction":
        # Compaction is a direct LLM call outside an agent turn/step.  Its
        # per-session event seq is the durable unique identity for accounting.
        turn, step = event_seq, 0
    else:
        turn = _nonnegative_token_integer(data.get("turn"))
        step = _nonnegative_token_integer(data.get("step"))
    input_tokens = _nonnegative_token_integer(
        usage.get("inputTokens", usage.get("input_tokens"))
    )
    output_tokens = _nonnegative_token_integer(
        usage.get("outputTokens", usage.get("output_tokens"))
    )
    cache_read_tokens = _optional_token_integer(
        usage.get("cacheReadTokens", usage.get("cache_read_tokens"))
    )
    cache_write_tokens = _optional_token_integer(
        usage.get("cacheWriteTokens", usage.get("cache_write_tokens"))
    )
    reasoning_tokens = _optional_token_integer(
        usage.get("reasoningTokens", usage.get("reasoning_tokens"))
    )
    if None in {turn, step, input_tokens, output_tokens}:
        return None
    if (
        cache_read_tokens is None
        or cache_write_tokens is None
        or reasoning_tokens is None
    ):
        return None

    session_id = payload.get("sessionId", payload.get("session_id"))
    if not isinstance(session_id, str) or not session_id.strip():
        # A missing session id would make root/subagent steps collide.  The
        # production SDK always supplies it, so malformed emitters are ignored.
        return None
    return TokenUsageSample(
        session_id=session_id,
        sample_kind=sample_kind,
        event_seq=event_seq,
        turn=turn,
        step=step,
        uncached_input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )


def _nonnegative_token_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_token_integer(value: object) -> int | None:
    return 0 if value is None else _nonnegative_token_integer(value)


def build_harness_prompt(
    content: str,
    attachments: list[dict[str, Any]],
    *,
    conversation_history: list[dict[str, str]] | None = None,
    workspace_path: str | Path | None = None,
) -> str:
    # The controller is a runtime invariant, not a model routing preference.
    # Keeping the slash command as the literal first line makes every fresh
    # stateless Harness session load the same controller before it can choose
    # any specialist skill.
    sections: list[str] = [SKILL_COMMAND]
    sections.append(
        "[总控激活]\n"
        "- 当前阶段：意图识别与任务执行\n"
        "- 主控 Skill：comprehensive-real-estate-expert（已由服务端确定性激活）\n"
        "- 路由模式：总控先行；由主控通过内置 skill tool 按需调用专项 Skill\n"
        "- 调用约束：主控不得调用自身；同一子 Skill 本轮最多调用一次，明确失败后的重试除外\n"
        "- 本轮已有授权能力：无额外授权"
    )

    if workspace_path is not None:
        workspace = Path(workspace_path).resolve()
        work = workspace / "work"
        outputs = workspace / "outputs"
        sections.append(
            "[唯一工作区路径]\n"
            f"- 会话工作区：{workspace}\n"
            f"- 过程文件唯一目录：{work}\n"
            f"- 最终成果唯一目录：{outputs}\n"
            "- write/edit 文件工具不跟随 persistent bash 的 cd；优先始终使用相对路径 work/<文件> 或 outputs/<文件>，其基准只能是上述会话工作区。\n"
            "- /tmp、/tmp/**/outputs、工作区内自建子目录的 outputs，以及当前 shell 的 ${PWD}/outputs 都不是交付目录；其中的文件不会出现在成果区，也不得据此声称已完成。\n"
            "- 宣布完成前必须从上述唯一最终成果目录逐一核对本轮要求的文件确实存在、非空且可打开。"
        )

    default_formats = " + ".join(format_name.upper() for format_name in DEFAULT_OUTPUT_FORMATS)
    sections.append(
        "[交付策略]\n"
        f"- 默认格式：{default_formats}\n"
        "- 当本轮主成果是地产研究、项目分析、策划方案或管理报告，且用户未明确指定最终格式或明确不要文件时，必须在 outputs/ 同时生成内容对应、非空、可打开的 Markdown（.md）与独立 HTML（.html）。\n"
        "- 用户明确指定单一格式、其他格式或不要文件时，以用户要求为准；纯澄清、简短问答和不形成文件成果的局部解释不强制生成文件。微信资料转换/归档、社交平台素材、数据表或模型等已有专项输出契约的任务按对应子 Skill 执行，除非同时形成上述主报告。\n"
        "- 主控在宣布完成前必须核对本轮要求的所有文件实际存在且可打开；默认不生成 PDF。"
    )

    sections.append(
        "[任务与成果清单]\n"
        "- 除读取本段固定规则与当前请求外，本轮第一个实质动作必须调用 todo_write；先提交完整清单，再调用 Skill、检索、读取、分析、命令或文件工具。\n"
        "- 清单必须至少包含一个以“任务｜”开头的执行任务，以及至少一个成果项。文件成果必须逐格式单列，严格写成“成果文件(.ext)｜说明”（例如成果文件(.md)｜研究报告），每种扩展名只列一项；不形成文件时写“成果回复｜说明”。\n"
        "- todo_write 每次发送完整清单。首次清单不得包含 completed；首次提交后不得改名、重排、新增或删除项目，只能更新状态；按顺序执行时最多一个项目为 in_progress。\n"
        "- 每完成并复核一个任务或成果要求，必须立即再次调用 todo_write 更新整表，每次最多把一个此前未完成项目改为 completed，不得批量补记。只有取得实际证据后才能标 completed。\n"
        "- Harness 显示 todo_write 成功只代表本地整表已替换；若收到“服务端清单状态纠正”，说明应用未接受上一版。下一动作必须且只能按其中 authoritative_todos 原样重置 todo_write，允许撤销本地过早完成状态；重置前不得继续其他操作或 final。\n"
        "- 输出文件必须在唯一 outputs/ 中实际存在、非空且对应本轮新增或更新，才可把相应成果文件项标为 completed；最终答复非空且已复核，才可把成果回复项标为 completed。\n"
        "- 提交 final 前必须最后调用一次 todo_write，同步所有已完成与未完成项目；未完成项目保持 pending，不得伪报 completed。"
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

    sections.append(
        "[当前请求]\n"
        + json.dumps({"content": content}, ensure_ascii=False, separators=(",", ":"))
    )
    return "\n\n".join(sections)


def harness_session_id(
    conversation_id: str,
    run_id: str,
    session_generation: int,
) -> str:
    """Build the one root SDK session id shared by the manager and observers."""

    return f"web-{conversation_id}-g{session_generation}-r{run_id}"


def _session_recovery_prompt(prompt: str, instruction: str) -> str:
    """Replay a bounded server correction in a clean SDK session.

    The Python SDK's ``session/prompt`` endpoint only queues a next-turn
    message.  Appending a correction to a live turn would leave already
    planned sibling tools free to execute, so checklist recovery restarts the
    runtime and gives the new root session both the original request and the
    authoritative correction.
    """

    return (
        prompt.rstrip()
        + "\n\n"
        + "[服务端恢复续接｜上一运行已隔离]\n"
        + "上一运行在服务端清单校验失败后已被终止；不要把上一运行中尚未确认的工具调用视为已完成。"
        + "请从下面的服务端指令开始，先完成清单恢复，再继续原任务；不要重复已经明确完成的外部副作用。\n"
        + instruction.strip()
    )


def notification_to_checklist_snapshot(
    notification: object,
    *,
    expected_session_id: str,
) -> ChecklistSnapshot | None:
    """Extract a successful root-session ``todo/write`` whole-list snapshot.

    The Python SDK forwards notifications for the root session and all known
    descendants. A child agent owns a different todo list, so accepting only the
    exact root id is mandatory. Tool-call arguments are deliberately ignored:
    only the committed ``todo/write`` event proves that validation and execution
    succeeded inside Harness.
    """

    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    if method != "session.event" or not isinstance(payload, dict):
        return None
    if payload.get("sessionId") != expected_session_id:
        return None
    event = payload.get("event")
    if not isinstance(event, dict) or event.get("type") != "todo/write":
        return None
    event_seq = event.get("seq")
    event_time_ms = event.get("time", 0)
    if (
        isinstance(event_seq, bool)
        or not isinstance(event_seq, int)
        or event_seq < 0
        or isinstance(event_time_ms, bool)
        or not isinstance(event_time_ms, int)
        or event_time_ms < 0
    ):
        return None
    data = event.get("data")
    todos = data.get("todos") if isinstance(data, dict) else None
    if not isinstance(todos, list) or not todos or len(todos) > CHECKLIST_MAX_ITEMS:
        return None
    normalized: list[ChecklistTodo] = []
    seen: set[str] = set()
    in_progress = 0
    for item in todos:
        if not isinstance(item, dict) or set(item) != {"content", "status"}:
            return None
        content = item.get("content")
        status = item.get("status")
        if not isinstance(content, str):
            return None
        content = content.strip()
        if (
            not content
            or len(content) > CHECKLIST_MAX_CONTENT_CHARACTERS
            or content in seen
            or status not in CHECKLIST_MODEL_STATUSES
        ):
            return None
        seen.add(content)
        in_progress += int(status == "in_progress")
        if in_progress > 1:
            return None
        normalized.append(ChecklistTodo(content=content, status=str(status)))
    return ChecklistSnapshot(
        session_id=expected_session_id,
        event_seq=event_seq,
        event_time_ms=event_time_ms,
        todos=tuple(normalized),
    )


def notification_to_output_write_attempt(
    notification: object,
    workspace_root: Path,
) -> OutputWriteAttempt | None:
    """Classify requested write/edit targets that use an ``outputs`` segment.

    DeepSeek Harness intentionally permits writes to platform temporary roots
    in ``workspace-write`` mode.  A model can therefore successfully write to
    ``/tmp/.../outputs`` even though the application only serves
    ``<workspace>/outputs``.  This parser gives the API a content-free signal
    for a pre-success persistence gate.
    """

    method = getattr(notification, "method", None)
    payload = getattr(notification, "payload", None)
    if isinstance(notification, dict):
        method = notification.get("method", method)
        payload = notification.get("payload", payload)
    if method != "session.event" or not isinstance(payload, dict):
        return None
    event = payload.get("event")
    if not isinstance(event, dict) or event.get("type") != "tool/call":
        return None
    data = event.get("data")
    if _operation_tool_category(_tool_name(data)) != "file_write":
        return None
    arguments = _tool_arguments(data)
    if arguments is None:
        return None
    raw_path = next(
        (
            value
            for key in ("file_path", "path", "target", "target_path")
            if isinstance((value := arguments.get(key)), str) and value.strip()
        ),
        None,
    )
    if raw_path is None or "\x00" in raw_path:
        return None

    supplied = Path(raw_path)
    # An outputs path outside the canonical root is still an output intent and
    # must not be allowed to produce a false-success run.
    output_indexes = [
        index
        for index, part in enumerate(supplied.parts)
        if part.lower() == "outputs"
    ]
    if not output_indexes:
        return None
    relative_parts = supplied.parts[output_indexes[-1] + 1 :]
    if not relative_parts:
        return None
    relative_output = Path(*relative_parts).as_posix()
    workspace = workspace_root.resolve()
    target = supplied if supplied.is_absolute() else workspace / supplied
    try:
        canonical_outputs = (workspace / "outputs").resolve()
        resolved_target = target.resolve()
        canonical_relative = resolved_target.relative_to(canonical_outputs)
        canonical = resolved_target != canonical_outputs
        if canonical:
            relative_output = canonical_relative.as_posix()
    except (OSError, ValueError):
        canonical = False
    suffix = supplied.suffix.lower().lstrip(".")
    return OutputWriteAttempt(
        canonical=canonical,
        output_format=suffix or None,
        target_id=output_relative_path_id(relative_output),
    )


def output_relative_path_id(relative_path: str | Path) -> str:
    """Return an opaque stable id without retaining a customer filename."""

    normalized = Path(relative_path).as_posix()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
    # Result/error envelopes frequently carry a generic message ``id``.  Only
    # call/start envelopes may use that legacy fallback; result correlation
    # must come from an explicit call-id or the runtime's nested source.
    call_id = _operation_call_id(
        data,
        allow_generic_id=event_type in {"tool/call", "tool/execute/start"},
    )
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
        ("todo_write", "checklist"),
        ("todo-write", "checklist"),
        ("todo", "checklist"),
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


def _operation_call_id(
    data: object,
    *,
    allow_generic_id: bool = True,
) -> str | None:
    if not isinstance(data, dict):
        return None

    def pick(candidate: object, *, include_generic_id: bool = True) -> str | None:
        if not isinstance(candidate, dict):
            return None
        keys = ["call_id", "callId", "tool_call_id", "toolCallId"]
        if include_generic_id:
            # ``id`` is useful on a normal tool/call envelope, but a result
            # message may also carry a message id.  The latter must not be
            # mistaken for the operation's call id.
            keys.append("id")
        for key in keys:
            value = candidate.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                safe = _safe_operation_identifier(str(value))
                if safe:
                    return safe
        return None

    # Current and older Harness tool envelopes put the explicit call
    # identifier directly on ``data`` or under ``data.call``.  Prefer the
    # call-specific keys before considering a generic ``id``: a result
    # envelope may use ``id`` for its message rather than its tool call.
    for candidate in (data, data.get("call")):
        call_id = pick(candidate, include_generic_id=False)
        if call_id:
            return call_id

    # The pinned runtime emits ``tool/result`` as an assistant message.  Its
    # canonical id is nested at ``data.message.source.callId`` (and is also
    # repeated as ``content[].toolCallId``).  Walk only those documented
    # containers so arbitrary message ids cannot leak into the operation log.
    message = data.get("message")
    if isinstance(message, dict):
        call_id = pick(message.get("source"), include_generic_id=False)
        if call_id:
            return call_id
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                call_id = pick(block, include_generic_id=False)
                if call_id:
                    return call_id

    # A few adapter/runtime versions wrap the same result envelope once under
    # ``result`` or ``output``.  Recurse through those bounded containers,
    # preserving the no-generic-id rule for their message payloads.
    for key in ("result", "output", "response"):
        nested = data.get(key)
        if isinstance(nested, dict):
            # A wrapper's generic ``id`` is commonly the response/message id,
            # not the underlying tool call.  Only canonical call-id keys may
            # cross that boundary.
            call_id = _operation_call_id(nested, allow_generic_id=False)
            if call_id:
                return call_id

    # Preserve compatibility with older tool/call envelopes that exposed only
    # a generic ``id`` after all canonical result paths have been checked.
    if allow_generic_id:
        for candidate in (data, data.get("call")):
            call_id = pick(candidate)
            if call_id:
                return call_id
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


def _tool_arguments(data: object) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    candidates: list[object] = [
        data.get("arguments"),
        data.get("args"),
        data.get("input"),
        data.get("parameters"),
    ]
    call = data.get("call")
    if isinstance(call, dict):
        candidates.extend(
            [
                call.get("arguments"),
                call.get("args"),
                call.get("input"),
                call.get("parameters"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, str) and len(candidate) <= 5_000_000:
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return None


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
        # A per-conversation startup lock linearizes cancellation with the
        # first SDK call.  The cancellation event is per run because a runner
        # can be rotated several times while one HTTP run remains active.
        self._start_locks: dict[str, threading.Lock] = {}
        self._run_cancel_events: dict[str, threading.Event] = {}
        self._cancel_cleanup_tasks: set[asyncio.Task[Any]] = set()
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
        controller_skill_exists = self._controller_skill_exists()
        main = self.runtime_config.main_agent() if self.runtime_config else {
            "api_key": self.settings.harness_api_key,
            "model": self.settings.harness_model,
        }
        credential_configured = bool(main.get("api_key"))
        configured = (
            enabled
            and installed
            and cordis_exists
            and controller_skill_exists
            and credential_configured
        )
        reasons: list[str] = []
        if not enabled:
            reasons.append("研究助手已被服务配置停用")
        if not installed:
            reasons.append("研究助手运行组件未安装")
        if not cordis_exists:
            reasons.append("研究助手运行配置缺失")
        if not controller_skill_exists:
            reasons.append("房地产综合研究总控 Skill 缺失")
        if not credential_configured:
            reasons.append("主模型 API 密钥尚未配置")
        return {
            "name": "research_agent",
            "configured": configured,
            "status": "configured" if configured else "degraded",
            "runtime_installed": installed,
            "runtime_configured": cordis_exists,
            "controller_skill_configured": controller_skill_exists,
            "credential_configured": credential_configured,
            "provider": self.settings.harness_provider,
            "model": main.get("model") or self.settings.harness_model,
            "reasons": reasons,
        }

    async def _start_gate_for(
        self,
        conversation_id: str,
        run_id: str,
    ) -> _HarnessStartGate:
        """Return the startup gate for an owned run after validating its lease."""

        async with self._cache_lock:
            if self._busy.get(conversation_id) != run_id:
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
            lock = self._start_locks.setdefault(conversation_id, threading.Lock())
            cancelled = self._run_cancel_events.setdefault(
                run_id,
                threading.Event(),
            )
        return _HarnessStartGate(lock, cancelled)

    async def run(
        self,
        conversation_id: str,
        prompt: str,
        on_notification: Callable[[object], HarnessFollowup | None],
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
        if not self._controller_skill_exists():
            raise HarnessAdapterError(
                "AGENT_CONTROLLER_SKILL_MISSING",
                "房地产综合研究总控 Skill 缺失",
            )

        if isinstance(session_generation, bool) or session_generation < 0:
            raise HarnessAdapterError("AGENT_PROTOCOL_ERROR", "研究助手运行会话代际无效")
        runner: Any | None = await self._runner_for(conversation_id, run_id)
        try:
            start_gate = await self._start_gate_for(conversation_id, run_id)
        except Exception:
            if runner is not None:
                await self._discard_runner(conversation_id, runner, run_id)
            raise
        # A web request is a self-contained SDK session.  Reusing a persisted
        # SDK session id in a fresh runtime can collide after restart, runner
        # eviction, or configuration reset.  The HTTP run id makes the SDK id
        # unique while the application restores continuity from its own
        # successful-message history.  A checklist correction may rotate this
        # generation again below because the pinned SDK has no interrupt RPC.
        current_generation = session_generation
        current_prompt = prompt
        session_id = harness_session_id(
            conversation_id,
            run_id,
            current_generation,
        )
        session_restart_count = 0

        try:
            while True:
                # A cancellation may have won the hand-off race immediately
                # after a replacement was installed.  Consume that marker
                # before starting another SDK turn so a detached/closed
                # runtime is never handed work after the request was stopped.
                if await self._take_cancelled(run_id):
                    if runner is not None:
                        await self._discard_runner(conversation_id, runner, run_id)
                    runner = None
                    raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
                # Bind these closures to the runner/session for this attempt.
                # They are called from the owned subscription thread.
                def checked_notification(notification: object) -> HarnessFollowup | None:
                    followup = on_notification(notification)
                    if followup is None:
                        return None
                    if not isinstance(followup, HarnessFollowup) or not followup.content.strip():
                        raise HarnessAdapterError(
                            "AGENT_PROTOCOL_ERROR",
                            "研究助手反馈指令无效",
                        )
                    return followup

                def observe(notification: object) -> None:
                    followup = checked_notification(notification)
                    if followup is None:
                        return
                    if followup.restart_session:
                        raise _HarnessSessionRestart(followup.content)
                    try:
                        assert runner is not None
                        runner.client.session_prompt(
                            session_id,
                            [{"type": "text", "text": followup.content}],
                        )
                    except _HarnessSessionRestart:
                        raise
                    except Exception as exc:
                        raise HarnessAdapterError(
                            "AGENT_CHECKLIST_RECOVERY_FAILED",
                            "研究助手无法接收任务清单纠正指令",
                        ) from exc

                try:
                    assert runner is not None
                    client = getattr(runner, "client", None)
                    if callable(getattr(runner, "start_session", None)) and callable(
                        getattr(client, "subscribe_session_notifications", None)
                    ):
                        # The pinned SDK's convenience Session.run stops at the
                        # first idle belonging to the original prompt. Own the
                        # subscription here so every ordinary correction is
                        # observed from its inbox receipt through a later idle.
                        result = await asyncio.to_thread(
                            _run_owned_harness_session,
                            runner,
                            current_prompt,
                            session_id=session_id,
                            on_notification=checked_notification,
                            start_guard=start_gate,
                        )
                    else:
                        # Minimal compatibility path for lightweight test
                        # doubles. Production DeepSeekHarness instances always
                        # take the owned subscription path above.
                        def run_compatibility_turn() -> object:
                            # Compatibility doubles do not expose the owned
                            # subscription API.  Claim the startup boundary
                            # atomically, then leave the gate free so cancel()
                            # can still close a blocking runner promptly.
                            start_gate.claim()
                            return runner.run(
                                current_prompt,
                                session_id=session_id,
                                on_notification=observe,
                            )

                        result = await asyncio.to_thread(run_compatibility_turn)
                except _HarnessSessionRestart as restart:
                    if await self._take_cancelled(run_id):
                        if runner is not None:
                            await self._discard_runner(conversation_id, runner, run_id)
                        runner = None
                        raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
                    session_restart_count += 1
                    if session_restart_count > 3:
                        raise HarnessAdapterError(
                            "AGENT_CHECKLIST_RECOVERY_EXHAUSTED",
                            "研究助手多次无法在隔离会话中恢复任务清单",
                        )
                    # The old SDK session may still have queued tool calls.  A
                    # replacement must therefore be an atomic hand-off: keep
                    # this run's busy lease while the old process is closed and
                    # the new one is created.  Dropping the lease first lets a
                    # concurrent HTTP request steal the conversation between
                    # the two sessions.
                    old_runner = runner
                    if old_runner is None:
                        raise HarnessAdapterError(
                            "AGENT_CHECKLIST_RECOVERY_FAILED",
                            "研究助手恢复会话已丢失",
                        )
                    current_generation += 1
                    next_session_id = harness_session_id(
                        conversation_id,
                        run_id,
                        current_generation,
                    )
                    next_prompt = _session_recovery_prompt(
                        prompt,
                        restart.content,
                    )
                    runner = await self._replace_runner(
                        conversation_id,
                        old_runner,
                        run_id,
                    )
                    session_id = next_session_id
                    current_prompt = next_prompt
                    continue
                break

            assert runner is not None
        except HarnessAdapterError:
            if await self._take_cancelled(run_id):
                if runner is not None:
                    await self._discard_runner(conversation_id, runner, run_id)
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
            if runner is not None:
                await self._discard_runner(conversation_id, runner, run_id)
            raise
        except Exception as exc:
            if await self._take_cancelled(run_id):
                if runner is not None:
                    await self._discard_runner(conversation_id, runner, run_id)
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止") from exc
            if runner is not None:
                await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError("AGENT_RUN_FAILED", self._safe_error_message(exc)) from exc
        if await self._take_cancelled(run_id):
            assert runner is not None
            await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
        finish_reason = getattr(result, "finish_reason", None)
        normalized_finish_reason = (
            finish_reason.strip().lower() if isinstance(finish_reason, str) else None
        )
        if normalized_finish_reason in {"error", "failed", "failure"}:
            assert runner is not None
            await self._discard_runner(conversation_id, runner, run_id)
            raise HarnessAdapterError(
                "AGENT_RESPONSE_ERROR",
                "研究助手本轮未能完成，请重新发送消息",
            )
        final_response = getattr(result, "final_response", None)
        if not isinstance(final_response, str) or not final_response.strip():
            assert runner is not None
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
        assert runner is not None
        await self._discard_runner(conversation_id, runner, run_id)
        return response

    def _controller_skill_exists(self) -> bool:
        return any(
            (root / CONTROLLER_SKILL_ID / "SKILL.md").is_file()
            or (root / f"{CONTROLLER_SKILL_ID}.md").is_file()
            for root in self.settings.harness_skill_dirs
        )

    async def _runner_for(self, conversation_id: str, run_id: str) -> Any:
        async with self._cache_lock:
            if conversation_id in self._busy:
                raise HarnessAdapterError("AGENT_BUSY", "研究助手正在处理这个项目的上一条消息")
            existing = self._runners.pop(conversation_id, None)
            self._busy[conversation_id] = run_id
            self._start_locks.setdefault(conversation_id, threading.Lock())
            self._run_cancel_events[run_id] = threading.Event()
            if existing is not None:
                self._runners[conversation_id] = existing
                return existing

        try:
            runner = await asyncio.to_thread(self._create_runner, conversation_id)
        except Exception as exc:
            cancelled = False
            async with self._cache_lock:
                cancelled = (
                    run_id in self._cancel_requested
                    or self._busy.get(conversation_id) != run_id
                )
                self._cancel_requested.discard(run_id)
                if self._busy.get(conversation_id) == run_id:
                    self._busy.pop(conversation_id, None)
                self._run_cancel_events.pop(run_id, None)
            if cancelled:
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止") from exc
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
                self._run_cancel_events.pop(run_id, None)
            else:
                self._runners[conversation_id] = runner
                await self._trim_cache_locked()
        if cancelled:
            await asyncio.to_thread(self._close_runner, runner)
            raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
        return runner

    async def _replace_runner(
        self,
        conversation_id: str,
        old_runner: Any,
        run_id: str,
    ) -> Any:
        """Rotate a runner without releasing the conversation's busy lease.

        Checklist recovery is triggered from inside an active SDK turn.  The
        pinned SDK exposes only a next-turn prompt, so the old process must be
        closed before replaying the request in a fresh process.  This helper
        deliberately keeps ``_busy[conversation_id]`` owned by ``run_id`` for
        the whole hand-off.  Cancellation may detach the old runner while it is
        being closed; identity checks ensure that neither side closes a runner
        twice, and every newly-created candidate is closed if ownership is lost
        before installation.
        """

        owns_old_close = False
        async with self._cache_lock:
            if self._busy.get(conversation_id) != run_id:
                # ``cancel``/``close`` already detached the old process and
                # owns its close operation.  Never close it a second time.
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
            current = self._runners.get(conversation_id)
            if current is old_runner:
                self._runners.pop(conversation_id, None)
                owns_old_close = True
            elif current is not None:
                # A different live runner under the same lease is an internal
                # ownership violation; fail closed without touching either
                # process.
                raise HarnessAdapterError(
                    "AGENT_PROTOCOL_ERROR",
                    "研究助手运行会话所有权不一致",
                )
            else:
                # A busy lease without its runner means cancellation/cleanup
                # detached it concurrently.  Do not create a replacement that
                # could outlive the operation which owns the lease.
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")

        if owns_old_close:
            await asyncio.to_thread(self._close_runner, old_runner)

        # Cancellation can arrive while the old process is shutting down.  Do
        # this check before allocating a replacement so a cancelled request
        # cannot spawn a fresh runtime.
        async with self._cache_lock:
            cancelled = (
                self._busy.get(conversation_id) != run_id
                or run_id in self._cancel_requested
            )
            if cancelled:
                if self._busy.get(conversation_id) == run_id:
                    self._busy.pop(conversation_id, None)
                raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")

        try:
            replacement = await asyncio.to_thread(
                self._create_runner,
                conversation_id,
            )
        except Exception:
            # The old process is already gone.  Do not leave a permanent busy
            # lease when construction fails; the caller will map the original
            # exception to its normal API error (or to cancellation if a cancel
            # marker won the race).
            async with self._cache_lock:
                if self._busy.get(conversation_id) == run_id:
                    self._busy.pop(conversation_id, None)
            raise

        installed = False
        async with self._cache_lock:
            cancelled = (
                self._busy.get(conversation_id) != run_id
                or run_id in self._cancel_requested
            )
            if not cancelled:
                # No other request can install a runner while this lease is
                # held.  Store the candidate before trimming idle cache entries
                # so cache eviction cannot mistake it for an orphan.
                self._runners[conversation_id] = replacement
                installed = True
                await self._trim_cache_locked()
            elif self._busy.get(conversation_id) == run_id:
                self._busy.pop(conversation_id, None)

        if cancelled:
            # ``cancel`` may already have detached/closed a candidate that was
            # installed just before this check.  Only close it when it is still
            # ours in the cache; an uninstalled candidate is ours exclusively.
            owns_replacement_close = not installed
            if installed:
                async with self._cache_lock:
                    if self._runners.get(conversation_id) is replacement:
                        self._runners.pop(conversation_id, None)
                        owns_replacement_close = True
            if owns_replacement_close:
                await asyncio.to_thread(self._close_runner, replacement)
            raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")

        # ``cancel()`` can run just after the installation lock is released.
        # Re-check ownership before returning to the loop; otherwise the next
        # turn could begin with a candidate that cancellation already removed
        # and is closing.  A cancellation that arrives after this final check
        # is still handled by the runtime's normal close/error path.
        owns_replacement_close = False
        async with self._cache_lock:
            if (
                self._busy.get(conversation_id) != run_id
                or run_id in self._cancel_requested
            ):
                if self._runners.get(conversation_id) is replacement:
                    self._runners.pop(conversation_id, None)
                    owns_replacement_close = True
                if self._busy.get(conversation_id) == run_id:
                    self._busy.pop(conversation_id, None)
                cancelled = True
            else:
                cancelled = False
        if cancelled:
            if owns_replacement_close:
                await asyncio.to_thread(self._close_runner, replacement)
            raise HarnessAdapterError("AGENT_CANCELLED", "本次研究已终止")
        return replacement

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
            self._run_cancel_events.pop(run_id, None)
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
            busy_run_ids = list(self._busy.values())
            lock_conversation_ids = set(self._busy)
            lock_conversation_ids.update(self._runners)
            self._cancel_requested.update(busy_run_ids)
            for run_id in busy_run_ids:
                event = self._run_cancel_events.get(run_id)
                if event is not None:
                    event.set()
            self._runners.clear()
            self._busy.clear()
            self._run_cancel_events.clear()
            start_locks = [
                self._start_locks[conversation_id]
                for conversation_id in lock_conversation_ids
                if conversation_id in self._start_locks
            ]
        acquired_locks: list[threading.Lock] = []
        try:
            # Wait until any in-flight initial SDK setup has crossed its
            # startup boundary before closing that runtime.  Events were set
            # above, so a worker that has not claimed setup will fail closed.
            for start_lock in start_locks:
                while not start_lock.acquire(blocking=False):
                    await asyncio.sleep(0.005)
                acquired_locks.append(start_lock)
            for runner in runners:
                await asyncio.to_thread(self._close_runner, runner)
        finally:
            for start_lock in reversed(acquired_locks):
                start_lock.release()

    @staticmethod
    async def _acquire_start_lock(lock: threading.Lock) -> None:
        """Acquire a threading lock without creating an orphaned executor job."""

        acquired = False
        try:
            while not lock.acquire(blocking=False):
                await asyncio.sleep(0.005)
            acquired = True
        except BaseException:
            # A cancellation delivered immediately after the non-blocking
            # acquire must not strand the per-conversation startup gate.
            if acquired:
                lock.release()
            raise

    def _track_cancel_cleanup(self, task: asyncio.Task[Any]) -> None:
        self._cancel_cleanup_tasks.add(task)

        def forget(done: asyncio.Task[Any]) -> None:
            self._cancel_cleanup_tasks.discard(done)
            # A shielded cleanup task may finish after its request task has
            # already returned.  Retrieve any exception here so an unusual
            # close failure does not become an unhandled-task warning.
            if not done.cancelled():
                try:
                    done.exception()
                except BaseException:
                    pass

        task.add_done_callback(forget)

    async def _finish_cancel_after_gate(
        self,
        conversation_id: str,
        run_id: str,
        start_lock: threading.Lock | None,
        *,
        lock_acquired: bool,
    ) -> bool:
        """Detach and close a cancelled run; optionally release its startup gate."""

        runner: Any | None = None
        active = False
        try:
            async with self._cache_lock:
                busy_run_id = self._busy.get(conversation_id)
                active = busy_run_id == run_id
                if active:
                    self._busy.pop(conversation_id, None)
                    runner = self._runners.pop(conversation_id, None)
                elif busy_run_id is None:
                    # The SDK call may have just completed but the web worker
                    # has not committed its response yet. Invalidate that
                    # cached session so a cancelled turn cannot be resumed as
                    # completed.
                    runner = self._runners.pop(conversation_id, None)
                else:
                    # Another run acquired the lease while we waited for the
                    # startup gate; never detach its runner.
                    self._cancel_requested.discard(run_id)
                    self._run_cancel_events.pop(run_id, None)
                    return False
                self._run_cancel_events.pop(run_id, None)
                # There is no worker left that could consume this marker when
                # the lease was already idle.  Clear it now instead of
                # retaining an unbounded stale run id in the manager.
                if not active:
                    self._cancel_requested.discard(run_id)
            if runner is not None:
                # Keep the close operation alive even if the caller's task is
                # cancelled (for example, an API timeout).
                close_task = asyncio.create_task(
                    asyncio.to_thread(self._close_runner, runner)
                )
                self._track_cancel_cleanup(close_task)
                await asyncio.shield(close_task)
            return active or runner is not None
        finally:
            if lock_acquired and start_lock is not None:
                start_lock.release()

    async def cancel(self, conversation_id: str, *, run_id: str) -> bool:
        # Mark cancellation before waiting for startup setup.  This makes a
        # timeout/cancellation of this coroutine safe: an unstarted worker
        # observes the event and fails closed, while a background cleanup task
        # below still detaches and closes the runtime.
        async with self._cache_lock:
            busy_run_id = self._busy.get(conversation_id)
            if busy_run_id is not None and busy_run_id != run_id:
                return False
            active_hint = busy_run_id == run_id
            cached_hint = busy_run_id is None and conversation_id in self._runners
            if not active_hint and not cached_hint:
                return False
            self._cancel_requested.add(run_id)
            cancelled_event = self._run_cancel_events.get(run_id)
            if cancelled_event is not None:
                cancelled_event.set()
            start_lock = self._start_locks.get(conversation_id)

        lock_acquired = False
        if start_lock is not None:
            acquire_task = asyncio.create_task(self._acquire_start_lock(start_lock))
            self._track_cancel_cleanup(acquire_task)
            try:
                # Shield the polling task so wait_for/task cancellation cannot
                # leave a lock acquisition running without its cleanup owner.
                await asyncio.shield(acquire_task)
                lock_acquired = True
            except asyncio.CancelledError:
                async def finish_after_acquire() -> None:
                    acquired = False
                    try:
                        # The outer request may be cancelled repeatedly while
                        # this background owner waits.  Keep the polling task
                        # shielded and continue until we know whether it
                        # acquired the lock; otherwise a late acquisition
                        # would strand the gate forever.
                        while True:
                            try:
                                await asyncio.shield(acquire_task)
                                acquired = True
                                break
                            except asyncio.CancelledError:
                                if not acquire_task.done():
                                    continue
                                if acquire_task.cancelled():
                                    return
                                try:
                                    acquire_task.result()
                                except BaseException:
                                    return
                                acquired = True
                                break
                            except BaseException:
                                return
                        # This coroutine owns the lock and releases it in its
                        # finally block, even if detachment is cancelled.
                        await self._finish_cancel_after_gate(
                            conversation_id,
                            run_id,
                            start_lock,
                            lock_acquired=False,
                        )
                    finally:
                        if acquired:
                            start_lock.release()

                cleanup_task = asyncio.create_task(finish_after_acquire())
                self._track_cancel_cleanup(cleanup_task)
                raise

        cleanup_task = asyncio.create_task(
            self._finish_cancel_after_gate(
                conversation_id,
                run_id,
                start_lock,
                lock_acquired=lock_acquired,
            )
        )
        self._track_cancel_cleanup(cleanup_task)
        try:
            return await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            # The shielded cleanup remains tracked and will release the gate
            # and close the detached runner in the background.
            raise

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
