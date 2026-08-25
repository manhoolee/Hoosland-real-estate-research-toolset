from __future__ import annotations

import unittest
from unittest.mock import patch

from app.pdf_runtime import pdf_runtime_status


class PdfRuntimeTests(unittest.TestCase):
    def test_ready_when_persistent_commands_poppler_and_pypdf_exist(self) -> None:
        with (
            patch("app.pdf_runtime.shutil.which", return_value="/installed/tool"),
            patch("app.pdf_runtime._module_available", return_value=True),
        ):
            status = pdf_runtime_status()
        self.assertTrue(status["configured"])
        self.assertEqual("configured", status["status"])
        self.assertIsNone(status["reason"])

    def test_missing_poppler_blocks_direct_pdf_readiness(self) -> None:
        def which(name: str) -> str | None:
            return None if name == "pdftoppm" else f"/installed/{name}"

        with (
            patch("app.pdf_runtime.shutil.which", side_effect=which),
            patch("app.pdf_runtime._module_available", return_value=True),
        ):
            status = pdf_runtime_status()
        self.assertFalse(status["configured"])
        self.assertEqual("dependency_missing", status["status"])
        self.assertIn("pdftoppm", status["reason"])

    def test_optional_python_modules_do_not_block_renderer(self) -> None:
        with (
            patch("app.pdf_runtime.shutil.which", return_value="/installed/tool"),
            patch(
                "app.pdf_runtime._module_available",
                side_effect=lambda name: name == "pypdf",
            ),
        ):
            status = pdf_runtime_status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["python_modules"]["reportlab"])
        self.assertFalse(status["python_modules"]["pdfplumber"])


if __name__ == "__main__":
    unittest.main()
