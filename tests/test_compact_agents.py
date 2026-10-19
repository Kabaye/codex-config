"""Keep installed agent instructions concise without losing critical gates."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CompactAgentInstructionsTests(unittest.TestCase):
    def test_instruction_size_budgets(self):
        budgets = {
            "AGENTS.md": 3500,
            "work/AGENTS.md": 850,
            "private/AGENTS.md": 750,
            "bots/AGENTS.md": 3300,
        }
        for path, max_bytes in budgets.items():
            with self.subTest(path=path):
                self.assertLessEqual(
                    len((ROOT / path).read_bytes()), max_bytes,
                    f"{path} should contain concise policies, not explanations",
                )

    def test_shared_git_and_security_contract(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for rule in (
            "git fetch",
            "git status",
            "Conventional Commits",
            "force-push",
            "without explicit authorization",
            "Never print, commit, export, or expose secrets",
            "temp/",
            "PowerShell 7",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_bot_release_and_keyboard_safety(self):
        text = (ROOT / "bots/AGENTS.md").read_text(encoding="utf-8")
        for rule in (
            "exact final message",
            "before deployment",
            "deploy",
            "verify",
            "idempotently",
            "only failed recipients",
            "Reply keyboard",
            "Inline buttons",
            "Forms and editors",
            "do not create a duplicate",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)


if __name__ == "__main__":
    unittest.main()
