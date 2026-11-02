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
        (repo / "work" / "AGENTS.md").write_text(
            "Select PRIVATE.md below {{PRIVATE_ROOT}}; otherwise WORK.md.\n", encoding="utf-8"
        )
        (repo / "work" / "WORK.md").write_text("work account rule\n", encoding="utf-8")
        (repo / "work" / "PRIVATE.md").write_text("personal account rule\n", encoding="utf-8")
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
                "work_fragments": ["work/WORK.md"],
                "private_fragments": ["work/PRIVATE.md"],
                "projects_fragments": ["bots/AGENTS.md"],
            },
            "profiles": {
                "work": {"instruction_layout": "split", "global_fragments": ["AGENTS.md", "work/AGENTS.md"], "projects_fragments": ["bots/AGENTS.md"], "skills": ["example"]},
                "private": {"instruction_layout": "inline", "global_fragments": ["AGENTS.md", "private/AGENTS.md"], "projects_fragments": ["bots/AGENTS.md"], "skills": ["example"]},
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
            self.assertEqual("work account rule\n", (args.repo / "work" / "WORK.md").read_text(encoding="utf-8"))
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

    def test_projects_rule_source_uses_default_and_custom_target_roots(self):
        for command in ("install", "sync-instructions"):
            for profile in ("work", "private"):
                for custom_root in (False, True):
                    with self.subTest(command=command, profile=profile, custom_root=custom_root), tempfile.TemporaryDirectory() as raw:
                        root = Path(raw)
                        fixture = self._fixture(root)
                        source = "shared rule\nRead {{PROJECTS_ROOT}}/AGENTS.md before bot work.\n"
                        (fixture.repo / "AGENTS.md").write_text(source, encoding="utf-8")
                        cli = [
                            command, "--profile", profile, "--repo", str(fixture.repo),
                            "--home", str(fixture.home), "--skills-root", str(fixture.skills_root),
                            "--project-root", str(fixture.repo),
                        ]
                        if custom_root:
                            cli += ["--projects-root", str(root / "custom workspace")]
                        with mock.patch.object(Path, "home", return_value=root / "user"):
                            args = manage.build_parser().parse_args(cli)
                        expected_root = root / ("custom workspace" if custom_root else "user/Projects")
                        self.assertEqual(expected_root, args.projects_root)
                        args.home.mkdir()
                        foreign = "<!-- codex-profiles:begin -->\nother manager policy\n<!-- codex-profiles:end -->"
                        (args.home / "AGENTS.md").write_text("user home prose\n\n" + foreign + "\n", encoding="utf-8")
                        args.projects_root.mkdir(parents=True)
                        (args.projects_root / "AGENTS.md").write_text(
                            "user project prose\n\n<!-- codex-config:projects:begin -->\n"
                            "bot rule\n<!-- codex-config:projects:end -->\n", encoding="utf-8"
                        )

                        args.handler(args)

                        installed = (args.home / "AGENTS.md").read_text(encoding="utf-8")
                        self.assertIn(f"Read {expected_root.resolve().as_posix()}/AGENTS.md before bot work.", installed)
                        self.assertNotIn("{{PROJECTS_ROOT}}", installed)
                        self.assertIn("user home prose", installed)
                        self.assertIn(foreign, installed)
                        self.assertIn("user project prose", (args.projects_root / "AGENTS.md").read_text(encoding="utf-8"))
                        self.assertIn("bot rule", (args.projects_root / "AGENTS.md").read_text(encoding="utf-8"))
                        self.assertEqual(profile == "work", (args.home / "WORK.md").exists())
                        self.assertEqual(profile == "work", (args.home / "PRIVATE.md").exists())
                        self.assertEqual(source, (args.repo / "AGENTS.md").read_text(encoding="utf-8"))

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

    def test_fresh_private_install_capture_status_remove_uses_only_inline_policy(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            args.profile = "private"
            manage.install_command(args)
            agents = (args.home / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("shared rule", agents)
            self.assertIn("personal account rule", agents)
            self.assertNotIn("work account rule", agents)
            self.assertNotIn("Select PRIVATE.md", agents)
            self.assertFalse((args.home / "WORK.md").exists())
            self.assertFalse((args.home / "PRIVATE.md").exists())
            state = manage.load_state(args.home)
            self.assertEqual({"global", "projects"}, set(state["instruction_block_sha256"]))
            with mock.patch("builtins.print") as output:
                manage.status_command(args)
            self.assertTrue(json.loads(output.call_args.args[0])["healthy"])
            (args.home / "AGENTS.md").write_text(
                agents.replace("personal account rule", "updated personal account rule"), encoding="utf-8"
            )
            manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))
            self.assertEqual("shared rule\n", (args.repo / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("updated personal account rule\n", (args.repo / "private" / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertNotIn("personal", (args.repo / "work" / "AGENTS.md").read_text(encoding="utf-8"))
            manage.remove_command(args)
            self.assertFalse((args.home / "AGENTS.md").exists())

    def _install_legacy_split_private(self, args):
        path = args.repo / "manifest.json"
        current_manifest = json.loads(path.read_text(encoding="utf-8"))
        legacy = json.loads(json.dumps(current_manifest))
        for config in legacy["profiles"].values():
            config.pop("instruction_layout")
        (args.repo / "AGENTS.md").write_text(
            "shared rule\n\nSelect PRIVATE.md below {{PRIVATE_ROOT}}; otherwise WORK.md.\n", encoding="utf-8"
        )
        path.write_text(json.dumps(legacy), encoding="utf-8")
        args.profile = "private"
        manage.install_command(args)
        (args.repo / "AGENTS.md").write_text("shared rule\n", encoding="utf-8")
        path.write_text(json.dumps(current_manifest), encoding="utf-8")

    def test_private_split_migration_preserves_other_manager_and_user_content(self):
        for command in (manage.install_command, manage.sync_instructions_command):
            with self.subTest(command=command.__name__), tempfile.TemporaryDirectory() as raw:
                args = self._fixture(Path(raw))
                self._install_legacy_split_private(args)
                foreign = "<!-- codex-profiles:begin -->\nother manager policy\n<!-- codex-profiles:end -->"
                work = args.home / "WORK.md"
                work.write_text("user policy\n\n" + work.read_text(encoding="utf-8") + "\n" + foreign + "\n", encoding="utf-8")
                global_path = args.home / "AGENTS.md"
                global_path.write_text(global_path.read_text(encoding="utf-8") + "\n" + foreign + "\n", encoding="utf-8")
                before = {path: path.read_bytes() for path in args.home.rglob("*") if path.is_file()}
                with mock.patch("builtins.print") as output:
                    command(argparse.Namespace(**{**vars(args), "dry_run": True}))
                result = json.loads(output.call_args.args[0])
                changed = result.get("files_changed", result.get("instruction_files_changed"))
                self.assertTrue(changed["work"])
                self.assertTrue(changed["private"])
                self.assertEqual(before, {path: path.read_bytes() for path in args.home.rglob("*") if path.is_file()})
                command(args)
                self.assertEqual("user policy\n\n" + foreign + "\n", work.read_text(encoding="utf-8"))
                self.assertFalse((args.home / "PRIVATE.md").exists())
                agents = global_path.read_text(encoding="utf-8")
                self.assertIn("personal account rule", agents)
                self.assertNotIn("Select PRIVATE.md", agents)
                self.assertIn(foreign, agents)
                self.assertLess(agents.index("<!-- codex-config:begin -->"), agents.index("<!-- codex-profiles:begin -->"))
                self.assertEqual({"global", "projects"}, set(manage.load_state(args.home)["instruction_block_sha256"]))
                manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))
                self.assertEqual("shared rule\n", (args.repo / "AGENTS.md").read_text(encoding="utf-8"))
                self.assertEqual("personal account rule\n", (args.repo / "private" / "AGENTS.md").read_text(encoding="utf-8"))
                manage.remove_command(args)
                self.assertEqual("user policy\n\n" + foreign + "\n", work.read_text(encoding="utf-8"))
                self.assertEqual(foreign + "\n", global_path.read_text(encoding="utf-8"))

    def test_capture_requires_matching_layout_before_writing_any_sources(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            self._install_legacy_split_private(args)
            paths = [args.repo / name for name in ("AGENTS.md", "work/AGENTS.md", "work/WORK.md", "work/PRIVATE.md", "private/AGENTS.md")]
            before = {path: path.read_bytes() for path in paths}
            with self.assertRaisesRegex(manage.ConfigError, "source markers"):
                manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))
            self.assertEqual(before, {path: path.read_bytes() for path in paths})

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
