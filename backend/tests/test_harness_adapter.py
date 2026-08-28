from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.harness_adapter import (
    SKILL_COMMAND,
    build_harness_prompt,
    notification_to_operation_event,
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
        prompt = build_harness_prompt(
            "请只做这个项目的竞品市场研究",
            [{"workspace_path": "inputs/file_a--plan.pdf", "name": "plan.pdf"}],
        )
        self.assertTrue(prompt.startswith(f"{SKILL_COMMAND}\n\n[总控激活]\n"))
        self.assertEqual(SKILL_COMMAND, prompt.splitlines()[0])
        self.assertEqual(
            [SKILL_COMMAND],
            re.findall(r"(?m)^/[A-Za-z0-9_-]+$", prompt),
        )
        headers = [
            "[总控激活]",
            "[交付策略]",
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
        self.assertIn("inputs/file_a--plan.pdf", prompt)
        self.assertIn('"可用状态":"可用"', prompt)
        self.assertNotIn("专业联网搜索（Bocha）", prompt)
        self.assertNotIn("hoosland-pdf-render", prompt)
        self.assertNotIn("客户可见输出纪律", prompt)
        self.assertTrue(prompt.endswith('{"content":"请只做这个项目的竞品市场研究"}'))

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
        self.assertEqual(1, cordis.count("real-estate-system-v0.2.1"))
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
