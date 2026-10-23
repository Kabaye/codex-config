"""Lifecycle checks for mixed-owner instruction files."""

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manage.py"
SPEC = importlib.util.spec_from_file_location("codex_config_manage_instructions", SCRIPT)
assert SPEC and SPEC.loader
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class InstructionLayoutTests(unittest.TestCase):
    def _fixture(self, root: Path):
        repo = root / "repo"
        home = root / "home"
        projects = root / "projects"
        skills = root / "global-skills"
        repo.mkdir()
        (repo / "work").mkdir()
        (repo / "private").mkdir()
        (repo / "bots").mkdir()
        (repo / "AGENTS.md").write_text("shared rule\n", encoding="utf-8")
        (repo / "work" / "AGENTS.md").write_text("work account rule\n", encoding="utf-8")
        (repo / "private" / "AGENTS.md").write_text("personal account rule\n", encoding="utf-8")
        (repo / "bots" / "AGENTS.md").write_text("bot rule\n", encoding="utf-8")
        skill = repo / "skills" / "example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "markers": {
                "global_begin": "<!-- codex-config:begin -->",
                "global_end": "<!-- codex-config:end -->",
                "projects_begin": "<!-- codex-config:projects:begin -->",
                "projects_end": "<!-- codex-config:projects:end -->",
                "work_begin": "<!-- codex-config:begin -->",
                "work_end": "<!-- codex-config:end -->",
                "private_begin": "<!-- codex-config:begin -->",
                "private_end": "<!-- codex-config:end -->",
            },
            "instructions": {
                "global_fragments": ["AGENTS.md"],
                "work_fragments": ["work/AGENTS.md"],
                "private_fragments": ["private/AGENTS.md"],
                "projects_fragments": ["bots/AGENTS.md"],
            },
            "profiles": {
                "work": {"global_fragments": ["AGENTS.md"], "projects_fragments": ["bots/AGENTS.md"], "skills": ["example"]},
                "private": {"global_fragments": ["AGENTS.md"], "projects_fragments": ["bots/AGENTS.md"], "skills": ["example"]},
            },
        }
        (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return argparse.Namespace(
            repo=repo, home=home, projects_root=projects, skills_root=skills,
            project_root=repo, profile="work", dry_run=False, force=False,
        )

    def test_install_capture_remove_preserves_foreign_blocks_and_user_prose(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            profile_block = "<!-- codex-profiles:begin -->\nprofile owner\n<!-- codex-profiles:end -->"
            args.home.mkdir()
            (args.home / "AGENTS.md").write_text("user home prose\n\n" + profile_block + "\n", encoding="utf-8")
            args.projects_root.mkdir()

            manage.install_command(args)
            projects_doc = args.projects_root / "AGENTS.md"
            projects_doc.write_text("user project prose\n\n" + projects_doc.read_text(encoding="utf-8"), encoding="utf-8")
            work_doc = (args.home / "WORK.md").read_text(encoding="utf-8")
            private_doc = (args.home / "PRIVATE.md").read_text(encoding="utf-8")
            self.assertIn("work account rule", work_doc)
            self.assertIn("personal account rule", private_doc)
            self.assertEqual(work_doc.count("<!-- codex-config:begin -->"), 1)
            self.assertEqual(private_doc.count("<!-- codex-config:begin -->"), 1)
            self.assertIn("shared rule", (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn(profile_block, (args.home / "AGENTS.md").read_text(encoding="utf-8"))

            # Changes owned only by codex-profiles do not invalidate our state.
            (args.home / "AGENTS.md").write_text(
                (args.home / "AGENTS.md").read_text(encoding="utf-8").replace("profile owner", "updated profile owner"),
                encoding="utf-8",
            )
            status_args = argparse.Namespace(**vars(args))
            with mock.patch("builtins.print") as output:
                manage.status_command(status_args)
            result = json.loads(output.call_args.args[0])
            self.assertTrue(result["instructions"]["work"])
            self.assertTrue(result["healthy"])

            manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))
            self.assertNotIn(str(args.home), (args.repo / "work" / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("work account rule\n", (args.repo / "work" / "AGENTS.md").read_text(encoding="utf-8"))
            remove_args = argparse.Namespace(**vars(args))
            remove_args.dry_run = False
            manage.remove_command(remove_args)
            self.assertFalse((args.home / "WORK.md").exists())
            self.assertFalse((args.home / "PRIVATE.md").exists())
            self.assertIn("user home prose", (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("updated profile owner", (args.home / "AGENTS.md").read_text(encoding="utf-8"))

    def test_sync_instructions_does_not_touch_skills_or_configuration(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            manage.install_command(args)
            skill_before = (args.skills_root / "example" / "SKILL.md").read_bytes()
            config = args.home / "config.toml"
            config.write_text("model = 'untouched'\n", encoding="utf-8")
            auth = args.home / "auth.json"
            auth.write_text("auth marker\n", encoding="utf-8")
            state_path = args.home / "codex-config" / "state.json"
            state_before = json.loads(state_path.read_text(encoding="utf-8"))
            (args.repo / "AGENTS.md").write_text("new shared rule\n", encoding="utf-8")

            sync_args = argparse.Namespace(**vars(args))
            sync_args.force = False
            manage.sync_instructions_command(sync_args)

            self.assertIn("new shared rule", (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual(skill_before, (args.skills_root / "example" / "SKILL.md").read_bytes())
            self.assertEqual("model = 'untouched'\n", config.read_text(encoding="utf-8"))
            self.assertEqual("auth marker\n", auth.read_text(encoding="utf-8"))
            state_after = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_before["skills"], state_after["skills"])

    def test_custom_private_root_capture_is_portable_and_root_boundary_is_component_based(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            (args.repo / "AGENTS.md").write_text(
                "Resolve {{PRIVATE_ROOT}} and compare path components.\n", encoding="utf-8"
            )
            manage.install_command(args)
            rendered = (args.projects_root / "private").resolve()
            self.assertIn(str(rendered), (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertNotIn(str(Path.home() / "Projects" / "private"), (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))
            self.assertIn("{{PRIVATE_ROOT}}", (args.repo / "AGENTS.md").read_text(encoding="utf-8"))

            root = rendered
            self.assertTrue(manage.is_path_within(root, root))
            self.assertTrue(manage.is_path_within(root / "nested", root))
            self.assertFalse(manage.is_path_within(root.parent / "private-ish", root))
            self.assertTrue(manage.is_path_within(Path(str(root).upper()) / "NESTED", root, windows=True))
            self.assertFalse(manage.is_path_within(root.parent / "private-ish", root, windows=True))

    def test_sync_without_previous_install_creates_reusable_valid_state(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            manage.sync_instructions_command(args)
            state = manage.load_state(args.home)
            self.assertEqual("work", state["profile"])
            self.assertEqual({}, state["skills"])
            self.assertFalse(args.skills_root.exists())
            before = {p: p.read_bytes() for p in args.home.rglob("*") if p.is_file()}
            manage.sync_instructions_command(args)
            self.assertEqual(before, {p: p.read_bytes() for p in args.home.rglob("*") if p.is_file()})

    def test_sync_write_failure_restores_documents_and_state(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            manage.install_command(args)
            files = [args.home / n for n in ("AGENTS.md", "WORK.md", "PRIVATE.md")]
            files += [args.projects_root / "AGENTS.md", manage.state_path(args.home)]
            before = {p: p.read_bytes() for p in files}
            (args.repo / "AGENTS.md").write_text("new shared rule\n", encoding="utf-8")
            original_write = manage.atomic_write_text
            def fail_private(path, value):
                if path == args.home / "PRIVATE.md":
                    raise OSError("synthetic write failure")
                return original_write(path, value)
            with mock.patch.object(manage, "atomic_write_text", side_effect=fail_private):
                with self.assertRaises(OSError):
                    manage.sync_instructions_command(args)
            self.assertEqual(before, {p: p.read_bytes() for p in files})
            self.assertFalse(list((args.home / "codex-config").glob("txn-*")))

    def test_sync_dry_run_rejects_local_owned_block_edit_but_allows_profile_edit(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            args.home.mkdir()
            profile_block = "<!-- codex-profiles:begin -->\nprofile owner\n<!-- codex-profiles:end -->"
            (args.home / "AGENTS.md").write_text(profile_block + "\n", encoding="utf-8")
            args.projects_root.mkdir()
            project_profile = "<!-- codex-profiles:begin -->\nproject profile\n<!-- codex-profiles:end -->"
            (args.projects_root / "AGENTS.md").write_text(project_profile + "\n", encoding="utf-8")
            manage.install_command(args)
            agents = args.home / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8").replace("shared rule", "locally changed"), encoding="utf-8")
            dry = argparse.Namespace(**{**vars(args), "dry_run": True, "force": False})
            with self.assertRaises(manage.ConfigError):
                manage.sync_instructions_command(dry)

            agents.write_text(agents.read_text(encoding="utf-8").replace("locally changed", "shared rule"), encoding="utf-8")
            agents.write_text(agents.read_text(encoding="utf-8").replace("profile owner", "edited profile owner"), encoding="utf-8")
            projects_doc = args.projects_root / "AGENTS.md"
            projects_doc.write_text(projects_doc.read_text(encoding="utf-8").replace("project profile", "edited project profile"), encoding="utf-8")
            with mock.patch("builtins.print") as output:
                manage.sync_instructions_command(dry)
            self.assertIn("edited profile owner", agents.read_text(encoding="utf-8"))
            self.assertIn("edited project profile", projects_doc.read_text(encoding="utf-8"))
            self.assertIn("skills_touched", output.call_args.args[0])

    def test_sync_preserves_legacy_state_and_does_not_adopt_unmanaged_account_docs(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            args.home.mkdir(parents=True)
            state_path = args.home / "codex-config" / "state.json"
            state_path.parent.mkdir(parents=True)
            legacy_state = {
                "schema_version": 1, "profile": "work", "skills": {},
                "project_skills": {}, "source_fingerprint": "0" * 64,
                "global_block_sha256": "0" * 64, "projects_block_sha256": "0" * 64,
            }
            state_path.write_text(json.dumps(legacy_state), encoding="utf-8")
            (args.home / "WORK.md").write_text("user work content\n", encoding="utf-8")
            with self.assertRaises(manage.ConfigError):
                manage.sync_instructions_command(argparse.Namespace(**{**vars(args), "dry_run": True}))

    def test_sync_rolls_back_instruction_files_and_state_after_write_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            manage.install_command(args)
            agents = args.home / "AGENTS.md"
            before_agents = agents.read_bytes()
            state_path = args.home / "codex-config" / "state.json"
            before_state = state_path.read_bytes()
            (args.repo / "AGENTS.md").write_text("changed shared rule\n", encoding="utf-8")
            original_write = manage.atomic_write_text
            calls = 0

            def fail_second(path, value):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated transaction failure")
                original_write(path, value)

            with mock.patch.object(manage, "atomic_write_text", side_effect=fail_second):
                with self.assertRaises(OSError):
                    manage.sync_instructions_command(argparse.Namespace(**vars(args)))
            self.assertEqual(before_agents, agents.read_bytes())
            self.assertEqual(before_state, state_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
