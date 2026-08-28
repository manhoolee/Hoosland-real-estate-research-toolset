from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from app.harness_adapter import (
    SKILL_COMMAND,
    build_harness_prompt,
    harness_session_id,
    notification_to_checklist_snapshot,
    notification_to_operation_event,
    notification_to_output_write_attempt,
    notification_to_stream_event,
    notification_to_token_retry_attempt,
    notification_to_token_usage_sample,
)


class FakeNotification:
    def __init__(self, method: str, payload: dict[str, object]) -> None:
        self.method = method
        self.payload = payload


class HarnessAdapterTests(unittest.TestCase):
    def test_single_specialty_prompt_deterministically_activates_controller(self) -> None:
        workspace = (Path.cwd() / "conversation-workspace").resolve()
        prompt = build_harness_prompt(
            "请只做这个项目的竞品市场研究",
            [{"workspace_path": "inputs/file_a--plan.pdf", "name": "plan.pdf"}],
            workspace_path=workspace,
        )
        self.assertTrue(prompt.startswith(f"{SKILL_COMMAND}\n\n[总控激活]\n"))
        self.assertEqual(SKILL_COMMAND, prompt.splitlines()[0])
        self.assertEqual(
            [SKILL_COMMAND],
            re.findall(r"(?m)^/[A-Za-z0-9_-]+$", prompt),
        )
        headers = [
            "[总控激活]",
            "[唯一工作区路径]",
            "[交付策略]",
            "[任务与成果清单]",
            "[已完成历史]",
            "[附件清单]",
            "[当前请求]",
        ]
        self.assertEqual(headers, [line for line in prompt.splitlines() if line in headers])
        self.assertTrue(all(prompt.count(header) == 1 for header in headers))
        self.assertIn("当前阶段：意图识别与任务执行", prompt)
        self.assertIn("主控 Skill：comprehensive-real-estate-expert", prompt)
        self.assertIn("路由模式：总控先行", prompt)
        self.assertIn("主控不得调用自身", prompt)
        self.assertIn("默认格式：MD + HTML", prompt)
        self.assertIn("必须在 outputs/ 同时生成", prompt)
        self.assertIn("用户明确指定单一格式、其他格式或不要文件时", prompt)
        self.assertIn("本轮已有授权能力：无额外授权", prompt)
        self.assertIn(f"会话工作区：{workspace}", prompt)
        self.assertIn(f"最终成果唯一目录：{workspace / 'outputs'}", prompt)
        self.assertIn("write/edit 文件工具不跟随 persistent bash 的 cd", prompt)
        self.assertIn("/tmp/**/outputs", prompt)
        self.assertIn("inputs/file_a--plan.pdf", prompt)
        self.assertIn('"可用状态":"可用"', prompt)
        self.assertNotIn("专业联网搜索（Bocha）", prompt)
        self.assertNotIn("hoosland-pdf-render", prompt)
        self.assertNotIn("客户可见输出纪律", prompt)
        self.assertTrue(prompt.endswith('{"content":"请只做这个项目的竞品市场研究"}'))

    def test_output_write_attempt_classifies_canonical_and_misplaced_paths(self) -> None:
        workspace = (Path.cwd() / "conversation-workspace").resolve()

        def notification(path: str, *, event_type: str = "tool/call") -> FakeNotification:
            return FakeNotification(
                "session.event",
                {
                    "event": {
                        "type": event_type,
                        "data": {
                            "name": "write",
                            "arguments": json.dumps(
                                {"file_path": path, "content": "private report"}
                            ),
                        },
                    }
                },
            )

        relative = notification_to_output_write_attempt(
            notification("outputs/report.md"),
            workspace,
        )
        self.assertIsNotNone(relative)
        assert relative is not None
        self.assertTrue(relative.canonical)
        self.assertEqual("md", relative.output_format)

        absolute = notification_to_output_write_attempt(
            notification(str(workspace / "outputs" / "report.html")),
            workspace,
        )
        self.assertIsNotNone(absolute)
        assert absolute is not None
        self.assertTrue(absolute.canonical)
        self.assertEqual("html", absolute.output_format)

        misplaced = notification_to_output_write_attempt(
            notification(str(workspace.parent / "temporary" / "outputs" / "report.md")),
            workspace,
        )
        self.assertIsNotNone(misplaced)
        assert misplaced is not None
        self.assertFalse(misplaced.canonical)
        self.assertEqual(relative.target_id, misplaced.target_id)

        nested = notification_to_output_write_attempt(
            notification("project-copy/outputs/report.md"),
            workspace,
        )
        self.assertIsNotNone(nested)
        assert nested is not None
        self.assertFalse(nested.canonical)

        self.assertIsNone(
            notification_to_output_write_attempt(
                notification("work/report.md"),
                workspace,
            )
        )
        self.assertIsNone(
            notification_to_output_write_attempt(
                notification("outputs/report.md", event_type="tool/execute/start"),
                workspace,
            )
        )

    def test_later_prompt_also_forces_the_same_controller(self) -> None:
        prompt = build_harness_prompt("继续", [])
        self.assertEqual(SKILL_COMMAND, prompt.splitlines()[0])
        self.assertIn("路由模式：总控先行", prompt)
        self.assertTrue(prompt.endswith('{"content":"继续"}'))

    def test_user_slash_command_does_not_replace_service_controller(self) -> None:
        prompt = build_harness_prompt(
            "/real-estate-research\n只做竞品研究",
            [],
        )
        self.assertEqual(SKILL_COMMAND, prompt.splitlines()[0])
        self.assertNotRegex(prompt, r"(?m)^/real-estate-research$")
        self.assertIn(
            '"content":"/real-estate-research\\n只做竞品研究"',
            prompt,
        )

    def test_rotated_session_prompt_seeds_completed_history(self) -> None:
        prompt = build_harness_prompt(
            "继续研究",
            [],
            conversation_history=[
                {"role": "user", "content": "先前问题"},
                {"role": "assistant", "content": "先前结论"},
            ],
        )
        self.assertTrue(prompt.startswith(f"{SKILL_COMMAND}\n\n[总控激活]\n"))
        self.assertIn('"content":"先前问题"', prompt)
        self.assertIn('"content":"先前结论"', prompt)
        self.assertTrue(prompt.endswith('{"content":"继续研究"}'))

    def test_main_system_prompt_has_one_versioned_source(self) -> None:
        cordis_path = Path(__file__).resolve().parents[1] / "cordis.yml"
        cordis = cordis_path.read_text(encoding="utf-8")
        self.assertEqual(1, cordis.count("real-estate-system-v0.2.3"))
        self.assertIn("includeRuntimeContext: true", cordis)
        self.assertIn("write/edit 文件工具不跟随 persistent Bash 的 cd", cordis)
        self.assertIn("/tmp/**/outputs", cordis)
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
        self.assertIn("每轮任务都必须先由服务端确定性激活", cordis)
        self.assertIn("单一专项任务同样遵守“总控 → 专项”", cordis)
        self.assertIn("不得绕过总控直达子 Skill", cordis)
        self.assertIn("同一子 Skill 最多加载一次", cordis)
        self.assertIn("默认必须在 outputs 同时生成内容对应的 Markdown", cordis)
        self.assertIn("该规则是主报告交付契约", cordis)
        self.assertIn("微信资料转换/归档、社交平台素材", cordis)
        self.assertIn("业务责任专项 → real-estate-report-editorial → real-estate-report-design", cordis)
        self.assertIn("最终 QA 放行前只能准确称为相应阶段的候选稿或待审批包", cordis)
        self.assertIn("name: '@deepseek-ai/dsh-tool-todo'", cordis)
        self.assertIn("allowParallelInProgress: false", cordis)
        self.assertIn("goals: false", cordis)
        self.assertIn("第一个实质动作必须调用 todo_write", cordis)

    def test_todo_write_parser_accepts_only_bounded_unique_root_snapshots(self) -> None:
        session_id = harness_session_id("conversation_123456", "a" * 32, 3)

        def notification(
            *,
            root: str = session_id,
            seq: object = 7,
            todos: object = None,
        ) -> FakeNotification:
            return FakeNotification(
                "session.event",
                {
                    "sessionId": root,
                    "event": {
                        "type": "todo/write",
                        "seq": seq,
                        "time": 123,
                        "data": {
                            "todos": todos
                            if todos is not None
                            else [
                                {"content": "任务｜核验数据", "status": "completed"},
                                {"content": "成果回复｜摘要", "status": "in_progress"},
                            ]
                        },
                    },
                },
            )

        snapshot = notification_to_checklist_snapshot(
            notification(),
            expected_session_id=session_id,
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(7, snapshot.event_seq)
        self.assertEqual(
            ["任务｜核验数据", "成果回复｜摘要"],
            [item.content for item in snapshot.todos],
        )

        self.assertIsNone(
            notification_to_checklist_snapshot(
                notification(root=f"{session_id}-child"),
                expected_session_id=session_id,
            )
        )
        self.assertIsNone(
            notification_to_checklist_snapshot(
                notification(seq=-1),
                expected_session_id=session_id,
            )
        )
        duplicate = [
            {"content": "任务｜重复", "status": "pending"},
            {"content": "任务｜重复", "status": "pending"},
        ]
        self.assertIsNone(
            notification_to_checklist_snapshot(
                notification(todos=duplicate),
                expected_session_id=session_id,
            )
        )
        two_active = [
            {"content": "任务｜一", "status": "in_progress"},
            {"content": "成果回复｜二", "status": "in_progress"},
        ]
        self.assertIsNone(
            notification_to_checklist_snapshot(
                notification(todos=two_active),
                expected_session_id=session_id,
            )
        )
        too_long = [
            {"content": "任" * 501, "status": "pending"},
        ]
        self.assertIsNone(
            notification_to_checklist_snapshot(
                notification(todos=too_long),
                expected_session_id=session_id,
            )
        )

    def test_todo_write_parser_ignores_calls_and_noncanonical_item_shapes(self) -> None:
        session_id = harness_session_id("conversation_123456", "b" * 32, 0)
        tool_call = FakeNotification(
            "session.event",
            {
                "sessionId": session_id,
                "event": {
                    "type": "tool/call",
                    "seq": 1,
                    "data": {"name": "todo_write", "arguments": {"todos": []}},
                },
            },
        )
        self.assertIsNone(
            notification_to_checklist_snapshot(
                tool_call,
                expected_session_id=session_id,
            )
        )
        todo_operation = notification_to_operation_event(tool_call)
        self.assertIsNotNone(todo_operation)
        assert todo_operation is not None
        self.assertEqual("checklist", todo_operation["tool_name"])
        self.assertNotIn("arguments", todo_operation)
        extra_key = FakeNotification(
            "session.event",
            {
                "sessionId": session_id,
                "event": {
                    "type": "todo/write",
                    "seq": 2,
                    "data": {
                        "todos": [
                            {
                                "content": "任务｜核验",
                                "status": "pending",
                                "private": "must not pass",
                            }
                        ]
                    },
                },
            },
        )
        self.assertIsNone(
            notification_to_checklist_snapshot(
                extra_key,
                expected_session_id=session_id,
            )
        )

    def test_text_notification_is_not_public_or_used_as_progress(self) -> None:
        event = notification_to_stream_event(
            FakeNotification(
                "session.event",
                {"event": {"type": "assistant/chunk", "data": {"chunk": {"type": "text-delta", "text": "A"}}}},
            )
        )
        self.assertIsNone(event)

    def test_usage_chunk_extracts_disjoint_provider_buckets(self) -> None:
        sample = notification_to_token_usage_sample(
            FakeNotification(
                "session.event",
                {
                    "sessionId": "child-session-1",
                    "event": {
                        "type": "assistant/chunk",
                        "seq": 17,
                        "data": {
                            "turn": 2,
                            "step": 3,
                            "chunk": {
                                "type": "usage",
                                "usage": {
                                    "inputTokens": 100,
                                    "outputTokens": 40,
                                    "reasoningTokens": 30,
                                    "cacheReadTokens": 20,
                                    "cacheWriteTokens": 5,
                                },
                            },
                        },
                    },
                },
            )
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual("child-session-1", sample.session_id)
        self.assertEqual("model_step", sample.sample_kind)
        self.assertEqual(17, sample.event_seq)
        self.assertEqual((2, 3), (sample.turn, sample.step))
        self.assertEqual(
            {
                "uncached_input_tokens": 100,
                "output_tokens": 40,
                "reasoning_tokens": 30,
                "cache_read_tokens": 20,
                "cache_write_tokens": 5,
            },
            sample.buckets(),
        )

    def test_final_usage_defaults_optional_buckets_and_requires_session_id(self) -> None:
        event = {
            "type": "assistant/message",
            "seq": 8,
            "data": {
                "turn": 1,
                "step": 1,
                "usage": {"inputTokens": 9, "outputTokens": 4},
            },
        }
        sample = notification_to_token_usage_sample(
            FakeNotification(
                "session.event",
                {"sessionId": "root-session", "event": event},
            )
        )
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(0, sample.reasoning_tokens)
        self.assertEqual(0, sample.cache_read_tokens)
        self.assertEqual(0, sample.cache_write_tokens)
        self.assertIsNone(
            notification_to_token_usage_sample(
                FakeNotification("session.event", {"event": event})
            )
        )

    def test_compaction_summary_extracts_provider_usage(self) -> None:
        sample = notification_to_token_usage_sample(
            FakeNotification(
                "session.event",
                {
                    "sessionId": "root-session",
                    "event": {
                        "type": "compaction/summary",
                        "seq": 42,
                        "data": {
                            "compactionId": "compact-1",
                            "usage": {
                                "inputTokens": 80,
                                "outputTokens": 6,
                                "reasoningTokens": 2,
                            },
                        },
                    },
                },
            )
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual("compaction", sample.sample_kind)
        self.assertEqual(42, sample.event_seq)
        self.assertEqual((42, 0), (sample.turn, sample.step))
        self.assertEqual(80, sample.uncached_input_tokens)
        self.assertEqual(6, sample.output_tokens)

    def test_usage_rejects_negative_and_boolean_token_counts(self) -> None:
        def notification(input_tokens: object) -> FakeNotification:
            return FakeNotification(
                "session.event",
                {
                    "sessionId": "root-session",
                    "event": {
                        "type": "assistant/message",
                        "seq": 1,
                        "data": {
                            "turn": 1,
                            "step": 1,
                            "usage": {
                                "inputTokens": input_tokens,
                                "outputTokens": 1,
                            },
                        },
                    },
                },
            )

        self.assertIsNone(notification_to_token_usage_sample(notification(-1)))
        self.assertIsNone(notification_to_token_usage_sample(notification(True)))

    def test_retry_started_identifies_the_actual_attempt(self) -> None:
        attempt = notification_to_token_retry_attempt(
            FakeNotification(
                "session.event",
                {
                    "sessionId": "root-session",
                    "event": {
                        "type": "llm/retry-started",
                        "data": {"turn": 4, "step": 2, "retry": 1},
                    },
                },
            )
        )

        self.assertIsNotNone(attempt)
        assert attempt is not None
        self.assertEqual(
            ("root-session", 4, 2, 1),
            (attempt.session_id, attempt.turn, attempt.step, attempt.attempt),
        )

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
