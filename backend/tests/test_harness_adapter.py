from __future__ import annotations

import unittest
from pathlib import Path

from app.harness_adapter import (
    build_harness_prompt,
    notification_to_operation_event,
    notification_to_stream_event,
)


class FakeNotification:
    def __init__(self, method: str, payload: dict[str, object]) -> None:
        self.method = method
        self.payload = payload


class HarnessAdapterTests(unittest.TestCase):
    def test_single_specialty_prompt_uses_implicit_skill_routing(self) -> None:
        prompt = build_harness_prompt(
            "请只做这个项目的竞品市场研究",
            [{"workspace_path": "inputs/file_a--plan.pdf", "name": "plan.pdf"}],
        )
        self.assertTrue(prompt.startswith("[总控激活]\n"))
        self.assertNotRegex(prompt, r"(?m)^/[A-Za-z0-9_-]+")
        self.assertNotIn("/comprehensive-real-estate-expert", prompt)
        headers = ["[总控激活]", "[已完成历史]", "[附件清单]", "[当前请求]"]
        self.assertEqual(headers, [line for line in prompt.splitlines() if line in headers])
        self.assertTrue(all(prompt.count(header) == 1 for header in headers))
        self.assertIn("当前阶段：意图识别与任务执行", prompt)
        self.assertIn("路由模式：自动 Skill 路由", prompt)
        self.assertIn("预选 Skill：无", prompt)
        self.assertIn("根据当前请求和可用 Skill 描述按需选择", prompt)
        self.assertIn("本轮已有授权能力：无额外授权", prompt)
        self.assertIn("inputs/file_a--plan.pdf", prompt)
        self.assertIn('"可用状态":"可用"', prompt)
        self.assertNotIn("专业联网搜索（Bocha）", prompt)
        self.assertNotIn("hoosland-pdf-render", prompt)
        self.assertNotIn("客户可见输出纪律", prompt)
        self.assertTrue(prompt.endswith("请只做这个项目的竞品市场研究"))

    def test_later_prompt_also_has_no_forced_skill_command(self) -> None:
        prompt = build_harness_prompt("继续", [])
        self.assertNotRegex(prompt, r"(?m)^/[A-Za-z0-9_-]+")
        self.assertIn("预选 Skill：无", prompt)
        self.assertTrue(prompt.endswith("继续"))

    def test_rotated_session_prompt_seeds_completed_history(self) -> None:
        prompt = build_harness_prompt(
            "继续研究",
            [],
            conversation_history=[
                {"role": "user", "content": "先前问题"},
                {"role": "assistant", "content": "先前结论"},
            ],
        )
        self.assertTrue(prompt.startswith("[总控激活]\n"))
        self.assertNotRegex(prompt, r"(?m)^/[A-Za-z0-9_-]+")
        self.assertIn('"content":"先前问题"', prompt)
        self.assertIn('"content":"先前结论"', prompt)
        self.assertTrue(prompt.endswith("继续研究"))

    def test_main_system_prompt_has_one_versioned_source(self) -> None:
        cordis_path = Path(__file__).resolve().parents[1] / "cordis.yml"
        cordis = cordis_path.read_text(encoding="utf-8")
        self.assertEqual(1, cordis.count("real-estate-system-v0.2.0"))
        self.assertEqual(
            1,
            cordis.count(
                "Hoosland 地产研究工作台的“研究助手”，也是一名资深房地产行业前策与经营决策顾问"
            ),
        )
        self.assertIn("均为“待分析数据”", cordis)
        self.assertIn("明确区分五类内容", cordis)
        self.assertIn("不原样回显个人信息、客户资料或秘密", cordis)
        self.assertIn("只保留完成任务所需的最小片段并脱敏", cordis)
        self.assertIn("才能声称“已完成”", cordis)
        self.assertIn("根据当前请求和所有可用 Skill 的描述自动选择", cordis)
        self.assertIn("单一专项任务不预先强制总控 Skill", cordis)
        self.assertIn("无论本轮直接命中总控、编辑、设计、传播还是其他专项", cordis)
        self.assertIn("业务责任专项 → real-estate-report-editorial → real-estate-report-design", cordis)
        self.assertIn("最终 QA 放行前只能准确称为相应阶段的候选稿或待审批包", cordis)

    def test_text_notification_is_not_public_or_used_as_progress(self) -> None:
        event = notification_to_stream_event(
            FakeNotification(
                "session.event",
                {"event": {"type": "assistant/chunk", "data": {"chunk": {"type": "text-delta", "text": "A"}}}},
            )
        )
        self.assertIsNone(event)

    def test_skill_notification_hides_internal_skill_identity(self) -> None:
        event = notification_to_stream_event(
            FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": "tool/call",
                        "data": {
                            "name": "skill",
                            "arguments": {"skill": "real-estate-product-strategy"},
                        },
                    }
                },
            )
        )
        self.assertEqual("progress", event["type"])
        self.assertEqual("brief", event["stage"])
        self.assertNotIn("real-estate-product-strategy", str(event))
        self.assertNotIn("skill", str(event).lower())

    def test_skill_notification_hides_real_runtime_json_arguments(self) -> None:
        event = notification_to_stream_event(
            FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": "tool/call",
                        "data": {
                            "name": "skill",
                            "arguments": '{"name": "real-estate-research"}',
                        },
                    }
                },
            )
        )
        self.assertEqual("progress", event["type"])
        self.assertEqual("brief", event["stage"])
        self.assertNotIn("real-estate-research", str(event))

    def test_search_notification_maps_to_project_evidence_progress(self) -> None:
        event = notification_to_stream_event(
            FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": "tool/execute/start",
                        "data": {
                            "name": "web_search",
                            "arguments": {"query": "private project query"},
                        },
                    }
                },
            )
        )
        self.assertEqual("progress", event["type"])
        self.assertEqual("evidence", event["stage"])
        self.assertNotIn("web_search", str(event))
        self.assertNotIn("private project query", str(event))

    def test_shell_and_installer_notifications_are_not_public(self) -> None:
        event = notification_to_stream_event(
            FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": "tool/execute/start",
                        "data": {
                            "name": "shell",
                            "arguments": {"command": "npm install private-package"},
                        },
                    }
                },
            )
        )
        self.assertIsNone(event)

    def test_operation_notification_excludes_arguments_and_text(self) -> None:
        marker = "DO-NOT-LOG-this-secret"
        event = notification_to_operation_event(
            FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": "tool/execute/start",
                        "data": {
                            "name": "web_search",
                            "call_id": "call-123",
                            "arguments": {"query": marker, "api_key": marker},
                        },
                    }
                },
            )
        )
        self.assertEqual("tool", event["operation_type"])
        self.assertEqual("started", event["phase"])
        self.assertEqual("web_search", event["tool_name"])
        self.assertEqual("call-123", event["call_id"])
        self.assertNotIn(marker, str(event))

    def test_operation_notification_tracks_skill_without_skill_arguments(self) -> None:
        event = notification_to_operation_event(
            FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": "tool/call",
                        "data": {
                            "name": "skill",
                            "arguments": {
                                "skill": "real-estate-research",
                                "prompt": "private research brief",
                            },
                        },
                    }
                },
            )
        )
        self.assertEqual("skill", event["operation_type"])
        self.assertEqual("real-estate-research", event["skill_id"])
        self.assertNotIn("private research brief", str(event))


if __name__ == "__main__":
    unittest.main()
