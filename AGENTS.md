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
## Reporting
- Be precise, distinguish verified facts from assumptions, and prefer clear explanations or diagrams when they help.
- Keep external tickets, reviews, and release notes focused on observable changes, not raw agent logs.
- Summarize changes, checks, unresolved risks, and required manual steps. Match the user's numbering when they gave a numbered task list.
