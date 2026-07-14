from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scan_pdf_text", ROOT / "scripts" / "scan_pdf_text.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PdfScannerTests(unittest.TestCase):
    def test_word_like_count(self) -> None:
        total, cjk, latin = MODULE.word_like_count("桥梁模型 Model-1 达到 95.2 percent")
        self.assertEqual(cjk, 6)
        self.assertEqual(latin, 3)
        self.assertEqual(total, 9)

    def test_a4_parser_accepts_named_and_numeric_sizes(self) -> None:
        self.assertTrue(MODULE.is_a4("595.276 x 841.89 pts (A4)"))
        self.assertTrue(MODULE.is_a4("595 x 842 pts"))
        self.assertFalse(MODULE.is_a4("612 x 792 pts (letter)"))

    def test_scan_pdf_uses_mocked_system_commands(self) -> None:
        info = "Pages: 2\nPage size: 595.276 x 841.89 pts (A4)\nEncrypted: no\nFile size: 100 bytes\nPDF version: 1.7\n"
        text = "材料性能结果完整，正文内容足够。\fTODO\f"

        def fake_output(args: list[str]) -> str:
            return info if args[0] == "pdfinfo" else text

        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/mock"), patch.object(MODULE, "command_output", side_effect=fake_output):
            findings, summary = MODULE.scan_pdf(Path("mock.pdf"), low_text_threshold=10)

        codes = {item.code for item in findings}
        self.assertTrue(summary["is_a4"])
        self.assertIn("draft-marker", codes)
        self.assertIn("low-text-pages", codes)


if __name__ == "__main__":
    unittest.main()
