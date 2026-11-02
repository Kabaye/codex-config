# Codex Config

Manages **Codex instructions and skill installation**. Model selection, agent roles and routing belong to [codex-profiles](https://github.com/Kabaye/codex-profiles); skill implementations and encrypted access bundles belong to the separate private `codex-skills` repository. The managers use independent ownership markers.

## Instruction sources

| Install profile | Global `$CODEX_HOME/AGENTS.md` | Additional policy files |
| --- | --- | --- |
| `work` | `AGENTS.md` + `work/AGENTS.md` | `work/WORK.md` → `WORK.md`; `work/PRIVATE.md` → `PRIVATE.md` |
| `private` | `AGENTS.md` + `private/AGENTS.md` | None |

On work installations, the global path router selects `PRIVATE.md` only inside `<projects-root>/private`, otherwise `WORK.md`. It reads the selected policy before **each request and delegation**. The Work installation's personal policy is independent of the separate Private installation.

The shared `bots/AGENTS.md` source is installed as `<projects-root>/AGENTS.md` and synchronized into bot repositories when working on Telegram bots. Other project instructions remain untouched.

`CODEX_PROJECT_STYLE.md` is the retained optional reference for Codex project colors, icons, and workspace ordering. It is consulted when styling projects; installation does not apply it automatically.

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

# Capture local managed edits back to their source files
./manage.ps1 capture -DryRun
./manage.ps1 capture

# Remove only manager-owned content
./manage.ps1 remove -DryRun
./manage.ps1 remove
```

Use `-Profile private` for the personal installation. By default the projects root is `$HOME/Projects`; provide `--projects-root` to change it and `--project-root` for project-scoped skills. `update` only fast-forwards clean repositories; it does **not** overwrite local changes.

Installation and instruction sync update only `codex-config`-owned blocks and skill directories. Unrelated user content and `codex-profiles` markers remain intact. Edited owned blocks are refused unless explicitly reconciled (`capture` or reviewed `--force`). Manager transactions have rollback and state under `$CODEX_HOME/codex-config/`; do not manually delete this installed state.

## Verification

```powershell
./manage.ps1 validate -BaseOnly
./manage.ps1 validate
python -m unittest discover -s tests -v
```

The full validation and tests need access to the private skills checkout. Do not commit secrets, `access.yml`, machine-specific settings, real endpoints or private operational data. Never force-push automatically.
