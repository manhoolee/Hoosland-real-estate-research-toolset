from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import Settings
from app.harness_adapter import (
    HarnessAdapterError,
    HarnessFollowup,
    HarnessRunResult,
    SKILL_COMMAND,
    harness_session_id,
)
from app.main import (
    _completed_conversation_history,
    _new_or_updated_output_formats,
    _session_generation_for_run,
    create_app,
)


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.settings = Settings.from_env(
            {
                "DATA_DIR": str(self.root / "data"),
                "FRONTEND_DIST": str(self.root / "missing-frontend"),
                "ADMIN_PASSWORD": "admin-password",
                "ADMIN_SESSION_SECRET": "a" * 48,
                "DEEPSEEK_API_KEY": "main-secret",
                "HARNESS_ENABLED": "false",
            },
            root_dir=self.root,
        )
        self.app = create_app(self.settings)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_session_generation_for_run_is_scoped_and_canonical(self) -> None:
        conversation_id = "conversation-123"
        run_id = "a" * 32
        self.assertEqual(
            0,
            _session_generation_for_run(
                harness_session_id(conversation_id, run_id, 0),
                conversation_id=conversation_id,
                run_id=run_id,
            ),
        )
        self.assertEqual(
            7,
            _session_generation_for_run(
                harness_session_id(conversation_id, run_id, 7),
                conversation_id=conversation_id,
                run_id=run_id,
            ),
        )
        for invalid in (
            harness_session_id("other-conversation", run_id, 1),
            harness_session_id(conversation_id, "b" * 32, 1),
            f"web-{conversation_id}-g01-r{run_id}",
            f"web-{conversation_id}-g-1-r{run_id}",
            f"web-{conversation_id}-g1-r{run_id}extra",
            "not-a-harness-session",
            None,
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(
                    _session_generation_for_run(
                        invalid,
                        conversation_id=conversation_id,
                        run_id=run_id,
                    )
                )

    @staticmethod
    def _completed_checklist_run(run: object) -> object:
        """Adapt legacy fake Harness runs to the native v0.1.1rc1 todo contract."""

        async def wrapped(
            conversation_id: str,
            prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            expected_session_id = harness_session_id(
                conversation_id,
                run_id,
                session_generation,
            )

            def observe(notification: object) -> None:
                on_notification(notification)

            def emit(seq: int, first_status: str, reply_status: str) -> None:
                observe(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": expected_session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "time": seq,
                                "data": {
                                    "todos": [
                                        {
                                            "content": "任务｜完成测试研究",
                                            "status": first_status,
                                        },
                                        {
                                            "content": "成果回复｜返回测试结论",
                                            "status": reply_status,
                                        },
                                    ]
                                },
                            },
                        },
                    }
                )

            emit(1, "in_progress", "pending")
            result = await run(
                conversation_id,
                prompt,
                observe,
                run_id=run_id,
                session_generation=session_generation,
            )
            emit(2, "completed", "in_progress")
            emit(3, "completed", "completed")
            return result

        return wrapped

    def test_run_output_format_audit_ignores_unchanged_old_files(self) -> None:
        baseline = {"report.html": (100, 1)}
        current = {
            "report.html": (100, 1),
            "report.md": (200, 2),
            "empty.pdf": (0, 3),
        }

        self.assertEqual(
            ["md"],
            _new_or_updated_output_formats(baseline, current),
        )

    def test_admin_config_hides_keys_and_requires_same_origin(self) -> None:
        denied = self.client.post(
            "/api/admin/login",
            json={"password": "admin-password"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(403, denied.status_code)

        logged_in = self.client.post(
            "/api/admin/login",
            json={"password": "admin-password"},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(200, logged_in.status_code)
        config = self.client.get("/api/admin/config")
        self.assertEqual(200, config.status_code)
        self.assertTrue(config.json()["main_agent"]["api_key_set"])
        self.assertNotIn("main-secret", config.text)

        updated = self.client.put(
            "/api/admin/config",
            json={"main_agent": {"model": "next-model"}},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(200, updated.status_code)
        self.assertEqual("next-model", updated.json()["main_agent"]["model"])
        self.assertTrue(updated.json()["main_agent"]["api_key_set"])

    def test_operation_log_records_lifecycle_without_private_content(self) -> None:
        # Include an explicit project action so this lifecycle/logging fixture
        # exercises the accepted path now that unknown opaque strings are
        # fail-closed by the ingress policy.
        message_marker = "请处理项目资料 PRIVATE-MESSAGE-7f69dfef"
        password_marker = "PRIVATE-PASSWORD-2c725f1b"
        path_marker = "PRIVATE-PATH-e70ebcbd"

        denied = self.client.post(
            "/api/admin/login",
            json={"password": password_marker},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(401, denied.status_code)
        created = self.client.post("/api/conversations", json={}).json()
        conversation_id = created["id"]
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": message_marker, "attachment_ids": []},
            headers={"X-Request-Id": "request-safe-123"},
        )
        self.assertEqual(200, response.status_code)
        unknown = self.client.get(f"/api/{path_marker}")
        self.assertEqual(404, unknown.status_code)

        raw = self.settings.operation_log_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in raw.splitlines() if line]
        self.assertNotIn(message_marker, raw)
        self.assertNotIn(password_marker, raw)
        self.assertNotIn(path_marker, raw)
        self.assertNotIn("main-secret", raw)
        self.assertTrue(
            any(
                item["event"] == "agent.run.accepted"
                and item["conversation_id"] == conversation_id
                and item["content_characters"] == len(message_marker)
                for item in records
            )
        )
        self.assertTrue(
            any(
                item["event"] == "agent.controller.injection.prepared"
                and item["conversation_id"] == conversation_id
                and item["skill_id"] == "comprehensive-real-estate-expert"
                for item in records
            )
        )
        terminal = [
            item
            for item in records
            if item["event"] == "agent.run.completed"
            and item["conversation_id"] == conversation_id
        ]
        self.assertEqual(1, len(terminal))
        self.assertEqual("AGENT_DISABLED", terminal[0]["error_code"])
        self.assertTrue(
            any(
                item["event"] == "http.request"
                and item["route"] == "/api/{unmatched}"
                for item in records
            )
        )

    def test_mcp_operation_log_excludes_tool_arguments_and_results(self) -> None:
        argument_marker = "PRIVATE-MCP-ARGUMENT-c6549550"
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        token = self.app.state.mcp_registry.issue(conversation_id)
        response = self.client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "web_search",
                    "arguments": {"query": argument_marker},
                },
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["result"]["isError"])

        raw = self.settings.operation_log_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in raw.splitlines() if line]
        self.assertNotIn(argument_marker, raw)
        self.assertNotIn(token, raw)
        tool_events = [
            item for item in records
            if item["event"] == "mcp.operation.completed"
            and item.get("conversation_id") == conversation_id
        ]
        self.assertEqual(1, len(tool_events))
        self.assertEqual("web_search", tool_events[0]["tool_name"])
        self.assertEqual("CAPABILITY_NOT_CONFIGURED", tool_events[0]["error_code"])

    def test_public_responses_and_message_metadata_hide_runtime_brand(self) -> None:
        created = self.client.post("/api/conversations", json={}).json()
        conversation_id = created["id"]
        self.app.state.store.append_message(
            conversation_id,
            role="assistant",
            content="Harness completed this report",
            metadata={"harness_session_id": "private-session", "reply_to": "msg"},
        )
        messages = self.client.get(f"/api/conversations/{conversation_id}/messages")
        self.assertEqual(200, messages.status_code)
        self.assertNotIn("harness", messages.text.lower())
        self.assertIn("研究助手", messages.text)
        self.assertNotIn("metadata", messages.json()["items"][0])
        self.assertNotIn("reply_to", messages.text)

        ready = self.client.get("/api/health/ready")
        capabilities = self.client.get("/api/capabilities")
        self.assertNotIn('"harness"', ready.text.lower())
        self.assertNotIn("harness", capabilities.text.lower())

    def test_public_checklist_hides_internal_prefixes_runtime_names_and_paths(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        run_id = "9" * 32
        store = self.app.state.store
        user_message = store.append_message(
            conversation_id,
            role="user",
            content="检查公开清单脱敏",
        )
        store.start_checklist(conversation_id, run_id)
        store.apply_checklist_snapshot(
            conversation_id,
            run_id=run_id,
            event_seq=1,
            todos=[
                {
                    "content": (
                        "任务｜调用 @deepseek-ai/dsh-secret 于 "
                        r"C:\Users\private\work\report.md"
                    ),
                    "status": "in_progress",
                },
                {
                    "content": "成果文件(.md)｜保存到 /tmp/private/report.md",
                    "status": "pending",
                },
                {
                    "content": "成果回复｜Cordis 最终结论",
                    "status": "pending",
                },
            ],
        )
        store.finalize_checklist(
            conversation_id,
            run_id=run_id,
            status="failed",
        )
        terminal = store.append_message(
            conversation_id,
            role="assistant",
            content="",
            status="error",
            metadata={
                "finish_reason": "failed",
                "reply_to": user_message["id"],
                "run_id": run_id,
                "public_error": "任务失败，可重试。",
            },
        )
        store.write_run(
            conversation_id,
            status="failed",
            run_id=run_id,
            user_message_id=user_message["id"],
            assistant_message_id=terminal["id"],
            error_code="INTERNAL_ERROR",
            retryable=True,
        )

        run_text = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).text
        messages_text = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).text
        public_text = run_text + messages_text
        for private_value in (
            "任务｜",
            "成果文件",
            "成果回复｜",
            "deepseek",
            "dsh-secret",
            "cordis",
            r"C:\Users\private",
            "/tmp/private",
        ):
            self.assertNotIn(private_value.lower(), public_text.lower())
        self.assertIn("[内部路径]", public_text)
        self.assertIn("（.md 文件）", public_text)
        self.assertIn("回复：研究助手 最终结论", public_text)

    def test_health_responses_expose_current_slot_and_build_identity(self) -> None:
        live = self.client.get("/api/health/live")
        self.assertEqual(200, live.status_code)
        self.assertEqual(
            {
                "ok": True,
                "version": "0.2.6",
                "slot": "slot-b",
                "build_id": "development",
            },
            live.json(),
        )

        ready = self.client.get("/api/health/ready")
        self.assertEqual(503, ready.status_code)
        self.assertEqual("0.2.6", ready.json()["version"])
        self.assertEqual("slot-b", ready.json()["slot"])
        self.assertEqual("development", ready.json()["build_id"])

    def test_conversation_list_returns_safe_sorted_summaries(self) -> None:
        older_id = "conversation_api_older"
        newer_id = "conversation_api_newer"
        self.client.post("/api/conversations", json={"id": older_id})
        self.app.state.store.append_message(
            older_id,
            role="user",
            content="Older research topic",
            metadata={"private": "do-not-return"},
        )
        self.app.state.store.append_message(
            older_id,
            role="assistant",
            content="Harness private runtime summary",
            metadata={"agent_session_id": "do-not-return"},
        )
        self.client.post("/api/conversations", json={"id": newer_id})

        older_meta = self.app.state.store.read_meta(older_id)
        older_meta["updated_at"] = "2026-01-01T00:00:00.000Z"
        self.app.state.store._atomic_json(
            self.app.state.store.require(older_id).meta,
            older_meta,
        )
        newer_meta = self.app.state.store.read_meta(newer_id)
        newer_meta["updated_at"] = "2026-01-02T00:00:00.000Z"
        self.app.state.store._atomic_json(
            self.app.state.store.require(newer_id).meta,
            newer_meta,
        )

        denied = self.client.get("/api/admin/conversations")
        self.assertEqual(401, denied.status_code)

        logged_in = self.client.post(
            "/api/admin/login",
            json={"password": "admin-password"},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(200, logged_in.status_code)
        response = self.client.get("/api/admin/conversations")

        self.assertEqual(200, response.status_code)
        items = response.json()["items"]
        self.assertEqual([newer_id, older_id], [item["id"] for item in items])
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
            set(items[0]),
        )
        self.assertEqual("Older research topic", items[1]["title"])
        self.assertEqual("研究助手 private runtime summary", items[1]["preview"])
        self.assertNotIn("metadata", response.text)
        self.assertNotIn("do-not-return", response.text)

    def test_project_and_child_conversation_api_builds_two_level_history(self) -> None:
        created = self.client.post("/api/projects", json={})
        self.assertEqual(201, created.status_code)
        project_id = created.json()["project_id"]
        first_id = created.json()["conversation"]["id"]
        self.assertEqual(project_id, created.json()["conversation"]["project_id"])

        detail = self.client.get(f"/api/conversations/{first_id}")
        self.assertEqual(200, detail.status_code)
        self.assertEqual(project_id, detail.json()["project_id"])

        child = self.client.post(f"/api/projects/{project_id}/conversations", json={})
        self.assertEqual(201, child.status_code)
        child_id = child.json()["id"]
        self.assertNotEqual(first_id, child_id)
        self.assertEqual(project_id, child.json()["project_id"])

        self.app.state.store.append_message(first_id, role="user", content="深圳项目总体研究")
        self.app.state.store.append_message(child_id, role="user", content="商业定位子对话")

        denied = self.client.get("/api/admin/projects")
        self.assertEqual(401, denied.status_code)
        logged_in = self.client.post(
            "/api/admin/login",
            json={"password": "admin-password"},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(200, logged_in.status_code)
        history = self.client.get("/api/admin/projects")
        self.assertEqual(200, history.status_code)
        project = next(item for item in history.json()["items"] if item["id"] == project_id)
        self.assertEqual("深圳项目总体研究", project["title"])
        self.assertEqual(2, project["conversation_count"])
        self.assertEqual(
            {first_id, child_id},
            {item["id"] for item in project["conversations"]},
        )
        self.assertTrue(all(item["project_id"] == project_id for item in project["conversations"]))

        raw_log = self.settings.operation_log_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in raw_log.splitlines() if line]
        self.assertTrue(
            any(
                item["event"] == "project.created"
                and item["project_id"] == project_id
                and item["conversation_id"] == first_id
                for item in records
            )
        )
        self.assertTrue(
            any(
                item["event"] == "conversation.created"
                and item["project_id"] == project_id
                and item["conversation_id"] == child_id
                for item in records
            )
        )

    def test_legacy_conversation_api_creates_standalone_project(self) -> None:
        created = self.client.post("/api/conversations", json={})
        self.assertEqual(201, created.status_code)
        self.assertEqual(created.json()["id"], created.json()["project_id"])
        missing = self.client.post(
            "/api/projects/project_missing_001/conversations",
            json={},
        )
        self.assertEqual(404, missing.status_code)

    def test_only_supported_output_files_can_open_inline(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        paths = self.app.state.store.require(conversation_id)
        report = paths.outputs / "report.html"
        report.write_text("<script>fetch('/api/admin/config')</script><h1>Report</h1>", encoding="utf-8")
        files = self.client.get(f"/api/conversations/{conversation_id}/files").json()["items"]
        output = next(item for item in files if item["kind"] == "output")
        self.assertTrue(output["open_url"].endswith("/open"))

        opened = self.client.get(output["open_url"])
        self.assertEqual(200, opened.status_code)
        self.assertIn("inline", opened.headers["content-disposition"])
        self.assertIn("sandbox", opened.headers["content-security-policy"])
        self.assertIn("script-src 'none'", opened.headers["content-security-policy"])
        self.assertEqual("same-origin", opened.headers["cross-origin-resource-policy"])

        pdf = paths.outputs / "report.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with pdf.open("wb") as handle:
            writer.write(handle)
        files = self.client.get(f"/api/conversations/{conversation_id}/files").json()["items"]
        pdf_output = next(item for item in files if item["name"] == "report.pdf")
        self.assertEqual("application/pdf", pdf_output["content_type"])
        pdf_opened = self.client.get(pdf_output["open_url"])
        self.assertEqual(200, pdf_opened.status_code)
        self.assertEqual("application/pdf", pdf_opened.headers["content-type"])
        self.assertIn("inline", pdf_opened.headers["content-disposition"])
        pdf_downloaded = self.client.get(pdf_output["download_url"])
        self.assertEqual(200, pdf_downloaded.status_code)
        self.assertIn("attachment", pdf_downloaded.headers["content-disposition"])

    def test_capabilities_always_report_pdf_runtime_readiness(self) -> None:
        response = self.client.get("/api/capabilities")
        self.assertEqual(200, response.status_code)
        pdf = next(item for item in response.json()["items"] if item["name"] == "pdf_output")
        self.assertIn(pdf["status"], {"configured", "dependency_missing"})
        self.assertIn("pypdf", pdf["python_modules"])
        self.assertIn("pdftoppm", pdf["system_commands"])

    def test_public_stream_has_milestones_not_operation_details(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        private_marker = "PRIVATE-SEARCH-QUERY-4e6bb1"
        intermediate_marker = "PRIVATE-INTERMEDIATE-TEXT-9d207a"
        output_path = self.app.state.store.require(conversation_id).outputs / "report.md"
        output_html_path = self.app.state.store.require(conversation_id).outputs / "report.html"

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/execute/start",
                            "data": {
                                "name": "web_search",
                                "arguments": {"query": private_marker},
                            },
                        }
                    },
                }
            )
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/execute/start",
                            "data": {
                                "name": "shell",
                                "arguments": {"command": "npm install private-package"},
                            },
                        }
                    },
                }
            )
            on_notification({"method": "subagent.started", "payload": {}})
            on_notification({"method": "subagent.finished", "payload": {}})
            for index in range(20):
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "event": {
                                "type": "assistant/chunk",
                                "data": {
                                    "chunk": {
                                        "type": "text-delta",
                                        "text": f"{intermediate_marker}-{index}",
                                    }
                                },
                            }
                        },
                    }
                )
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "assistant/chunk",
                            "data": {
                                "chunk": {
                                    "type": "reasoning-delta",
                                    "text": "PRIVATE-REASONING",
                                }
                            },
                        }
                    },
                }
            )
            output_path.write_text("# 项目成果", encoding="utf-8")
            output_html_path.write_text(
                "<!doctype html><html><body><h1>项目成果</h1></body></html>",
                encoding="utf-8",
            )
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/result",
                            "data": {
                                "name": "shell",
                                "result": "PRIVATE-TOOL-RESULT",
                            },
                        }
                    },
                }
            )
            await asyncio.sleep(0)
            return HarnessRunResult(
                final_response="项目结论：建议优先验证去化速度。",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "研究这个项目", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn('"type":"progress"', response.text)
        self.assertIn('"stage":"evidence"', response.text)
        self.assertIn('"stage":"analysis"', response.text)
        self.assertIn('"stage":"delivery"', response.text)
        self.assertIn("项目结论：建议优先验证去化速度。", response.text)
        for hidden in (
            private_marker,
            intermediate_marker,
            "PRIVATE-REASONING",
            "PRIVATE-TOOL-RESULT",
            "web_search",
            "shell",
            "npm install",
            "skill_id",
            "正在调用",
            "finish_reason",
        ):
            self.assertNotIn(hidden, response.text)

        raw_log = self.settings.operation_log_path.read_text(encoding="utf-8")
        self.assertNotIn(private_marker, raw_log)
        self.assertNotIn("npm install", raw_log)
        operations = [
            item
            for item in (json.loads(line) for line in raw_log.splitlines() if line)
            if item["event"] == "agent.operation"
            and item.get("conversation_id") == conversation_id
        ]
        self.assertTrue(any(item.get("tool_name") == "web_search" for item in operations))
        self.assertTrue(any(item.get("tool_name") == "shell" for item in operations))
        completed = [
            item
            for item in (json.loads(line) for line in raw_log.splitlines() if line)
            if item["event"] == "agent.run.completed"
            and item.get("conversation_id") == conversation_id
        ]
        self.assertEqual(["html", "md"], completed[-1]["run_output_formats"])
        self.assertTrue(completed[-1]["default_output_pair_present_this_run"])

    def test_output_write_outside_canonical_outputs_cannot_report_success(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def misplaced_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/call",
                            "data": {
                                "name": "write",
                                "arguments": json.dumps(
                                    {
                                        "file_path": "/tmp/web/outputs/report.md",
                                        "content": "private report",
                                    }
                                ),
                            },
                        }
                    },
                }
            )
            return HarnessRunResult(
                final_response="错误地声称文件已交付",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(misplaced_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "生成正式报告", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("本轮研究暂未完成", response.text)
        self.assertNotIn("错误地声称文件已交付", response.text)
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual("failed", run["status"])
        self.assertTrue(run["retryable"])
        self.assertEqual(
            [],
            self.client.get(
                f"/api/conversations/{conversation_id}/files"
            ).json()["items"],
        )
        records = [
            json.loads(line)
            for line in self.settings.operation_log_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        rejected = [
            item
            for item in records
            if item.get("event") == "agent.output.persistence_rejected"
            and item.get("conversation_id") == conversation_id
        ]
        self.assertEqual(1, len(rejected))
        self.assertEqual("AGENT_OUTPUT_NOT_PERSISTED", rejected[0]["error_code"])
        self.assertEqual(1, rejected[0]["misplaced_output_write_attempt_count"])
        self.assertNotIn("/tmp/web", json.dumps(rejected))

    def test_every_attempted_output_target_must_be_persisted_before_success(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        paths = self.app.state.store.require(conversation_id)

        async def incomplete_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            for file_path in ("outputs/kept.md", "/tmp/web/outputs/missing.md"):
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "event": {
                                "type": "tool/call",
                                "data": {
                                    "name": "write",
                                    "arguments": {
                                        "file_path": file_path,
                                        "content": "report",
                                    },
                                },
                            }
                        },
                    }
                )
            paths.outputs.joinpath("kept.md").write_text(
                "# report",
                encoding="utf-8",
            )
            return HarnessRunResult(
                final_response="不完整交付",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(incomplete_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "生成双格式正式报告", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("本轮研究暂未完成", response.text)
        self.assertEqual(
            "failed",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )

    def test_zero_byte_canonical_output_cannot_report_success(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        paths = self.app.state.store.require(conversation_id)

        async def empty_output_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/call",
                            "data": {
                                "name": "write",
                                "arguments": {
                                    "file_path": "outputs/empty.md",
                                    "content": "",
                                },
                            },
                        }
                    },
                }
            )
            paths.outputs.joinpath("empty.md").write_bytes(b"")
            return HarnessRunResult(
                final_response="空文件也声称完成",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(empty_output_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "生成正式报告", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("本轮研究暂未完成", response.text)
        self.assertNotIn("空文件也声称完成", response.text)
        self.assertEqual(
            "failed",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )

    def test_truncating_existing_output_to_zero_bytes_cannot_report_success(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        paths = self.app.state.store.require(conversation_id)
        output_path = paths.outputs.joinpath("report.md")
        output_path.write_text("# previous report", encoding="utf-8")

        async def truncated_output_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/call",
                            "data": {
                                "name": "edit",
                                "arguments": {
                                    "file_path": "outputs/report.md",
                                    "old_string": "# previous report",
                                    "new_string": "",
                                },
                            },
                        }
                    },
                }
            )
            output_path.write_bytes(b"")
            return HarnessRunResult(
                final_response="截空旧文件也声称完成",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(truncated_output_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "更新现有报告", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("本轮研究暂未完成", response.text)
        self.assertNotIn("截空旧文件也声称完成", response.text)
        self.assertEqual(
            "failed",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )

    def test_file_delivery_skill_without_persisted_output_cannot_succeed(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def missing_delivery_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "event": {
                            "type": "tool/call",
                            "data": {
                                "name": "skill",
                                "arguments": json.dumps(
                                    {"name": "hoosland-pdf-output"}
                                ),
                            },
                        }
                    },
                }
            )
            return HarnessRunResult(
                final_response="没有文件却声称完成",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(missing_delivery_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "生成正式报告", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("本轮研究暂未完成", response.text)
        self.assertNotIn("没有文件却声称完成", response.text)
        self.assertEqual(
            "failed",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )

    def test_advisory_skills_may_return_inline_text_without_an_output_file(self) -> None:
        for skill_id, request_text in (
            (
                "real-estate-report-editorial",
                "只在聊天中润色这段文字，不要生成文件",
            ),
            (
                "real-estate-report-design",
                "只在聊天中点评这份报告的版式，不要生成文件",
            ),
        ):
            with self.subTest(skill_id=skill_id):
                conversation_id = self.client.post(
                    "/api/conversations",
                    json={},
                ).json()["id"]

                async def inline_advisory_run(
                    _conversation_id: str,
                    _prompt: str,
                    on_notification: object,
                    *,
                    run_id: str,
                    session_generation: int = 0,
                ) -> HarnessRunResult:
                    del run_id, session_generation
                    on_notification(
                        {
                            "method": "session.event",
                            "payload": {
                                "event": {
                                    "type": "tool/call",
                                    "data": {
                                        "name": "skill",
                                        "arguments": json.dumps({"name": skill_id}),
                                    },
                                }
                            },
                        }
                    )
                    return HarnessRunResult(
                        final_response="只在聊天中返回的建议",
                        finish_reason="stop",
                        session_id=f"web-{conversation_id}",
                    )

                self.app.state.harness.run = self._completed_checklist_run(
                    inline_advisory_run
                )
                response = self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={"content": request_text, "attachment_ids": []},
                )

                self.assertEqual(200, response.status_code)
                self.assertIn("只在聊天中返回的建议", response.text)
                self.assertEqual(
                    "succeeded",
                    self.client.get(
                        f"/api/conversations/{conversation_id}/run"
                    ).json()["status"],
                )
                self.assertEqual(
                    [],
                    self.client.get(
                        f"/api/conversations/{conversation_id}/files"
                    ).json()["items"],
                )

    def test_canonical_output_write_attempt_succeeds_and_prompt_names_workspace(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        paths = self.app.state.store.require(conversation_id)
        captured_prompt = ""

        async def persisted_run(
            _conversation_id: str,
            prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            nonlocal captured_prompt
            del run_id, session_generation
            captured_prompt = prompt
            for name, content in (
                ("report.md", "# report"),
                ("report.html", "<!doctype html><html><body>report</body></html>"),
            ):
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "event": {
                                "type": "tool/call",
                                "data": {
                                    "name": "write",
                                    "arguments": json.dumps(
                                        {
                                            "file_path": f"outputs/{name}",
                                            "content": content,
                                        }
                                    ),
                                },
                            }
                        },
                    }
                )
                paths.outputs.joinpath(name).write_text(content, encoding="utf-8")
            return HarnessRunResult(
                final_response="已完成并持久化",
                finish_reason="stop",
                session_id=f"web-{conversation_id}",
            )

        self.app.state.harness.run = self._completed_checklist_run(persisted_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "生成正式报告", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("已完成并持久化", response.text)
        self.assertEqual(
            "succeeded",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )
        self.assertIn(f"会话工作区：{paths.workspace.resolve()}", captured_prompt)
        self.assertIn("/tmp/**/outputs", captured_prompt)
        files = self.client.get(
            f"/api/conversations/{conversation_id}/files"
        ).json()["items"]
        self.assertEqual({"report.html", "report.md"}, {item["name"] for item in files})

    def test_checklist_stream_refresh_and_terminal_format_verification(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        output_path = self.app.state.store.require(conversation_id).outputs / "report.md"

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            session_id = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )
            contents = [
                "任务｜核验项目数据",
                "成果文件(.md)｜研究报告",
                "成果文件(.html)｜可视化报告",
                "成果回复｜结论摘要",
            ]

            def emit(seq: int, statuses: list[str]) -> None:
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "time": 123 + seq,
                                "data": {
                                    "todos": [
                                        {"content": content, "status": status}
                                        for content, status in zip(
                                            contents,
                                            statuses,
                                            strict=True,
                                        )
                                    ]
                                },
                            },
                        },
                    }
                )

            emit(1, ["in_progress", "pending", "pending", "pending"])
            output_path.write_text("# 已核验报告", encoding="utf-8")
            emit(2, ["completed", "in_progress", "pending", "pending"])
            emit(3, ["completed", "completed", "in_progress", "pending"])
            emit(4, ["completed", "completed", "completed", "in_progress"])
            emit(5, ["completed", "completed", "completed", "completed"])
            await asyncio.sleep(0)
            return HarnessRunResult(
                final_response="结论摘要已完成。",
                finish_reason="stop",
                session_id=session_id,
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请研究并输出报告", "attachment_ids": []},
        )
        self.assertEqual(200, response.status_code)
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        checklist_events = [event for event in events if event.get("type") == "checklist"]
        self.assertGreaterEqual(len(checklist_events), 4)
        self.assertEqual("planning", checklist_events[0]["checklist"]["phase"])
        terminal = checklist_events[-1]["checklist"]
        self.assertEqual(
            {"version", "revision", "phase", "updated_at", "tasks", "deliverables"},
            set(terminal),
        )
        self.assertEqual("succeeded", terminal["phase"])
        self.assertEqual("completed", terminal["tasks"][0]["status"])
        self.assertEqual("核验项目数据", terminal["tasks"][0]["text"])
        deliverables = {item["text"]: item for item in terminal["deliverables"]}
        self.assertEqual(
            "completed",
            deliverables["研究报告（.md 文件）"]["status"],
        )
        self.assertEqual(
            "已检测到本轮新增或更新的 .md 成果",
            deliverables["研究报告（.md 文件）"]["detail"],
        )
        self.assertEqual(
            "incomplete",
            deliverables["可视化报告（.html 文件）"]["status"],
        )
        self.assertEqual(
            "未检测到本轮新增或更新的 .html 成果",
            deliverables["可视化报告（.html 文件）"]["detail"],
        )
        self.assertEqual(
            "completed",
            deliverables["回复：结论摘要"]["status"],
        )
        terminal_index = max(
            index
            for index, event in enumerate(events)
            if event.get("type") == "checklist"
        )
        final_index = next(
            index for index, event in enumerate(events) if event.get("type") == "final"
        )
        self.assertLess(terminal_index, final_index)

        refreshed_run = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        self.assertEqual(terminal, refreshed_run["checklist"])
        refreshed_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        assistant = next(item for item in refreshed_messages if item["role"] == "assistant")
        self.assertEqual(terminal, assistant["checklist"])
        run_id = self.app.state.store.read_run(conversation_id)["run_id"]
        sidecar = self.app.state.store.require(conversation_id).checklists / f"{run_id}.json"
        self.assertTrue(sidecar.is_file())
        self.assertNotIn("checklist", self.app.state.store.read_run(conversation_id))

    def test_missing_checklist_is_rejected_before_success_and_assistant_completion(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response="这段回复不能绕过清单门禁。",
                finish_reason="stop",
                session_id="fake-session",
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并验证无清单运行", "attachment_ids": []},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        error_index = next(
            index for index, event in enumerate(events) if event.get("type") == "error"
        )
        terminal_checklist_index = max(
            index
            for index, event in enumerate(events)
            if event.get("type") == "checklist"
        )
        self.assertLess(terminal_checklist_index, error_index)
        self.assertEqual("AGENT_CHECKLIST_MISSING", events[error_index]["code"])
        self.assertEqual(
            "failed",
            events[terminal_checklist_index]["checklist"]["phase"],
        )
        self.assertNotIn("这段回复不能绕过清单门禁。", response.text)
        stored = self.app.state.store.list_messages(conversation_id)
        assistant = next(item for item in stored if item["role"] == "assistant")
        self.assertEqual("error", assistant["status"])
        self.assertEqual("", assistant["content"])
        self.assertEqual(
            "failed",
            self.app.state.store.read_run(conversation_id)["status"],
        )

    def test_pre_checklist_substantive_operation_rejects_otherwise_valid_run(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        private_marker = "PRIVATE-PRE-CHECKLIST-OPERATION-93d2"

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            session_id = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "sessionId": session_id,
                        "event": {
                            "type": "tool/call",
                            "seq": 1,
                            "data": {
                                "name": "web_search",
                                "arguments": {"query": private_marker},
                            },
                        },
                    },
                }
            )
            contents = ["任务｜先列清单再研究", "成果回复｜研究结论"]
            for seq, statuses in enumerate(
                (
                    ("in_progress", "pending"),
                    ("completed", "in_progress"),
                    ("completed", "completed"),
                ),
                start=2,
            ):
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "data": {
                                    "todos": [
                                        {"content": content, "status": status}
                                        for content, status in zip(
                                            contents,
                                            statuses,
                                            strict=True,
                                        )
                                    ]
                                },
                            },
                        },
                    }
                )
            return HarnessRunResult(
                final_response="不得绕过首动作门禁",
                finish_reason="stop",
                session_id=session_id,
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并验证先搜索后补清单", "attachment_ids": []},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        error_index = next(
            index for index, event in enumerate(events) if event.get("type") == "error"
        )
        checklist_index = max(
            index for index, event in enumerate(events) if event.get("type") == "checklist"
        )
        self.assertEqual("AGENT_CHECKLIST_MISSING", events[error_index]["code"])
        self.assertLess(checklist_index, error_index)
        self.assertEqual("failed", events[checklist_index]["checklist"]["phase"])
        self.assertFalse(any(event.get("type") == "final" for event in events))
        raw_log = self.settings.operation_log_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in raw_log.splitlines() if line]
        violation = next(
            item
            for item in records
            if item.get("event") == "agent.checklist.order_violation"
        )
        self.assertTrue(violation["checklist_order_violation"])
        self.assertEqual(1, violation["operation_count"])
        self.assertNotIn(private_marker, raw_log)

    def test_todo_write_tool_call_is_not_a_pre_checklist_order_violation(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            session_id = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )
            on_notification(
                {
                    "method": "session.event",
                    "payload": {
                        "sessionId": session_id,
                        "event": {
                            "type": "tool/call",
                            "seq": 1,
                            "data": {
                                "name": "todo_write",
                                "arguments": {"todos": "private-call-arguments"},
                            },
                        },
                    },
                }
            )
            contents = ["任务｜执行研究", "成果回复｜研究结论"]
            for seq, statuses in enumerate(
                (
                    ("in_progress", "pending"),
                    ("completed", "in_progress"),
                    ("completed", "completed"),
                ),
                start=2,
            ):
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "data": {
                                    "todos": [
                                        {"content": content, "status": status}
                                        for content, status in zip(
                                            contents,
                                            statuses,
                                            strict=True,
                                        )
                                    ]
                                },
                            },
                        },
                    }
                )
            return HarnessRunResult(
                final_response="首个工具调用仅为清单自身",
                finish_reason="stop",
                session_id=session_id,
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并验证合法首清单", "attachment_ids": []},
        )
        self.assertIn('"type":"final"', response.text)
        self.assertNotIn("AGENT_CHECKLIST_MISSING", response.text)
        self.assertEqual(
            "succeeded",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )

    def test_checklist_state_machine_rejects_completion_shortcuts(self) -> None:
        cases = {
            "initial_completed": (
                "AGENT_CHECKLIST_RECOVERY_FAILED",
                ("completed", "completed"),
            ),
            "batch_completed": (
                "AGENT_CHECKLIST_MISSING",
                ("in_progress", "pending"),
                ("completed", "completed"),
            ),
            "no_post_initial_completion": (
                "AGENT_CHECKLIST_MISSING",
                ("pending", "pending"),
                ("pending", "pending"),
            ),
        }
        for case_name, case in cases.items():
            with self.subTest(case=case_name):
                expected_error, *snapshots = case
                conversation_id = self.client.post(
                    "/api/conversations",
                    json={},
                ).json()["id"]

                async def fake_run(
                    current_conversation_id: str,
                    _prompt: str,
                    on_notification: object,
                    *,
                    run_id: str,
                    session_generation: int = 0,
                    current_snapshots: tuple[tuple[str, str], ...] = snapshots,
                ) -> HarnessRunResult:
                    session_id = harness_session_id(
                        current_conversation_id,
                        run_id,
                        session_generation,
                    )
                    contents = ["任务｜逐项研究", "成果回复｜逐项结论"]
                    for seq, statuses in enumerate(current_snapshots, start=1):
                        on_notification(
                            {
                                "method": "session.event",
                                "payload": {
                                    "sessionId": session_id,
                                    "event": {
                                        "type": "todo/write",
                                        "seq": seq,
                                        "data": {
                                            "todos": [
                                                {
                                                    "content": content,
                                                    "status": status,
                                                }
                                                for content, status in zip(
                                                    contents,
                                                    statuses,
                                                    strict=True,
                                                )
                                            ]
                                        },
                                    },
                                },
                            }
                        )
                    return HarnessRunResult(
                        final_response="快捷完成不得通过",
                        finish_reason="stop",
                        session_id=session_id,
                    )

                self.app.state.harness.run = fake_run
                response = self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={"content": f"请分析项目并验证 {case_name}", "attachment_ids": []},
                )
                events = [
                    json.loads(line.removeprefix("data: "))
                    for line in response.text.splitlines()
                    if line.startswith("data: ")
                ]
                error = next(event for event in events if event.get("type") == "error")
                self.assertEqual(expected_error, error["code"])
                self.assertFalse(any(event.get("type") == "final" for event in events))
                terminal = [
                    event["checklist"]
                    for event in events
                    if event.get("type") == "checklist"
                ][-1]
                self.assertEqual("failed", terminal["phase"])

    def test_rejected_batch_completion_recovers_from_authoritative_snapshot(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        private_marker = "PRIVATE-CHECKLIST-REPAIR-91e2"
        received_followups: list[HarnessFollowup] = []

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            session_id = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )
            contents = [
                f"任务｜核验市场数据 {private_marker}",
                "任务｜核验竞品数据",
                "任务｜形成研究结论",
                "任务｜复核最终答复",
                "成果回复｜提交研究结论",
            ]

            def emit(seq: int, statuses: tuple[str, ...]) -> HarnessFollowup | None:
                assert callable(on_notification)
                return on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "data": {
                                    "todos": [
                                        {"content": content, "status": status}
                                        for content, status in zip(
                                            contents,
                                            statuses,
                                            strict=True,
                                        )
                                    ]
                                },
                            },
                        },
                    }
                )

            self.assertIsNone(
                emit(1, ("in_progress", "pending", "pending", "pending", "pending"))
            )
            accepted = ("completed", "in_progress", "pending", "pending", "pending")
            self.assertIsNone(emit(2, accepted))
            followup = emit(
                3,
                ("completed", "completed", "in_progress", "pending", "completed"),
            )
            self.assertIsInstance(followup, HarnessFollowup)
            assert isinstance(followup, HarnessFollowup)
            received_followups.append(followup)
            self.assertIn("服务端清单状态纠正", followup.content)
            self.assertIn('"rejection_reason":"BULK_COMPLETION"', followup.content)
            self.assertIn('"accepted_revision":2', followup.content)
            self.assertIn(private_marker, followup.content)

            self.assertIsNone(emit(4, accepted))
            self.assertIsNone(
                emit(5, ("completed", "completed", "in_progress", "pending", "pending"))
            )
            self.assertIsNone(
                emit(6, ("completed", "completed", "completed", "in_progress", "pending"))
            )
            self.assertIsNone(
                emit(7, ("completed", "completed", "completed", "completed", "in_progress"))
            )
            self.assertIsNone(
                emit(8, ("completed", "completed", "completed", "completed", "completed"))
            )
            return HarnessRunResult(
                final_response="已逐项复核并完成研究结论",
                finish_reason="stop",
                session_id=session_id,
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并测试清单状态恢复", "attachment_ids": []},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(1, len(received_followups))
        self.assertTrue(any(event.get("type") == "final" for event in events))
        self.assertFalse(any(event.get("type") == "error" for event in events))
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual("succeeded", run["status"])
        self.assertEqual("succeeded", run["checklist"]["phase"])
        public_items = run["checklist"]["tasks"] + run["checklist"]["deliverables"]
        self.assertTrue(all(item["status"] == "completed" for item in public_items))

        raw_log = self.settings.operation_log_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in raw_log.splitlines() if line]
        checklist_records = [
            record for record in records if record.get("conversation_id") == conversation_id
        ]
        self.assertNotIn(private_marker, raw_log)
        self.assertEqual(
            ["BULK_COMPLETION"],
            [
                record["rejection_reason"]
                for record in checklist_records
                if record.get("event") == "agent.checklist.rejected"
            ],
        )
        self.assertEqual(
            1,
            sum(
                record.get("event") == "agent.checklist.repair.requested"
                for record in checklist_records
            ),
        )
        self.assertEqual(
            1,
            sum(
                record.get("event") == "agent.checklist.repair.completed"
                for record in checklist_records
            ),
        )

    def test_recovery_session_accepts_reset_with_session_local_sequence(self) -> None:
        """A fresh Harness session may restart its event seq at one."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        received_followups: list[HarnessFollowup] = []

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            assert callable(on_notification)
            first_session = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )

            def emit(
                session_id: str,
                seq: int,
                statuses: tuple[str, str, str],
            ) -> object:
                return on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "time": seq,
                                "data": {
                                    "todos": [
                                        {
                                            "content": "任务｜恢复后继续研究",
                                            "status": statuses[0],
                                        },
                                        {
                                            "content": "成果回复｜提交恢复结论",
                                            "status": statuses[1],
                                        },
                                        {
                                            "content": "任务｜复核恢复结论",
                                            "status": statuses[2],
                                        },
                                    ]
                                },
                            },
                        },
                    }
                )

            self.assertIsNone(
                emit(first_session, 1, ("in_progress", "pending", "pending"))
            )
            self.assertIsNone(
                emit(first_session, 2, ("completed", "in_progress", "pending"))
            )
            followup = emit(
                first_session,
                3,
                ("completed", "completed", "completed"),
            )
            self.assertIsInstance(followup, HarnessFollowup)
            assert isinstance(followup, HarnessFollowup)
            self.assertTrue(followup.restart_session)
            received_followups.append(followup)

            # This is the only root-session event after the manager rotates the
            # runtime.  Its raw seq restarts at one, but it must still be
            # accepted as the next durable event in this run.
            recovery_session = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation + 1,
            )
            self.assertIsNone(
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": recovery_session,
                            "event": {
                                "type": "tool/call",
                                "seq": 1,
                                "data": {
                                    "callId": "todo-recovery-call",
                                    "name": "todo_write",
                                },
                            },
                        },
                    }
                )
            )
            self.assertIsNone(
                emit(recovery_session, 1, ("completed", "in_progress", "pending"))
            )
            self.assertIsNone(
                emit(recovery_session, 2, ("completed", "completed", "pending"))
            )
            self.assertIsNone(
                emit(recovery_session, 3, ("completed", "completed", "completed"))
            )
            # A late event from the disposed generation must not take the root
            # session filter back to the old runtime.
            self.assertIsNone(
                emit(first_session, 4, ("completed", "completed", "completed"))
            )
            return HarnessRunResult(
                final_response="恢复后已完成",
                finish_reason="stop",
                session_id=recovery_session,
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并测试跨会话清单恢复", "attachment_ids": []},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(1, len(received_followups))
        self.assertFalse(any(event.get("type") == "error" for event in events))
        self.assertTrue(any(event.get("type") == "final" for event in events))
        self.assertEqual(
            "succeeded",
            self.client.get(f"/api/conversations/{conversation_id}/run").json()[
                "status"
            ],
        )
        run_id = self.app.state.store.read_run(conversation_id)["run_id"]
        sidecar = self.app.state.store.read_checklist(conversation_id, run_id)
        self.assertIsNotNone(sidecar)
        assert sidecar is not None
        self.assertEqual(6, sidecar["source_seq"])
        records = [
            json.loads(line)
            for line in self.settings.operation_log_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        current = [
            record
            for record in records
            if record.get("conversation_id") == conversation_id
        ]
        self.assertEqual(
            1,
            sum(record.get("event") == "agent.checklist.repair.requested" for record in current),
        )
        self.assertEqual(
            1,
            sum(record.get("event") == "agent.checklist.repair.completed" for record in current),
        )
        self.assertFalse(
            any(record.get("event") == "agent.checklist.repair.failed" for record in current)
        )

    def test_checklist_recovery_exhaustion_fails_fast(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        followups: list[HarnessFollowup] = []

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            session_id = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )
            contents = [
                "任务｜核验数据",
                "任务｜形成结论",
                "任务｜复核结论",
                "任务｜检查最终答复",
                "成果回复｜提交结论",
            ]

            def emit(seq: int, statuses: tuple[str, ...]) -> HarnessFollowup | None:
                assert callable(on_notification)
                return on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "data": {
                                    "todos": [
                                        {"content": content, "status": status}
                                        for content, status in zip(
                                            contents,
                                            statuses,
                                            strict=True,
                                        )
                                    ]
                                },
                            },
                        },
                    }
                )

            baseline_0 = (
                "in_progress",
                "pending",
                "pending",
                "pending",
                "pending",
            )
            baseline_1 = (
                "completed",
                "in_progress",
                "pending",
                "pending",
                "pending",
            )
            baseline_2 = (
                "completed",
                "completed",
                "in_progress",
                "pending",
                "pending",
            )
            baseline_3 = (
                "completed",
                "completed",
                "completed",
                "in_progress",
                "pending",
            )
            repair_cycles = (
                (
                    2,
                    ("completed", "completed", "in_progress", "pending", "pending"),
                    3,
                    baseline_0,
                    4,
                    baseline_1,
                ),
                (
                    5,
                    ("completed", "completed", "completed", "in_progress", "pending"),
                    6,
                    baseline_1,
                    7,
                    baseline_2,
                ),
                (
                    8,
                    ("completed", "completed", "completed", "completed", "in_progress"),
                    9,
                    baseline_2,
                    10,
                    baseline_3,
                ),
            )
            self.assertIsNone(emit(1, baseline_0))
            for (
                rejected_seq,
                rejected_statuses,
                reset_seq,
                reset_statuses,
                accepted_seq,
                accepted_statuses,
            ) in repair_cycles:
                followup = emit(rejected_seq, rejected_statuses)
                self.assertIsInstance(followup, HarnessFollowup)
                assert isinstance(followup, HarnessFollowup)
                followups.append(followup)
                self.assertIsNone(emit(reset_seq, reset_statuses))
                self.assertIsNone(emit(accepted_seq, accepted_statuses))
            emit(11, ("completed", "completed", "completed", "completed", "completed"))
            raise AssertionError("the fourth rejection must abort the run")

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并测试连续忽略清单纠正", "attachment_ids": []},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        error = next(event for event in events if event.get("type") == "error")
        self.assertEqual("AGENT_CHECKLIST_RECOVERY_EXHAUSTED", error["code"])
        self.assertEqual(3, len(followups))
        self.assertFalse(any(event.get("type") == "final" for event in events))
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual("failed", run["status"])

        records = [
            json.loads(line)
            for line in self.settings.operation_log_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        checklist_records = [
            record for record in records if record.get("conversation_id") == conversation_id
        ]
        rejections = [
            record
            for record in checklist_records
            if record.get("event") == "agent.checklist.rejected"
        ]
        self.assertEqual(
            [
                "BULK_COMPLETION",
                "BULK_COMPLETION",
                "BULK_COMPLETION",
                "BULK_COMPLETION",
            ],
            [record["rejection_reason"] for record in rejections],
        )
        requested = [
            record
            for record in checklist_records
            if record.get("event") == "agent.checklist.repair.requested"
        ]
        self.assertEqual(
            [1, 2, 3],
            [record["attempt"] for record in requested],
        )
        exhausted = [
            record
            for record in checklist_records
            if record.get("event") == "agent.checklist.repair.exhausted"
        ]
        self.assertEqual(1, len(exhausted))
        self.assertEqual(3, exhausted[0]["attempt_count"])

    def test_pending_checklist_repair_cannot_be_committed_as_success(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        repair_requested = False

        async def fake_run(
            current_conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            nonlocal repair_requested
            session_id = harness_session_id(
                current_conversation_id,
                run_id,
                session_generation,
            )
            contents = [
                "任务｜核验数据",
                "任务｜形成结论",
                "成果回复｜提交结论",
            ]

            def emit(seq: int, statuses: tuple[str, ...]) -> HarnessFollowup | None:
                assert callable(on_notification)
                return on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "data": {
                                    "todos": [
                                        {"content": content, "status": status}
                                        for content, status in zip(
                                            contents,
                                            statuses,
                                            strict=True,
                                        )
                                    ]
                                },
                            },
                        },
                    }
                )

            self.assertIsNone(emit(1, ("in_progress", "pending", "pending")))
            self.assertIsNone(emit(2, ("completed", "pending", "pending")))
            followup = emit(3, ("completed", "completed", "completed"))
            self.assertIsInstance(followup, HarnessFollowup)
            repair_requested = True
            return HarnessRunResult(
                final_response="不得在未确认状态纠正时提交",
                finish_reason="stop",
                session_id=session_id,
            )

        self.app.state.harness.run = fake_run
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请分析项目并测试未确认的清单纠正", "attachment_ids": []},
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertTrue(repair_requested)
        error = next(event for event in events if event.get("type") == "error")
        self.assertEqual("AGENT_CHECKLIST_MISSING", error["code"])
        self.assertFalse(any(event.get("type") == "final" for event in events))

        records = [
            json.loads(line)
            for line in self.settings.operation_log_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        missing = next(
            record
            for record in records
            if record.get("conversation_id") == conversation_id
            and record.get("event") == "agent.checklist.missing"
        )
        self.assertTrue(missing["checklist_repair_pending"])

    def test_pending_checklist_repair_rejects_mismatch_and_other_tools(self) -> None:
        for violation in ("mismatched_todo", "other_tool"):
            with self.subTest(violation=violation):
                conversation_id = self.client.post(
                    "/api/conversations",
                    json={},
                ).json()["id"]
                followups: list[HarnessFollowup] = []

                async def fake_run(
                    current_conversation_id: str,
                    _prompt: str,
                    on_notification: object,
                    *,
                    run_id: str,
                    session_generation: int = 0,
                    current_violation: str = violation,
                ) -> HarnessRunResult:
                    session_id = harness_session_id(
                        current_conversation_id,
                        run_id,
                        session_generation,
                    )
                    contents = [
                        "任务｜核验数据",
                        "任务｜形成结论",
                        "成果回复｜提交结论",
                    ]

                    def emit_todo(
                        seq: int,
                        statuses: tuple[str, ...],
                    ) -> HarnessFollowup | None:
                        assert callable(on_notification)
                        return on_notification(
                            {
                                "method": "session.event",
                                "payload": {
                                    "sessionId": session_id,
                                    "event": {
                                        "type": "todo/write",
                                        "seq": seq,
                                        "data": {
                                            "todos": [
                                                {"content": content, "status": status}
                                                for content, status in zip(
                                                    contents,
                                                    statuses,
                                                    strict=True,
                                                )
                                            ]
                                        },
                                    },
                                },
                            }
                        )

                    self.assertIsNone(
                        emit_todo(1, ("in_progress", "pending", "pending"))
                    )
                    self.assertIsNone(
                        emit_todo(2, ("completed", "in_progress", "pending"))
                    )
                    followup = emit_todo(3, ("completed", "completed", "completed"))
                    self.assertIsInstance(followup, HarnessFollowup)
                    assert isinstance(followup, HarnessFollowup)
                    followups.append(followup)

                    if current_violation == "mismatched_todo":
                        emit_todo(4, ("completed", "completed", "in_progress"))
                    else:
                        assert callable(on_notification)
                        on_notification(
                            {
                                "method": "session.event",
                                "payload": {
                                    "sessionId": session_id,
                                    "event": {
                                        "type": "tool/call",
                                        "seq": 4,
                                        "data": {
                                            "name": "write",
                                            "arguments": {
                                                "file_path": "work/draft.md"
                                            },
                                        },
                                    },
                                },
                            }
                        )
                    raise AssertionError("the recovery violation must abort the run")

                self.app.state.harness.run = fake_run
                response = self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={"content": f"请分析项目并验证 {violation}", "attachment_ids": []},
                )
                events = [
                    json.loads(line.removeprefix("data: "))
                    for line in response.text.splitlines()
                    if line.startswith("data: ")
                ]
                error = next(
                    event for event in events if event.get("type") == "error"
                )
                self.assertEqual("AGENT_CHECKLIST_RECOVERY_FAILED", error["code"])
                self.assertEqual(1, len(followups))
                self.assertFalse(
                    any(event.get("type") == "final" for event in events)
                )

                records = [
                    json.loads(line)
                    for line in self.settings.operation_log_path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line
                ]
                current = [
                    record
                    for record in records
                    if record.get("conversation_id") == conversation_id
                ]
                self.assertEqual(
                    1,
                    sum(
                        record.get("event")
                        == "agent.checklist.repair.requested"
                        for record in current
                    ),
                )
                self.assertEqual(
                    1,
                    sum(
                        record.get("event") == "agent.checklist.repair.failed"
                        for record in current
                    ),
                )
                self.assertFalse(
                    any(
                        record.get("event") == "agent.checklist.repair.completed"
                        for record in current
                    )
                )

    def test_success_commit_failure_is_compensated_before_error_streams(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response="不应在提交失败后写入的成功回复",
                finish_reason="stop",
                session_id="fake-session",
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        store = self.app.state.store
        original_commit = store.commit_checklist_success

        def fail_commit(*_args: object, **_kwargs: object) -> object:
            raise OSError("simulated checklist commit failure")

        store.commit_checklist_success = fail_commit
        try:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "请分析项目并测试清单提交故障", "attachment_ids": []},
            )
        finally:
            store.commit_checklist_success = original_commit

        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        error_index = next(
            index for index, event in enumerate(events) if event.get("type") == "error"
        )
        terminal_index = max(
            index for index, event in enumerate(events) if event.get("type") == "checklist"
        )
        self.assertLess(terminal_index, error_index)
        self.assertEqual("failed", events[terminal_index]["checklist"]["phase"])
        self.assertFalse(
            any(
                event.get("type") == "checklist"
                and event["checklist"].get("phase") == "succeeded"
                for event in events
            )
        )
        self.assertFalse(any(event.get("type") == "final" for event in events))
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual("failed", run["status"])
        self.assertEqual("failed", run["checklist"]["phase"])
        assistants = [
            item
            for item in store.list_messages(conversation_id)
            if item["role"] == "assistant"
        ]
        self.assertEqual(["error"], [item["status"] for item in assistants])

    def test_assistant_append_failure_rechecks_success_sidecar_as_failed(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        final_response = "该成功回复必须模拟落盘失败"

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response=final_response,
                finish_reason="stop",
                session_id="fake-session",
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        store = self.app.state.store
        original_append = store.append_message

        def fail_complete_assistant(
            current_conversation_id: str,
            **kwargs: object,
        ) -> dict[str, object]:
            if kwargs.get("role") == "assistant" and kwargs.get("content") == final_response:
                raise OSError("simulated complete assistant append failure")
            return original_append(current_conversation_id, **kwargs)

        store.append_message = fail_complete_assistant
        try:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "请分析项目并测试成功回复持久化故障", "attachment_ids": []},
            )
        finally:
            store.append_message = original_append

        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertFalse(any(event.get("type") == "final" for event in events))
        self.assertFalse(
            any(
                event.get("type") == "checklist"
                and event["checklist"].get("phase") == "succeeded"
                for event in events
            )
        )
        error_index = next(
            index for index, event in enumerate(events) if event.get("type") == "error"
        )
        terminal_index = max(
            index for index, event in enumerate(events) if event.get("type") == "checklist"
        )
        self.assertLess(terminal_index, error_index)
        terminal = events[terminal_index]["checklist"]
        self.assertEqual("failed", terminal["phase"])
        self.assertEqual("incomplete", terminal["deliverables"][0]["status"])
        self.assertEqual(
            "未检测到本轮非空成果回复",
            terminal["deliverables"][0]["detail"],
        )
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual(("failed", "failed"), (run["status"], run["checklist"]["phase"]))
        assistants = [
            item
            for item in store.list_messages(conversation_id)
            if item["role"] == "assistant"
        ]
        self.assertEqual(["error"], [item["status"] for item in assistants])
        self.assertNotIn(final_response, response.text)

    def test_run_success_write_retries_without_duplicate_terminal_messages(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response="提交重试后仍只有一条成功回复",
                finish_reason="stop",
                session_id="fake-session",
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        store = self.app.state.store
        original_write_run = store.write_run
        success_writes = 0

        def fail_first_success_write(
            current_conversation_id: str,
            **kwargs: object,
        ) -> dict[str, object]:
            nonlocal success_writes
            if kwargs.get("status") == "succeeded":
                success_writes += 1
                if success_writes == 1:
                    raise OSError("simulated first succeeded run write failure")
            return original_write_run(current_conversation_id, **kwargs)

        store.write_run = fail_first_success_write
        try:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "请分析项目并测试run提交重试", "attachment_ids": []},
            )
        finally:
            store.write_run = original_write_run

        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(2, success_writes)
        self.assertTrue(any(event.get("type") == "final" for event in events))
        self.assertFalse(any(event.get("type") == "error" for event in events))
        success_index = next(
            index
            for index, event in enumerate(events)
            if event.get("type") == "checklist"
            and event["checklist"].get("phase") == "succeeded"
        )
        final_index = next(
            index for index, event in enumerate(events) if event.get("type") == "final"
        )
        self.assertLess(success_index, final_index)
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual(("succeeded", "succeeded"), (run["status"], run["checklist"]["phase"]))
        assistants = [
            item
            for item in store.list_messages(conversation_id)
            if item["role"] == "assistant"
        ]
        self.assertEqual(1, len(assistants))
        self.assertEqual("completed", assistants[0]["status"])

    def test_post_commit_audit_failure_emits_success_events_exactly_once(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response="后置审计恢复成功",
                finish_reason="stop",
                session_id="fake-session",
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        store = self.app.state.store
        original_list_files = store.list_files
        calls = 0

        def fail_first_list_files(current_conversation_id: str) -> list[dict[str, object]]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated post-commit audit failure")
            return original_list_files(current_conversation_id)

        store.list_files = fail_first_list_files
        try:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "请分析项目并测试成功事件恰好一次", "attachment_ids": []},
            )
        finally:
            store.list_files = original_list_files

        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(1, sum(event.get("type") == "final" for event in events))
        self.assertEqual(
            1,
            sum(
                event.get("type") == "checklist"
                and event["checklist"].get("phase") == "succeeded"
                for event in events
            ),
        )
        self.assertFalse(any(event.get("type") == "error" for event in events))
        assistants = [
            item
            for item in store.list_messages(conversation_id)
            if item["role"] == "assistant"
        ]
        self.assertEqual(1, len(assistants))

    def test_run_success_write_recovers_after_two_worker_failures_and_one_get_failure(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response="可由持久化成功回复恢复run终态",
                finish_reason="stop",
                session_id="fake-session",
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        store = self.app.state.store
        original_write_run = store.write_run
        success_writes = 0

        def fail_three_success_writes(
            current_conversation_id: str,
            **kwargs: object,
        ) -> dict[str, object]:
            nonlocal success_writes
            if kwargs.get("status") == "succeeded":
                success_writes += 1
                if success_writes <= 3:
                    raise OSError(f"simulated succeeded run write failure {success_writes}")
            return original_write_run(current_conversation_id, **kwargs)

        store.write_run = fail_three_success_writes
        try:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "请分析项目并测试二次恢复", "attachment_ids": []},
            )
            events = [
                json.loads(line.removeprefix("data: "))
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            self.assertTrue(
                any(
                    event.get("type") == "error"
                    and event.get("code") == "RUN_COMMIT_PENDING"
                    for event in events
                )
            )
            self.assertFalse(any(event.get("type") == "final" for event in events))
            self.assertFalse(
                any(
                    event.get("type") == "checklist"
                    and event["checklist"].get("phase") == "succeeded"
                    for event in events
                )
            )
            pending_checklist = [
                event["checklist"]
                for event in events
                if event.get("type") == "checklist"
            ][-1]
            self.assertEqual("running", pending_checklist["phase"])
            pending_messages = self.client.get(
                f"/api/conversations/{conversation_id}/messages"
            ).json()["items"]
            self.assertEqual(
                ["user"],
                [item["role"] for item in pending_messages],
            )
            self.assertNotIn(
                "可由持久化成功回复恢复run终态",
                json.dumps(pending_messages, ensure_ascii=False),
            )
            self.assertEqual(
                1,
                sum(
                    item["role"] == "assistant"
                    and item["status"] == "completed"
                    for item in store.list_messages(conversation_id)
                ),
            )
            with self.assertRaisesRegex(OSError, "failure 3"):
                self.client.get(f"/api/conversations/{conversation_id}/run")
            pending_run_id = store.read_run(conversation_id)["run_id"]
            self.assertEqual(
                pending_checklist["revision"],
                store.read_checklist(
                    conversation_id,
                    pending_run_id,
                )["revision"],
            )
            recovered = self.client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
            revision = recovered["checklist"]["revision"]
            recovered_again = self.client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
            recovered_messages = self.client.get(
                f"/api/conversations/{conversation_id}/messages"
            ).json()["items"]
        finally:
            store.write_run = original_write_run

        self.assertEqual(4, success_writes)
        self.assertEqual(("succeeded", "succeeded"), (recovered["status"], recovered["checklist"]["phase"]))
        self.assertGreater(recovered["checklist"]["revision"], pending_checklist["revision"])
        self.assertEqual(revision, recovered_again["checklist"]["revision"])
        assistants = [
            item
            for item in store.list_messages(conversation_id)
            if item["role"] == "assistant"
        ]
        self.assertEqual(1, len(assistants))
        self.assertEqual("completed", assistants[0]["status"])
        self.assertEqual(
            ["user", "assistant"],
            [item["role"] for item in recovered_messages],
        )
        self.assertEqual("complete", recovered_messages[-1]["status"])
        self.assertEqual(
            "succeeded",
            recovered_messages[-1]["checklist"]["phase"],
        )

    def test_provider_usage_streams_and_persists_by_conversation(self) -> None:
        missing = self.client.get(
            "/api/conversations/conversation_missing_000/usage"
        )
        self.assertEqual(404, missing.status_code)

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def fake_run(
            _conversation_id: str,
            _prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del session_generation
            root_session = f"root-{run_id}"

            def emit(
                session_id: str,
                event_type: str,
                seq: int,
                data: dict[str, object],
            ) -> None:
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": session_id,
                            "event": {"type": event_type, "seq": seq, "data": data},
                        },
                    }
                )

            emit(
                root_session,
                "assistant/chunk",
                1,
                {
                    "turn": 1,
                    "step": 1,
                    "chunk": {
                        "type": "usage",
                        "usage": {
                            "inputTokens": 100,
                            "outputTokens": 10,
                            "reasoningTokens": 9,
                            "cacheReadTokens": 20,
                            "cacheWriteTokens": 5,
                        },
                    },
                },
            )
            emit(
                root_session,
                "assistant/message",
                2,
                {
                    "turn": 1,
                    "step": 1,
                    "usage": {
                        "inputTokens": 110,
                        "outputTokens": 12,
                        "reasoningTokens": 10,
                        "cacheReadTokens": 25,
                        "cacheWriteTokens": 5,
                    },
                },
            )
            emit(
                f"child-{run_id}",
                "assistant/message",
                1,
                {
                    "turn": 1,
                    "step": 1,
                    "usage": {
                        "inputTokens": 30,
                        "outputTokens": 4,
                        "reasoningTokens": 2,
                        "cacheReadTokens": 2,
                    },
                },
            )
            emit(
                root_session,
                "llm/retry-started",
                3,
                {"turn": 1, "step": 1, "retry": 1},
            )
            emit(
                root_session,
                "assistant/message",
                4,
                {
                    "turn": 1,
                    "step": 1,
                    "usage": {
                        "inputTokens": 55,
                        "outputTokens": 4,
                        "reasoningTokens": 3,
                    },
                },
            )
            emit(
                root_session,
                "compaction/summary",
                5,
                {
                    "compactionId": "compact-1",
                    "usage": {
                        "inputTokens": 20,
                        "outputTokens": 2,
                        "reasoningTokens": 1,
                        "cacheReadTokens": 3,
                    },
                },
            )
            # A replayed durable event must not bill the compaction twice.
            emit(
                root_session,
                "compaction/summary",
                5,
                {
                    "compactionId": "compact-1",
                    "usage": {
                        "inputTokens": 20,
                        "outputTokens": 2,
                        "reasoningTokens": 1,
                        "cacheReadTokens": 3,
                    },
                },
            )
            await asyncio.sleep(0)
            return HarnessRunResult(
                final_response="usage complete",
                finish_reason="stop",
                session_id=root_session,
            )

        self.app.state.harness.run = self._completed_checklist_run(fake_run)
        response = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "analyze this project", "attachment_ids": []},
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("event: usage", response.text)
        self.assertIn('"total_tokens":272', response.text)
        self.assertLess(
            response.text.rfind('"type":"usage"'),
            response.text.index('"type":"final"'),
        )
        self.assertNotIn("sessionId", response.text)
        self.assertNotIn("root-", response.text)
        usage_response = self.client.get(
            f"/api/conversations/{conversation_id}/usage"
        )
        self.assertEqual(200, usage_response.status_code)
        self.assertEqual(conversation_id, usage_response.json()["conversation_id"])
        self.assertEqual(
            {
                "uncached_input_tokens": 215,
                "output_tokens": 22,
                "reasoning_tokens": 16,
                "cache_read_tokens": 30,
                "cache_write_tokens": 5,
                "total_tokens": 272,
                "updated_at": usage_response.json()["usage"]["updated_at"],
                "includes_subagents": True,
                "source": "provider_reported",
            },
            usage_response.json()["usage"],
        )
        self.assertIsNotNone(usage_response.json()["usage"]["updated_at"])

        other_conversation = self.client.post("/api/conversations", json={}).json()["id"]
        other_usage = self.client.get(
            f"/api/conversations/{other_conversation}/usage"
        ).json()["usage"]
        self.assertEqual(0, other_usage["total_tokens"])

    def test_config_generation_swap_blocks_new_agent_runs(self) -> None:
        logged_in = self.client.post(
            "/api/admin/login",
            json={"password": "admin-password"},
            headers={"Origin": "http://testserver"},
        )
        self.assertEqual(200, logged_in.status_code)
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        reset_started = threading.Event()
        release_reset = threading.Event()
        update_responses = []

        async def slow_reset() -> None:
            reset_started.set()
            await asyncio.to_thread(release_reset.wait, 2)

        self.app.state.harness.reset = slow_reset

        def update_config() -> None:
            update_responses.append(
                self.client.put(
                    "/api/admin/config",
                    json={"main_agent": {"model": "generation-two"}},
                    headers={"Origin": "http://testserver"},
                )
            )

        thread = threading.Thread(target=update_config, daemon=True)
        thread.start()
        self.assertTrue(reset_started.wait(timeout=1))
        blocked = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "start during reset", "attachment_ids": []},
        )
        self.assertEqual(409, blocked.status_code)
        self.assertIn("配置正在更新", blocked.text)
        release_reset.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(200, update_responses[0].status_code)

    def test_cancelled_run_rotates_session_and_continues_with_history(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        prior_user = self.app.state.store.append_message(
            conversation_id,
            role="user",
            content="先前已完成的问题",
        )
        self.app.state.store.append_message(
            conversation_id,
            role="assistant",
            content="先前已完成的结论",
            metadata={
                "finish_reason": "stop",
                "agent_session_id": f"web-{conversation_id}",
                "reply_to": prior_user["id"],
            },
        )
        first_started = threading.Event()
        release_first = threading.Event()
        calls: list[tuple[int, str]] = []

        async def fake_run(
            _conversation_id: str,
            prompt: str,
            on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            call_index = len(calls)
            calls.append((session_generation, prompt))
            if call_index == 0:
                root_session_id = harness_session_id(
                    _conversation_id,
                    run_id,
                    session_generation,
                )
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": root_session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": 1,
                                "time": 1,
                                "data": {
                                    "todos": [
                                        {
                                            "content": "任务｜执行待取消研究",
                                            "status": "in_progress",
                                        },
                                        {
                                            "content": "成果回复｜研究结论",
                                            "status": "pending",
                                        },
                                    ]
                                },
                            },
                        },
                    }
                )
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": f"root-{run_id}",
                            "event": {
                                "type": "assistant/chunk",
                                "seq": 1,
                                "data": {
                                    "turn": 1,
                                    "step": 1,
                                    "chunk": {
                                        "type": "usage",
                                        "usage": {
                                            "inputTokens": 21,
                                            "outputTokens": 3,
                                        },
                                    },
                                },
                            },
                        },
                    }
                )
                first_started.set()
                await asyncio.to_thread(release_first.wait, 2)
                return HarnessRunResult(
                    final_response="不应写回的旧回复",
                    finish_reason="stop",
                    session_id=f"web-{conversation_id}",
                )
            continued_session_id = harness_session_id(
                _conversation_id,
                run_id,
                session_generation,
            )
            for seq, statuses in enumerate(
                (
                    ("in_progress", "pending"),
                    ("completed", "in_progress"),
                    ("completed", "completed"),
                ),
                start=1,
            ):
                on_notification(
                    {
                        "method": "session.event",
                        "payload": {
                            "sessionId": continued_session_id,
                            "event": {
                                "type": "todo/write",
                                "seq": seq,
                                "time": seq,
                                "data": {
                                    "todos": [
                                        {
                                            "content": "任务｜继续研究",
                                            "status": statuses[0],
                                        },
                                        {
                                            "content": "成果回复｜续聊结论",
                                            "status": statuses[1],
                                        },
                                    ]
                                },
                            },
                        },
                    }
                )
            return HarnessRunResult(
                final_response="续聊成功",
                finish_reason="stop",
                session_id=continued_session_id,
            )

        async def fake_cancel(_conversation_id: str, *, run_id: str) -> bool:
            del run_id
            release_first.set()
            return True

        self.app.state.harness.run = fake_run
        self.app.state.harness.cancel = fake_cancel
        first_responses = []

        def send_first() -> None:
            first_responses.append(
                self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={"content": "这轮需要被取消", "attachment_ids": []},
                )
            )

        thread = threading.Thread(target=send_first, daemon=True)
        thread.start()
        self.assertTrue(first_started.wait(timeout=1))
        cancelled = self.client.post(
            f"/api/conversations/{conversation_id}/cancel"
        )
        self.assertEqual(200, cancelled.status_code)
        self.assertEqual("cancelled", cancelled.json()["status"])
        self.assertTrue(cancelled.json()["cancelled"])
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(200, first_responses[0].status_code)
        cancelled_events = [
            json.loads(line.removeprefix("data: "))
            for line in first_responses[0].text.splitlines()
            if line.startswith("data: ")
        ]
        terminal_checklist_index = max(
            index
            for index, event in enumerate(cancelled_events)
            if event.get("type") == "checklist"
        )
        cancelled_event_index = next(
            index
            for index, event in enumerate(cancelled_events)
            if event.get("type") == "cancelled"
        )
        self.assertLess(terminal_checklist_index, cancelled_event_index)
        cancelled_checklist = cancelled_events[terminal_checklist_index]["checklist"]
        self.assertEqual("cancelled", cancelled_checklist["phase"])
        self.assertEqual(
            "本轮结束时尚未完成或未完成复核",
            cancelled_checklist["tasks"][0]["detail"],
        )
        self.assertEqual(
            "incomplete",
            cancelled_checklist["deliverables"][0]["status"],
        )

        after_cancel = self.app.state.store.list_messages(conversation_id)
        self.assertEqual(
            ["先前已完成的结论", ""],
            [item["content"] for item in after_cancel if item["role"] == "assistant"],
        )
        self.assertEqual("stopped", after_cancel[-1]["status"])
        cancelled_run = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        self.assertEqual("cancelled", cancelled_run["status"])
        self.assertEqual(cancelled_checklist, cancelled_run["checklist"])
        metadata = self.app.state.store.read_meta(conversation_id)
        self.assertEqual(1, metadata["agent_session_generation"])
        cancelled_usage = self.client.get(
            f"/api/conversations/{conversation_id}/usage"
        ).json()["usage"]
        self.assertEqual(24, cancelled_usage["total_tokens"])

        continued = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "取消后继续", "attachment_ids": []},
        )
        self.assertEqual(200, continued.status_code)
        self.assertNotIn("上一轮研究", continued.text)
        self.assertIn("续聊成功", continued.text)
        self.assertEqual([0, 1], [generation for generation, _prompt in calls])
        second_prompt = calls[1][1]
        self.assertTrue(second_prompt.startswith(f"{SKILL_COMMAND}\n\n[总控激活]\n"))
        self.assertIn("路由模式：总控先行", second_prompt)
        self.assertIn("默认格式：MD + HTML", second_prompt)
        self.assertIn("先前已完成的问题", second_prompt)
        self.assertIn("先前已完成的结论", second_prompt)
        self.assertNotIn("这轮需要被取消", second_prompt)

        final_messages = self.app.state.store.list_messages(conversation_id)
        assistant_contents = [
            item["content"] for item in final_messages if item["role"] == "assistant"
        ]
        self.assertEqual(["先前已完成的结论", "", "续聊成功"], assistant_contents)
        final_metadata = self.app.state.store.read_meta(conversation_id)
        self.assertEqual(1, final_metadata["agent_session_seeded_generation"])

    def test_restart_first_turn_uses_controller_and_completed_history(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        calls: list[tuple[str, int, str]] = []

        async def first_run(
            _conversation_id: str,
            prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            calls.append((run_id, session_generation, prompt))
            return HarnessRunResult(
                final_response="第一轮结论",
                finish_reason="stop",
                session_id=(
                    f"web-{conversation_id}-g{session_generation}-r{run_id}"
                ),
            )

        self.app.state.harness.run = self._completed_checklist_run(first_run)
        first = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "第一轮问题", "attachment_ids": []},
        )
        self.assertEqual(200, first.status_code)
        self.assertIn("第一轮结论", first.text)
        self.assertTrue(calls[0][2].startswith(f"{SKILL_COMMAND}\n\n[总控激活]\n"))

        # A second app over the same persistent data simulates a service
        # restart: it has no in-memory runner/cache state from the first app.
        restarted_app = create_app(self.settings)
        restarted_calls: list[tuple[str, int, str]] = []

        async def restarted_run(
            _conversation_id: str,
            prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            restarted_calls.append((run_id, session_generation, prompt))
            return HarnessRunResult(
                final_response="重启后首轮成功",
                finish_reason="stop",
                session_id=(
                    f"web-{conversation_id}-g{session_generation}-r{run_id}"
                ),
            )

        restarted_app.state.harness.run = self._completed_checklist_run(restarted_run)
        with TestClient(restarted_app) as restarted_client:
            continued = restarted_client.post(
                f"/api/conversations/{conversation_id}/messages",
                json={"content": "重启后继续", "attachment_ids": []},
            )

        self.assertEqual(200, continued.status_code)
        self.assertNotIn('event: error', continued.text)
        self.assertIn("重启后首轮成功", continued.text)
        self.assertEqual(1, len(restarted_calls))
        second_run_id, _generation, second_prompt = restarted_calls[0]
        self.assertNotEqual(calls[0][0], second_run_id)
        self.assertTrue(second_prompt.startswith(f"{SKILL_COMMAND}\n\n[总控激活]\n"))
        self.assertIn('"content":"第一轮问题"', second_prompt)
        self.assertIn('"content":"第一轮结论"', second_prompt)
        self.assertTrue(second_prompt.endswith('{"content":"重启后继续"}'))

        public_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        assistants = [item for item in public_messages if item["role"] == "assistant"]
        self.assertEqual(["第一轮结论", "重启后首轮成功"], [item["content"] for item in assistants])
        self.assertTrue(all("metadata" not in item for item in public_messages))

    def test_concurrent_send_starts_only_one_stateless_run(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        started = threading.Event()
        release = threading.Event()
        run_ids: list[str] = []

        async def slow_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            run_ids.append(run_id)
            started.set()
            await asyncio.to_thread(release.wait, 2)
            return HarnessRunResult(
                final_response="唯一回复",
                finish_reason="stop",
                session_id=(
                    f"web-{conversation_id}-g{session_generation}-r{run_id}"
                ),
            )

        self.app.state.harness.run = self._completed_checklist_run(slow_run)
        first_responses = []

        def send_first() -> None:
            first_responses.append(
                self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={"content": "第一条", "attachment_ids": []},
                )
            )

        thread = threading.Thread(target=send_first, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=1))
        running = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        )
        self.assertEqual(200, running.status_code)
        self.assertEqual("running", running.json()["status"])
        self.assertTrue(running.json()["active"])
        self.assertRegex(running.json()["user_message_id"], r"^msg_[0-9a-f]{32}$")
        blocked = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "并发第二条", "attachment_ids": []},
        )
        self.assertEqual(409, blocked.status_code)
        self.assertEqual("RUN_ACTIVE", blocked.json()["error"]["code"])
        self.assertIn("刷新不会中断", blocked.json()["error"]["message"])
        release.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(200, first_responses[0].status_code)
        self.assertEqual(1, len(run_ids))
        messages = self.app.state.store.list_messages(conversation_id)
        self.assertEqual(
            ["第一条", "唯一回复"],
            [item["content"] for item in messages],
        )
        completed = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        self.assertEqual("succeeded", completed["status"])
        self.assertFalse(completed["active"])
        self.assertFalse(completed["retryable"])

    def test_refresh_snapshot_preserves_active_turn_until_terminal_reply(self) -> None:
        """A page reload can rebuild the active turn from public GET endpoints alone."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        client_request_id = "123e4567-e89b-42d3-a456-426614174000"
        started = threading.Event()
        release = threading.Event()

        async def slow_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            started.set()
            await asyncio.to_thread(release.wait, 2)
            return HarnessRunResult(
                final_response="刷新后自动出现的最终结论",
                finish_reason="stop",
                session_id=(
                    f"web-{conversation_id}-g{session_generation}-r{run_id}"
                ),
            )

        self.app.state.harness.run = self._completed_checklist_run(slow_run)
        responses = []

        def send() -> None:
            responses.append(
                self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={
                        "content": "刷新期间继续执行",
                        "attachment_ids": [],
                        "client_request_id": client_request_id,
                    },
                )
            )

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=1))

        # These are the only snapshots a newly loaded page has available.
        active_snapshot = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        active_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        self.assertEqual("running", active_snapshot["status"])
        self.assertTrue(active_snapshot["active"])
        self.assertEqual(client_request_id, active_snapshot["client_request_id"])
        self.assertEqual(1, len(active_messages))
        self.assertEqual("user", active_messages[0]["role"])
        self.assertEqual(active_messages[0]["id"], active_snapshot["user_message_id"])

        release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(200, responses[0].status_code)

        terminal_snapshot = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        terminal_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        self.assertEqual("succeeded", terminal_snapshot["status"])
        self.assertFalse(terminal_snapshot["active"])
        self.assertEqual(client_request_id, terminal_snapshot["client_request_id"])
        self.assertEqual(["user", "assistant"], [item["role"] for item in terminal_messages])
        self.assertEqual("complete", terminal_messages[-1]["status"])
        self.assertEqual(active_messages[0]["id"], terminal_messages[-1]["reply_to"])
        self.assertEqual("刷新后自动出现的最终结论", terminal_messages[-1]["content"])

    def test_message_rejects_invalid_client_request_id_without_starting_turn(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        rejected = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "请分析项目，此请求不应进入任务队列",
                "attachment_ids": [],
                "client_request_id": "not-a-canonical-uuid",
            },
        )

        self.assertEqual(422, rejected.status_code)
        self.assertEqual(
            [],
            self.client.get(
                f"/api/conversations/{conversation_id}/messages"
            ).json()["items"],
        )
        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual("idle", run["status"])
        self.assertFalse(run["active"])
        self.assertNotIn("client_request_id", run)

    def test_orphaned_running_state_is_reconciled_after_service_restart(self) -> None:
        """A durable running marker without an in-process worker must not stay active."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        user_message = self.app.state.store.append_message(
            conversation_id,
            role="user",
            content="服务重启前仍在执行的任务",
        )
        self.app.state.store.write_run(
            conversation_id,
            status="running",
            run_id="a" * 32,
            user_message_id=user_message["id"],
        )

        restarted_app = create_app(self.settings)
        with TestClient(restarted_app) as restarted_client:
            recovered = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            )
            recovered_again = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            )

        self.assertEqual(200, recovered.status_code)
        self.assertEqual("interrupted", recovered.json()["status"])
        self.assertEqual("interrupted", recovered_again.json()["status"])
        self.assertEqual(
            recovered.json()["updated_at"],
            recovered_again.json()["updated_at"],
        )
        self.assertFalse(recovered.json()["active"])
        self.assertTrue(recovered.json()["retryable"])
        self.assertEqual(user_message["id"], recovered.json()["user_message_id"])

    def test_orphaned_complete_assistant_recovers_success_idempotently(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        run_id = "c" * 32
        store = self.app.state.store
        user_message = store.append_message(
            conversation_id,
            role="user",
            content="提交run前服务退出的任务",
        )
        store.write_run(
            conversation_id,
            status="running",
            run_id=run_id,
            user_message_id=user_message["id"],
        )
        store.start_checklist(conversation_id, run_id)
        contents = ["任务｜完成恢复研究", "成果回复｜恢复后的结论"]
        for seq, statuses in enumerate(
            (
                ("in_progress", "pending"),
                ("completed", "in_progress"),
                ("completed", "completed"),
            ),
            start=1,
        ):
            store.apply_checklist_snapshot(
                conversation_id,
                run_id=run_id,
                event_seq=seq,
                todos=[
                    {"content": content, "status": status}
                    for content, status in zip(contents, statuses, strict=True)
                ],
            )
        store.prepare_checklist_success(
            conversation_id,
            run_id=run_id,
            final_response="已持久化的完整成功回复",
        )
        store.commit_checklist_success(conversation_id, run_id=run_id)
        assistant = store.append_message(
            conversation_id,
            role="assistant",
            content="已持久化的完整成功回复",
            metadata={
                "finish_reason": "stop",
                "reply_to": user_message["id"],
                "run_id": run_id,
            },
        )

        restarted_app = create_app(self.settings)
        with TestClient(restarted_app) as restarted_client:
            recovered = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
            first_revision = recovered["checklist"]["revision"]
            recovered_again = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
            messages = restarted_client.get(
                f"/api/conversations/{conversation_id}/messages"
            ).json()["items"]

        self.assertEqual(("succeeded", "succeeded"), (recovered["status"], recovered["checklist"]["phase"]))
        self.assertNotIn("assistant_message_id", recovered)
        self.assertEqual(
            assistant["id"],
            store.read_run(conversation_id)["assistant_message_id"],
        )
        self.assertEqual(first_revision, recovered_again["checklist"]["revision"])
        self.assertEqual(
            ["user", "assistant"],
            [item["role"] for item in messages],
        )
        self.assertEqual("complete", messages[-1]["status"])

    def test_orphaned_success_sidecar_without_assistant_is_rechecked_as_interrupted(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        run_id = "d" * 32
        store = self.app.state.store
        user_message = store.append_message(
            conversation_id,
            role="user",
            content="成功sidecar后服务退出的任务",
        )
        store.write_run(
            conversation_id,
            status="running",
            run_id=run_id,
            user_message_id=user_message["id"],
        )
        store.start_checklist(conversation_id, run_id)
        contents = ["任务｜完成研究", "成果回复｜最终结论"]
        for seq, statuses in enumerate(
            (
                ("in_progress", "pending"),
                ("completed", "in_progress"),
                ("completed", "completed"),
            ),
            start=1,
        ):
            store.apply_checklist_snapshot(
                conversation_id,
                run_id=run_id,
                event_seq=seq,
                todos=[
                    {"content": content, "status": status}
                    for content, status in zip(contents, statuses, strict=True)
                ],
            )
        store.prepare_checklist_success(
            conversation_id,
            run_id=run_id,
            final_response="尚未落盘的回复",
        )
        store.commit_checklist_success(conversation_id, run_id=run_id)

        restarted_app = create_app(self.settings)
        with TestClient(restarted_app) as restarted_client:
            recovered = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
            recovered_again = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()

        self.assertEqual(("interrupted", "interrupted"), (recovered["status"], recovered["checklist"]["phase"]))
        self.assertEqual(
            ("interrupted", recovered["checklist"]["revision"]),
            (
                recovered_again["status"],
                recovered_again["checklist"]["revision"],
            ),
        )
        deliverable = recovered["checklist"]["deliverables"][0]
        self.assertEqual("incomplete", deliverable["status"])
        self.assertEqual("未检测到本轮非空成果回复", deliverable["detail"])
        stored_assistants = [
            item
            for item in store.list_messages(conversation_id)
            if item["role"] == "assistant"
        ]
        self.assertEqual(1, len(stored_assistants))
        self.assertEqual("error", stored_assistants[0]["status"])

    def test_explicit_failed_run_is_not_promoted_by_complete_assistant(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        run_id = "f" * 32
        store = self.app.state.store
        user_message = store.append_message(
            conversation_id,
            role="user",
            content="显式失败的任务",
        )
        assistant = store.append_message(
            conversation_id,
            role="assistant",
            content="更早写入但不得晋升终态的回复",
            metadata={
                "finish_reason": "stop",
                "reply_to": user_message["id"],
                "run_id": run_id,
            },
        )
        store.start_checklist(conversation_id, run_id)
        store.apply_checklist_snapshot(
            conversation_id,
            run_id=run_id,
            event_seq=1,
            todos=[
                {"content": "任务｜失败研究", "status": "in_progress"},
                {"content": "成果回复｜失败结论", "status": "pending"},
            ],
        )
        store.finalize_checklist(
            conversation_id,
            run_id=run_id,
            status="failed",
        )
        store.write_run(
            conversation_id,
            status="failed",
            run_id=run_id,
            user_message_id=user_message["id"],
            assistant_message_id=assistant["id"],
            error_code="EXPLICIT_FAILURE",
            retryable=True,
        )

        restarted_app = create_app(self.settings)
        restarted_store = restarted_app.state.store
        original_write_run = restarted_store.write_run
        failed_writes = 0

        def fail_first_repair_write(
            current_conversation_id: str,
            **kwargs: object,
        ) -> dict[str, object]:
            nonlocal failed_writes
            if kwargs.get("status") == "failed":
                failed_writes += 1
                if failed_writes == 1:
                    raise OSError("simulated explicit failure repair write")
            return original_write_run(current_conversation_id, **kwargs)

        restarted_store.write_run = fail_first_repair_write
        with TestClient(restarted_app) as restarted_client:
            try:
                with self.assertRaisesRegex(OSError, "explicit failure repair"):
                    restarted_client.get(
                        f"/api/conversations/{conversation_id}/run"
                    )
                self.assertEqual(
                    1,
                    sum(
                        item["role"] == "assistant" and item["status"] == "error"
                        for item in store.list_messages(conversation_id)
                    ),
                )
                recovered = restarted_client.get(
                    f"/api/conversations/{conversation_id}/run"
                ).json()
                public_messages = restarted_client.get(
                    f"/api/conversations/{conversation_id}/messages"
                ).json()["items"]
            finally:
                restarted_store.write_run = original_write_run

        self.assertEqual(("failed", "failed"), (recovered["status"], recovered["checklist"]["phase"]))
        durable = store.read_run(conversation_id)
        self.assertEqual("failed", durable["status"])
        self.assertEqual("EXPLICIT_FAILURE", durable["error_code"])
        self.assertEqual("error", public_messages[-1]["status"])
        self.assertEqual("", public_messages[-1]["content"])
        self.assertNotEqual(assistant["id"], durable["assistant_message_id"])
        self.assertEqual(
            1,
            sum(
                item["role"] == "assistant" and item["status"] == "error"
                for item in store.list_messages(conversation_id)
            ),
        )

    def test_orphaned_retry_run_ignores_previous_terminal_reply_after_restart(self) -> None:
        """A stale reply for the same user turn must not complete the newer retry run."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        user_message = self.app.state.store.append_message(
            conversation_id,
            role="user",
            content="失败后正在重试的任务",
        )
        old_run_id = "a" * 32
        new_run_id = "b" * 32
        client_request_id = "123e4567-e89b-42d3-a456-426614174000"
        old_reply = self.app.state.store.append_message(
            conversation_id,
            role="assistant",
            content="",
            status="error",
            metadata={
                "finish_reason": "failed",
                "reply_to": user_message["id"],
                "run_id": old_run_id,
                "public_error": "旧一轮失败，可重试。",
            },
        )
        self.app.state.store.write_run(
            conversation_id,
            status="failed",
            run_id=old_run_id,
            user_message_id=user_message["id"],
            assistant_message_id=old_reply["id"],
            retryable=True,
        )
        self.app.state.store.write_run(
            conversation_id,
            status="running",
            run_id=new_run_id,
            client_request_id=client_request_id,
            user_message_id=user_message["id"],
        )

        restarted_app = create_app(self.settings)
        with TestClient(restarted_app) as restarted_client:
            recovered = restarted_client.get(
                f"/api/conversations/{conversation_id}/run"
            )
            public_messages = restarted_client.get(
                f"/api/conversations/{conversation_id}/messages"
            ).json()["items"]

        self.assertEqual(200, recovered.status_code)
        self.assertEqual("interrupted", recovered.json()["status"])
        self.assertFalse(recovered.json()["active"])
        self.assertTrue(recovered.json()["retryable"])
        self.assertEqual(client_request_id, recovered.json()["client_request_id"])
        self.assertEqual(user_message["id"], recovered.json()["user_message_id"])

        stored = self.app.state.store.list_messages(conversation_id)
        stored_assistants = [item for item in stored if item["role"] == "assistant"]
        self.assertEqual(2, len(stored_assistants))
        self.assertEqual(old_reply["id"], stored_assistants[0]["id"])
        self.assertEqual(new_run_id, stored_assistants[-1]["metadata"]["run_id"])
        self.assertEqual("interrupted", stored_assistants[-1]["metadata"]["finish_reason"])
        persisted = self.app.state.store.read_run(conversation_id)
        self.assertEqual("interrupted", persisted["status"])
        self.assertEqual(stored_assistants[-1]["id"], persisted["assistant_message_id"])

        self.assertEqual(["user", "assistant"], [item["role"] for item in public_messages])
        self.assertEqual("error", public_messages[-1]["status"])
        self.assertEqual(stored_assistants[-1]["id"], public_messages[-1]["id"])
        self.assertIn("服务重启", public_messages[-1]["error_message"])

    def test_legacy_conversation_without_run_file_recovers_orphan_user(self) -> None:
        """V0.1 conversations remain retryable even though they have no run.json."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        user_message = self.app.state.store.append_message(
            conversation_id,
            role="user",
            content="旧版本中尚未收到回复的任务",
        )
        run_path = self.app.state.store.require(conversation_id).run
        run_path.unlink()

        recovered = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        )

        self.assertEqual(200, recovered.status_code)
        self.assertEqual("interrupted", recovered.json()["status"])
        self.assertFalse(recovered.json()["active"])
        self.assertTrue(recovered.json()["retryable"])
        self.assertEqual(user_message["id"], recovered.json()["user_message_id"])
        self.assertTrue(run_path.is_file())
        persisted = self.app.state.store.read_run(conversation_id)
        self.assertEqual("interrupted", persisted["status"])
        self.assertNotIn("legacy", persisted)
        public_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        self.assertEqual(
            ["user", "assistant"],
            [item["role"] for item in public_messages],
        )
        self.assertEqual("error", public_messages[-1]["status"])
        self.assertTrue(public_messages[-1]["retryable"])
        self.assertEqual(user_message["id"], public_messages[-1]["reply_to"])
        self.assertIn("服务重启", public_messages[-1]["error_message"])
        self.assertEqual(public_messages[-1]["id"], persisted["assistant_message_id"])

    def test_active_projection_never_reuses_previous_run_user_identity(self) -> None:
        """A refresh during run initialization must not attach the old turn to the new run."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        prior_user = self.app.state.store.append_message(
            conversation_id,
            role="user",
            content="上一轮任务",
        )
        self.app.state.store.write_run(
            conversation_id,
            status="succeeded",
            run_id="a" * 32,
            user_message_id=prior_user["id"],
        )

        class InitializingRun:
            run_id = "b" * 32
            cancel_event = asyncio.Event()
            user_message_id = None

        self.app.state.active_runs[conversation_id] = InitializingRun()
        try:
            snapshot = self.client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
        finally:
            self.app.state.active_runs.pop(conversation_id, None)

        self.assertTrue(snapshot["active"])
        self.assertEqual("running", snapshot["status"])
        self.assertNotIn("user_message_id", snapshot)

    def test_active_projection_hides_durable_success_until_run_commit(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        run_id = "e" * 32
        store = self.app.state.store
        user_message = store.append_message(
            conversation_id,
            role="user",
            content="成功提交窗口中的任务",
        )
        store.write_run(
            conversation_id,
            status="running",
            run_id=run_id,
            user_message_id=user_message["id"],
        )
        store.start_checklist(conversation_id, run_id)
        contents = ["任务｜提交研究", "成果回复｜提交结论"]
        for seq, statuses in enumerate(
            (
                ("in_progress", "pending"),
                ("completed", "in_progress"),
                ("completed", "completed"),
            ),
            start=1,
        ):
            store.apply_checklist_snapshot(
                conversation_id,
                run_id=run_id,
                event_seq=seq,
                todos=[
                    {"content": content, "status": status}
                    for content, status in zip(contents, statuses, strict=True)
                ],
            )
        store.prepare_checklist_success(
            conversation_id,
            run_id=run_id,
            final_response="提交结论",
        )
        store.commit_checklist_success(conversation_id, run_id=run_id)

        class CommittingRun:
            cancel_event = asyncio.Event()
            client_request_id = None
            user_message_id = user_message["id"]

            def __init__(self) -> None:
                self.run_id = run_id

        self.app.state.active_runs[conversation_id] = CommittingRun()
        try:
            snapshot = self.client.get(
                f"/api/conversations/{conversation_id}/run"
            ).json()
        finally:
            self.app.state.active_runs.pop(conversation_id, None)

        self.assertEqual("succeeded", store.read_checklist(conversation_id, run_id)["phase"])
        self.assertEqual("running", snapshot["status"])
        self.assertEqual("running", snapshot["checklist"]["phase"])

    def test_running_state_persistence_failure_prevents_model_start(self) -> None:
        """The API must not accept work that a refreshed page cannot rediscover."""

        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]
        first_client_request_id = "123e4567-e89b-42d3-a456-426614174000"
        retry_client_request_id = "123e4567-e89b-42d3-b456-426614174000"
        model_started = False
        original_write_run = self.app.state.store.write_run

        async def model_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            nonlocal model_started
            del run_id, session_generation
            model_started = True
            return HarnessRunResult(
                final_response="不应启动",
                finish_reason="stop",
                session_id="should-not-start",
            )

        def fail_running_state(*args: object, **kwargs: object) -> dict[str, object]:
            if kwargs.get("status") == "running":
                raise OSError("simulated run-state write failure")
            return original_write_run(*args, **kwargs)

        self.app.state.harness.run = self._completed_checklist_run(model_run)
        self.app.state.store.write_run = fail_running_state
        try:
            with self.assertRaisesRegex(OSError, "simulated run-state write failure"):
                self.client.post(
                    f"/api/conversations/{conversation_id}/messages",
                    json={
                        "content": "必须可恢复地执行",
                        "attachment_ids": [],
                        "client_request_id": first_client_request_id,
                    },
                )
        finally:
            self.app.state.store.write_run = original_write_run

        self.assertFalse(model_started)
        self.assertNotIn(conversation_id, self.app.state.active_runs)
        failed_run = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        failed_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        self.assertEqual("failed", failed_run["status"])
        self.assertFalse(failed_run["active"])
        self.assertTrue(failed_run["retryable"])
        self.assertEqual(first_client_request_id, failed_run["client_request_id"])
        self.assertEqual(["user", "assistant"], [item["role"] for item in failed_messages])
        self.assertEqual("error", failed_messages[-1]["status"])
        self.assertTrue(failed_messages[-1]["retryable"])
        self.assertEqual(failed_messages[0]["id"], failed_messages[-1]["reply_to"])

        retried = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": failed_messages[0]["content"],
                "attachment_ids": failed_messages[0]["attachment_ids"],
                "retry_of": failed_messages[0]["id"],
                "client_request_id": retry_client_request_id,
            },
        )
        self.assertEqual(200, retried.status_code)
        self.assertTrue(model_started)
        completed_run = self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()
        self.assertEqual("succeeded", completed_run["status"])
        self.assertEqual(retry_client_request_id, completed_run["client_request_id"])
        stored = self.app.state.store.list_messages(conversation_id)
        self.assertEqual(1, len([item for item in stored if item["role"] == "user"]))

    def test_failed_turn_persists_public_state_and_retries_without_duplicate_user(self) -> None:
        conversation_id = self.client.post("/api/conversations", json={}).json()["id"]

        async def failed_run(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            raise HarnessAdapterError("AGENT_RUN_FAILED", "private provider detail")

        self.app.state.harness.run = self._completed_checklist_run(failed_run)
        failed = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "请读取原附件并继续", "attachment_ids": []},
        )
        self.assertEqual(200, failed.status_code)
        self.assertIn("本轮研究暂未完成", failed.text)
        self.assertNotIn("private provider detail", failed.text)

        run = self.client.get(f"/api/conversations/{conversation_id}/run").json()
        self.assertEqual("failed", run["status"])
        self.assertTrue(run["retryable"])
        public_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        self.assertEqual(["user", "assistant"], [item["role"] for item in public_messages])
        self.assertEqual("error", public_messages[-1]["status"])
        self.assertTrue(public_messages[-1]["retryable"])
        self.assertEqual(public_messages[0]["id"], public_messages[-1]["reply_to"])
        self.assertNotIn("metadata", public_messages[-1])
        self.assertNotIn("AGENT_RUN_FAILED", json.dumps(public_messages))

        async def successful_retry(
            _conversation_id: str,
            _prompt: str,
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id, session_generation
            return HarnessRunResult(
                final_response="恢复成功",
                finish_reason="completed",
                session_id=f"web-{conversation_id}-retry",
            )

        self.app.state.harness.run = self._completed_checklist_run(successful_retry)
        retried = self.client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": public_messages[0]["content"],
                "attachment_ids": public_messages[0]["attachment_ids"],
                "retry_of": public_messages[0]["id"],
            },
        )
        self.assertEqual(200, retried.status_code)
        self.assertIn("恢复成功", retried.text)
        stored = self.app.state.store.list_messages(conversation_id)
        self.assertEqual(1, len([item for item in stored if item["role"] == "user"]))
        self.assertEqual("succeeded", self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()["status"])
        refreshed_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).json()["items"]
        self.assertEqual(
            ["user", "assistant"],
            [item["role"] for item in refreshed_messages],
        )
        self.assertEqual("恢复成功", refreshed_messages[-1]["content"])
        self.assertEqual("complete", refreshed_messages[-1]["status"])

    def test_completed_history_strictly_caps_oversized_user_and_assistant(self) -> None:
        history = _completed_conversation_history(
            [
                {"id": "user-1", "role": "user", "content": "U" * 200_000},
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": "A" * 200_000,
                    "metadata": {"finish_reason": "stop", "reply_to": "user-1"},
                },
            ],
            maximum_characters=120_000,
        )

        self.assertEqual(["user", "assistant"], [item["role"] for item in history])
        self.assertEqual(
            120_000,
            sum(len(item["content"]) for item in history),
        )


if __name__ == "__main__":
    unittest.main()
