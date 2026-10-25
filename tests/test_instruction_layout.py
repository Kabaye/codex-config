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
        (repo / "work" / "ROUTER.md").write_text(
            "Select PRIVATE.md below {{PRIVATE_ROOT}}; otherwise WORK.md.\n", encoding="utf-8"
        )
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
                "work": {"instruction_layout": "split", "global_fragments": ["AGENTS.md", "work/ROUTER.md"], "projects_fragments": ["bots/AGENTS.md"], "skills": ["example"]},
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
            (args.repo / "work" / "ROUTER.md").write_text(
                "Resolve {{PRIVATE_ROOT}} and compare path components.\n", encoding="utf-8"
            )
            manage.install_command(args)
            rendered = (args.projects_root / "private").resolve()
            self.assertIn(str(rendered), (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertNotIn(str(Path.home() / "Projects" / "private"), (args.home / "AGENTS.md").read_text(encoding="utf-8"))
            manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))
            self.assertIn("{{PRIVATE_ROOT}}", (args.repo / "work" / "ROUTER.md").read_text(encoding="utf-8"))
            self.assertEqual("shared rule\n", (args.repo / "AGENTS.md").read_text(encoding="utf-8"))

            root = rendered
            self.assertTrue(manage.is_path_within(root, root))
            self.assertTrue(manage.is_path_within(root / "nested", root))
            self.assertFalse(manage.is_path_within(root.parent / "private-ish", root))
            self.assertTrue(manage.is_path_within(Path(str(root).upper()) / "NESTED", root, windows=True))
            self.assertFalse(manage.is_path_within(root.parent / "private-ish", root, windows=True))

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

    def test_capture_restores_projects_and_private_tokens_in_each_layout(self):
        for profile in ("work", "private"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as raw:
                args = self._fixture(Path(raw))
                args.profile = profile
                args.projects_root = Path(raw) / "custom workspace"
                shared = "shared rule\nCanonical source: {{PROJECTS_ROOT}}/AGENTS.md.\nPrivate root: {{PRIVATE_ROOT}}.\nKeep source note.\n"
                bots = "bot rule\nCanonical source: {{PROJECTS_ROOT}}/AGENTS.md.\n"
                (args.repo / "AGENTS.md").write_text(shared, encoding="utf-8")
                (args.repo / "bots" / "AGENTS.md").write_text(bots, encoding="utf-8")
                manage.install_command(args)
                foreign = "<!-- codex-profiles:begin -->\nother manager policy\n<!-- codex-profiles:end -->"
                agents = args.home / "AGENTS.md"
                projects = args.projects_root / "AGENTS.md"
                installed = agents.read_text(encoding="utf-8").replace("shared rule", "updated shared rule")
                if manage.os.name == "nt":
                    # Capture accepts Windows path spelling changes without storing them.
                    installed = installed.replace(args.projects_root.resolve().as_posix(), str(args.projects_root.resolve()).upper())
                agents.write_text("user home prose\n\n" + installed + "\n" + foreign + "\n", encoding="utf-8")
                projects.write_text("user project prose\n\n" + projects.read_text(encoding="utf-8").replace("bot rule", "updated bot rule"), encoding="utf-8")
                installed_before = {path: path.read_bytes() for path in (agents, projects)}
                router_before = (args.repo / "work" / "ROUTER.md").read_text(encoding="utf-8")

                manage.capture_command(argparse.Namespace(**vars(args), capture_secrets=False))

                self.assertEqual(shared.replace("shared rule", "updated shared rule"), (args.repo / "AGENTS.md").read_text(encoding="utf-8"))
                self.assertEqual(bots.replace("bot rule", "updated bot rule"), (args.repo / "bots" / "AGENTS.md").read_text(encoding="utf-8"))
                self.assertEqual(router_before, (args.repo / "work" / "ROUTER.md").read_text(encoding="utf-8"))
                self.assertEqual(installed_before, {path: path.read_bytes() for path in (agents, projects)})
                for source in args.repo.rglob("*.md"):
                    content = source.read_text(encoding="utf-8")
                    self.assertNotIn(str(args.projects_root.resolve()).casefold(), content.casefold())
                    self.assertNotIn(args.projects_root.resolve().as_posix().casefold(), content.casefold())

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
            # Windows temporary paths can have equivalent short/long spellings.
            # Exercise a noncanonical spelling without depending on 8.3 support.
            fixture_root = Path(raw)
            (fixture_root / "path-alias").mkdir()
            args = self._fixture(fixture_root / "path-alias" / "..")
            manage.install_command(args)
            files = [args.home / n for n in ("AGENTS.md", "WORK.md", "PRIVATE.md")]
            files += [args.projects_root / "AGENTS.md", manage.state_path(args.home)]
            before = {p: p.read_bytes() for p in files}
            (args.repo / "AGENTS.md").write_text("new shared rule\n", encoding="utf-8")
            original_write = manage.atomic_write_text
            failure_target = (args.home / "PRIVATE.md").resolve()
            def fail_private(path, value):
                if path.resolve() == failure_target:
                    # The failure must happen after a real partial update.
                    self.assertIn("new shared rule", (args.home / "AGENTS.md").read_text(encoding="utf-8"))
                    raise OSError("synthetic write failure")
                return original_write(path, value)
            with mock.patch.object(manage, "atomic_write_text", side_effect=fail_private):
                with self.assertRaisesRegex(OSError, "synthetic write failure"):
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
            self.assertNotIn("personal", (args.repo / "work" / "ROUTER.md").read_text(encoding="utf-8"))
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

    def test_private_sync_from_legacy_inline_state_preserves_unmanaged_sidecars(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            args.profile = "private"
            manage.install_command(args)
            state = manage.load_state(args.home)
            state.pop("instruction_block_sha256")
            manage.write_json(manage.state_path(args.home), state)
            foreign = "<!-- codex-profiles:begin -->\nother manager policy\n<!-- codex-profiles:end -->\n"
            (args.home / "WORK.md").write_text("unmanaged work prose\n", encoding="utf-8")
            (args.home / "PRIVATE.md").write_text(foreign, encoding="utf-8")
            manage.sync_instructions_command(args)
            self.assertEqual("unmanaged work prose\n", (args.home / "WORK.md").read_text(encoding="utf-8"))
            self.assertEqual(foreign, (args.home / "PRIVATE.md").read_text(encoding="utf-8"))

    def test_legacy_inline_profiles_migrate_to_their_selected_layout(self):
        for profile in ("work", "private"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as raw:
                args = self._fixture(Path(raw))
                args.profile = profile
                manifest_path = args.repo / "manifest.json"
                current = json.loads(manifest_path.read_text(encoding="utf-8"))
                legacy = json.loads(json.dumps(current))
                legacy.pop("instructions")
                for name, config in legacy["profiles"].items():
                    config.pop("instruction_layout")
                    config["global_fragments"] = ["AGENTS.md", f"{name}/AGENTS.md"]
                manifest_path.write_text(json.dumps(legacy), encoding="utf-8")
                manage.install_command(args)
                agents = (args.home / "AGENTS.md").read_text(encoding="utf-8")
                self.assertIn("work account rule" if profile == "work" else "personal account rule", agents)
                self.assertFalse((args.home / "WORK.md").exists())
                self.assertFalse((args.home / "PRIVATE.md").exists())
                manifest_path.write_text(json.dumps(current), encoding="utf-8")
                manage.sync_instructions_command(args)
                agents = (args.home / "AGENTS.md").read_text(encoding="utf-8")
                if profile == "work":
                    self.assertIn("Select PRIVATE.md", agents)
                    self.assertNotIn("work account rule", agents)
                    self.assertNotIn("personal account rule", agents)
                    self.assertIn("work account rule", (args.home / "WORK.md").read_text(encoding="utf-8"))
                    self.assertIn("personal account rule", (args.home / "PRIVATE.md").read_text(encoding="utf-8"))
                else:
                    self.assertNotIn("Select PRIVATE.md", agents)
                    self.assertIn("personal account rule", agents)
                    self.assertFalse((args.home / "WORK.md").exists())
                    self.assertFalse((args.home / "PRIVATE.md").exists())

    def test_unrecorded_sidecars_require_known_generated_content_before_retirement(self):
        for known in (True, False):
            with self.subTest(known=known), tempfile.TemporaryDirectory() as raw:
                args = self._fixture(Path(raw))
                args.profile = "private"
                args.home.mkdir()
                manifest = manage.load_manifest(args.repo)
                content = manage.render_fragment_block(
                    args.repo, ["work/AGENTS.md"], manifest["markers"]["global_begin"], manifest["markers"]["global_end"]
                )
                if not known:
                    content = content.replace("work account rule", "unknown customized rule")
                work = args.home / "WORK.md"
                work.write_text(content + "\n", encoding="utf-8")
                if known:
                    manage.sync_instructions_command(args)
                    self.assertFalse(work.exists())
                else:
                    before = work.read_bytes()
                    with self.assertRaisesRegex(manage.ConfigError, "Cannot retire unrecorded"):
                        manage.sync_instructions_command(args)
                    self.assertEqual(before, work.read_bytes())
                    self.assertFalse(manage.state_path(args.home).exists())

    def test_private_migration_failure_restores_deleted_sidecars_and_state(self):
        for command in (manage.install_command, manage.sync_instructions_command):
            with self.subTest(command=command.__name__), tempfile.TemporaryDirectory() as raw:
                args = self._fixture(Path(raw))
                self._install_legacy_split_private(args)
                files = [args.home / name for name in ("AGENTS.md", "WORK.md", "PRIVATE.md")]
                files += [args.projects_root / "AGENTS.md", manage.state_path(args.home)]
                before = {path: path.read_bytes() for path in files}
                with mock.patch.object(manage, "mark_transaction_committed", side_effect=OSError("synthetic commit failure")):
                    with self.assertRaises(OSError):
                        command(args)
                self.assertEqual(before, {path: path.read_bytes() for path in files})
                self.assertFalse(list((args.home / "codex-config").glob("txn-*")))

    def test_capture_requires_matching_layout_before_writing_any_sources(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self._fixture(Path(raw))
            self._install_legacy_split_private(args)
            paths = [args.repo / name for name in ("AGENTS.md", "work/ROUTER.md", "work/AGENTS.md", "private/AGENTS.md")]
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
