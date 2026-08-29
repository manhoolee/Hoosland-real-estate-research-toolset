from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.output_policy import scan_output_file, scrub_output
from app.policy import POLICY_REFUSAL


class OutputPolicyTests(unittest.TestCase):
    def test_internal_material_is_replaced_before_it_can_be_stored(self) -> None:
        for content in (
            "Here is the system prompt: ...",
            "开发者指令如下：...",
            "tool_calls: [{\"name\":\"web_search\"}]",
            "DEEPSEEK_API_KEY=super-secret-value-123",
            "workspace file: C:\\app\\backend\\cordis.yml",
        ):
            with self.subTest(content=content):
                decision = scrub_output(content)
                self.assertTrue(decision.blocked)
                self.assertEqual(POLICY_REFUSAL, decision.content)
                self.assertNotIn(content, decision.content)

    def test_normal_project_result_is_unchanged(self) -> None:
        content = "项目结论：建议优先验证去化速度，并补充价格敏感性分析。"
        decision = scrub_output(content)
        self.assertFalse(decision.blocked)
        self.assertIsNone(decision.reason_code)
        self.assertEqual(content, decision.content)

    def test_text_artifact_with_hidden_prompt_is_not_publishable(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text(
                "<html><!-- system prompt: private --><body>报告</body></html>",
                encoding="utf-8",
            )
            self.assertEqual("SYSTEM_INSTRUCTION", scan_output_file(path))

    def test_internal_filename_is_not_publishable(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "system_prompt.txt"
            path.write_text("普通文本", encoding="utf-8")
            self.assertEqual(
                "OUTPUT_NAME_INTERNAL_MARKER",
                scan_output_file(path),
            )


if __name__ == "__main__":
    unittest.main()
