import argparse
from contextlib import contextmanager
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_full_replacement as replacement


manage = replacement.manage


class CrossVolumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "source" / "codex-config"
        self.home = self.root / "home"
        self.projects = self.root / "projects"
        self.skills = self.root / "global-skills"
        self.project = self.repo.parent
        self.project_skills = self.project / ".agents" / "skills"
        self.fixture = replacement.FullReplacementTests()
        self.fixture._write_repo(self.repo)
        self.fixture._write_skill(
            self.repo / ".agents" / "skills" / "project-only", "project current"
        )
        manifest_path = self.repo / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["profiles"]["active"]["project_skills"] = ["project-only"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.args = argparse.Namespace(
            repo=self.repo,
            home=self.home,
            projects_root=self.projects,
            skills_root=self.skills,
            project_root=self.project,
            profile="active",
            dry_run=False,
            force=False,
        )

    @contextmanager
    def _different_volumes(self, windows_error: bool = False):
        original_rename = Path.rename
        attempts = []

        def rename(source: Path, destination: Path):
            destination = Path(destination)
            if source.is_relative_to(self.home) != destination.is_relative_to(self.home):
                attempts.append((source, destination))
                error = OSError(errno.EXDEV, "simulated cross-volume rename")
                if windows_error:
                    error = OSError(errno.EACCES, "simulated Windows cross-volume rename")
                    error.winerror = 17
                raise error
            return original_rename(source, destination)

        with mock.patch.object(Path, "rename", new=rename):
            yield attempts

    def _install(self) -> None:
        with self._different_volumes():
            manage.install_command(self.args)

    def _recover(self) -> None:
        manage.recover_transactions(
            self.home / "codex-config",
            self.home,
            self.projects,
            self.repo,
            self.project,
        )

    def _snapshot(self) -> dict[str, dict[str, str]]:
        return {
            str(path): manage.tree_hashes(path)
            for path in (
                self.skills,
                self.project_skills,
                self.home / "skills",
                self.project / ".codex" / "skills",
            )
        }

    def _assert_clean(self) -> None:
        self.assertEqual([], list((self.home / "codex-config").glob("txn-*")))
        self.assertEqual([], list(self.root.rglob("*.txn-*.tmp")))

    @staticmethod
    def _partial_copy(source, destination, **_kwargs):
        destination = Path(destination)
        destination.mkdir()
        (destination / "partial.txt").write_text("incomplete", encoding="utf-8")
        raise OSError(errno.EIO, "simulated interrupted copy")

    def test_install_and_remove_across_volumes(self) -> None:
        for windows_error in (False, True):
            with self.subTest(windows_error=windows_error):
                self.fixture._write_skill(self.skills / "active", "old", "stale.txt")
                self.fixture._write_skill(self.skills / "inactive", "inactive old")
                self.fixture._write_skill(self.project_skills / "project-only", "old")
                self.fixture._write_skill(self.home / "skills" / "active", "legacy")
                legacy_project = self.project / ".codex" / "skills" / "project-only"
                self.fixture._write_skill(legacy_project, "legacy project")
                self.fixture._write_skill(self.skills / "unrelated", "keep")

                # An old state owns the former global location.
                manage.write_json(
                    manage.state_path(self.home),
                    {"profile": "active", "skills": {"active": {}}},
                )
                with self._different_volumes(windows_error) as attempts:
                    manage.install_command(self.args)
                    self.assertEqual(
                        "current\n", (self.skills / "active" / "SKILL.md").read_text()
                    )
                    self.assertEqual(
                        "project current\n",
                        (self.project_skills / "project-only" / "SKILL.md").read_text(),
                    )
                    self.assertFalse((self.skills / "active" / "stale.txt").exists())
                    self.assertFalse((self.skills / "inactive").exists())
                    self.assertFalse((self.home / "skills" / "active").exists())
                    self.assertFalse(legacy_project.exists())
                    self.assertTrue(any(dst.parent.name == "rollback" for _, dst in attempts))
                    self.assertTrue(any(dst.parent.name == "project-rollback" for _, dst in attempts))
                    self.assertTrue(any(dst.parent.name == "legacy-project-rollback" for _, dst in attempts))
                    manage.remove_command(self.args)

                self.assertFalse((self.skills / "active").exists())
                self.assertFalse((self.project_skills / "project-only").exists())
                self.assertEqual("keep\n", (self.skills / "unrelated" / "SKILL.md").read_text())
                self.assertFalse(manage.state_path(self.home).exists())
                self._assert_clean()

    def test_capture_backs_up_and_publishes_source_across_volumes(self) -> None:
        self._install()
        (self.skills / "active" / "SKILL.md").write_text("captured global\n")
        (self.project_skills / "project-only" / "SKILL.md").write_text("captured project\n")

        with self._different_volumes(True) as attempts:
            manage.capture_command(self.args)

        self.assertEqual(
            "captured global\n", (self.repo / "skills" / "active" / "SKILL.md").read_text()
        )
        self.assertEqual(
            "captured project\n",
            (self.repo / ".agents" / "skills" / "project-only" / "SKILL.md").read_text(),
        )
        self.assertTrue(any(dst.parent.name == "source-backup" for _, dst in attempts))
        self.assertTrue(any(dst.parent.name == "project-source-backup" for _, dst in attempts))
        self._assert_clean()

    def test_failed_backup_or_publish_restores_the_original_installation(self) -> None:
        self._install()
        original = self._snapshot()
        state_bytes = manage.state_path(self.home).read_bytes()
        (self.repo / "skills" / "active" / "SKILL.md").write_text("updated\n")
        real_copytree = manage.shutil.copytree

        for stage in ("rollback", "desired"):
            with self.subTest(stage=stage):
                def copytree(source, destination, *args, **kwargs):
                    source = Path(source)
                    if source.name == "active" and (
                        (stage == "rollback" and source.parent == self.skills)
                        or (stage == "desired" and source.parent.name == "desired")
                    ):
                        return self._partial_copy(source, destination)
                    return real_copytree(source, destination, *args, **kwargs)

                with self._different_volumes(), mock.patch.object(
                    manage.shutil, "copytree", side_effect=copytree
                ):
                    with self.assertRaisesRegex(OSError, "interrupted copy"):
                        manage.install_command(self.args)
                self.assertEqual(original, self._snapshot())
                self.assertEqual(state_bytes, manage.state_path(self.home).read_bytes())
                self._assert_clean()

    def test_remove_recovery_can_retry_after_a_partial_restore_copy(self) -> None:
        self._install()
        original = self._snapshot()
        state_bytes = manage.state_path(self.home).read_bytes()
        with self._different_volumes(), mock.patch.object(
            manage, "mark_transaction_committed", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                manage.remove_command(self.args)

        transaction = next((self.home / "codex-config").glob("txn-remove-*"))
        project_target = self.project_skills / "project-only"
        orphan = manage.directory_copy_staging(project_target, transaction)
        orphan.mkdir()
        (orphan / "partial.txt").write_text("from interrupted process")
        real_copytree = manage.shutil.copytree

        def copytree(source, destination, *args, **kwargs):
            if Path(source).parent.name == "project-skills":
                return self._partial_copy(source, destination)
            return real_copytree(source, destination, *args, **kwargs)

        with self._different_volumes(), mock.patch.object(
            manage.shutil, "copytree", side_effect=copytree
        ):
            with self.assertRaisesRegex(OSError, "interrupted copy"):
                self._recover()

        # The first global restoration succeeded, but its complete backup must
        # survive the later project restoration failure and the next retry.
        self.assertEqual(
            manage.tree_hashes(self.skills / "active"),
            manage.tree_hashes(transaction / "skills" / "active"),
        )
        self.assertTrue((transaction / "skills" / "active" / "SKILL.md").is_file())
        self.assertTrue((transaction / "project-skills" / "project-only" / "SKILL.md").is_file())
        self.assertFalse(orphan.exists())
        with self._different_volumes():
            self._recover()
            self._recover()
        self.assertEqual(original, self._snapshot())
        self.assertEqual(state_bytes, manage.state_path(self.home).read_bytes())
        self._assert_clean()

if __name__ == "__main__":
    unittest.main()
