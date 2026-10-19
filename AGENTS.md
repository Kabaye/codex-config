# Shared Codex Rules

## Git and workspace

- **Before every task in a Git repository with a remote, run `git fetch`**, then inspect `git status` and the branch/upstream as relevant. If fetch fails, report it; never assume remote information is current. With no remote, note that fetching is inapplicable. Fetch does **not** authorize pull, merge, rebase, reset, branch switches, force-push, or discarding local changes.
- Read applicable instructions, code, and tests before editing. Preserve unrelated changes, including untracked files. Reuse an existing checkout; no worktrees without explicit permission. Initialize Git only for authorized implementation that needs it, never for read-only research.
- Use Conventional Commits; stage only task-related files. Before committing, recheck `git status` and the repository's Git identity; never invent an identity. No force-push or published-history rewrite without explicit authorization.

## Access and authorization

- Use only accounts, credentials, and integrations authorized for this task. Never guess credentials or attempt automated login attacks.
- Never print, commit, export, or expose secrets, personal information, private keys, or decrypted access files. Keep credentials and private policies out of public Git; use supported secret managers.
- Ask before unapproved destructive, externally visible, privilege-changing, or out-of-scope operations. Research-only requests remain read-only.

## Files and tooling

- Put agent-only scratch files, downloads, one-off scripts, and logs under the project's `temp/`; never commit them.
- Verify required tools before use. On Windows use PowerShell 7 (`pwsh`), not legacy PowerShell. Put standalone user tools under `$HOME/Programs` unless configured otherwise; install project dependencies in the project's environment.
- Report installed tools/dependencies and their purpose in the final response.

## Work and verification

- Follow the user's scope and corrections; do not revert unrelated edits. Inspect existing behavior first.
- Batch changes and run focused checks while implementing; run broader checks when the batch is complete. Security, migration, concurrency, and public-contract changes may warrant earlier validation.
- Update documentation for public APIs and HTTP specifications as needed. Deploy and announce releases only with authorization and verification. Report a started dev server's exact URL and how to stop it.
- For Telegram bot tasks, read `$HOME/Projects/AGENTS.md` and any project contract. Use `CODEX_PROJECT_STYLE.md` only for requested Codex project appearance changes; never reorganize projects automatically.

## Reporting

- Be precise, distinguish verified facts from assumptions, and prefer clear explanations or diagrams when they help.
- Keep external tickets, reviews, and release notes focused on observable changes, not raw agent logs.
- Summarize changes, checks, unresolved risks, and required manual steps. Match the user's numbering when they gave a numbered task list.
