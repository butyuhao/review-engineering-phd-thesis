from __future__ import annotations

import importlib.util
import subprocess
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


def codes(findings: list[object]) -> set[str]:
    return {item.check_id for item in findings}


class LatexScannerTests(unittest.TestCase):
    def test_materials_fixture_has_no_high_priority_candidates(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "materials"
        findings, summary = MODULE.scan_project(fixture)
        self.assertEqual(summary["active_tex_files"], 1)
        self.assertEqual(summary["active_bib_files"], 1)
        self.assertFalse([item for item in findings if item.status == "candidate" and item.priority == "high"])
        self.assertNotIn("unreferenced-object", codes(findings))

    def test_civil_fixture_detects_active_reference_and_draft_candidates(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "civil"
        findings, _ = MODULE.scan_project(fixture)
        found = codes(findings)
        self.assertIn("duplicate-label", found)
        self.assertIn("missing-label-target", found)
        self.assertIn("missing-bib-entry", found)
        self.assertIn("unreferenced-object", found)
        self.assertIn("draft-marker", found)
        self.assertNotIn("mixed-caption-punctuation", found)
        self.assertNotIn("mixed-paragraph-punctuation", found)

    def test_all_scanner_outputs_are_candidates_or_coverage_gaps(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "civil"
        findings, _ = MODULE.scan_project(fixture)
        self.assertTrue(findings)
        self.assertTrue(all(item.status in {"candidate", "not_verified"} for item in findings))
        self.assertTrue(all(item.requires_confirmation for item in findings))
        self.assertTrue(all(not hasattr(item, "severity") for item in findings))

    def test_configurable_retired_term(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "materials"
        findings, _ = MODULE.scan_project(fixture, [("两步烧结工艺", "分步烧结工艺")])
        retired = [item for item in findings if item.check_id == "retired-term"]
        self.assertEqual(len(retired), 1)
        self.assertIn("分步烧结工艺", retired[0].message)

    def test_comment_stripping_preserves_escaped_percent(self) -> None:
        text = "保留 10\\% 数值 % 删除注释\n下一行\n"
        cleaned = MODULE.strip_comments(text)
        self.assertIn("10\\%", cleaned)
        self.assertNotIn("删除注释", cleaned)
        self.assertEqual(cleaned.count("\n"), text.count("\n"))

    def test_citations_without_active_bibliography_are_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{book}\\begin{document}参见 \\citep{missing}。\\end{document}",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        self.assertIn("missing-bibliography", codes(findings))

    def test_unloaded_tex_is_excluded_from_all_content_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{book}\\begin{document}正文\\label{ok}\\end{document}",
                encoding="utf-8",
            )
            (root / "unused.tex").write_text(
                "TODO � \\label{dup}\\label{dup}\\ref{missing}",
                encoding="utf-8",
            )
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["active_tex_files"], 1)
        self.assertEqual(summary["inactive_tex_files"], 1)
        self.assertFalse(codes(findings) & {"draft-marker", "garbled-source-text", "duplicate-label", "missing-label-target"})

    def test_unused_bib_cannot_hide_missing_active_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{book}\\begin{document}\\citep{onlyUnused}\\bibliography{active}\\end{document}",
                encoding="utf-8",
            )
            (root / "active.bib").write_text("@article{activeKey, title={A}}", encoding="utf-8")
            (root / "unused.bib").write_text("@article{onlyUnused, title={B}}", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["active_bib_files"], 1)
        self.assertEqual(summary["inactive_bib_files"], 1)
        self.assertIn("missing-bib-entry", codes(findings))

    def test_only_recursively_loaded_sources_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapters").mkdir()
            (root / "main.tex").write_text(
                "\\documentclass{book}\\begin{document}\\input{chapters/one}\\end{document}",
                encoding="utf-8",
            )
            (root / "chapters" / "one.tex").write_text("\\input{two}\nTODO", encoding="utf-8")
            (root / "chapters" / "two.tex").write_text("正文", encoding="utf-8")
            (root / "chapters" / "unused.tex").write_text("FIXME", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["active_tex_files"], 3)
        draft = [item for item in findings if item.check_id == "draft-marker"]
        self.assertEqual(len(draft), 1)
        self.assertEqual(draft[0].path, "chapters/one.tex")

    def test_unresolved_source_macro_is_not_verified_not_missing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{book}\\newcommand{\\chapterfile}{chapter}\\input{\\chapterfile}",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        unresolved = [item for item in findings if item.check_id == "source-dependency-unresolved"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].status, "not_verified")

    def test_appledouble_and_auxiliary_files_are_observed_without_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text("\\documentclass{book}正文", encoding="utf-8")
            (root / "._chapter.tex").write_text("�TODO \\ref{missing}", encoding="utf-8")
            (root / "main.aux").write_text("\\newlabel{old}{{1}{1}}", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["project_artifacts_observed"], 2)
        self.assertNotIn("project-artifact", codes(findings))
        self.assertNotIn("garbled-source-text", codes(findings))

    def test_latex_draft_option_is_not_treated_as_visible_draft_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass[draft]{book}\n\\def\\draftfigure{off}\n",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        self.assertNotIn("draft-marker", codes(findings))

    def test_standalone_draft_marker_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text("DRAFT: 尚未定稿\n", encoding="utf-8")
            findings, _ = MODULE.scan_project(root)
        self.assertIn("draft-marker", codes(findings))

    def test_subfigure_labels_do_not_require_individual_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                r"""
\documentclass{book}
\begin{document}
\begin{figure}
\begin{subfigure}{.4\linewidth}\caption{子图}\label{fig:child}\end{subfigure}
\caption{主图}\label{fig:parent}
\end{figure}
参见图~\ref{fig:parent}。
\end{document}
""",
                encoding="utf-8",
            )
            findings, summary = MODULE.scan_project(root)
        self.assertNotIn("unreferenced-object", codes(findings))
        self.assertEqual(summary["floating_objects_with_labels"], 1)

    def test_git_and_tracked_artifacts_are_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "main.tex").write_text("\\documentclass{book}正文\n", encoding="utf-8")
            (root / ".DS_Store").write_bytes(b"metadata")
            subprocess.run(["git", "-C", str(root), "add", "main.tex", ".DS_Store"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "initial"],
                check=True,
            )
            default_findings, default_summary = MODULE.scan_project(root)
            profile_findings, profile_summary = MODULE.scan_project(root, check_provenance=True)
        self.assertIsNone(default_summary["git"])
        self.assertNotIn("tracked-project-artifact", codes(default_findings))
        self.assertEqual(len(profile_summary["git"]["head"]), 40)
        self.assertIn("tracked-project-artifact", codes(profile_findings))

    def test_empty_loaded_source_and_duplicate_loaded_chapter_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{book}\\input{chapter}\\input{empty}\\chapter{方法研究}",
                encoding="utf-8",
            )
            (root / "chapter.tex").write_text("\\chapter{方法研究}\n", encoding="utf-8")
            (root / "empty.tex").write_text("% 只有注释\n", encoding="utf-8")
            findings, summary = MODULE.scan_project(root)
        self.assertEqual(summary["chapter_titles"], 1)
        self.assertIn("duplicate-chapter-title", codes(findings))
        self.assertIn("empty-active-source", codes(findings))

    def test_existing_graphics_with_implicit_extension_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figures").mkdir()
            (root / "figures" / "result.pdf").write_bytes(b"%PDF-1.4")
            (root / "main.tex").write_text(
                "\\documentclass{book}\\includegraphics{figures/result}\n",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        self.assertNotIn("missing-graphics-file", codes(findings))

    def test_graphicspath_and_declared_extension_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "figures").mkdir()
            (root / "figures" / "plot.webp").write_bytes(b"image")
            (root / "main.tex").write_text(
                "\\documentclass{book}\n\\graphicspath{{figures/}}\n\\DeclareGraphicsExtensions{.webp}\n\\includegraphics{plot}\n",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        self.assertNotIn("missing-graphics-file", codes(findings))

    def test_macro_graphics_path_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                "\\documentclass{book}\\includegraphics{\\figureRoot/plot}\n",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        unresolved = [item for item in findings if item.check_id == "graphics-path-unresolved"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].status, "not_verified")

    def test_caption_formatting_and_punctuation_are_not_automatic_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tex").write_text(
                r"""\documentclass{book}
\begin{figure}\caption{含 \textbf{必要面板标记}。}\label{fig:a}\end{figure}
图~\ref{fig:a}。
\begin{figure}\caption{无句号}\label{fig:b}\end{figure}
图~\ref{fig:b}。
\paragraph{任务设置。}正文
\paragraph{评价指标}正文
""",
                encoding="utf-8",
            )
            findings, _ = MODULE.scan_project(root)
        self.assertFalse(codes(findings) & {"caption-formatting", "mixed-caption-punctuation", "mixed-paragraph-punctuation"})


if __name__ == "__main__":
    unittest.main()
