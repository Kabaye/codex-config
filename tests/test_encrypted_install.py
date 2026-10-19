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
    def test_matching_installed_plaintext_is_reused_without_decryption(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo = root / "repo"
            skills_root = root / ".agents" / "skills"
            staging = root / "staging"
            skill = repo / "skills" / "access-personal"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("test\n", encoding="utf-8")
            cipher = skill / "access.yml.age"
            cipher.write_bytes(b"encrypted")

            plaintext = b"access: test\n"
            installed = skills_root / "access-personal" / "access.yml"
            installed.parent.mkdir(parents=True)
            installed.write_bytes(plaintext)
            manifest = {
                "encrypted_files": {
                    "access-personal": {
                        "source": "skills/access-personal/access.yml.age",
                        "destination": "access.yml",
                        "plaintext_sha256": manage.hashlib.sha256(plaintext).hexdigest(),
                    }
                }
            }

            session = mock.Mock()
            session.decrypt.return_value = plaintext
            staged = manage.stage_skill(
                repo,
                skills_root,
                manifest,
                "access-personal",
                staging,
                session,
            )

            session.decrypt.assert_not_called()
            self.assertEqual(plaintext, (staged / "access.yml").read_bytes())
            self.assertFalse(
                manage.secret_requires_decryption(
                    manifest,
                    skills_root,
                    "access-personal",
                )
            )


if __name__ == "__main__":
    unittest.main()
