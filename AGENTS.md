## Git and workspace
- **Before every task in a Git repository with a remote, run `git fetch`.**
- Create worktrees only when the user explicitly requests one.
- Use Conventional Commits.
- Never force-push unless the user explicitly requests it.
## Access and authorization
- Never commit secrets or private information, including credentials, decrypted access files, payment card numbers, passport details, and real financial transactions.
- Display secrets or private information only when the user explicitly requests those details.
## Files and tooling
- Keep agent-only scratch files, downloads, one-off scripts, and logs in the project's `temp/`; add `temp/` to `.gitignore`.
- Verify required tools before use.
- On Windows, use PowerShell 7 (`pwsh`).
- Install standalone user tools under `$HOME/Programs`.
- Install project dependencies in the project's environment.
- Report installed tools/dependencies and their purpose in the final response.
## Work and verification
- Run focused tests while implementing; run broader checks after the full implementation.
- Store task workflow files in `temp/task-plans/`.
## Runtime account policy
- Runtime instruction files beside this `AGENTS.md` are exactly `WORK.md` and `PRIVATE.md`.
- For each task, resolve the target repository root with `git rev-parse --show-toplevel`; when the target is not in a Git repository, use the current working directory. Normalize the absolute path before comparing it with `{{PRIVATE_ROOT}}`.
- Select `PRIVATE.md` only when the target path is that directory or a descendant by path component; otherwise select `WORK.md`. Do not use substring matching. On Windows, compare normalized path components case-insensitively.
- Load only the selected sidecar. Reuse it while the task remains in context and its file is unchanged; re-evaluate if the target repository changes.
## Reporting
- Be precise, distinguish verified facts from assumptions, and prefer clear explanations or diagrams when they help.
- Keep external tickets, reviews, and release notes focused on observable changes, not raw agent logs.
- Summarize changes, checks, unresolved risks, and required manual steps. Match the user's numbering when they gave a numbered task list.
