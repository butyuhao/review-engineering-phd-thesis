from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillStructureTests(unittest.TestCase):
    def test_root_skill_has_required_frontmatter(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = match.group(1) if match else ""
        self.assertRegex(frontmatter, r"(?m)^name:\s*review-engineering-phd-thesis\s*$")
        self.assertRegex(frontmatter, r"(?m)^description:\s*\S.+$")

    def test_core_rules_exist_and_are_linked(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "shared/core-checklist.md",
            "shared/severity-rules.md",
            "shared/report-template.md",
        )
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertIn(relative, skill)

    def test_paradigms_and_profiles_are_routed_not_loaded_unconditionally(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        resources = (
            "shared/paradigms/algorithm-model.md",
            "shared/paradigms/system-hardware.md",
            "shared/paradigms/experiment-process.md",
            "shared/paradigms/theory-modeling.md",
            "shared/paradigms/application-interdisciplinary.md",
            "profiles/final-pdf.md",
            "profiles/latex-build-and-provenance.md",
            "profiles/blind-review.md",
            "profiles/migration-audit.md",
            "profiles/degree-materials.md",
        )
        for relative in resources:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertIn(relative, skill)
        self.assertIn("Load optional profiles only", skill)
        self.assertNotIn("read all of these files", skill.lower())

    def test_legacy_files_are_only_compatibility_pointers(self) -> None:
        checklist = (ROOT / "shared" / "checklist.md").read_text(encoding="utf-8")
        discipline = (ROOT / "shared" / "discipline-adaptation.md").read_text(encoding="utf-8")
        self.assertLess(len(checklist.splitlines()), 10)
        self.assertLess(len(discipline.splitlines()), 15)
        self.assertIn("兼容", checklist)
        self.assertIn("兼容", discipline)

    def test_openai_interface_metadata_is_present(self) -> None:
        text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^interface:\s*$")
        self.assertRegex(text, r"(?m)^\s+display_name:\s*\S.+$")
        self.assertRegex(text, r"(?m)^\s+short_description:\s*\S.+$")
        self.assertRegex(text, r"(?m)^\s+default_prompt:\s*\S.+$")

    def test_claude_adapter_uses_core_rules_and_profile_routing(self) -> None:
        text = (ROOT / "claude_code" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("../shared/core-checklist.md", text)
        self.assertIn("../profiles/final-pdf.md", text)
        self.assertNotIn("../shared/checklist.md", text)


if __name__ == "__main__":
    unittest.main()
