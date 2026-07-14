from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("scan_latex_thesis", ROOT / "scripts" / "scan_latex_thesis.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LatexScannerTests(unittest.TestCase):
    def test_materials_fixture_has_no_blocking_findings(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "materials"
        findings, summary = MODULE.scan_project(fixture)
        self.assertEqual(summary["tex_files"], 1)
        self.assertEqual(summary["bib_files"], 1)
        self.assertFalse([item for item in findings if item.severity == "P0"])
        self.assertFalse([item for item in findings if item.code == "unreferenced-object"])

    def test_civil_fixture_detects_cross_reference_and_style_risks(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "civil"
        findings, _ = MODULE.scan_project(fixture)
        codes = {item.code for item in findings}
        self.assertIn("duplicate-label", codes)
        self.assertIn("missing-label-target", codes)
        self.assertIn("missing-bib-entry", codes)
        self.assertIn("missing-label", codes)
        self.assertIn("unreferenced-object", codes)
        self.assertIn("mixed-caption-punctuation", codes)
        self.assertIn("mixed-paragraph-punctuation", codes)
        self.assertIn("draft-marker", codes)

    def test_configurable_retired_term(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "materials"
        findings, _ = MODULE.scan_project(fixture, [("两步烧结工艺", "分步烧结工艺")])
        retired = [item for item in findings if item.code == "retired-term"]
        self.assertEqual(len(retired), 1)
        self.assertIn("分步烧结工艺", retired[0].message)

    def test_comment_stripping_preserves_escaped_percent(self) -> None:
        text = "保留 10\\% 数值 % 删除注释\n下一行\n"
        cleaned = MODULE.strip_comments(text)
        self.assertIn("10\\%", cleaned)
        self.assertNotIn("删除注释", cleaned)
        self.assertEqual(cleaned.count("\n"), text.count("\n"))

    def test_citations_without_bibliography_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text("\\documentclass{book}\\begin{document}参见 \\citep{missing}。\\end{document}", encoding="utf-8")
            findings, _ = MODULE.scan_project(root)
        self.assertIn("missing-bibliography", {item.code for item in findings})

    def test_appledouble_source_is_ignored_and_reported_as_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text("\\documentclass{book}\\begin{document}正文\\end{document}", encoding="utf-8")
            (root / "._chapter.tex").write_text("�TODO \\ref{missing}", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["tex_files"], 1)
        self.assertEqual(summary["project_artifacts"], 1)
        self.assertIn("project-artifact", {item.code for item in findings})
        self.assertNotIn("garbled-text", {item.code for item in findings})
        self.assertNotIn("draft-marker", {item.code for item in findings})

    def test_build_auxiliary_files_are_reported_without_becoming_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text("\\documentclass{book}\\begin{document}正文\\end{document}", encoding="utf-8")
            (root / "main.aux").write_text("\\newlabel{old}{{1}{1}}", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["project_artifacts"], 1)
        artifacts = [item for item in findings if item.code == "project-artifact"]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].severity, "P3")

    def test_latex_draft_option_is_not_treated_as_draft_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass[draft]{book}\n\\def\\draftfigure{off}\n",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        self.assertNotIn("draft-marker", {item.code for item in findings})

    def test_standalone_draft_marker_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text("DRAFT: 尚未定稿\n", encoding="utf-8")
            findings, _ = MODULE.scan_project(root)
        self.assertIn("draft-marker", {item.code for item in findings})

    def test_subfigure_labels_do_not_require_individual_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                """
\\begin{figure}
\\begin{subfigure}{.4\\linewidth}\\caption{子图}\\label{fig:child}\\end{subfigure}
\\caption{主图}\\label{fig:parent}
\\end{figure}
参见图~\\ref{fig:parent}。
""",
                encoding="utf-8",
            )
            findings, summary = MODULE.scan_project(root)
        unreferenced = [item for item in findings if item.code == "unreferenced-object"]
        self.assertFalse(unreferenced)
        self.assertEqual(summary["floating_objects"], 1)

    def test_git_tracked_artifact_has_higher_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "main.tex").write_text("正文\n", encoding="utf-8")
            (root / ".DS_Store").write_bytes(b"metadata")
            subprocess.run(["git", "-C", str(root), "add", "main.tex", ".DS_Store"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "initial",
                ],
                check=True,
            )
            findings, summary = MODULE.scan_project(root)
        tracked = [item for item in findings if item.code == "tracked-project-artifact"]
        self.assertEqual(summary["tracked_project_artifacts"], 1)
        self.assertEqual(len(tracked), 1)
        self.assertEqual(tracked[0].severity, "P2")

    def test_git_provenance_is_reported_only_for_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "main.tex").write_text("正文\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "main.tex"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "initial",
                ],
                check=True,
            )
            _, root_summary = MODULE.scan_project(root)
            child = root / "child"
            child.mkdir()
            (child / "chapter.tex").write_text("正文\n", encoding="utf-8")
            _, child_summary = MODULE.scan_project(child)
        self.assertEqual(len(root_summary["git"]["head"]), 40)
        self.assertFalse(root_summary["git"]["dirty"])
        self.assertIsNone(child_summary["git"])

    def test_empty_source_duplicate_chapter_and_missing_graphics_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\chapter{方法研究}\n\\includegraphics{figures/missing}\n",
                encoding="utf-8",
            )
            (root / "chapter.tex").write_text("\\chapter{方法研究}\n", encoding="utf-8")
            (root / "empty.tex").write_text("% 只有注释\n", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        codes = {item.code for item in findings}
        self.assertEqual(summary["chapter_titles"], 1)
        self.assertIn("duplicate-chapter-title", codes)
        self.assertIn("missing-graphics-file", codes)
        self.assertIn("empty-source", codes)

    def test_existing_graphics_with_implicit_extension_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figures").mkdir()
            (root / "figures" / "result.pdf").write_bytes(b"%PDF-1.4")
            (root / "main.tex").write_text("\\includegraphics{figures/result}\n", encoding="utf-8")
            findings, _ = MODULE.scan_project(root)
        self.assertNotIn("missing-graphics-file", {item.code for item in findings})


if __name__ == "__main__":
    unittest.main()
