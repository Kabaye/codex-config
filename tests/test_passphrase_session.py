import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pyrage import passphrase


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manage.py"
SPEC = importlib.util.spec_from_file_location("codex_config_manage_passphrase", SCRIPT)
assert SPEC and SPEC.loader
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class PassphraseSessionTests(unittest.TestCase):
    def test_one_phrase_decrypts_two_files_after_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            first = root / "first.age"
            second = root / "second.age"
            first.write_bytes(passphrase.encrypt(b"work", "correct phrase"))
            second.write_bytes(passphrase.encrypt(b"personal", "correct phrase"))

            with mock.patch.object(manage, "read_masked_passphrase", side_effect=["wrong", "correct phrase"]) as prompt:
                session = manage.PassphraseSession()
                self.assertEqual(b"work", session.decrypt(first))
                self.assertEqual(b"personal", session.decrypt(second))

            self.assertEqual(2, prompt.call_count)
            prompt.assert_any_call("Enter age passphrase: ")

    def test_different_phrase_in_second_file_is_reported_without_reprompt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            first = root / "first.age"
            second = root / "second.age"
            first.write_bytes(passphrase.encrypt(b"work", "first phrase"))
            second.write_bytes(passphrase.encrypt(b"personal", "second phrase"))

            with mock.patch.object(manage, "read_masked_passphrase", return_value="first phrase") as prompt:
                session = manage.PassphraseSession()
                session.decrypt(first)
                with self.assertRaisesRegex(manage.ConfigError, "same passphrase"):
                    session.decrypt(second)

            prompt.assert_called_once()

    def test_three_wrong_attempts_do_not_write_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            cipher = root / "source.age"
            destination = root / "access.yml"
            cipher.write_bytes(passphrase.encrypt(b"secret", "correct phrase"))

            with mock.patch.object(manage, "read_masked_passphrase", return_value="wrong") as prompt:
                session = manage.PassphraseSession()
                with self.assertRaisesRegex(manage.ConfigError, "three attempts"):
                    manage.decrypt_file(session, cipher, destination)

            self.assertEqual(3, prompt.call_count)
            self.assertFalse(destination.exists())

    def test_empty_entry_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            cipher = Path(raw_root) / "source.age"
            cipher.write_bytes(passphrase.encrypt(b"data", "correct phrase"))

            with mock.patch.object(manage, "read_masked_passphrase", side_effect=["", "correct phrase"]) as prompt:
                self.assertEqual(b"data", manage.PassphraseSession().decrypt(cipher))

            self.assertEqual(2, prompt.call_count)

    def test_encrypt_uses_verified_phrase_and_standard_age_format(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            source = root / "source.age"
            source.write_bytes(passphrase.encrypt(b"original", "correct phrase"))

            with mock.patch.object(manage, "read_masked_passphrase", return_value="correct phrase") as prompt:
                session = manage.PassphraseSession()
                session.decrypt(source)
                ciphertext = session.encrypt(b"updated")

            prompt.assert_called_once()
            self.assertTrue(ciphertext.startswith(b"age-encryption.org/v1\n"))
            self.assertEqual(b"updated", passphrase.decrypt(ciphertext, "correct phrase"))


class InstallSecretReuseTests(unittest.TestCase):
    @staticmethod
    def _setup_secret(root: Path, installed: bytes) -> tuple[Path, Path, dict]:
        repo = root / "repo"
        skills_root = root / ".agents" / "skills"
        source = repo / "skills" / "access"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("access skill\n", encoding="utf-8")
        (source / "access.yml.age").write_bytes(
            passphrase.encrypt(b"expected secret\n", "correct phrase")
        )
        target = skills_root / "access" / "access.yml"
        target.parent.mkdir(parents=True)
        target.write_bytes(installed)
        manifest = {
            "encrypted_files": {
                "access": {
                    "source": "skills/access/access.yml.age",
                    "destination": "access.yml",
                    "plaintext_sha256": manage.sha256_bytes(b"expected secret\n"),
                }
            }
        }
        return repo, skills_root, manifest

    def test_matching_installed_secret_is_reused_without_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo, skills_root, manifest = self._setup_secret(
                root, b"expected secret\n"
            )
            staging = root / "staging"

            self.assertFalse(
                manage.secret_requires_decryption(manifest, skills_root, "access")
            )
            staged = manage.stage_skill(
                repo, skills_root, manifest, "access", staging, None
            )

            self.assertEqual(
                b"expected secret\n",
                (staged / "access.yml").read_bytes(),
            )

    def test_changed_installed_secret_still_requires_passphrase(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo, skills_root, manifest = self._setup_secret(
                root, b"locally changed secret\n"
            )
            staging = root / "staging"

            self.assertTrue(
                manage.secret_requires_decryption(manifest, skills_root, "access")
            )
            with self.assertRaisesRegex(
                manage.ConfigError, "Passphrase session is required"
            ):
                manage.stage_skill(
                    repo, skills_root, manifest, "access", staging, None
                )


class MaskedInputTests(unittest.TestCase):
    def test_pasted_characters_are_masked(self) -> None:
        characters = iter(["a", "b", "c", "\r"])
        output = io.StringIO()

        self.assertEqual("abc", manage._collect_masked_input(lambda: next(characters), output))
        self.assertEqual("***\r\n", output.getvalue())

    def test_backspace_erases_one_mask_character(self) -> None:
        characters = iter(["a", "b", "\b", "c", "\r"])
        output = io.StringIO()

        self.assertEqual("ac", manage._collect_masked_input(lambda: next(characters), output))
        self.assertEqual("**\b \b*\r\n", output.getvalue())

    def test_unicode_surrogate_pair_uses_one_star(self) -> None:
        characters = iter(["\ud83d", "\udd10", "\r"])
        output = io.StringIO()

        self.assertEqual("🔐", manage._collect_masked_input(lambda: next(characters), output))
        self.assertEqual("*\r\n", output.getvalue())

    def test_control_c_does_not_return_partial_input(self) -> None:
        characters = iter(["a", "\x03"])
        output = io.StringIO()

        with self.assertRaises(KeyboardInterrupt):
            manage._collect_masked_input(lambda: next(characters), output)
        self.assertEqual("*\r\n", output.getvalue())


if __name__ == "__main__":
    unittest.main()
