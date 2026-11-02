"""Global role ownership and the profiles-to-config handoff in isolated homes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "manage.py"
SPEC = importlib.util.spec_from_file_location("codex_config_manage_roles", SCRIPT)
assert SPEC and SPEC.loader
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class AgentRoleTests(unittest.TestCase):
    def setUp(self):
        output = mock.patch("builtins.print")
        output.start()
        self.addCleanup(output.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo, self.home = root / "repo", root / "home"
        self.repo.mkdir()
        (self.repo / "skills").mkdir()
        (self.repo / "bots").mkdir()
        (self.repo / "agents").mkdir()
        (self.repo / "AGENTS.md").write_text("Shared policy fixture.\n", encoding="utf-8")
        (self.repo / "bots" / "AGENTS.md").write_text("Project policy fixture.\n", encoding="utf-8")
        for profile in ("work", "private"):
            (self.repo / profile).mkdir()
            (self.repo / profile / "AGENTS.md").write_text(f"{profile} policy fixture.\n", encoding="utf-8")
        self.role_name = "codex-config/fixture-gui.toml"
        self.source = self.repo / "agents" / "fixture-source.toml"
        self.source.write_text(self.definition(), encoding="utf-8")
        self.manifest = {
            "schema_version": 1,
            "agent_roles": {self.role_name: "agents/fixture-source.toml"},
            "markers": {
                "global_begin": "<!-- codex-config:begin -->", "global_end": "<!-- codex-config:end -->",
                "projects_begin": "<!-- codex-config:projects:begin -->", "projects_end": "<!-- codex-config:projects:end -->",
            },
            "profiles": {profile: {
                "global_fragments": ["AGENTS.md", f"{profile}/AGENTS.md"],
                "projects_fragments": ["bots/AGENTS.md"], "work_fragments": [], "private_fragments": [],
                "skills": [], "project_skills": [],
            } for profile in ("work", "private")},
        }
        self.write_manifest()
        self.args = argparse.Namespace(
            repo=self.repo, home=self.home, projects_root=root / "projects", skills_root=root / "skills",
            project_root=root / "project", profile="private", dry_run=False, force=False,
        )

    def definition(self, model="fixture-model"):
        return ('name = "fixture_gui"\ndescription = "Fixture role"\n'
                f'model = "{model}"\nmodel_reasoning_effort = "high"\n'
                'developer_instructions = "Bounded fixture task"\n[agents]\nenabled = false\n')

    def write_manifest(self):
        (self.repo / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def snapshot(self):
        return {path.relative_to(self.home).as_posix(): path.read_bytes()
                for path in self.home.rglob("*") if path.is_file()}

    def role_path(self):
        return self.home / "agents" / self.role_name

    def expected_role_bytes(self):
        return self.source.read_bytes().replace(b"\r\n", b"\n")

    def legacy_role_path(self):
        return self.home / "agents" / Path(self.role_name).name

    def state(self):
        return json.loads(manage.role_state_path(self.home).read_text(encoding="utf-8"))

    def seed_legacy(self, raw=None):
        raw = self.definition("older-fixture-model").encode() if raw is None else raw
        self.legacy_role_path().parent.mkdir(parents=True, exist_ok=True)
        self.legacy_role_path().write_bytes(raw)
        path = self.home / "profiles" / "roles-state.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"version": 2, "profile": "private", "mode": "team",
                                   "owned": {self.legacy_role_path().name: manage.sha256_bytes(raw)}}), encoding="utf-8")
        return path

    def test_sync_roles_installs_source_data_and_independent_ownership_without_skills_or_secrets(self):
        (self.repo / "skills").rmdir()
        with mock.patch.object(manage, "ensure_skills_checkout", side_effect=AssertionError("no skill checkout")), \
                mock.patch.object(manage, "skills_repository_root", side_effect=AssertionError("no skill source")), \
                mock.patch.object(manage, "PassphraseSession", side_effect=AssertionError("no decryption")):
            manage.sync_roles_command(self.args)
            manage.sync_roles_command(self.args)
        raw = self.role_path().read_bytes()
        self.assertEqual(raw, self.expected_role_bytes())
        self.assertEqual(self.state(), {"version": 1, "owned": {self.role_name: manage.sha256_bytes(raw)}})
        self.assertEqual(set(self.snapshot()), {f"agents/{self.role_name}", "codex-config/roles-state.json"})
        self.assertFalse((self.home / ".agent-roles.lock").exists())
        with mock.patch("builtins.print") as output:
            manage.status_command(self.args)
        self.assertTrue(json.loads(output.call_args.args[0])["healthy"])
        self.source.write_text(self.definition("updated-fixture-model"), encoding="utf-8")
        manage.sync_roles_command(self.args)
        self.assertIn(b'updated-fixture-model', self.role_path().read_bytes())

    def test_full_install_both_profiles_and_remove_manage_roles_preserving_other_owners(self):
        self.role_path().parent.mkdir(parents=True)
        other = self.home / "agents" / "codex-profiles" / "native-worker.toml"
        other.parent.mkdir()
        other.write_text("native fixture\n", encoding="utf-8")
        for profile in ("work", "private"):
            self.args.profile = profile
            manage.install_command(self.args)
            self.assertEqual(self.role_path().read_bytes(), self.expected_role_bytes())
            with mock.patch("builtins.print") as output:
                manage.status_command(self.args)
            report = json.loads(output.call_args.args[0])
            self.assertEqual(report["agent_roles"], {self.role_name: True})
            self.assertTrue(report["healthy"])
        manage.remove_command(self.args)
        self.assertFalse(self.role_path().exists())
        self.assertFalse(manage.role_state_path(self.home).exists())
        self.assertEqual(other.read_text(encoding="utf-8"), "native fixture\n")

    def test_role_only_remove_uses_ownership_and_preserves_unrelated_files(self):
        manage.sync_roles_command(self.args)
        (self.home / "config.toml").write_text("config fixture\n", encoding="utf-8")
        manage.remove_command(self.args)
        self.assertFalse(self.role_path().exists())
        self.assertFalse(manage.role_state_path(self.home).exists())
        self.assertEqual((self.home / "config.toml").read_text(), "config fixture\n")

    def test_retired_manifest_role_is_removed_and_old_manifests_default_to_no_roles(self):
        manage.sync_roles_command(self.args)
        self.manifest.pop("agent_roles")
        self.write_manifest()
        self.assertEqual(manage.load_manifest(self.repo, base_only=True)["agent_roles"], {})
        manage.sync_roles_command(self.args)
        self.assertFalse(self.role_path().exists())
        self.assertFalse(manage.role_state_path(self.home).exists())

    def test_sync_roles_cli_never_loads_private_sources_or_decrypts(self):
        arguments = ["manage.py", "sync-roles", "--repo", str(self.repo), "--home", str(self.home),
                     "--projects-root", str(self.args.projects_root), "--project-root", str(self.args.project_root),
                     "--skills-root", str(self.args.skills_root)]
        with mock.patch.object(manage.sys, "argv", arguments), \
                mock.patch.object(manage, "skills_repository_root", side_effect=AssertionError("no private sources")), \
                mock.patch.object(manage, "PassphraseSession", side_effect=AssertionError("no decryption")):
            self.assertEqual(manage.main(), 0)
        self.assertEqual(self.role_path().read_bytes(), self.expected_role_bytes())
        self.assertFalse((self.home / "AGENTS.md").exists())
        self.assertFalse(manage.state_path(self.home).exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 wrapper check")
    def test_powershell_wrapper_forwards_role_only_dry_run(self):
        result = subprocess.run([
            "pwsh", "-NoProfile", "-File", str(SCRIPT.parents[1] / "manage.ps1"), "sync-roles",
            "--repo", str(self.repo), "--home", str(self.home), "--dry-run",
        ], capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["action"], "sync-roles")
        self.assertFalse(report["skills_touched"])
        self.assertFalse(self.home.exists())

    def test_identical_canonical_file_is_adopted_and_written_with_lf(self):
        self.role_path().parent.mkdir(parents=True)
        self.role_path().write_bytes(self.expected_role_bytes().replace(b"\n", b"\r\n"))
        manage.sync_roles_command(self.args)
        raw = self.role_path().read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertEqual(self.state()["owned"][self.role_name], manage.sha256_bytes(raw))

    def test_exact_legacy_profiles_hash_authorizes_handoff_without_changing_profiles_state(self):
        legacy = self.seed_legacy()
        before = legacy.read_bytes()
        manage.sync_roles_command(self.args)
        self.assertEqual(self.role_path().read_bytes(), self.expected_role_bytes())
        self.assertFalse(self.legacy_role_path().exists())
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(self.state()["owned"][self.role_name], manage.sha256_file(self.role_path()))

    def test_canonical_flat_copy_moves_to_namespace_before_old_file_is_removed(self):
        self.legacy_role_path().parent.mkdir(parents=True)
        self.legacy_role_path().write_bytes(self.expected_role_bytes().replace(b"\n", b"\r\n"))
        real_write = manage.atomic_write_bytes

        def check_publication_order(path, raw):
            if path == self.role_path():
                self.assertTrue(self.legacy_role_path().exists())
            real_write(path, raw)

        with mock.patch.object(manage, "atomic_write_bytes", side_effect=check_publication_order):
            manage.sync_roles_command(self.args)
        self.assertFalse(self.legacy_role_path().exists())
        self.assertEqual(self.role_path().read_bytes(), self.expected_role_bytes())
        self.assertEqual(set(self.state()["owned"]), {self.role_name})

    def test_old_config_flat_ownership_migrates_to_nested_owner_state(self):
        old = self.definition("older-config-model").encode()
        self.legacy_role_path().parent.mkdir(parents=True)
        self.legacy_role_path().write_bytes(old)
        manage.write_json(manage.role_state_path(self.home), {
            "version": 1, "owned": {self.legacy_role_path().name: manage.sha256_bytes(old)},
        })
        manage.sync_roles_command(self.args)
        self.assertFalse(self.legacy_role_path().exists())
        self.assertEqual(self.role_path().read_bytes(), self.expected_role_bytes())
        self.assertEqual(set(self.state()["owned"]), {self.role_name})

    def test_namespace_migration_failure_restores_flat_role_and_state(self):
        legacy = self.seed_legacy()
        before = self.snapshot()
        real_write = manage.atomic_write_bytes
        failed = False

        def fail_state_once(path, raw):
            nonlocal failed
            if path == manage.role_state_path(self.home) and not failed:
                failed = True
                raise OSError("simulated namespace publication failure")
            real_write(path, raw)

        with mock.patch.object(manage, "atomic_write_bytes", side_effect=fail_state_once):
            with self.assertRaisesRegex(OSError, "namespace publication failure"):
                manage.sync_roles_command(self.args)
        self.assertFalse(self.role_path().exists())
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(legacy.exists())

    def test_normal_role_sync_ignores_profiles_namespace_and_state(self):
        manage.sync_roles_command(self.args)
        foreign = self.home / "agents" / "codex-profiles" / "native-fixture.toml"
        foreign.parent.mkdir()
        foreign.write_text("foreign role fixture\n", encoding="utf-8")
        foreign_state = self.home / "profiles" / "roles-state.json"
        foreign_state.parent.mkdir()
        foreign_state.write_text("foreign state fixture\n", encoding="utf-8")
        self.source.write_text(self.definition("updated-fixture-model"), encoding="utf-8")
        manage.sync_roles_command(self.args)
        self.assertEqual(foreign.read_text(), "foreign role fixture\n")
        self.assertEqual(foreign_state.read_text(), "foreign state fixture\n")

    def test_unowned_and_modified_legacy_files_are_refused_without_writes(self):
        legacy = self.seed_legacy()
        self.legacy_role_path().write_bytes(self.legacy_role_path().read_bytes() + b"# user edit\n")
        before = self.snapshot()
        with self.assertRaisesRegex(manage.ConfigError, "Unowned legacy flat agent role collision"):
            manage.sync_roles_command(self.args)
        self.assertEqual(self.snapshot(), before)
        legacy.unlink()
        before = self.snapshot()
        with self.assertRaisesRegex(manage.ConfigError, "Unowned legacy flat agent role collision"):
            manage.sync_roles_command(self.args)
        self.assertEqual(self.snapshot(), before)

    def test_modified_config_owned_role_refuses_sync_install_and_remove_even_with_force(self):
        manage.install_command(self.args)
        self.role_path().write_bytes(self.role_path().read_bytes() + b"# user edit\n")
        before = self.snapshot()
        self.args.force = True
        for command in (manage.sync_roles_command, manage.install_command, manage.remove_command):
            with self.subTest(command=command.__name__), self.assertRaisesRegex(manage.ConfigError, "role changed or missing"):
                command(self.args)
            self.assertEqual(self.snapshot(), before)

    def test_legacy_adoption_proof_is_rechecked_before_publication(self):
        legacy = self.seed_legacy()
        manifest = manage.load_manifest(self.repo, base_only=True)
        with manage.AgentRolesLock(self.home):
            plan = manage.plan_agent_roles(self.repo, manifest, self.home)
            legacy.write_text(legacy.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(manage.ConfigError, "changed during preflight"):
                manage.apply_agent_role_plan(plan, self.home)
        self.assertFalse(manage.role_state_path(self.home).exists())

    def test_role_sync_write_failure_restores_role_and_ownership_state(self):
        manage.sync_roles_command(self.args)
        before = self.snapshot()
        self.source.write_text(self.definition("updated-fixture-model"), encoding="utf-8")
        real_write = manage.atomic_write_bytes
        failed = False

        def fail_state_once(path, raw):
            nonlocal failed
            if path == manage.role_state_path(self.home) and not failed:
                failed = True
                raise OSError("simulated role state write failure")
            real_write(path, raw)

        with mock.patch.object(manage, "atomic_write_bytes", side_effect=fail_state_once):
            with self.assertRaisesRegex(OSError, "role state write failure"):
                manage.sync_roles_command(self.args)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list((self.home / "codex-config").glob("txn-*")))
        self.assertFalse((self.home / ".agent-roles.lock").exists())

    def test_full_install_failure_after_role_write_restores_all_managed_files(self):
        manage.install_command(self.args)
        before = self.snapshot()
        self.source.write_text(self.definition("updated-fixture-model"), encoding="utf-8")
        self.args.profile = "work"
        real_write = manage.write_json

        def fail_main_state(path, value):
            if path == manage.state_path(self.home):
                raise OSError("simulated full state write failure")
            real_write(path, value)

        with mock.patch.object(manage, "write_json", side_effect=fail_main_state):
            with self.assertRaisesRegex(OSError, "full state write failure"):
                manage.install_command(self.args)
        self.assertEqual(self.snapshot(), before)

    def test_full_remove_failure_restores_role_and_base_ownership(self):
        manage.install_command(self.args)
        before = self.snapshot()
        with mock.patch.object(manage, "mark_transaction_committed", side_effect=OSError("simulated commit failure")):
            with self.assertRaisesRegex(OSError, "commit failure"):
                manage.remove_command(self.args)
        self.assertEqual(self.snapshot(), before)

    def test_interrupted_role_transaction_recovers_under_shared_lock(self):
        manage.sync_roles_command(self.args)
        before = self.snapshot()
        self.source.write_text(self.definition("updated-fixture-model"), encoding="utf-8")
        manifest = manage.load_manifest(self.repo, base_only=True)
        manager_root = self.home / "codex-config"
        transaction = manager_root / "txn-sync-roles-fixture"
        transaction.mkdir()
        with manage.AgentRolesLock(self.home):
            plan = manage.plan_agent_roles(self.repo, manifest, self.home)
            backups = manage.backup_agent_roles(plan, transaction, self.home)
            manage.write_json(transaction / "journal.json", {
                "schema_version": 1, "phase": "prepared", "operation": "sync-roles",
                "repo_root": str(self.repo), "home": str(self.home),
                "projects_root": str(self.args.projects_root), "project_root": str(self.args.project_root),
                "skills": {}, "project_skills": {}, **backups,
            })
            manage.apply_agent_role_plan(plan, self.home)
        manage.recover_transactions(manager_root, self.home, self.args.projects_root, self.repo, self.args.project_root)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / ".agent-roles.lock").exists())

    def test_instruction_sync_does_not_check_or_modify_owned_roles(self):
        manage.install_command(self.args)
        self.role_path().write_text("user-edited role fixture\n", encoding="utf-8")
        (self.home / "config.toml").write_text("selected model fixture\n", encoding="utf-8")
        before = self.snapshot()
        (self.repo / "AGENTS.md").write_text("Updated shared policy fixture.\n", encoding="utf-8")
        with mock.patch.object(manage, "PassphraseSession", side_effect=AssertionError("no decryption")):
            manage.sync_instructions_command(self.args)
        after = self.snapshot()
        for name, raw in before.items():
            if name not in {"AGENTS.md", "codex-config/state.json"}:
                self.assertEqual(after[name], raw)

    def test_shared_role_lock_refuses_mutation_and_dry_run_is_read_only(self):
        dry = argparse.Namespace(**{**vars(self.args), "dry_run": True})
        manage.sync_roles_command(dry)
        self.assertFalse(self.home.exists())
        self.home.mkdir()
        (self.home / ".agent-roles.lock").mkdir()
        for args in (self.args, dry):
            with self.assertRaisesRegex(manage.ConfigError, "Another agent role operation"):
                manage.sync_roles_command(args)
        self.assertEqual(self.snapshot(), {})

    def test_manifest_rejects_unsafe_role_destinations_and_sources(self):
        for mapping in ({"../escape.toml": "agents/fixture-source.toml"},
                        {"CON.toml": "agents/fixture-source.toml"},
                        {"codex-profiles/foreign.toml": "agents/fixture-source.toml"},
                        {"codex-config/../escape.toml": "agents/fixture-source.toml"},
                        {"codex-config\\escape.toml": "agents/fixture-source.toml"},
                        {self.role_name: "../outside.toml"}):
            with self.subTest(mapping=mapping):
                self.manifest["agent_roles"] = mapping
                self.write_manifest()
                with self.assertRaises(manage.ConfigError):
                    manage.load_manifest(self.repo, base_only=True)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_linked_role_directory_is_refused_without_touching_target(self):
        import _winapi
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / self.role_name).parent.mkdir(parents=True)
        (outside / self.role_name).write_text("outside fixture\n", encoding="utf-8")
        self.home.mkdir()
        _winapi.CreateJunction(str(outside), str(self.home / "agents"))
        with self.assertRaisesRegex(manage.ConfigError, "Symlinked or junction|escapes its allowed root"):
            manage.sync_roles_command(self.args)
        self.assertEqual((outside / self.role_name).read_text(), "outside fixture\n")


if __name__ == "__main__":
    unittest.main()
