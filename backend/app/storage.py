from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{15,79}$")
PROJECT_ID_RE = CONVERSATION_ID_RE
FILE_ID_RE = re.compile(r"^(?:file_[0-9a-f]{32}|out_[0-9a-f]{24})$")
MESSAGE_ID_RE = re.compile(r"^msg_[0-9a-f]{32}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
CLIENT_REQUEST_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
RUN_STATUSES = frozenset(
    {"idle", "running", "succeeded", "failed", "cancelled", "interrupted"}
)
TOKEN_USAGE_BUCKET_FIELDS = (
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


class StorageError(RuntimeError):
    code = "STORAGE_ERROR"


class InvalidIdentifier(StorageError):
    code = "INVALID_IDENTIFIER"


class ConversationNotFound(StorageError):
    code = "CONVERSATION_NOT_FOUND"


class ProjectNotFound(StorageError):
    code = "PROJECT_NOT_FOUND"


class ProjectConflict(StorageError):
    code = "PROJECT_CONFLICT"


class FileNotFound(StorageError):
    code = "FILE_NOT_FOUND"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _zero_token_usage() -> dict[str, int]:
    return {field: 0 for field in TOKEN_USAGE_BUCKET_FIELDS}


def _validated_token_usage_buckets(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise StorageError("conversation token usage buckets are invalid")
    result: dict[str, int] = {}
    for field in TOKEN_USAGE_BUCKET_FIELDS:
        item = value.get(field, 0 if field == "reasoning_tokens" else None)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise StorageError("conversation token usage buckets are invalid")
        result[field] = item
    return result


def sanitize_filename(value: str | None) -> str:
    raw = unicodedata.normalize("NFKC", value or "upload.bin")
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = "".join(character for character in raw if character >= " " and character != "\x7f")
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    if not raw or raw in {".", ".."}:
        raw = "upload.bin"
    stem, suffix = os.path.splitext(raw)
    stem = re.sub(r"[^\w .()\-\u4e00-\u9fff]", "_", stem, flags=re.UNICODE).strip(" .")
    suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)[:16]
    stem = stem[:120] or "upload"
    return f"{stem}{suffix}"[:140]


def _summary_text(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= maximum:
        return normalized
    return normalized[: maximum - 1].rstrip() + "…"


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise StorageError(f"conversation {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StorageError(f"conversation {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise StorageError(f"conversation {field} must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ConversationPaths:
    root: Path
    workspace: Path
    inputs: Path
    work: Path
    outputs: Path
    meta: Path
    messages: Path
    files: Path
    run: Path
    usage: Path


class ConversationStore:
    """Small durable store with one filesystem namespace per conversation."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock(self, conversation_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(conversation_id, threading.RLock())

    @staticmethod
    def validate_conversation_id(conversation_id: str) -> str:
        if not CONVERSATION_ID_RE.fullmatch(conversation_id):
            raise InvalidIdentifier("conversation id must match [A-Za-z0-9][A-Za-z0-9_-]{15,79}")
        return conversation_id

    @staticmethod
    def validate_project_id(project_id: str) -> str:
        if not PROJECT_ID_RE.fullmatch(project_id):
            raise InvalidIdentifier("project id must match [A-Za-z0-9][A-Za-z0-9_-]{15,79}")
        return project_id

    def paths(self, conversation_id: str) -> ConversationPaths:
        self.validate_conversation_id(conversation_id)
        root = (self.root / conversation_id).resolve()
        try:
            root.relative_to(self.root)
        except ValueError as exc:  # defense in depth around future id-shape changes
            raise InvalidIdentifier("conversation path escapes storage root") from exc
        workspace = root / "workspace"
        return ConversationPaths(
            root=root,
            workspace=workspace,
            inputs=workspace / "inputs",
            work=workspace / "work",
            outputs=workspace / "outputs",
            meta=root / "meta.json",
            messages=root / "messages.jsonl",
            files=root / "files.json",
            run=root / "run.json",
            usage=root / "usage.json",
        )

    def create_or_reuse(
        self,
        requested_id: str | None = None,
        *,
        project_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        conversation_id = requested_id or str(uuid.uuid4())
        self.validate_conversation_id(conversation_id)
        effective_project_id = self.validate_project_id(project_id or conversation_id)
        paths = self.paths(conversation_id)
        with self._lock(conversation_id):
            if paths.root.exists():
                if not paths.meta.is_file():
                    raise StorageError(f"conversation {conversation_id!r} exists without metadata")
                existing = self.read_meta(conversation_id)
                if project_id is not None and existing["project_id"] != effective_project_id:
                    raise ProjectConflict("conversation already belongs to another project")
                return existing, False

            # The id was validated and the parent is a fixed resolved root.
            paths.root.mkdir(mode=0o750)
            paths.inputs.mkdir(parents=True, mode=0o750)
            paths.work.mkdir(mode=0o750)
            paths.outputs.mkdir(mode=0o750)
            now = utc_now()
            metadata: dict[str, Any] = {
                "id": conversation_id,
                "project_id": effective_project_id,
                "created_at": now,
                "updated_at": now,
                # Generation zero retains the historical ``web-{conversation}``
                # runtime session id.  A confirmed cancellation advances this
                # value so a disposed SDK session is never resumed.
                "agent_session_generation": 0,
                "agent_session_seeded_generation": 0,
            }
            self._atomic_json(paths.meta, metadata)
            self._atomic_json(paths.files, {"items": []})
            self._atomic_json(
                paths.run,
                {
                    "version": 1,
                    "status": "idle",
                    "updated_at": now,
                    "retryable": False,
                },
            )
            self._atomic_json(
                paths.usage,
                {
                    "version": 1,
                    "totals": _zero_token_usage(),
                    "updated_at": None,
                    "samples": {},
                },
            )
            paths.messages.touch(mode=0o640)
            return metadata, True

    def create_project(
        self,
        requested_project_id: str | None = None,
        *,
        requested_conversation_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Create an independent project containing its first blank conversation."""

        project_id = requested_project_id or str(uuid.uuid4())
        self.validate_project_id(project_id)
        with self._lock(f"project:{project_id}"):
            if self.project_exists(project_id):
                raise ProjectConflict(f"project {project_id!r} already exists")
            metadata, created = self.create_or_reuse(
                requested_conversation_id,
                project_id=project_id,
            )
            if not created:
                raise ProjectConflict("project conversation already exists")
            return project_id, metadata

    def create_conversation_in_project(
        self,
        project_id: str,
        requested_conversation_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create a new isolated conversation beneath an existing project."""

        self.validate_project_id(project_id)
        with self._lock(f"project:{project_id}"):
            if not self.project_exists(project_id):
                raise ProjectNotFound(f"project {project_id!r} does not exist")
            return self.create_or_reuse(
                requested_conversation_id,
                project_id=project_id,
            )

    def project_exists(self, project_id: str) -> bool:
        self.validate_project_id(project_id)
        try:
            candidates = list(self.root.iterdir())
        except OSError as exc:
            raise StorageError("conversation storage cannot be enumerated") from exc
        for candidate in candidates:
            try:
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                conversation_id = self.validate_conversation_id(candidate.name)
                paths = self.paths(conversation_id)
                if paths.root != candidate.resolve() or paths.meta.is_symlink():
                    continue
                with paths.meta.open("r", encoding="utf-8") as handle:
                    metadata = json.load(handle)
                if not isinstance(metadata, dict) or metadata.get("id") != conversation_id:
                    continue
                candidate_project_id = metadata.get("project_id") or conversation_id
                if candidate_project_id == project_id:
                    return True
            except (json.JSONDecodeError, OSError, StorageError, UnicodeError, ValueError):
                continue
        return False

    def require(self, conversation_id: str) -> ConversationPaths:
        paths = self.paths(conversation_id)
        if not paths.root.is_dir() or not paths.meta.is_file():
            raise ConversationNotFound(f"conversation {conversation_id!r} does not exist")
        if paths.root.is_symlink() or paths.workspace.is_symlink():
            raise StorageError("conversation workspace contains a forbidden symbolic link")
        workspace_root = paths.workspace.resolve()
        for name, directory in (
            ("inputs", paths.inputs),
            ("work", paths.work),
            ("outputs", paths.outputs),
        ):
            if (
                directory.is_symlink()
                or not directory.is_dir()
                or directory.resolve() != workspace_root / name
            ):
                raise StorageError(f"conversation {name} directory is missing or unsafe")
        return paths

    def read_meta(self, conversation_id: str) -> dict[str, Any]:
        paths = self.require(conversation_id)
        with paths.meta.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or value.get("id") != conversation_id:
            raise StorageError(f"conversation {conversation_id!r} metadata is invalid")
        project_id = value.get("project_id") or conversation_id
        self.validate_project_id(project_id)
        value["project_id"] = project_id
        return value

    def update_meta(self, conversation_id: str, **changes: Any) -> dict[str, Any]:
        paths = self.require(conversation_id)
        with self._lock(conversation_id):
            value = self.read_meta(conversation_id)
            value.update(changes)
            value["updated_at"] = utc_now()
            self._atomic_json(paths.meta, value)
            return value

    def read_token_usage(self, conversation_id: str) -> dict[str, Any]:
        """Read durable provider-reported usage, defaulting old chats to zero."""

        paths = self.require(conversation_id)
        if not paths.usage.exists():
            return {
                "version": 1,
                "totals": _zero_token_usage(),
                "updated_at": None,
                "samples": {},
            }
        if paths.usage.is_symlink() or not paths.usage.is_file():
            raise StorageError("conversation token usage state is missing or unsafe")
        try:
            with paths.usage.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except json.JSONDecodeError as exc:
            raise StorageError("conversation token usage state is invalid") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise StorageError("conversation token usage state is invalid")

        totals = _validated_token_usage_buckets(value.get("totals"))
        samples = value.get("samples")
        if not isinstance(samples, dict):
            raise StorageError("conversation token usage samples are invalid")
        normalized_samples: dict[str, dict[str, Any]] = {}
        for sample_id, sample in samples.items():
            if not isinstance(sample_id, str) or not re.fullmatch(
                r"[0-9a-f]{64}", sample_id
            ):
                raise StorageError("conversation token usage sample id is invalid")
            if not isinstance(sample, dict):
                raise StorageError("conversation token usage sample is invalid")
            seq = sample.get("seq")
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
                raise StorageError("conversation token usage sample seq is invalid")
            normalized_samples[sample_id] = {
                "seq": seq,
                "buckets": _validated_token_usage_buckets(sample.get("buckets")),
            }

        updated_at = value.get("updated_at")
        if updated_at is not None:
            _timestamp(updated_at, "token usage updated_at")
        active_run_id = value.get("active_run_id")
        if active_run_id is not None and (
            not isinstance(active_run_id, str) or not RUN_ID_RE.fullmatch(active_run_id)
        ):
            raise StorageError("conversation token usage run id is invalid")
        return {
            "version": 1,
            "totals": totals,
            "updated_at": updated_at,
            "samples": normalized_samples,
            **(
                {"active_run_id": active_run_id}
                if isinstance(active_run_id, str)
                else {}
            ),
        }

    def begin_token_usage_run(
        self,
        conversation_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Open a new accounting run without discarding replay protection."""

        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("run id is invalid")
        paths = self.require(conversation_id)
        with self._lock(conversation_id):
            previous = self.read_token_usage(conversation_id)
            if previous.get("active_run_id") == run_id:
                return previous
            value = {
                "version": 1,
                "totals": previous["totals"],
                "updated_at": previous.get("updated_at"),
                "active_run_id": run_id,
                "samples": previous["samples"],
            }
            self._atomic_json(paths.usage, value)
            return value

    def record_token_usage(
        self,
        conversation_id: str,
        *,
        run_id: str,
        session_id: str,
        event_seq: int,
        turn: int,
        step: int,
        attempt: int,
        buckets: dict[str, int],
        sample_kind: str = "model_step",
    ) -> tuple[dict[str, Any], bool]:
        """Atomically replace one attempt sample and update conversation totals.

        Samples from an early usage chunk and the finalized assistant message
        share the same run/session/turn/step/attempt key.  Different retry
        attempts deliberately use different keys and are therefore additive.
        """

        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("run id is invalid")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session id is invalid")
        if sample_kind not in {"model_step", "compaction"}:
            raise ValueError("token usage sample kind is invalid")
        for name, item in (
            ("event seq", event_seq),
            ("turn", turn),
            ("step", step),
            ("attempt", attempt),
        ):
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise ValueError(f"{name} is invalid")
        normalized = _validated_token_usage_buckets(buckets)
        sample_material = "\0".join(
            (run_id, session_id, sample_kind, str(turn), str(step), str(attempt))
        ).encode("utf-8")
        sample_id = hashlib.sha256(sample_material).hexdigest()

        paths = self.require(conversation_id)
        with self._lock(conversation_id):
            previous_state = self.read_token_usage(conversation_id)
            samples = dict(previous_state["samples"])
            previous_entry = samples.get(sample_id)
            if previous_entry is not None and event_seq <= previous_entry["seq"]:
                return previous_state, False
            previous_sample = (
                previous_entry["buckets"] if previous_entry is not None else None
            )

            totals = dict(previous_state["totals"])
            for field in TOKEN_USAGE_BUCKET_FIELDS:
                totals[field] = (
                    totals[field]
                    - (previous_sample.get(field, 0) if previous_sample else 0)
                    + normalized[field]
                )
                if totals[field] < 0:
                    raise StorageError("conversation token usage total became invalid")
            samples[sample_id] = {"seq": event_seq, "buckets": normalized}
            value = {
                "version": 1,
                "totals": totals,
                "updated_at": utc_now(),
                "active_run_id": previous_state.get("active_run_id") or run_id,
                "samples": samples,
            }
            self._atomic_json(paths.usage, value)
            return value, True

    def read_run(self, conversation_id: str) -> dict[str, Any]:
        """Return the durable, content-free state of the latest research turn.

        Older conversations predate ``run.json``.  Infer a content-free latest
        turn projection from message order so an unfinished legacy turn can be
        recovered after this upgrade.  The API persists that projection on its
        next run-state read.
        """

        paths = self.require(conversation_id)
        if not paths.run.exists():
            messages = self.list_messages(conversation_id)
            latest_user_index: int | None = None
            for index in range(len(messages) - 1, -1, -1):
                if messages[index].get("role") == "user":
                    latest_user_index = index
                    break
            if latest_user_index is None:
                return {
                    "version": 1,
                    "status": "idle",
                    "updated_at": self.read_meta(conversation_id)["updated_at"],
                    "retryable": False,
                    "legacy": True,
                }

            user_message = messages[latest_user_index]
            reply = next(
                (
                    item
                    for item in reversed(messages[latest_user_index + 1 :])
                    if item.get("role") == "assistant"
                ),
                None,
            )
            reply_status = str(reply.get("status") or "completed").lower() if reply else ""
            if reply_status in {"complete", "completed", "succeeded"}:
                status, retryable = "succeeded", False
            elif reply_status in {"stopped", "cancelled", "canceled"}:
                status, retryable = "cancelled", True
            elif reply is not None:
                status, retryable = "failed", True
            else:
                status, retryable = "interrupted", True
            value: dict[str, Any] = {
                "version": 1,
                "status": status,
                "updated_at": self.read_meta(conversation_id)["updated_at"],
                "retryable": retryable,
                "legacy": True,
            }
            user_message_id = user_message.get("id")
            if isinstance(user_message_id, str) and MESSAGE_ID_RE.fullmatch(user_message_id):
                value["user_message_id"] = user_message_id
            if reply is not None:
                reply_id = reply.get("id")
                if isinstance(reply_id, str) and MESSAGE_ID_RE.fullmatch(reply_id):
                    value["assistant_message_id"] = reply_id
            if status == "interrupted":
                value["error_code"] = "RUN_INTERRUPTED"
            return value
        if paths.run.is_symlink() or not paths.run.is_file():
            raise StorageError("conversation run state is missing or unsafe")
        try:
            with paths.run.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except json.JSONDecodeError as exc:
            raise StorageError("conversation run state is invalid") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise StorageError("conversation run state is invalid")
        status = value.get("status")
        if status not in RUN_STATUSES:
            raise StorageError("conversation run status is invalid")
        _timestamp(value.get("updated_at"), "run updated_at")
        for field, pattern in (
            ("run_id", RUN_ID_RE),
            ("client_request_id", CLIENT_REQUEST_ID_RE),
            ("user_message_id", MESSAGE_ID_RE),
            ("assistant_message_id", MESSAGE_ID_RE),
        ):
            item = value.get(field)
            if item is not None and (not isinstance(item, str) or not pattern.fullmatch(item)):
                raise StorageError(f"conversation run {field} is invalid")
        return value

    def write_run(
        self,
        conversation_id: str,
        *,
        status: str,
        run_id: str | None = None,
        client_request_id: str | None = None,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        started_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist a content-free latest-run projection."""

        if status not in RUN_STATUSES:
            raise ValueError(f"unsupported run status {status!r}")
        if run_id is not None and not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("run id is invalid")
        if client_request_id is not None and not CLIENT_REQUEST_ID_RE.fullmatch(
            client_request_id
        ):
            raise ValueError("client request id is invalid")
        if user_message_id is not None and not MESSAGE_ID_RE.fullmatch(user_message_id):
            raise ValueError("user message id is invalid")
        if assistant_message_id is not None and not MESSAGE_ID_RE.fullmatch(
            assistant_message_id
        ):
            raise ValueError("assistant message id is invalid")
        if error_code is not None:
            error_code = str(error_code).strip()[:120] or None

        paths = self.require(conversation_id)
        with self._lock(conversation_id):
            previous = self.read_run(conversation_id)
            now = utc_now()
            value: dict[str, Any] = {
                "version": 1,
                "status": status,
                "updated_at": now,
                "retryable": bool(retryable),
            }
            effective_started_at = started_at or previous.get("started_at")
            if status == "running":
                effective_started_at = started_at or now
            if isinstance(effective_started_at, str):
                value["started_at"] = effective_started_at
            if status in {"succeeded", "failed", "cancelled", "interrupted"}:
                value["completed_at"] = now
            run_value = run_id if status == "running" else run_id or previous.get("run_id")
            client_request_value = (
                client_request_id
                if status == "running"
                else client_request_id or previous.get("client_request_id")
            )
            user_value = (
                user_message_id
                if status == "running"
                else user_message_id or previous.get("user_message_id")
            )
            assistant_value = (
                None
                if status == "running"
                else assistant_message_id or previous.get("assistant_message_id")
            )
            for field, item in (
                ("run_id", run_value),
                ("client_request_id", client_request_value),
                ("user_message_id", user_value),
                ("assistant_message_id", assistant_value),
                ("error_code", error_code),
            ):
                if item is not None:
                    value[field] = item
            self._atomic_json(paths.run, value)
            return value

    def append_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        attachment_ids: Iterable[str] = (),
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"unsupported message role {role!r}")
        paths = self.require(conversation_id)
        message: dict[str, Any] = {
            "id": f"msg_{uuid.uuid4().hex}",
            "role": role,
            "content": content,
            "attachment_ids": list(attachment_ids),
            "status": status,
            "created_at": utc_now(),
        }
        if metadata:
            message["metadata"] = metadata
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock(conversation_id):
            with paths.messages.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self.update_meta(conversation_id)
        return message

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        paths = self.require(conversation_id)
        result: list[dict[str, Any]] = []
        with paths.messages.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StorageError(
                        f"invalid message log at {paths.messages.name}:{line_number}"
                    ) from exc
                if isinstance(value, dict):
                    result.append(value)
        return result

    def list_conversations(self) -> list[dict[str, Any]]:
        """Return safe, user-facing summaries for valid conversation directories.

        Files and directories that do not match the managed conversation layout,
        contain unsafe symbolic links, or have damaged metadata/message logs are
        ignored. Internal metadata is deliberately never copied into the result.
        """

        try:
            candidates = list(self.root.iterdir())
        except OSError as exc:
            raise StorageError("conversation storage cannot be enumerated") from exc

        ranked: list[tuple[datetime, str, dict[str, Any]]] = []
        for candidate in candidates:
            try:
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                conversation_id = self.validate_conversation_id(candidate.name)
                paths = self.paths(conversation_id)
                if paths.root != candidate.resolve():
                    continue
                with self._lock(conversation_id):
                    summary, updated_sort = self._conversation_summary(paths, conversation_id)
                ranked.append((updated_sort, conversation_id, summary))
            except (
                json.JSONDecodeError,
                OSError,
                StorageError,
                UnicodeError,
                ValueError,
            ):
                continue

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [summary for _, _, summary in ranked]

    def list_projects(self) -> list[dict[str, Any]]:
        """Group conversations into a safe two-level project history projection."""

        grouped: dict[str, list[dict[str, Any]]] = {}
        for conversation in self.list_conversations():
            project_id = self.validate_project_id(str(conversation["project_id"]))
            grouped.setdefault(project_id, []).append(conversation)

        projects: list[tuple[datetime, str, dict[str, Any]]] = []
        for project_id, conversations in grouped.items():
            conversations.sort(
                key=lambda item: (_timestamp(item["updated_at"], "updated_at"), item["id"]),
                reverse=True,
            )
            chronological = sorted(
                conversations,
                key=lambda item: (_timestamp(item["created_at"], "created_at"), item["id"]),
            )
            created_at = min(
                chronological,
                key=lambda item: _timestamp(item["created_at"], "created_at"),
            )["created_at"]
            newest = conversations[0]
            project_title = next(
                (
                    str(item["title"])
                    for item in chronological
                    if item.get("message_count", 0) > 0 and item.get("title") != "新对话"
                ),
                "新项目",
            )
            project = {
                "id": project_id,
                "created_at": created_at,
                "updated_at": newest["updated_at"],
                "title": project_title,
                "preview": newest.get("preview", ""),
                "conversation_count": len(conversations),
                "message_count": sum(int(item.get("message_count", 0)) for item in conversations),
                "conversations": conversations,
            }
            projects.append(
                (_timestamp(newest["updated_at"], "updated_at"), project_id, project)
            )

        projects.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [project for _, _, project in projects]

    def _conversation_summary(
        self,
        paths: ConversationPaths,
        conversation_id: str,
    ) -> tuple[dict[str, Any], datetime]:
        self.require(conversation_id)
        if (
            paths.meta.is_symlink()
            or paths.messages.is_symlink()
            or not paths.messages.is_file()
        ):
            raise StorageError("conversation metadata or message log is unsafe")

        with paths.meta.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        if not isinstance(metadata, dict) or metadata.get("id") != conversation_id:
            raise StorageError("conversation metadata is invalid")
        project_id = metadata.get("project_id") or conversation_id
        self.validate_project_id(project_id)
        created_at = metadata.get("created_at")
        updated_at = metadata.get("updated_at")
        _timestamp(created_at, "created_at")
        updated_sort = _timestamp(updated_at, "updated_at")

        title = ""
        preview = ""
        message_count = 0
        with paths.messages.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StorageError(
                        f"invalid message log at {paths.messages.name}:{line_number}"
                    ) from exc
                if not isinstance(message, dict):
                    raise StorageError(
                        f"invalid message log at {paths.messages.name}:{line_number}"
                    )
                role = message.get("role")
                content = message.get("content")
                if role not in {"user", "assistant", "system"} or not isinstance(content, str):
                    raise StorageError(
                        f"invalid message log at {paths.messages.name}:{line_number}"
                    )
                message_count += 1
                normalized = _summary_text(content, 160)
                if role == "user" and not title and normalized:
                    title = _summary_text(content, 80)
                if role in {"user", "assistant"} and normalized:
                    preview = normalized

        return (
            {
                "id": conversation_id,
                "project_id": project_id,
                "created_at": created_at,
                "updated_at": updated_at,
                "title": title or "新对话",
                "preview": preview,
                "message_count": message_count,
            },
            updated_sort,
        )

    def allocate_upload(self, conversation_id: str, original_name: str | None) -> tuple[str, str, Path]:
        paths = self.require(conversation_id)
        file_id = f"file_{uuid.uuid4().hex}"
        safe_name = sanitize_filename(original_name)
        target = paths.inputs / f"{file_id}--{safe_name}"
        return file_id, safe_name, target

    def register_upload(
        self,
        conversation_id: str,
        *,
        file_id: str,
        original_name: str,
        stored_path: Path,
        size: int,
        content_type: str | None,
    ) -> dict[str, Any]:
        if not FILE_ID_RE.fullmatch(file_id) or not file_id.startswith("file_"):
            raise InvalidIdentifier("invalid upload id")
        paths = self.require(conversation_id)
        resolved = stored_path.resolve()
        try:
            relative = resolved.relative_to(paths.workspace.resolve())
        except ValueError as exc:
            raise StorageError("upload path is outside the conversation workspace") from exc
        item = {
            "id": file_id,
            "name": original_name,
            "size": size,
            "content_type": content_type or "application/octet-stream",
            "kind": "input",
            "workspace_path": relative.as_posix(),
            "created_at": utc_now(),
            "download_url": f"/api/conversations/{conversation_id}/files/{file_id}",
        }
        with self._lock(conversation_id):
            index = self._read_file_index(paths)
            index.append(item)
            self._atomic_json(paths.files, {"items": index})
            self.update_meta(conversation_id)
        return item

    def _read_file_index(self, paths: ConversationPaths) -> list[dict[str, Any]]:
        with paths.files.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        items = value.get("items") if isinstance(value, dict) else None
        if not isinstance(items, list):
            raise StorageError("file index is invalid")
        return [item for item in items if isinstance(item, dict)]

    def input_files(self, conversation_id: str, ids: Iterable[str]) -> list[dict[str, Any]]:
        paths = self.require(conversation_id)
        requested = list(dict.fromkeys(ids))
        if any(not FILE_ID_RE.fullmatch(file_id) for file_id in requested):
            raise InvalidIdentifier("one or more file ids are invalid")
        by_id = {str(item.get("id")): item for item in self._read_file_index(paths)}
        missing = [file_id for file_id in requested if file_id not in by_id]
        if missing:
            raise FileNotFound(f"unknown file ids: {', '.join(missing)}")
        return [by_id[file_id] for file_id in requested]

    def list_files(self, conversation_id: str) -> list[dict[str, Any]]:
        paths = self.require(conversation_id)
        inputs = self._read_file_index(paths)
        outputs: list[dict[str, Any]] = []
        if paths.outputs.is_symlink() or not paths.outputs.is_dir():
            raise StorageError("conversation outputs directory is missing or unsafe")
        workspace_root = paths.workspace.resolve()
        output_root = paths.outputs.resolve()
        if output_root != workspace_root / "outputs":
            raise StorageError("conversation outputs directory escapes the workspace")
        candidates: list[Path] = []
        for directory, dirnames, filenames in os.walk(output_root, followlinks=False):
            directory_path = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not (directory_path / name).is_symlink()
            )
            for filename in sorted(filenames):
                candidates.append(directory_path / filename)
        for candidate in candidates:
            if not candidate.is_file() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            try:
                relative = resolved.relative_to(output_root)
            except ValueError:
                continue
            relative_text = relative.as_posix()
            digest = hashlib.sha256(relative_text.encode("utf-8")).hexdigest()[:24]
            stat = resolved.stat()
            outputs.append(
                {
                    "id": f"out_{digest}",
                    "name": relative_text,
                    "size": stat.st_size,
                    "content_type": mimetypes.guess_type(relative_text)[0] or "application/octet-stream",
                    "kind": "output",
                    "workspace_path": f"outputs/{relative_text}",
                    "created_at": datetime.fromtimestamp(stat.st_mtime, UTC)
                    .isoformat(timespec="milliseconds")
                    .replace("+00:00", "Z"),
                    "download_url": f"/api/conversations/{conversation_id}/files/out_{digest}",
                    "open_url": (
                        f"/api/conversations/{conversation_id}/files/out_{digest}/open"
                        if resolved.suffix.lower() in {".md", ".html", ".pdf"}
                        else None
                    ),
                }
            )
        return inputs + outputs

    def resolve_file(self, conversation_id: str, file_id: str) -> tuple[Path, dict[str, Any]]:
        if not FILE_ID_RE.fullmatch(file_id):
            raise InvalidIdentifier("invalid file id")
        paths = self.require(conversation_id)
        for item in self.list_files(conversation_id):
            if item.get("id") != file_id:
                continue
            workspace_path = item.get("workspace_path")
            if not isinstance(workspace_path, str):
                break
            candidate = (paths.workspace / workspace_path).resolve()
            try:
                candidate.relative_to(paths.workspace.resolve())
            except ValueError as exc:
                raise StorageError("file index points outside the workspace") from exc
            if not candidate.is_file() or candidate.is_symlink():
                break
            return candidate, item
        raise FileNotFound(f"file {file_id!r} does not exist")

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
