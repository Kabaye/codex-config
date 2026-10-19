"""Installing encrypted skill sources always decrypts fresh age data."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manage.py"
SPEC = importlib.util.spec_from_file_location("codex_config_manage", SCRIPT)
assert SPEC and SPEC.loader
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class EncryptedInstallTests(unittest.TestCase):
    def test_installed_plaintext_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo = root / "repo"
            staging = root / "staging"
            skill = repo / "skills" / "access-demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("test\n", encoding="utf-8")
            cipher = skill / "access.yml.age"
            cipher.write_bytes(b"age-encryption.org/v1\nsynthetic fixture")

            installed = root / ".agents" / "skills" / "access-demo" / "access.yml"
            installed.parent.mkdir(parents=True)
            installed.write_bytes(b"previous installed plaintext")
            manifest = {
                "encrypted_files": {
                    "access-demo": {
                        "source": "skills/access-demo/access.yml.age",
                        "destination": "access.yml",
                    }
                }
            }

            session = mock.Mock()
            session.decrypt.return_value = b"new plaintext from age"
            staged = manage.stage_skill(
                repo, manifest, "access-demo", staging, session
            )

            session.decrypt.assert_called_once_with(cipher)
            self.assertEqual(
                b"new plaintext from age", (staged / "access.yml").read_bytes()
            )
            self.assertEqual(b"previous installed plaintext", installed.read_bytes())

    def test_missing_session_does_not_install_previous_plaintext(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            skill = root / "repo" / "skills" / "access-demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("test\n", encoding="utf-8")
            (skill / "access.yml.age").write_bytes(b"age-encryption.org/v1\nfixture")
            manifest = {"encrypted_files": {
                "access-demo": {
                    "source": "skills/access-demo/access.yml.age",
                    "destination": "access.yml",
                }
            }}
            with self.assertRaisesRegex(manage.ConfigError, "Passphrase session"):
                manage.stage_skill(
                    root / "repo", manifest, "access-demo", root / "staging", None
                )


if __name__ == "__main__":
    unittest.main()
