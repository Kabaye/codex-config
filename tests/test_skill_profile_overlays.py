"""Offline coverage for profile overlays and their capture ownership."""

import argparse
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "skill_profile_manager", ROOT / "scripts" / "manage.py"
)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class SkillProfileOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = ROOT / "temp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.repo = root / "codex-config"
        self.skills = root / "codex-skills"
        self.home = root / "home"
        self.projects = root / "projects"
        self.project = root / "project"
        self.installed = root / "global-skills"
        self.source = self.skills / "skills" / "access-personal"
        self.write(self.repo / "AGENTS.md", "shared rules\n")
        self.write(self.repo / "bots" / "AGENTS.md", "bot rules\n")
        self.write(self.source / "SKILL.md", "Private agent and file instructions\n")
        self.write(self.source / "profile.json", '{"profile":"private"}\n')
        self.write(self.source / "scripts" / "helper.py", "# common helper\n")
        self.write(self.source / "profiles" / "work" / "SKILL.md", "Work file-only instructions\n")
        self.write(self.source / "profiles" / "work" / "profile.json", '{"profile":"work"}\n')
        self.write(self.source / "profiles" / "work" / "work-note.txt", "work only\n")
        self.write(self.source / "profiles" / "preview" / "SKILL.md", "unselected preview\n")
        self.write(self.skills / "skills" / "ordinary" / "SKILL.md", "ordinary instructions\n")
        self.write(self.skills / "skills" / "ordinary" / "asset.dat", b"\x00\xff")
        project_source = self.skills / "skills" / "project-demo"
        self.write(project_source / "SKILL.md", "private project instructions\n")
        self.write(project_source / "profiles" / "work" / "SKILL.md", "work project instructions\n")
        self.write(self.skills / "skills-manifest.json", json.dumps({
            "schema_version": 1,
            "skills": {name: {} for name in ("access-personal", "ordinary", "project-demo")},
        }))
        self.manifest = {
            "schema_version": 1,
            "markers": {
                "global_begin": "<!-- codex-config:begin -->",
                "global_end": "<!-- codex-config:end -->",
                "projects_begin": "<!-- codex-config:projects:begin -->",
                "projects_end": "<!-- codex-config:projects:end -->",
            },
            "profiles": {
                profile: {
                    "global_fragments": ["AGENTS.md"],
                    "projects_fragments": ["bots/AGENTS.md"],
                    "skills": ["access-personal", "ordinary"],
                    "project_skills": ["project-demo"],
                }
                for profile in ("work", "private")
            },
            "encrypted_files": {},
        }
        self.write_manifest()
        environment = mock.patch.dict(os.environ, {"CODEX_SKILLS_REPO": str(self.skills)})
        environment.start()
        self.addCleanup(environment.stop)

    @staticmethod
    def write(path: Path, value: str | bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)

    def write_manifest(self) -> None:
        self.write(self.repo / "manifest.json", json.dumps(self.manifest))

    def args(self, profile: str = "work") -> argparse.Namespace:
        return argparse.Namespace(
            repo=self.repo, home=self.home, projects_root=self.projects,
            project_root=self.project, skills_root=self.installed,
            profile=profile, dry_run=False, force=False, capture_secrets=False,
        )

    def snapshot(self, path: Path) -> dict[str, bytes]:
        return {
            file.relative_to(path).as_posix(): file.read_bytes()
            for file in manager.iter_tree_files(path)
        }

    def test_install_selects_only_the_chosen_static_policy(self) -> None:
        for profile, text in (("work", "Work file-only"), ("private", "Private agent and file")):
            with self.subTest(profile=profile), mock.patch.object(manager, "PassphraseSession") as session:
                manager.install_command(self.args(profile))
                target = self.installed / "access-personal"
                self.assertEqual(json.loads((target / "profile.json").read_text()), {"profile": profile})
                self.assertEqual((target / "SKILL.md").read_text(), f"{text} instructions\n")
                self.assertFalse((target / "profiles").exists())
                self.assertEqual((target / "work-note.txt").exists(), profile == "work")
                self.assertEqual((target / "scripts" / "helper.py").read_text(), "# common helper\n")
                self.assertEqual(self.snapshot(self.installed / "ordinary"), {
                    "SKILL.md": b"ordinary instructions\n", "asset.dat": b"\x00\xff",
                })
                project_target = self.project / ".agents" / "skills" / "project-demo"
                self.assertEqual((project_target / "SKILL.md").read_text(), f"{profile} project instructions\n")
                self.assertFalse((project_target / "profiles").exists())
                session.assert_not_called()

    def test_switch_removes_obsolete_owned_access_mode(self) -> None:
        self.write(self.skills / "skills" / "access-mode" / "SKILL.md", "legacy mode helper\n")
        catalog = manager.load_json(self.skills / "skills-manifest.json")
        catalog["skills"]["access-mode"] = {}
        self.write(self.skills / "skills-manifest.json", json.dumps(catalog))
        for config in self.manifest["profiles"].values():
            config["skills"].append("access-mode")
        self.write_manifest()
        manager.install_command(self.args("work"))
        self.assertTrue((self.installed / "access-mode").is_dir())
        for config in self.manifest["profiles"].values():
            config["skills"].remove("access-mode")
        self.write_manifest()

        manager.install_command(self.args("private"))

        self.assertFalse((self.installed / "access-mode").exists())
        self.assertFalse((self.installed / "access-personal" / "work-note.txt").exists())
        self.assertNotIn("access-mode", manager.load_state(self.home)["skills"])

    def test_capture_routes_overlay_edits_and_preserves_other_variants(self) -> None:
        original = self.snapshot(self.source)
        manager.install_command(self.args())
        target = self.installed / "access-personal"
        self.write(target / "SKILL.md", "edited work instructions\n")
        self.write(target / "profile.json", '{"profile":"work", "policy":"file"}\n')
        self.write(target / "scripts" / "helper.py", "# edited common helper\n")
        self.write(target / "scripts" / "new.py", "# new common helper\n")
        self.write(self.project / ".agents" / "skills" / "project-demo" / "SKILL.md", "edited project work\n")

        manager.capture_command(self.args())

        captured = self.snapshot(self.source)
        for path in ("SKILL.md", "profile.json", "profiles/preview/SKILL.md"):
            self.assertEqual(captured[path], original[path])
        self.assertEqual(captured["profiles/work/SKILL.md"], b"edited work instructions\n")
        self.assertEqual(captured["profiles/work/profile.json"], b'{"profile":"work", "policy":"file"}\n')
        self.assertEqual(captured["scripts/helper.py"], b"# edited common helper\n")
        self.assertEqual(captured["scripts/new.py"], b"# new common helper\n")
        project_source = self.skills / "skills" / "project-demo"
        self.assertEqual((project_source / "SKILL.md").read_text(), "private project instructions\n")
        self.assertEqual((project_source / "profiles" / "work" / "SKILL.md").read_text(), "edited project work\n")
        manager.capture_command(self.args())
        self.assertEqual(self.snapshot(self.source), captured)
        manager.install_command(self.args("private"))
        self.assertEqual((target / "SKILL.md").read_bytes(), original["SKILL.md"])
        self.assertEqual((target / "scripts" / "helper.py").read_text(), "# edited common helper\n")

    def test_capture_preserves_ciphertext_without_decrypting(self) -> None:
        cipher = b"age-encryption.org/v1\nsynthetic ciphertext only\n"
        self.write(self.source / "access.yml.age", cipher)
        session = mock.Mock()
        session.decrypt.return_value = b"synthetic fixture value\n"
        with mock.patch.object(manager, "PassphraseSession", return_value=session):
            manager.install_command(self.args())
        target = self.installed / "access-personal"
        self.assertFalse((target / "access.yml.age").exists())
        self.write(target / "SKILL.md", "edited work instructions\n")
        with mock.patch.object(manager, "PassphraseSession") as capture_session:
            manager.capture_command(self.args())
        capture_session.assert_not_called()
        self.assertEqual((self.source / "access.yml.age").read_bytes(), cipher)
        self.assertFalse((self.source / "access.yml").exists())
        self.assertEqual((self.source / "profiles" / "work" / "SKILL.md").read_text(), "edited work instructions\n")

    def test_private_capture_updates_base_and_preserves_work(self) -> None:
        original_work = self.snapshot(self.source / "profiles" / "work")
        manager.install_command(self.args("private"))
        self.write(self.installed / "access-personal" / "SKILL.md", "edited private instructions\n")

        manager.capture_command(self.args("private"))

        self.assertEqual((self.source / "SKILL.md").read_text(), "edited private instructions\n")
        self.assertEqual(self.snapshot(self.source / "profiles" / "work"), original_work)

    def test_capture_removes_deleted_common_and_overlay_only_files(self) -> None:
        manager.install_command(self.args())
        target = self.installed / "access-personal"
        (target / "scripts" / "helper.py").unlink()
        (target / "work-note.txt").unlink()

        manager.capture_command(self.args())
        manager.install_command(self.args())

        self.assertFalse((self.source / "scripts" / "helper.py").exists())
        self.assertFalse((self.source / "profiles" / "work" / "work-note.txt").exists())
        self.assertFalse((target / "scripts" / "helper.py").exists())
        self.assertFalse((target / "work-note.txt").exists())

    def test_fingerprint_includes_unselected_variants(self) -> None:
        manifest = manager.load_manifest(self.repo)
        first = manager.source_fingerprint(self.repo, manifest, "private")
        self.write(self.source / "profiles" / "work" / "SKILL.md", "changed work variant\n")
        self.assertNotEqual(first, manager.source_fingerprint(self.repo, manifest, "private"))

    def test_optional_staging_profile_defaults_to_base(self) -> None:
        manifest = manager.load_manifest(self.repo)
        staged = manager.stage_skill(self.repo, manifest, "access-personal", Path(self.temp.name) / "staging", None)
        self.assertEqual((staged / "SKILL.md").read_bytes(), (self.source / "SKILL.md").read_bytes())
        self.assertFalse((staged / "profiles").exists())

    def test_rejects_unsafe_variant_names_and_contents(self) -> None:
        for name, value in (("bad name", "directory"), ("file-variant", "file"), ("nested", "nested"), ("plain", "plain")):
            with self.subTest(value=value):
                variant = self.source / "profiles" / name
                if value == "file":
                    self.write(variant, "not a directory\n")
                elif value == "nested":
                    self.write(variant / "profiles" / "work" / "SKILL.md", "invalid nesting\n")
                elif value == "plain":
                    self.write(variant / "access.yml", "synthetic forbidden plaintext\n")
                else:
                    self.write(variant / "SKILL.md", "invalid name\n")
                try:
                    with self.assertRaises(manager.ConfigError):
                        manager.validate_source(self.repo, manager.load_manifest(self.repo))
                finally:
                    manager.remove_managed_path(variant, self.source)
        for profile in ("../work", "..", "bad name", "NUL"):
            with self.subTest(profile=profile), self.assertRaises(manager.ConfigError):
                manager.copy_source_skill(self.source, Path(self.temp.name) / "bad-stage", profile)

    def test_rejects_linked_unselected_variant(self) -> None:
        outside = Path(self.temp.name) / "outside"
        self.write(outside / "SKILL.md", "outside instructions\n")
        linked = self.source / "profiles" / "linked"
        link_check = nullcontext()
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError:
            # Exercise the rejection on Windows sessions without symlink rights.
            linked.mkdir()
            original_check = manager.is_link_like
            link_check = mock.patch.object(
                manager, "is_link_like",
                side_effect=lambda path: path == linked or original_check(path),
            )
        with link_check:
            with self.assertRaises(manager.ConfigError):
                manager.validate_source(self.repo, manager.load_manifest(self.repo))
            with self.assertRaises(manager.ConfigError):
                manager.copy_source_skill(self.source, Path(self.temp.name) / "staging", "work")

    def test_capture_rejects_shadowed_deletion_before_source_changes(self) -> None:
        manager.install_command(self.args())
        original = self.snapshot(self.source)
        (self.installed / "access-personal" / "SKILL.md").unlink()
        with self.assertRaisesRegex(manager.ConfigError, "deletion of a profile override"):
            manager.capture_command(self.args())
        self.assertEqual(self.snapshot(self.source), original)

    def test_failed_switch_restores_installed_selection_and_state(self) -> None:
        manager.install_command(self.args("work"))
        original_skill = self.snapshot(self.installed / "access-personal")
        original_state = manager.state_path(self.home).read_bytes()
        original_instructions = (self.home / "AGENTS.md").read_bytes()
        with mock.patch.object(manager, "mark_transaction_committed", side_effect=OSError("synthetic commit failure")):
            with self.assertRaisesRegex(OSError, "synthetic commit failure"):
                manager.install_command(self.args("private"))
        self.assertEqual(self.snapshot(self.installed / "access-personal"), original_skill)
        self.assertEqual(manager.state_path(self.home).read_bytes(), original_state)
        self.assertEqual((self.home / "AGENTS.md").read_bytes(), original_instructions)
        self.assertFalse(list((self.home / "codex-config").glob("txn-*")))

    def test_failed_capture_restores_source_variants_and_state(self) -> None:
        manager.install_command(self.args())
        original = self.snapshot(self.source)
        original_state = manager.state_path(self.home).read_bytes()
        self.write(self.installed / "access-personal" / "SKILL.md", "edited work instructions\n")
        with mock.patch.object(manager, "mark_transaction_committed", side_effect=OSError("synthetic commit failure")):
            with self.assertRaisesRegex(OSError, "synthetic commit failure"):
                manager.capture_command(self.args())
        self.assertEqual(self.snapshot(self.source), original)
        self.assertEqual(manager.state_path(self.home).read_bytes(), original_state)
        self.assertFalse(list((self.home / "codex-config").glob("txn-*")))


if __name__ == "__main__":
    unittest.main()
