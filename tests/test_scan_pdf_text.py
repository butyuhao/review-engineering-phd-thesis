from __future__ import annotations

import importlib.util
import sys
import tempfile
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
    def test_extractable_text_estimate(self) -> None:
        total, cjk, latin = MODULE.extractable_text_estimate("桥梁模型 Model-1 达到 95.2 percent")
        self.assertEqual(cjk, 6)
        self.assertEqual(latin, 3)
        self.assertEqual(total, 9)

    def test_page_size_parser_accepts_named_and_numeric_sizes(self) -> None:
        self.assertTrue(MODULE.is_a4("595.276 x 841.89 pts (A4)"))
        self.assertTrue(MODULE.is_a4("595 x 842 pts"))
        self.assertFalse(MODULE.is_a4("612 x 792 pts (letter)"))
        self.assertTrue(MODULE.matches_expected_page_size("612 x 792 pts", "Letter"))

    def test_non_a4_is_not_a_finding_without_expected_size(self) -> None:
        info = "Pages: 1\nPage size: 612 x 792 pts (letter)\nEncrypted: no\n"
        text = "正文内容足够。\f"

        def fake_output(args: list[str]) -> str:
            return info if args[0] == "pdfinfo" else text

        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/mock"), patch.object(MODULE, "command_output", side_effect=fake_output):
            findings, summary = MODULE.scan_pdf(Path("mock.pdf"), low_text_threshold=0)

        self.assertNotIn("unexpected-page-size", {item.check_id for item in findings})
        self.assertIsNone(summary["expected_page_size"])
        self.assertTrue(any("未提供期望页面尺寸" in item for item in summary["diagnostics"]))

    def test_expected_a4_mismatch_is_candidate_not_final_severity(self) -> None:
        info = "Pages: 1\nPage size: 612 x 792 pts (letter)\nEncrypted: no\n"
        text = "正文内容足够。\f"

        def fake_output(args: list[str]) -> str:
            return info if args[0] == "pdfinfo" else text

        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/mock"), patch.object(MODULE, "command_output", side_effect=fake_output):
            findings, summary = MODULE.scan_pdf(Path("mock.pdf"), low_text_threshold=0, expected_page_size="A4")

        mismatch = [item for item in findings if item.check_id == "unexpected-page-size"]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0].status, "candidate")
        self.assertFalse(hasattr(mismatch[0], "severity"))
        self.assertFalse(summary["page_size_matches_expected"])

    def test_scan_pdf_uses_low_text_pages_only_as_navigation(self) -> None:
        info = "Pages: 2\nPage size: 595.276 x 841.89 pts (A4)\nEncrypted: no\nFile size: 100 bytes\nPDF version: 1.7\n"
        text = "材料性能结果完整，正文内容足够。\fTODO\f"

        def fake_output(args: list[str]) -> str:
            return info if args[0] == "pdfinfo" else text

        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/mock"), patch.object(MODULE, "command_output", side_effect=fake_output):
            findings, summary = MODULE.scan_pdf(Path("mock.pdf"), low_text_threshold=10)

        found = {item.check_id for item in findings}
        self.assertIn("visible-draft-marker", found)
        self.assertNotIn("low-text-pages", found)
        self.assertEqual(summary["visual_navigation"]["low_text_pages"], [2])
        self.assertIsNone(summary["sha256"])

    def test_garbled_text_is_text_layer_candidate(self) -> None:
        info = "Pages: 1\nPage size: 595 x 842 pts\nEncrypted: no\n"
        text = "正文�内容\f"

        def fake_output(args: list[str]) -> str:
            return info if args[0] == "pdfinfo" else text

        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/mock"), patch.object(MODULE, "command_output", side_effect=fake_output):
            findings, _ = MODULE.scan_pdf(Path("mock.pdf"), low_text_threshold=0)

        garbled = [item for item in findings if item.check_id == "text-layer-garbled"]
        self.assertEqual(len(garbled), 1)
        self.assertEqual(garbled[0].confidence, "medium")
        self.assertIn("视觉", garbled[0].confirmation_action)

    def test_page_extraction_mismatch_is_diagnostic_not_finding(self) -> None:
        info = "Pages: 5\nPage size: 595 x 842 pts\nEncrypted: no\n"
        text = "第一页\f第二页\f"

        def fake_output(args: list[str]) -> str:
            return info if args[0] == "pdfinfo" else text

        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/mock"), patch.object(MODULE, "command_output", side_effect=fake_output):
            findings, summary = MODULE.scan_pdf(Path("mock.pdf"), low_text_threshold=0)

        self.assertNotIn("page-extraction-mismatch", {item.check_id for item in findings})
        self.assertTrue(any("工具诊断" in item for item in summary["diagnostics"]))

    def test_file_sha256_is_opt_in_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pdf"
            path.write_bytes(b"thesis")
            first = MODULE.file_sha256(path)
            second = MODULE.file_sha256(path)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
