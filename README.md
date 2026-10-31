# Codex Config

**A reproducible configuration layer for Codex.** This repository manages
shared agent instructions, profile-specific rules, installation, verification,
and rollback. It keeps environment-specific credentials and skill
implementations outside this repository.

The setup is split into three repositories:

| Repository | Responsibility |
| --- | --- |
| **codex-config** (this repository) | Shared `AGENTS.md`, installation manifest, manager, and tests |
| [codex-profiles](https://github.com/Kabaye/codex-profiles) | Model selection, agent roles, and routing policy |
| **codex-skills** (private) | Skill implementations, resources, tests, and encrypted access bundles |

The two configuration managers have separate ownership markers and can be
installed independently. Skill access is never implied by access to this
public configuration repository.

## What the manager installs

| Component | Target |
| --- | --- |
| Shared instructions and profile metadata | `$CODEX_HOME/AGENTS.md` (managed blocks only) |
| Work account policy (work profile) | `$CODEX_HOME/WORK.md` (managed block only) |
| Personal account policy (work profile) | `$CODEX_HOME/PRIVATE.md` (managed block only) |
| Personal account policy (private profile) | Inline in `$CODEX_HOME/AGENTS.md` |
| Shared bot rules source | `<projects-root>/AGENTS.md` (managed block only; defaults to `$HOME/Projects`) |
| Bot repository rules | `<bot-repo>/AGENTS.md` (common block synchronized by the agent before implementation) |
| User-global skills | `$HOME/.agents/skills/<skill>` |
| Project-scoped skills | `<project-root>/.agents/skills/<skill>` |
| Installation state and rollback transactions | `$CODEX_HOME/codex-config/` |

The `work` and `private` profiles choose which skills belong to each scope
through `manifest.json`. The manager installs only the selected profile's
managed skill directories and preserves unrelated files and profile overlays.
The **work** profile installs both account sidecars for automatic target-path
selection: the runtime loads `PRIVATE.md` only for repositories under
`<projects-root>/private` (the default `<projects-root>` is `$HOME/Projects`)
and `WORK.md` elsewhere. Its global `AGENTS.md` is assembled from the shared
`AGENTS.md` and `work/AGENTS.md` (including account routing and policy preflight).
The work account policy itself is sourced from `work/WORK.md` and written to
`WORK.md`; the personal policy on the work computer is sourced from
`work/PRIVATE.md` and written to `PRIVATE.md`. This source is independent of
the separate `private` profile.

The **private** profile installs shared rules and personal account policy
together in one global `AGENTS.md`. It has no path-based account selection
and creates neither account sidecar. Moving an older split private installation
to this layout removes only codex-config's sidecar blocks. Other managers'
blocks and user prose remain; a sidecar is deleted only when empty.

The canonical skill directory is `codex-skills/skills/<name>`, regardless
of installation scope. Access bundles remain encrypted in its private Git
history; they are decrypted only on an authorized user's machine.

Both profiles install one `access-personal` skill with shared scripts and the
instructions selected for the installation profile. The `work` profile uses
saved SSH credentials only. The `private` profile defaults to 1Password and
supports a persistent `agent`/`file` selection; an explicit file exception in
agent mode lasts 60 minutes for one chat and resource. The SSH helper checks
the installed profile, current mode and expiry for each new connection.
Existing connections continue unchanged. No hooks or background process are
required; the task must still authorize the resource and action.

Skills can provide profile overrides under `profiles/<profile>/`. Installation
overlays those files onto the common skill and omits the source variants from
the installed copy. Capture routes changes to selected overrides back to that
variant while preserving the common files and other profiles.

## Prerequisites

- Git
- Python 3.11+
- PowerShell 7 on Windows
- Access to your own private `codex-skills` checkout if installing skills
- The pinned Python dependency in `requirements.txt` for encrypted access

## Install

Clone this repository and place the private skills checkout next to it.
For the maintainer's deployment, the latter is
`git@github.com:Kabaye/codex-skills.git`. Other users can supply a compatible
private skill repository.

```powershell
git clone https://github.com/Kabaye/codex-config.git
git clone git@github.com:Kabaye/codex-skills.git
Set-Location ./codex-config

./manage.ps1 install -Profile work
./manage.ps1 status
```

Use `-Profile private` for the personal profile.

By default, project-scoped skills are installed into the parent directory
of the `codex-config` checkout. Supply `--project-root <path>` when the
target project is elsewhere, and set `CODEX_SKILLS_REPO` when the private
skill repository is not a sibling checkout.

Only managed instruction blocks and selected managed skill directories are
replaced. Existing auth sessions, profile role configuration, and unrelated
user files are preserved.

## Common commands

```powershell
# Preview changes without writing files
./manage.ps1 install -Profile work -DryRun

# Install or switch between profiles
./manage.ps1 install -Profile work
./manage.ps1 install -Profile private

# Refresh both codex-config and private codex-skills, then reinstall
./manage.ps1 update -Profile work

# Inspect the installed profile and the two skill scopes
./manage.ps1 status

# Refresh instructions only, without touching skills, auth, config.toml, or roles
./manage.ps1 sync-instructions -Profile work
# Use the same project root as install when it is customized
./manage.ps1 sync-instructions -Profile work --projects-root D:/workspace
# Restore a private installation to its single-file instruction layout
./manage.ps1 sync-instructions -Profile private

# Capture managed local changes back to their original source repositories
./manage.ps1 capture -DryRun
./manage.ps1 capture

# Optional: explicitly re-encrypt installed access files
./manage.ps1 capture -CaptureSecrets

# Uninstall only the files owned by the manager
./manage.ps1 remove -DryRun
./manage.ps1 remove
```

The `update` command fetches both Git remotes and only pulls by fast-forward
when the checkouts are clean. It refuses to overwrite uncommitted changes.

Instruction refreshes preserve edits outside codex-config's owned blocks and
refuse to overwrite changed owned blocks without `--force`. An unrecorded
sidecar block can be retired only when it exactly matches a known generated
block. Run `sync-instructions` before `capture` when upgrading an installation
whose source markers describe an older layout; capture rejects mismatched
layouts before writing sources.

## Encrypted access

Encrypted `access.yml.age` files remain inside private skill directories.
The installer opens those files directly using an interactive age passphrase
for each installation or update. No supplementary private configuration
directory is required.

Ordinary `capture` preserves existing encrypted source files. Use
`capture -CaptureSecrets` when you explicitly intend to re-encrypt installed
access files. Failed operations are recovered from protected rollback backups.

Never commit `access.yml`, local application configuration, passwords, tokens,
or machine-specific runtime files.

## Agent conventions

The shared `AGENTS.md` includes Git integrity, least-privilege access,
project-local temporary files, conventional commits, and validation guidance.
In the work profile, `WORK.md` contains work account rules and `PRIVATE.md`
contains personal account rules. Both use the same codex-config markers.
The private profile includes `private/AGENTS.md` directly after shared rules
in the global managed block. It does not include `work/AGENTS.md` or
`work/PRIVATE.md`; the two profiles maintain independent personal policies.
**Every Git repository task starts with `git fetch`** when a remote exists;
fetch never implies permission to merge, reset, or force-push.

The optional `CODEX_PROJECT_STYLE.md` is a reusable reference for organizing
Codex projects. The `bots/AGENTS.md` file provides general Telegram bot
release-communication and interaction conventions. The global instructions point
to its installed copy in `<projects-root>/AGENTS.md`. Before implementing a
Telegram bot change, the agent synchronizes these rules into the repository's
`AGENTS.md`, between `<!-- codex-config:bots:begin -->` and
`<!-- codex-config:bots:end -->`, preserving other content. Each bot repository
keeps the same common rules; subsequent bot work refreshes a stale copy.

Model routing is intentionally out of scope: use
[codex-profiles](https://github.com/Kabaye/codex-profiles) for
`work` and `private` routing.

## Development and checks

```powershell
python -m py_compile ./scripts/manage.py

# Public/base checks do not require the private skills checkout
./manage.ps1 validate -BaseOnly

# Full source validation requires the private skills checkout
./manage.ps1 validate

python -m unittest discover -s tests -v
```

Continuous integration compiles the manager, validates the public base, and
runs isolated manager tests. Skill implementation tests run in the private
`codex-skills` repository.

## Safety boundaries

- Never commit secrets, personal access material, or operational identifiers.
- Keep private skill sources and encrypted access files in the private repository.
- Do not infer publication rights from a skill name or a sharing-policy label.
- Verify repository visibility and Git history before making a formerly
  private configuration public.
