# Shared Codex Agent Instructions

These rules apply to the `work` and `private` profiles. Profile-specific
instructions may add restrictions, but must not override user authorization,
repository integrity, or credential safety.

## Start of a Task

1. If the current project is a Git repository with a configured remote, run
   `git fetch` **before analyzing, planning, or changing project files**.
2. Inspect `git status`, the active branch, and upstream divergence as needed.
3. Read the relevant instructions, project files, and tests before editing.
4. Do not treat a failed fetch as evidence that the remote is up to date.
   If no remote exists or network access is unavailable, report the limitation.
5. Fetch does **not** authorize pulling, merging, rebasing, resetting,
   switching branches, force-pushing, or discarding local changes.

## Ownership and Git Safety

- Preserve all unrelated user changes, including untracked files.
- Do not create a worktree without explicit permission. Reuse an existing
  checkout instead of cloning another copy.
- For authorized implementation, initialize Git only when the project actually
  needs version control; never initialize during read-only inspection.
- Use Conventional Commits. Stage only files relevant to the task.
- Before committing, check `git status` again and verify the repository's
  configured Git identity. Never invent an author or committer identity.
- Never force-push or rewrite published history without explicit authorization.
- Avoid destructive file operations unless they are necessary and authorized.

## Credentials and External Systems

- Use only the credentials, accounts, and integrations authorized for the
  specific task and environment.
- Do not guess credentials or attempt automated login attacks.
- Never print, commit, export, or expose passwords, tokens, personal data,
  private key material, or decrypted access files.
- Keep secret storage, configuration, and access policy outside public Git
  repositories. A private skill source does not imply public sharing rights.
- Ask before destructive, externally visible, privilege-changing, or
  materially out-of-scope actions if they have not already been authorized.
- Use private credential managers and supported identity mechanisms for
  environment-specific authentication.

## Temporary Files and Tooling

- Keep generated scratch files, downloads, one-off scripts, and diagnostic logs
  under `temp/` in the active project. Never commit the directory.
- Check whether a required program is installed before attempting to run it.
- On Windows, use PowerShell 7 (`pwsh`), not legacy Windows PowerShell.
- Install standalone user tools in `$HOME/Programs` unless configured otherwise.
- Install application dependencies in the project's own managed environment.
- Document any new standalone tools or project dependencies in the final report.

## Implementation and Validation

- Keep work within the user's requested scope and incorporate corrections.
- Inspect existing behavior and tests before implementing changes.
- Use focused checks during development; run broader validation after a
  coherent implementation batch rather than after every small edit.
- Validate sensitive changes, migrations, security boundaries, concurrency,
  or public contracts more thoroughly when the risk warrants it.
- Document changes to public APIs and update API specifications as needed.
- Do not deploy or send announcements without an appropriate authorization
  and verification path. Repository-specific rules may impose additional gates.
- If starting a development server, report its exact URL and how to stop it.

## Project-Specific Instructions

- For Telegram bot projects, read the installed shared bot contract in
  `$HOME/Projects/AGENTS.md`. Project-level rules may further constrain it.
- When asked to organize Codex projects, consult `CODEX_PROJECT_STYLE.md`
  in this repository. Do not change appearance during unrelated tasks.

## Communication

- Prefer clear, precise language over jargon for its own sake.
- Put prerequisites before actions and separate verified facts from assumptions.
- When a diagram or small artifact conveys structure more clearly than prose,
  use it when the tools and task support that format.
- Keep user-facing release notes, comments, and change summaries concise and
  focused on observable behavior. Avoid dumping internal implementation logs.
- In the final response, report what changed, relevant validation results,
  any unresolved risks, and genuinely required manual steps.
- If the user supplied a numbered task list, answer using the same numbering.
