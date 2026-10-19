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


class InstallDirectDecryptTests(unittest.TestCase):
    @staticmethod
    def _setup_secret(root: Path, installed: bytes) -> tuple[Path, dict]:
        repo = root / "repo"
        source = repo / "skills" / "access"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("access skill\n", encoding="utf-8")
        (source / "access.yml.age").write_bytes(
            passphrase.encrypt(b"actual encrypted secret\n", "correct phrase")
        )
        target = root / ".agents" / "skills" / "access" / "access.yml"
        target.parent.mkdir(parents=True)
        target.write_bytes(installed)
        manifest = {
            "encrypted_files": {
                "access": {
                    "source": "skills/access/access.yml.age",
                    "destination": "access.yml",
                }
            }
        }
        return repo, manifest

    def test_existing_installed_value_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo, manifest = self._setup_secret(root, b"untrusted old value\n")
            with mock.patch.object(
                manage, "read_masked_passphrase", return_value="correct phrase"
            ) as prompt:
                staged = manage.stage_skill(
                    repo, manifest, "access", root / "staging",
                    manage.PassphraseSession()
                )
            self.assertEqual(
                b"actual encrypted secret\n",
                (staged / "access.yml").read_bytes(),
            )
            prompt.assert_called_once()

    def test_secret_requires_passphrase_even_if_old_plaintext_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            repo, manifest = self._setup_secret(root, b"actual encrypted secret\n")
            with self.assertRaisesRegex(manage.ConfigError, "Passphrase session"):
                manage.stage_skill(repo, manifest, "access", root / "staging", None)


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
