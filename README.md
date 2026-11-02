# Codex Config

Manages **Codex instructions, universal browser/Computer Use policy, global specialist roles and skill installation**. Root model selection, native Solo/Team workers and their routing belong to [codex-profiles](https://github.com/Kabaye/codex-profiles); skill implementations and encrypted access bundles belong to the separate private `codex-skills` repository. The managers keep separate ownership state.

## Instruction sources

| Install profile | Global `$CODEX_HOME/AGENTS.md` | Inline account scope |
| --- | --- | --- |
| `work` | `AGENTS.md` + `profiles/work/AGENTS.md` | Personal policy under `<projects-root>/private`; work policy elsewhere |
| `private` | `AGENTS.md` + `profiles/private/AGENTS.md` | Personal policy |

`manifest.json` lists every profile's instruction sources in concatenation order, their runtime destinations and selected skills. Its global `agent_roles` mapping lists role destinations relative to `$CODEX_HOME/agents/` and their source TOMLs. Current profiles are declared entirely in the manifest; the Python manager reads and applies them. It retains compatibility with older manifests.

For manual installation, open `profiles.private` or `profiles.work` in the manifest, concatenate each `*_fragments` list in order and place the result at the corresponding `instruction_targets` destination. Replace `{{PROJECTS_ROOT}}` with the projects directory and `{{PRIVATE_ROOT}}` with its `private` subdirectory. Keep other content in the destination files. Use the declared begin/end markers around this manager's block if you will later manage it with the script. Source comments are bookkeeping and add no rules.

Both installations carry their complete account policy in the global `AGENTS.md`. Work applies the inline personal-account, Git-identity and SSH access-file rules under `<projects-root>/private`, using normalized path components; it applies the work rules elsewhere. The Work installation's personal policy remains independent of the separate Private installation.

Corporate routing and native Solo/Team delegation belong to the global `codex-profiles` block. Universal browser/Computer Use policy belongs to this repository's common `AGENTS.md` and is installed in both profiles. Install or instruction sync retires recorded legacy `WORK.md`/`PRIVATE.md` blocks while preserving user prose and other managers' blocks.

The shared `bots/AGENTS.md` source is installed as `<projects-root>/AGENTS.md` and synchronized into bot repositories when working on Telegram bots. Other project instructions remain untouched.

`CODEX_PROJECT_STYLE.md` is the retained optional reference for Codex project colors, icons, and workspace ordering. It is consulted when styling projects; installation does not apply it automatically.

## Global specialist roles

`agent_roles` applies independently of the Work/Private profile and native Solo/Team mode. The current mapping installs `agents/terra-computer.toml` as `$CODEX_HOME/agents/codex-config/terra-computer.toml`. Role models, effort and instructions live only in the source TOML. For manual installation, copy each declared source to its mapped destination under `$CODEX_HOME/agents/`, using UTF-8 and LF line endings. This manager uses only the `codex-config/` namespace; native profile roles use the separate `codex-profiles/` namespace.

`sync-roles` installs or refreshes only those role files and `$CODEX_HOME/codex-config/roles-state.json`. It needs no private skills checkout, crypto dependency or passphrase. The version-1 role state records relative POSIX destination paths and SHA-256 hashes of the actual installed bytes. Full install/remove also manage these roles within their existing rollback transactions; unrelated native and custom roles remain untouched.

For migration from flat role files, run `./manage.ps1 sync-roles` first, then refresh the installed native profile's current mode with its manager. Config publishes the nested role before removing an authenticated flat copy. A flat role can be adopted when its canonical contents match the source, or when older config/profiles ownership state proves its exact current hash. Config-owned roles with local edits, unowned collisions and linked paths are refused; `--force` does not bypass role ownership checks. Edit role sources and run `sync-roles` to change pinned role data. `capture` does not capture role edits.

Both managers coordinate role publication through `$CODEX_HOME/.agent-roles.lock`. A leftover lock requires review before retrying. Ownership and transaction state should not be deleted manually.

## Skill installation and access

`manifest.json` selects global and project-scoped skills per profile. Global skills go to `~/.agents/skills/<name>`; project-scoped skills go to `<project-root>/.agents/skills/<name>`. Skill sources are in the sibling private `codex-skills/skills/<name>` checkout. `profiles/<profile>/` overlays inside a skill source customize only the selected installation.

The `access-personal` skill has shared scripts with profile-dependent access rules. Work uses saved SSH credentials; Private can select native SSH through 1Password (`agent`) or a file-based helper (`file`). A user-authorized file exception is scoped to one chat/resource for 60 minutes. Host keys must be preverified. SSH config, endpoints, keys, credentials and runtime mode state **never belong in Git**. Encrypted `access.yml.age` sources are decrypted only on an authorized machine; `capture` does not re-encrypt them unless explicitly requested.

## Install and update

Requires **PowerShell 7**, **Python 3.11+**, Git, and the private `codex-skills` checkout alongside this repository (or an explicit `CODEX_SKILLS_REPO`). `manage.ps1` provisions its pinned Python dependency only when necessary.

```powershell
./manage.ps1 install -Profile work -DryRun
./manage.ps1 install -Profile work
./manage.ps1 status

# Refresh sources and reinstall, with clean Git checkouts
./manage.ps1 update -Profile work

# Refresh only managed instructions, preserving skills/auth/model/roles
./manage.ps1 sync-instructions -Profile work

# Refresh only global specialist roles, without private skills or passphrase access
./manage.ps1 sync-roles -DryRun
./manage.ps1 sync-roles

# Capture local managed edits back to their source files
./manage.ps1 capture -DryRun
./manage.ps1 capture

# Remove only manager-owned content
./manage.ps1 remove -DryRun
./manage.ps1 remove
```

Use `-Profile private` for the personal installation. By default the projects root is `$HOME/Projects`; provide `--projects-root` to change it and `--project-root` for project-scoped skills. `update` only fast-forwards clean repositories; it does **not** overwrite local changes.

Installation updates `codex-config`-owned blocks, selected skills and declared specialist roles. Instruction sync updates only instruction blocks and their hashes; it does not inspect or modify installed roles, model configuration or skills. Unrelated user content and `codex-profiles` markers remain intact. Edited owned blocks are refused unless explicitly reconciled (`capture` or reviewed `--force`). Manager transactions have rollback and state under `$CODEX_HOME/codex-config/`; do not manually delete this installed state.

## Verification

```powershell
./manage.ps1 validate -BaseOnly
./manage.ps1 validate
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

The full validation and tests need access to the private skills checkout. Do not commit secrets, `access.yml`, machine-specific settings, real endpoints or private operational data. Never force-push automatically.
