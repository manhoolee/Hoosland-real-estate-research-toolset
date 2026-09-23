import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.delivery import has_report_pair, requires_report_pair


class DeliveryTests(unittest.TestCase):
    def test_report_defaults_and_explicit_exceptions(self):
        self.assertTrue(requires_report_pair("输出研究报告", set()))
        self.assertTrue(requires_report_pair("查找项目信息", {"report.md"}))
        self.assertTrue(requires_report_pair("输出 Markdown 和 HTML", {"report.md"}))
        for request in ("输出pdf文件", "生成 Word 报告", "只要 Markdown 格式", "不要文件，只在聊天中解释"):
            self.assertFalse(requires_report_pair(request, {"report.md"}), request)
        self.assertFalse(requires_report_pair("解释去化率的含义", set()))

    def test_pair_must_be_same_name_current_and_structurally_html(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.html").write_text("<html><body>报告</body></html>")
            self.assertTrue(has_report_pair({"report.md", "report.html"}, root))
            self.assertFalse(has_report_pair({"report.md"}, root))
            self.assertFalse(has_report_pair({"other.md", "report.html"}, root))
            (root / "report.html").write_text("只有路径，无网页正文")
            self.assertFalse(has_report_pair({"report.md", "report.html"}, root))
