from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.storage import (
    ConversationStore,
    InvalidIdentifier,
    ProjectConflict,
    ProjectNotFound,
    StorageError,
    sanitize_filename,
)


class ConversationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temporary.name) / "conversations")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_reuse_and_message_log(self) -> None:
        metadata, created = self.store.create_or_reuse("conversation_123456")
        self.assertTrue(created)
        again, created_again = self.store.create_or_reuse("conversation_123456")
        self.assertFalse(created_again)
        self.assertEqual(metadata["id"], again["id"])

        message = self.store.append_message(
            "conversation_123456", role="user", content="hello", attachment_ids=[]
        )
        self.assertEqual([message], self.store.list_messages("conversation_123456"))

    def test_run_state_is_atomic_content_free_and_legacy_compatible(self) -> None:
        conversation_id = "conversation_run_0001"
        client_request_id = "123e4567-e89b-42d3-a456-426614174000"
        self.store.create_or_reuse(conversation_id)
        initial = self.store.read_run(conversation_id)
        self.assertEqual("idle", initial["status"])
        self.assertFalse(initial["retryable"])

        user = self.store.append_message(
            conversation_id,
            role="user",
            content="private request must not be copied into run state",
        )
        running = self.store.write_run(
            conversation_id,
            status="running",
            run_id="a" * 32,
            client_request_id=client_request_id,
            user_message_id=user["id"],
        )
        self.assertEqual("running", running["status"])
        self.assertEqual(client_request_id, running["client_request_id"])
        self.assertIn("started_at", running)
        self.assertNotIn("private request", json.dumps(running))

        failed = self.store.write_run(
            conversation_id,
            status="failed",
            run_id="a" * 32,
            user_message_id=user["id"],
            error_code="AGENT_RUN_FAILED",
            retryable=True,
        )
        self.assertEqual("failed", failed["status"])
        self.assertTrue(failed["retryable"])
        self.assertEqual(client_request_id, failed["client_request_id"])
        self.assertIn("completed_at", failed)

        self.store.require(conversation_id).run.unlink()
        legacy = self.store.read_run(conversation_id)
        self.assertEqual("interrupted", legacy["status"])
        self.assertTrue(legacy["retryable"])
        self.assertTrue(legacy["legacy"])
        self.assertEqual(user["id"], legacy["user_message_id"])

    def test_run_state_rejects_noncanonical_client_request_id(self) -> None:
        conversation_id = "conversation_run_0002"
        self.store.create_or_reuse(conversation_id)

        with self.assertRaisesRegex(ValueError, "client request id is invalid"):
            self.store.write_run(
                conversation_id,
                status="running",
                run_id="a" * 32,
                client_request_id="not-a-canonical-uuid",
            )

    def test_token_usage_replaces_same_attempt_and_accumulates_retries(self) -> None:
        conversation_id = "conversation_usage_001"
        first_run = "a" * 32
        second_run = "b" * 32
        self.store.create_or_reuse(conversation_id)
        self.store.begin_token_usage_run(conversation_id, first_run)

        first, changed = self.store.record_token_usage(
            conversation_id,
            run_id=first_run,
            session_id="root-session",
            event_seq=1,
            turn=1,
            step=1,
            attempt=0,
            buckets={
                "uncached_input_tokens": 10,
                "output_tokens": 2,
                "reasoning_tokens": 2,
                "cache_read_tokens": 3,
                "cache_write_tokens": 0,
            },
        )
        self.assertTrue(changed)
        self.assertEqual(10, first["totals"]["uncached_input_tokens"])

        finalized, changed = self.store.record_token_usage(
            conversation_id,
            run_id=first_run,
            session_id="root-session",
            event_seq=2,
            turn=1,
            step=1,
            attempt=0,
            buckets={
                "uncached_input_tokens": 12,
                "output_tokens": 5,
                "reasoning_tokens": 4,
                "cache_read_tokens": 7,
                "cache_write_tokens": 1,
            },
        )
        self.assertTrue(changed)
        self.assertEqual(
            {
                "uncached_input_tokens": 12,
                "output_tokens": 5,
                "reasoning_tokens": 4,
                "cache_read_tokens": 7,
                "cache_write_tokens": 1,
            },
            finalized["totals"],
        )

        child_buckets = {
            "uncached_input_tokens": 8,
            "output_tokens": 3,
            "reasoning_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        self.store.record_token_usage(
            conversation_id,
            run_id=first_run,
            session_id="child-session",
            event_seq=1,
            turn=1,
            step=1,
            attempt=0,
            buckets=child_buckets,
        )
        retry_buckets = {
            "uncached_input_tokens": 4,
            "output_tokens": 1,
            "reasoning_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        retried, changed = self.store.record_token_usage(
            conversation_id,
            run_id=first_run,
            session_id="root-session",
            event_seq=4,
            turn=1,
            step=1,
            attempt=1,
            buckets=retry_buckets,
        )
        self.assertTrue(changed)
        self.assertEqual(24, retried["totals"]["uncached_input_tokens"])
        self.assertEqual(9, retried["totals"]["output_tokens"])
        repeated, changed = self.store.record_token_usage(
            conversation_id,
            run_id=first_run,
            session_id="root-session",
            event_seq=4,
            turn=1,
            step=1,
            attempt=1,
            buckets={**retry_buckets, "output_tokens": 999},
        )
        self.assertFalse(changed)
        self.assertEqual(retried["totals"], repeated["totals"])

        self.store.begin_token_usage_run(conversation_id, second_run)
        second, _changed = self.store.record_token_usage(
            conversation_id,
            run_id=second_run,
            session_id="root-session",
            event_seq=1,
            turn=1,
            step=1,
            attempt=0,
            buckets={
                "uncached_input_tokens": 2,
                "output_tokens": 1,
                "reasoning_tokens": 1,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
        )
        self.assertEqual(26, second["totals"]["uncached_input_tokens"])
        self.assertEqual(10, second["totals"]["output_tokens"])

        reopened = ConversationStore(self.store.root).read_token_usage(conversation_id)
        self.assertEqual(second["totals"], reopened["totals"])
        self.assertEqual(second_run, reopened["active_run_id"])

    def test_legacy_conversation_without_usage_file_reads_as_zero(self) -> None:
        conversation_id = "conversation_usage_old"
        self.store.create_or_reuse(conversation_id)
        self.store.require(conversation_id).usage.unlink()

        usage = self.store.read_token_usage(conversation_id)

        self.assertEqual(
            {
                "uncached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
            usage["totals"],
        )
        self.assertIsNone(usage["updated_at"])

    def test_identifier_cannot_escape_root(self) -> None:
        with self.assertRaises(InvalidIdentifier):
            self.store.create_or_reuse("../../outside")

    def test_list_conversations_is_sorted_safe_and_skips_damaged_entries(self) -> None:
        older_id = "conversation_older_001"
        newer_id = "conversation_newer_001"
        damaged_id = "conversation_broken_01"
        self.store.create_or_reuse(older_id)
        self.store.append_message(older_id, role="user", content="  First\nproject  ")
        self.store.append_message(
            older_id,
            role="assistant",
            content="Latest assistant summary",
            metadata={"private_session": "must-not-leak"},
        )
        self.store.create_or_reuse(newer_id)

        older_meta = self.store.read_meta(older_id)
        older_meta.update(
            created_at="2026-01-01T00:00:00.000Z",
            updated_at="2026-01-02T00:00:00.000Z",
            private_metadata="must-not-leak",
        )
        self.store._atomic_json(self.store.require(older_id).meta, older_meta)
        newer_meta = self.store.read_meta(newer_id)
        newer_meta.update(
            created_at="2026-01-03T00:00:00.000Z",
            updated_at="2026-01-04T00:00:00.000Z",
        )
        self.store._atomic_json(self.store.require(newer_id).meta, newer_meta)

        self.store.create_or_reuse(damaged_id)
        self.store.require(damaged_id).messages.write_text("{not-json\n", encoding="utf-8")
        (self.store.root / "not-a-conversation").mkdir()
        (self.store.root / "conversation_file_001").write_text("ignored", encoding="utf-8")

        summaries = self.store.list_conversations()

        self.assertEqual([newer_id, older_id], [item["id"] for item in summaries])
        self.assertEqual(
            {
                "id",
                "project_id",
                "created_at",
                "updated_at",
                "title",
                "preview",
                "message_count",
            },
            set(summaries[0]),
        )
        self.assertEqual("新对话", summaries[0]["title"])
        self.assertEqual("", summaries[0]["preview"])
        self.assertEqual(0, summaries[0]["message_count"])
        self.assertEqual("First project", summaries[1]["title"])
        self.assertEqual("Latest assistant summary", summaries[1]["preview"])
        self.assertEqual(2, summaries[1]["message_count"])
        self.assertNotIn("must-not-leak", json.dumps(summaries))

    def test_projects_group_child_conversations_and_preserve_isolation(self) -> None:
        project_id, first = self.store.create_project(
            "project_group_0001",
            requested_conversation_id="conversation_child_01",
        )
        second, created = self.store.create_conversation_in_project(
            project_id,
            "conversation_child_02",
        )
        self.assertTrue(created)
        self.assertEqual(project_id, first["project_id"])
        self.assertEqual(project_id, second["project_id"])

        self.store.append_message(first["id"], role="user", content="项目总体研究")
        self.store.append_message(second["id"], role="user", content="项目内第二条对话")
        first_paths = self.store.require(first["id"])
        second_paths = self.store.require(second["id"])
        (first_paths.outputs / "first.md").write_text("first", encoding="utf-8")
        self.assertEqual([], [item for item in self.store.list_files(second["id"]) if item["kind"] == "output"])
        self.assertNotEqual(first_paths.workspace, second_paths.workspace)

        projects = self.store.list_projects()
        self.assertEqual(1, len(projects))
        self.assertEqual(project_id, projects[0]["id"])
        self.assertEqual("项目总体研究", projects[0]["title"])
        self.assertEqual(2, projects[0]["conversation_count"])
        self.assertEqual(
            {first["id"], second["id"]},
            {item["id"] for item in projects[0]["conversations"]},
        )

    def test_legacy_conversation_becomes_one_project_without_read_time_write(self) -> None:
        conversation_id = "conversation_legacy_01"
        self.store.create_or_reuse(conversation_id)
        paths = self.store.require(conversation_id)
        metadata = json.loads(paths.meta.read_text(encoding="utf-8"))
        metadata.pop("project_id")
        self.store._atomic_json(paths.meta, metadata)
        before = paths.meta.read_bytes()

        self.assertEqual(conversation_id, self.store.read_meta(conversation_id)["project_id"])
        projects = self.store.list_projects()
        self.assertEqual(conversation_id, projects[0]["id"])
        self.assertEqual([conversation_id], [item["id"] for item in projects[0]["conversations"]])
        self.assertEqual(before, paths.meta.read_bytes())

    def test_project_membership_conflict_and_missing_project_are_rejected(self) -> None:
        project_id, first = self.store.create_project(
            "project_conflict_01",
            requested_conversation_id="conversation_conflict1",
        )
        with self.assertRaises(ProjectConflict):
            self.store.create_or_reuse(first["id"], project_id="project_conflict_02")
        with self.assertRaises(ProjectNotFound):
            self.store.create_conversation_in_project(
                "project_missing_001",
                "conversation_missing1",
            )
        self.assertTrue(self.store.project_exists(project_id))

    def test_list_conversations_rejects_symlinked_message_log(self) -> None:
        conversation_id = "conversation_symlink_01"
        self.store.create_or_reuse(conversation_id)
        paths = self.store.require(conversation_id)
        external = Path(self.temporary.name) / "external-messages.jsonl"
        external.write_text(
            '{"id":"external","role":"user","content":"secret"}\n',
            encoding="utf-8",
        )
        paths.messages.unlink()
        try:
            paths.messages.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symbolic links are unavailable: {exc}")

        self.assertEqual([], self.store.list_conversations())

    def test_upload_and_generated_output_are_listed_and_resolved(self) -> None:
        self.store.create_or_reuse("conversation_123456")
        paths = self.store.require("conversation_123456")
        file_id, name, target = self.store.allocate_upload(
            "conversation_123456", "../../户型图.png"
        )
        target.write_bytes(b"png")
        uploaded = self.store.register_upload(
            "conversation_123456",
            file_id=file_id,
            original_name=name,
            stored_path=target,
            size=3,
            content_type="image/png",
        )
        self.assertEqual("户型图.png", uploaded["name"])

        report = paths.outputs / "report.txt"
        report.write_text("done", encoding="utf-8")
        items = self.store.list_files("conversation_123456")
        self.assertEqual({"input", "output"}, {item["kind"] for item in items})
        output = next(item for item in items if item["kind"] == "output")
        resolved, _ = self.store.resolve_file("conversation_123456", output["id"])
        self.assertEqual(report.resolve(), resolved)

    def test_filename_sanitization(self) -> None:
        self.assertEqual("passwd", sanitize_filename("../../passwd"))
        self.assertEqual("upload.bin", sanitize_filename("..."))

    def test_outputs_root_symlink_is_rejected_before_enumeration(self) -> None:
        self.store.create_or_reuse("conversation_123456")
        paths = self.store.require("conversation_123456")
        external = Path(self.temporary.name) / "external"
        external.mkdir()
        (external / "secret-name.txt").write_text("secret", encoding="utf-8")
        paths.outputs.rmdir()
        try:
            paths.outputs.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symbolic links are unavailable: {exc}")
        with self.assertRaises(StorageError):
            self.store.list_files("conversation_123456")


if __name__ == "__main__":
    unittest.main()
