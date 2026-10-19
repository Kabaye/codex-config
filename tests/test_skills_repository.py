"""Offline tests for public config + private skill source integration."""

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "public_skills_manager", ROOT / "scripts" / "manage.py"
)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class PrivateSkillsRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.config = root / "codex-config"
        self.skills = root / "codex-skills"
        self.home = root / "home" / ".codex"
        self.global_skills = root / "user" / ".agents" / "skills"
        self.projects = root / "Projects"
        self.project = root / "working-project"
        self.config.mkdir()
        self.skills.mkdir()
        self.plaintext = b"test-only synthetic credential"
        self.ciphertext = b"age-encryption.org/v1\nfake non-secret test payload"

        self._file(self.config / "AGENTS.md", "shared instructions\n")
        self._file(self.config / "work" / "AGENTS.md", "work rules\n")
        self._file(self.config / "bots" / "AGENTS.md", "bot rules\n")
        self._file(self.skills / "skills" / "global-demo" / "SKILL.md", "global demo\n")
        self._file(
            self.skills / "skills" / "global-demo" / "access.yml.age",
            self.ciphertext,
        )
        self._file(
            self.skills / "skills" / "project-demo" / "SKILL.md",
            "project demo\n",
        )
        self._file(
            self.skills / "skills" / "project-demo" / "asset.dat",
            b"\x00\xff\x01",
        )
        self._file(
            self.skills / "skills-manifest.json",
            json.dumps({
                "schema_version": 1,
                "source": "unit-test",
                "skills": {
                    "global-demo": {
                        "scope": "global",
                        "usage": "work",
                        "sharing": "private",
                    },
                    "project-demo": {
                        "scope": "project",
                        "usage": "common",
                        "sharing": "private",
                    },
                },
            }),
        )
        self.manifest_path = self.config / "manifest.json"
        self.public_manifest = {
            "schema_version": 1,
            "markers": {
                "global_begin": "<!-- codex-config:begin -->",
                "global_end": "<!-- codex-config:end -->",
                "projects_begin": "<!-- codex-config:projects:begin -->",
                "projects_end": "<!-- codex-config:projects:end -->",
            },
            "profiles": {
                "work": {
                    "global_fragments": ["AGENTS.md", "work/AGENTS.md"],
                    "projects_fragments": ["bots/AGENTS.md"],
                    "skills": ["global-demo"],
                    "project_skills": ["project-demo"],
                },
            },
            "encrypted_files": {},
            "skill_policy": {},
        }
        self._file(
            self.manifest_path, json.dumps(self.public_manifest, indent=2)
        )

    @staticmethod
    def _file(path: Path, content: str | bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)

    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(
            repo=self.config,
            home=self.home,
            projects_root=self.projects,
            skills_root=self.global_skills,
            project_root=self.project,
            profile="work",
            dry_run=False,
            force=False,
        )

    def test_age_cipher_is_discovered_without_hash_manifest(self) -> None:
        result = manager.load_manifest(self.config)
        self.assertEqual(result["encrypted_files"], {
            "global-demo": {
                "source": "skills/global-demo/access.yml.age",
                "destination": "access.yml",
            }
        })
        self.assertNotIn("plaintext_sha256", str(result))
        manager.validate_source(self.config, result)

        base = manager.load_manifest(self.config, base_only=True)
        self.assertEqual(base["encrypted_files"], {})
        self.assertFalse((self.skills / "private-config").exists())

    def test_install_keeps_private_material_out_of_public_repo(self) -> None:
        secret_session = mock.Mock()
        secret_session.decrypt.return_value = self.plaintext
        with mock.patch.object(manager, "PassphraseSession", return_value=secret_session):
            manager.install_command(self._args())

        self.assertEqual(
            self.plaintext,
            (self.global_skills / "global-demo" / "access.yml").read_bytes(),
        )
        self.assertEqual(
            b"\x00\xff\x01",
            (self.project / ".agents" / "skills" / "project-demo" / "asset.dat").read_bytes(),
        )
        self.assertFalse((self.global_skills / "project-demo").exists())
        self.assertFalse(
            (self.project / ".agents" / "skills" / "global-demo").exists()
        )
        self.assertEqual(
            self.public_manifest,
            json.loads(self.manifest_path.read_text(encoding="utf-8")),
        )
        secret_session.decrypt.assert_called_once()
        self.assertTrue((self.home / "codex-config" / "state.json").is_file())

    def test_capture_edits_private_skill_not_public_manifest(self) -> None:
        session = mock.Mock()
        session.decrypt.return_value = self.plaintext
        with mock.patch.object(manager, "PassphraseSession", return_value=session):
            manager.install_command(self._args())

        installed = (
            self.project / ".agents" / "skills" / "project-demo" / "SKILL.md"
        )
        installed.write_text("changed locally\n", encoding="utf-8")

        manager.capture_command(self._args())
        self.assertEqual(
            "changed locally\n",
            (self.skills / "skills" / "project-demo" / "SKILL.md")
            .read_text(encoding="utf-8"),
        )
        self.assertEqual(
            self.public_manifest,
            json.loads(self.manifest_path.read_text(encoding="utf-8")),
        )
        self.assertEqual(
            self.plaintext,
            (self.global_skills / "global-demo" / "access.yml").read_bytes(),
        )

    def test_fingerprint_accounts_for_private_source_changes(self) -> None:
        manifest = manager.load_manifest(self.config)
        first = manager.source_fingerprint(self.config, manifest, "work")
        self._file(
            self.skills / "skills" / "project-demo" / "SKILL.md",
            "new skill source version\n",
        )
        second = manager.source_fingerprint(self.config, manifest, "work")
        self.assertNotEqual(first, second)

    def test_secret_capture_is_opt_in(self) -> None:
        session = mock.Mock()
        session.decrypt.return_value = self.plaintext
        session.encrypt.return_value = b"age-encryption.org/v1\nsynthetic replacement"
        with mock.patch.object(manager, "PassphraseSession", return_value=session):
            manager.install_command(self._args())
            secret_file = self.skills / "skills/global-demo/access.yml.age"
            original = secret_file.read_bytes()
            manager.capture_command(self._args())
            self.assertEqual(original, secret_file.read_bytes())

            args = self._args()
            args.capture_secrets = True
            manager.capture_command(args)

        self.assertEqual(session.encrypt.call_count, 1)
        session.encrypt.assert_called_with(self.plaintext)
        self.assertEqual(
            b"age-encryption.org/v1\nsynthetic replacement",
            (self.skills / "skills/global-demo/access.yml.age").read_bytes(),
        )
        self.assertEqual(
            self.public_manifest,
            json.loads(self.manifest_path.read_text(encoding="utf-8")),
        )
        self.assertNotIn("plaintext_sha256", self.manifest_path.read_text())



if __name__ == "__main__":
    unittest.main()
