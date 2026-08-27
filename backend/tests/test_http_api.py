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
from app.harness_adapter import HarnessAdapterError, HarnessRunResult, SKILL_COMMAND
from app.main import (
    _completed_conversation_history,
    _new_or_updated_output_formats,
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

    def test_run_output_format_audit_ignores_unchanged_old_files(self) -> None:
        baseline = {"report.html": (100, 1)}
        current = {"report.html": (100, 1), "report.md": (200, 2)}

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
        message_marker = "PRIVATE-MESSAGE-7f69dfef"
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

    def test_health_responses_expose_v02_slot_and_build_identity(self) -> None:
        live = self.client.get("/api/health/live")
        self.assertEqual(200, live.status_code)
        self.assertEqual(
            {
                "ok": True,
                "version": "0.2.0",
                "slot": "slot-b",
                "build_id": "development",
            },
            live.json(),
        )

        ready = self.client.get("/api/health/ready")
        self.assertEqual(503, ready.status_code)
        self.assertEqual("0.2.0", ready.json()["version"])
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

        self.app.state.harness.run = fake_run
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
            _on_notification: object,
            *,
            run_id: str,
            session_generation: int = 0,
        ) -> HarnessRunResult:
            del run_id
            call_index = len(calls)
            calls.append((session_generation, prompt))
            if call_index == 0:
                first_started.set()
                await asyncio.to_thread(release_first.wait, 2)
                return HarnessRunResult(
                    final_response="不应写回的旧回复",
                    finish_reason="stop",
                    session_id=f"web-{conversation_id}",
                )
            return HarnessRunResult(
                final_response="续聊成功",
                finish_reason="stop",
                session_id=f"web-{conversation_id}-g{session_generation}",
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

        after_cancel = self.app.state.store.list_messages(conversation_id)
        self.assertEqual(
            ["先前已完成的结论", ""],
            [item["content"] for item in after_cancel if item["role"] == "assistant"],
        )
        self.assertEqual("stopped", after_cancel[-1]["status"])
        self.assertEqual("cancelled", self.client.get(
            f"/api/conversations/{conversation_id}/run"
        ).json()["status"])
        metadata = self.app.state.store.read_meta(conversation_id)
        self.assertEqual(1, metadata["agent_session_generation"])

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

        self.app.state.harness.run = first_run
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

        restarted_app.state.harness.run = restarted_run
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

        self.app.state.harness.run = slow_run
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

        self.app.state.harness.run = slow_run
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
                "content": "不应进入任务队列",
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

        self.assertEqual(200, recovered.status_code)
        self.assertEqual("interrupted", recovered.json()["status"])
        self.assertFalse(recovered.json()["active"])
        self.assertTrue(recovered.json()["retryable"])
        self.assertEqual(user_message["id"], recovered.json()["user_message_id"])

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

        self.app.state.harness.run = model_run
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

        self.app.state.harness.run = failed_run
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

        self.app.state.harness.run = successful_retry
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
