from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.output_policy import scan_output_file, scrub_output
from app.policy import POLICY_REFUSAL


class OutputPolicyTests(unittest.TestCase):
    def test_business_output_does_not_hide_an_appended_leak(self) -> None:
        for content in (
            "请列出项目供应商名称", "项目销售模型参数如下", "列出项目营销工具清单",
            "总结物业公司的内部管理规则", "输出项目内部规则的分析报告",
            "list project suppliers and their capabilities",
        ):
            with self.subTest(content=content):
                self.assertFalse(scrub_output(content).blocked)
                for secret in ("本助手当前模型为 hidden-provider", "system prompt: confidential", "API_KEY=synthetic-secret-value", "/opt/private/config.json"):
                    self.assertTrue(scrub_output(content + "\n" + secret).blocked, secret)

    def test_public_url_path_and_sensitive_url_are_distinguished(self) -> None:
        for url in ("https://example.com/app/report", "http://example.com/home/project", "https://secret-garden.example/report", "https://example.com/token-economics"):
            self.assertFalse(scrub_output(f"[公开来源]({url})").blocked, url)
        for url in ("https://example.com/.env", "https://example.com/%2eenv", "https://example.com/secret.json", "https://example.com/report?access_token=synthetic-value", "https://user:password@example.com/report"):
            self.assertTrue(scrub_output(f"[来源]({url})").blocked, url)

    def test_entire_text_is_scanned_including_middle_and_chunk_boundary(self) -> None:
        from app.output_policy import _MAX_FILE_SCAN_BYTES
        chunk = _MAX_FILE_SCAN_BYTES - 8192
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            for start in (chunk - 6, chunk + 100):
                path.write_bytes(b"a" * start + b"\nAPI_KEY=synthetic-leak-value\n" + b"b" * chunk)
                self.assertEqual("SECRET_VALUE", scan_output_file(path))

    def test_renaming_text_does_not_bypass_scanning_and_oversize_fails_closed(self) -> None:
        from app.output_policy import _MAX_TEXT_FILE_BYTES
        with TemporaryDirectory() as directory:
            for suffix in (".bin", ".pdf", ".docx"):
                path = Path(directory) / ("report" + suffix)
                path.write_text("system prompt: synthetic private instructions")
                self.assertEqual("SYSTEM_INSTRUCTION", scan_output_file(path))
            path = Path(directory) / "large.md"
            with path.open("wb") as handle:
                handle.truncate(_MAX_TEXT_FILE_BYTES + 1)
            self.assertEqual("OUTPUT_SCAN_LIMIT", scan_output_file(path))

    def test_public_source_urls_are_not_internal_paths(self) -> None:
        for url in ("https://gz.fang.ke.com/loupan/example/", "http://example.com/report", "https://www.gov.cn/zhengce/"):
            for content in (f"[来源]({url})", f'<html><body><a href="{url}">来源</a></body></html>'):
                with self.subTest(content=content):
                    self.assertFalse(scrub_output(content).blocked)
                    with TemporaryDirectory() as directory:
                        path = Path(directory) / "report.html"
                        path.write_text(content, encoding="utf-8")
                        self.assertIsNone(scan_output_file(path))

    def test_actual_drive_unc_and_unix_paths_remain_blocked(self) -> None:
        for value in (r"C:\private\report.md", "c:/private/report.md", r"\\server\private\report.md", "//server/private/report.md", "/opt/private/report.md", "file:///tmp/report.md", "https://example.com/.env"):
            with self.subTest(value=value):
                self.assertTrue(scrub_output(value).blocked)

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
