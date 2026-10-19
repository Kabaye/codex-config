import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manage.py"
SPEC = importlib.util.spec_from_file_location("codex_config_manage_replace", SCRIPT)
assert SPEC and SPEC.loader
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class FullReplacementTests(unittest.TestCase):
    def test_install_replaces_all_owned_artifacts_and_preserves_other_owners(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo = root / "repo"
            home = root / "home"
            projects = root / "projects"
            skills_root = root / ".agents" / "skills"
            self._write_repo(repo)

            profile_block = """<!-- codex-profiles:begin -->
profile state
<!-- codex-profiles:end -->"""
            config_block = """<!-- codex-config:begin -->
locally edited old base
<!-- codex-config:end -->"""
            home.mkdir(parents=True)
            (home / "AGENTS.md").write_text(
                f"{config_block}\n\n{profile_block}\n", encoding="utf-8"
            )
            (home / "auth.json").write_text("keep auth\n", encoding="utf-8")
            projects.mkdir(parents=True)
            (projects / "AGENTS.md").write_text(
                """unrelated project rules

<!-- codex-config:projects:begin -->
locally edited old projects
<!-- codex-config:projects:end -->
""",
                encoding="utf-8",
            )
            self._write_skill(home / "skills" / "active", "old", "stale.txt")
            self._write_skill(home / "skills" / "inactive", "old", "access.yml")
            self._write_skill(home / "skills" / "historical", "old", "access.yml")
            self._write_skill(home / "skills" / "unrelated", "keep", "legacy-user.txt")
            self._write_skill(skills_root / "unrelated-global", "keep", "user.txt")
            state_root = home / "codex-config"
            state_root.mkdir()
            (state_root / "state.json").write_text(
                json.dumps(
                    {
                        "profile": "obsolete-profile",
                        "skills": {"historical": {"invalid": "old state"}},
                    }
                ),
                encoding="utf-8",
            )

            manage.install_command(
                argparse.Namespace(
                    repo=repo,
                    home=home,
                    projects_root=projects,
                    skills_root=skills_root,
                    profile="active",
                    age=None,
                    dry_run=False,
                    force=False,
                )
            )

            installed_global = (home / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("current base", installed_global)
            self.assertNotIn("locally edited old base", installed_global)
            self.assertIn(profile_block, installed_global)
            installed_projects = (projects / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("current projects", installed_projects)
            self.assertNotIn("locally edited old projects", installed_projects)
            self.assertIn("unrelated project rules", installed_projects)
            self.assertEqual(
                "current\n",
                (skills_root / "active" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertFalse((skills_root / "active" / "stale.txt").exists())
            self.assertFalse((skills_root / "inactive").exists())
            self.assertFalse((skills_root / "historical").exists())
            self.assertEqual(
                "keep auth\n", (home / "auth.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "keep\n",
                (home / "skills" / "unrelated" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(
                "keep\n",
                (skills_root / "unrelated-global" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertFalse((home / "skills" / "active").exists())
            self.assertFalse((home / "skills" / "inactive").exists())
            self.assertFalse((home / "skills" / "historical").exists())
            state = json.loads(
                (home / "codex-config" / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["profile"], "active")
            self.assertEqual(Path(state["skills_root"]), skills_root.resolve())
            self.assertEqual(set(state["skills"]), {"active"})

    def test_project_scoped_skills_install_into_target_and_migrate_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo = root / "source" / "codex-config"
            home = root / "home"
            projects = root / "projects"
            skills_root = root / "global-skills"
            project_root = repo.parent
            self._write_repo(repo)

            self._write_skill(
                repo / ".agents" / "skills" / "project-only",
                "project current",
            )
            manifest_path = repo / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["profiles"]["active"]["project_skills"] = ["project-only"]
            manifest["profiles"]["inactive"]["project_skills"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self._write_skill(
                project_root / ".codex" / "skills" / "project-only",
                "legacy project",
                "stale.txt",
            )
            self._write_skill(
                project_root / ".codex" / "skills" / "unrelated-local",
                "keep local",
                "user.txt",
            )

            manage.install_command(
                argparse.Namespace(
                    repo=repo,
                    home=home,
                    projects_root=projects,
                    skills_root=skills_root,
                    project_root=project_root,
                    profile="active",
                    age=None,
                    dry_run=False,
                    force=False,
                )
            )

            installed = project_root / ".agents" / "skills" / "project-only"
            self.assertEqual(
                "project current\n",
                (installed / "SKILL.md").read_text(encoding="utf-8"),
            )
            self.assertFalse((installed / "stale.txt").exists())
            self.assertFalse(
                (project_root / ".codex" / "skills" / "project-only").exists()
            )
            self.assertEqual(
                "keep local\n",
                (
                    project_root
                    / ".codex"
                    / "skills"
                    / "unrelated-local"
                    / "SKILL.md"
                ).read_text(encoding="utf-8"),
            )

            state = json.loads(
                (home / "codex-config" / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                Path(state["project_skills_root"]),
                (project_root / ".agents" / "skills").resolve(),
            )
            self.assertEqual(set(state["project_skills"]), {"project-only"})

    def test_shared_skill_migrates_from_project_to_global_across_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo = root / "source" / "codex-config"
            self._write_repo(repo)
            project_source = repo / ".agents" / "skills" / "shared-width"
            self._write_skill(project_source, "shared width")
            manifest_path = repo / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["profiles"]["active"]["project_skills"] = ["shared-width"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            args = argparse.Namespace(
                repo=repo,
                home=root / "home",
                projects_root=root / "projects",
                skills_root=root / "global-skills",
                project_root=repo.parent,
                profile="active",
                age=None,
                dry_run=False,
                force=False,
            )
            manage.install_command(args)
            project_target = repo.parent / ".agents" / "skills" / "shared-width"
            self.assertTrue(project_target.is_dir())

            project_source.rename(repo / "skills" / "shared-width")
            manifest["profiles"]["active"]["project_skills"] = []
            for config in manifest["profiles"].values():
                config["skills"].append("shared-width")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            for profile in ("active", "inactive"):
                with self.subTest(profile=profile):
                    args.profile = profile
                    manage.install_command(args)
                    global_target = args.skills_root / "shared-width"
                    self.assertEqual(
                        "shared width\n",
                        (global_target / "SKILL.md").read_text(encoding="utf-8"),
                    )
                    self.assertFalse(project_target.exists())
                    state = json.loads(
                        (args.home / "codex-config" / "state.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertIn("shared-width", state["skills"])
                    self.assertNotIn("shared-width", state["project_skills"])

    def test_install_repairs_duplicate_owned_markers(self) -> None:
        begin = "<!-- codex-config:begin -->"
        end = "<!-- codex-config:end -->"
        routing = """<!-- codex-profiles:begin -->
profile state
<!-- codex-profiles:end -->"""

        global_text = manage.build_global_text(
            (
                f"unrelated\n\n{begin}\nold one\n{end}\n\n"
                f"{begin}\nold two\n{end}\n\n{routing}\n"
            ),
            f"{begin}\ncurrent\n{end}",
            "legacy",
            begin,
            end,
            False,
        )
        self.assertIn("unrelated", global_text)
        self.assertIn("current", global_text)
        self.assertIn(routing, global_text)
        self.assertNotIn("old one", global_text)
        self.assertNotIn("old two", global_text)
        self.assertEqual(global_text.count(begin), 1)

        projects_begin = "<!-- codex-config:projects:begin -->"
        projects_end = "<!-- codex-config:projects:end -->"
        projects_text = manage.build_projects_text(
            (
                f"{projects_begin}\nold one\n{projects_end}\n\n"
                f"keep\n\n{projects_begin}\nold two\n{projects_end}\n"
            ),
            f"{projects_begin}\ncurrent projects\n{projects_end}",
            "legacy projects",
            projects_begin,
            projects_end,
            False,
        )
        self.assertIn("keep", projects_text)
        self.assertIn("current projects", projects_text)
        self.assertNotIn("old one", projects_text)
        self.assertNotIn("old two", projects_text)
        self.assertEqual(projects_text.count(projects_begin), 1)

        with self.assertRaisesRegex(manage.ConfigError, "no matching end"):
            manage.build_global_text(
                f"{begin}\nstale\nkeep ambiguous trailing instructions\n",
                f"{begin}\ncurrent\n{end}",
                "legacy",
                begin,
                end,
                False,
            )

    def test_unreadable_old_state_is_disposable_on_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo = root / "repo"
            home = root / "home"
            projects = root / "projects"
            skills_root = root / ".agents" / "skills"
            self._write_repo(repo)
            state = home / "codex-config" / "state.json"
            state.parent.mkdir(parents=True)
            state.write_bytes(b"\xff\xfe")
            self._write_skill(home / "skills" / "inactive", "old", "access.yml")

            manage.install_command(
                argparse.Namespace(
                    repo=repo,
                    home=home,
                    projects_root=projects,
                    skills_root=skills_root,
                    profile="active",
                    age=None,
                    dry_run=False,
                    force=False,
                )
            )

            self.assertFalse((skills_root / "inactive").exists())
            installed = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(installed["profile"], "active")

    @staticmethod
    def _write_skill(root: Path, content: str, extra_name: str | None = None) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "SKILL.md").write_text(f"{content}\n", encoding="utf-8")
        if extra_name:
            (root / extra_name).write_text("remove me\n", encoding="utf-8")

    def _write_repo(self, repo: Path) -> None:
        repo.mkdir(parents=True)
        (repo / "AGENTS.md").write_text("current base\n", encoding="utf-8")
        (repo / "bots").mkdir()
        (repo / "bots" / "AGENTS.md").write_text("current projects\n", encoding="utf-8")
        self._write_skill(repo / "skills" / "active", "current")
        self._write_skill(repo / "skills" / "inactive", "inactive")
        manifest = {
            "schema_version": 1,
            "age": {
                "version": "1.3.2",
                "asset": "age.zip",
                "download_url": "https://example.invalid/age.zip",
                "sha256": "0" * 64,
                "executable_sha256": "1" * 64,
            },
            "markers": {
                "global_begin": "<!-- codex-config:begin -->",
                "global_end": "<!-- codex-config:end -->",
                "projects_begin": "<!-- codex-config:projects:begin -->",
                "projects_end": "<!-- codex-config:projects:end -->",
            },
            "profiles": {
                "active": {
                    "global_fragments": ["AGENTS.md"],
                    "projects_fragments": ["bots/AGENTS.md"],
                    "skills": ["active"],
                },
                "inactive": {
                    "global_fragments": ["AGENTS.md"],
                    "projects_fragments": ["bots/AGENTS.md"],
                    "skills": ["inactive"],
                },
            },
            "encrypted_files": {},
        }
        (repo / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
