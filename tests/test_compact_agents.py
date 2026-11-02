"""Keep installed agent instructions concise without losing critical gates."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CompactAgentInstructionsTests(unittest.TestCase):
    def test_shared_git_and_security_contract(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for rule in (
            "git fetch",
            "Create worktrees only when the user explicitly requests one.",
            "Conventional Commits",
            "Never force-push unless the user explicitly requests it.",
            "Never commit secrets or private information",
            "Display secrets or private information only when the user explicitly requests those details.",
            "temp/",
            ".gitignore",
            "PowerShell 7",
            "temp/task-plans/",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)

    def test_only_work_inline_policy_uses_path_conditions(self):
        shared = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        router = (ROOT / "profiles/work/AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("Runtime account policy", shared)
        self.assertNotIn("{{PRIVATE_ROOT}}", shared)
        self.assertNotIn("Policy before work", shared)
        for rule in ("path component", "{{PRIVATE_ROOT}}", "git rev-parse --show-toplevel"):
            self.assertIn(rule, router)
        for obsolete in ("WORK.md", "PRIVATE.md", "standalone tool call", "read the selected policy"):
            self.assertNotIn(obsolete, router)

    def test_account_rules_are_inline_and_keep_work_personal_access_distinct(self):
        work = (ROOT / "profiles/work/AGENTS.md").read_text(encoding="utf-8")
        inline_private = (ROOT / "profiles/private/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("corporate Git identity", work)
        self.assertIn("personal accounts", work)
        self.assertIn("personal Git identity", work)
        self.assertIn("installed `access-personal` access file", work)
        self.assertIn("file helper for SSH", work)
        self.assertIn("Webex CLI", work)
        self.assertIn("send messages only when explicitly requested", work)
        self.assertFalse((ROOT / "profiles/work/WORK.md").exists())
        self.assertFalse((ROOT / "profiles/work/PRIVATE.md").exists())
        self.assertIn("personal Git identity", inline_private)

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
