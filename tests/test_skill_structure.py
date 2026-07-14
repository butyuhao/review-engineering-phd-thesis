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

    def test_required_shared_rules_exist_and_are_linked(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "shared/checklist.md",
            "shared/discipline-adaptation.md",
            "shared/severity-rules.md",
            "shared/report-template.md",
        )
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertIn(relative, skill)

    def test_openai_interface_metadata_is_present(self) -> None:
        text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^interface:\s*$")
        self.assertRegex(text, r"(?m)^\s+display_name:\s*\S.+$")
        self.assertRegex(text, r"(?m)^\s+short_description:\s*\S.+$")
        self.assertRegex(text, r"(?m)^\s+default_prompt:\s*\S.+$")

    def test_claude_adapter_uses_shared_rules(self) -> None:
        text = (ROOT / "claude_code" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("../shared/checklist.md", text)
        self.assertIn("../shared/discipline-adaptation.md", text)


if __name__ == "__main__":
    unittest.main()
