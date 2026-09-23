from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.intake import (
    IntakeError,
    build_intake,
    classify_task,
    intake_expired,
    merge_prompt,
    validate_answers,
)
from app.storage import ConversationStore


class GuidedIntakeTests(unittest.TestCase):
    def test_classification_is_deterministic_and_bounded(self) -> None:
        self.assertEqual("research", classify_task("请做一个市场竞品研究"))
        self.assertEqual("pdf_output", classify_task("请把报告导出成 PDF"))
        self.assertEqual("pdf_output", classify_task("把微信文章导出成 PDF"))
        self.assertEqual("pdf_output", classify_task("PDF导出"))
        self.assertEqual("pdf_output", classify_task("阅读PDF并导出"))
        self.assertEqual("report_design", classify_task("HTML报告"))
        self.assertEqual("report_editorial", classify_task("请阅读 PDF 后生成报告"))
        self.assertEqual("report_design", classify_task("请分析并输出网页报告"))
        self.assertEqual("report_editorial", classify_task("帮我润色这份报告"))
        self.assertEqual("report_editorial", classify_task("帮我写一份报告"))
        self.assertEqual("report_editorial", classify_task("写报告初稿"))
        self.assertEqual("delivery_qa", classify_task("检查成果文件"))
        self.assertEqual("delivery_qa", classify_task("审阅成果"))
        self.assertEqual("research", classify_task("请分析 PDF 并输出结论"))
        self.assertEqual("research", classify_task("请分析这份 PDF 报告"))
        self.assertEqual("research", classify_task("请分析 PDF 文件"))
        self.assertEqual("research", classify_task("请分析网页数据"))
        self.assertEqual("research", classify_task("请分析网页报告"))
        self.assertEqual("research", classify_task("analyze pdf"))
        self.assertEqual("delivery_qa", classify_task("review delivery files"))
        self.assertEqual("pdf_output", classify_task("convert this report into a pdf"))
        self.assertEqual("report_design", classify_task("analyze PDF then generate a web report"))
        self.assertEqual("report_design", classify_task("请生成一个网页报告"))
        self.assertEqual("social_promotion", classify_task("请改成小红书内容"))
        self.assertEqual("research", classify_task("请分析附件", attachment_ids=["file_1"]))

    def test_build_intake_has_small_allow_list_and_expiry(self) -> None:
        record = build_intake("请做市场研究")
        self.assertTrue(record["intake_id"].startswith("intake_"))
        self.assertLessEqual(len(record["questions"]), 3)
        self.assertTrue(all(2 <= len(item["options"]) <= 4 for item in record["questions"]))
        self.assertGreater(
            datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00")),
            datetime.now(UTC),
        )

    def test_answers_accept_scalar_array_and_custom_text(self) -> None:
        record = build_intake("请做市场研究")
        mapping_answers = {
            question["id"]: [question["options"][0]["id"]]
            for question in record["questions"]
        }
        normalized = validate_answers(record, mapping_answers)
        self.assertEqual(3, len(normalized))
        self.assertTrue(all(item["option_ids"] for item in normalized))

        list_answers = [
            {
                "question_id": question["id"],
                "option_ids": [question["options"][0]["id"]],
                **({"custom_text": "优先关注现金流"} if index == 0 else {}),
            }
            for index, question in enumerate(record["questions"])
        ]
        normalized_list = validate_answers(record, list_answers)
        self.assertEqual("优先关注现金流", normalized_list[0]["custom_text"])

    def test_invalid_or_incomplete_answers_are_rejected_without_mutating_record(self) -> None:
        record = build_intake("请做市场研究")
        with self.assertRaisesRegex(IntakeError, "未提供的选项"):
            validate_answers(
                record,
                {question["id"]: question["options"][0]["id"] for question in record["questions"][:-1]}
                | {record["questions"][-1]["id"]: "not-an-option"},
            )
        with self.assertRaisesRegex(IntakeError, "所有必答"):
            validate_answers(record, {})
        self.assertEqual("awaiting_input", record["status"])

    def test_skip_preserves_original_and_confirmed_prompt_contains_choices(self) -> None:
        record = build_intake("请做市场研究")
        answers = validate_answers(
            record,
            {
                question["id"]: question["options"][0]["id"]
                for question in record["questions"]
            },
        )
        self.assertEqual(record["original_content"], merge_prompt(record["original_content"], record, [], action="skip"))
        merged = merge_prompt(record["original_content"], record, answers, action="confirm")
        self.assertIn("[已确认选项]", merged)
        self.assertIn(record["original_content"], merged)
        self.assertIn(answers[0]["label"], merged)

    def test_skip_ignores_accidental_answer_payload(self) -> None:
        record = build_intake("请做市场研究")
        # A bypass action must remain a verbatim legacy run even if an
        # integration accidentally forwards stale/malformed answer data.
        self.assertEqual(
            record["original_content"],
            merge_prompt(
                record["original_content"],
                record,
                {"unexpected": {"option_ids": ["stale"]}},
                action="skip",
            ),
        )

    def test_skip_still_bounds_answer_container(self) -> None:
        record = build_intake("请做市场研究")
        with self.assertRaisesRegex(IntakeError, "答案项过多"):
            validate_answers(
                record,
                {f"q-{index}": "ignored" for index in range(33)},
                action="skip",
            )

    def test_expiry_helper_handles_expired_and_live_records(self) -> None:
        now = datetime.now(UTC)
        self.assertTrue(intake_expired({"expires_at": (now - timedelta(seconds=1)).isoformat()}))
        self.assertFalse(intake_expired({"expires_at": (now + timedelta(seconds=1)).isoformat()}))


class GuidedIntakeStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temporary.name) / "conversations")
        self.conversation_id = "conversation_intake_001"
        self.store.create_or_reuse(self.conversation_id)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sidecar_round_trip_and_atomic_consume(self) -> None:
        record = build_intake("请做市场研究")
        self.store.write_pending_intake(self.conversation_id, record)
        self.assertEqual(record["intake_id"], self.store.read_pending_intake(self.conversation_id)["intake_id"])
        consumed = self.store.consume_pending_intake(
            self.conversation_id,
            intake_id=record["intake_id"],
            content_sha256=record["content_sha256"],
            attachment_ids=[],
        )
        self.assertEqual(record["intake_id"], consumed["intake_id"])
        self.assertIsNone(self.store.read_pending_intake(self.conversation_id))

    def test_missing_expiry_is_fail_closed_and_does_not_block_refresh(self) -> None:
        paths = self.store.require(self.conversation_id)
        for expiry in (None, "not-a-timestamp", 123):
            record = build_intake("请做市场研究")
            if expiry is None:
                record.pop("expires_at")
            else:
                record["expires_at"] = expiry
            paths.pending_intake.write_text(
                json.dumps(record, ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertIsNone(self.store.read_live_pending_intake(self.conversation_id))
            self.assertFalse(paths.pending_intake.exists())
