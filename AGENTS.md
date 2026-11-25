## Git and workspace
- **Before every task in a Git repository with a remote, run `git fetch`.**
- Create worktrees only when the user explicitly requests one.
- Use Conventional Commits.
- Never force-push unless the user explicitly requests it.
## Access and authorization
- Treat every repository as public, even if marked private.
- Never commit secrets or private information in files or Git metadata. Use synthetic data and portable placeholders instead of personal, financial or infrastructure details.
- Display secrets or private information only when the user explicitly requests those details.
- Before SSH, check `access-personal` for the resource's source: native SSH with 1Password for `agent`, its helper for `file`. Change modes or grant file exceptions only at the user's explicit request.
## Tools and interfaces
- Prefer a suitable installed CLI, then API/MCP, then browser, then desktop Computer Use. Fix invocation errors before falling back; respect access denials across interfaces.
- When the user asks you to send a Telegram message on their behalf, use the connected plugin with @thekabaye by default.
- When sending images, use the service's image upload mode. In Webex, set the multipart `files` part's `Content-Type` to the actual image MIME type (e.g. `image/png`). Use the Webex Messages API if the CLI cannot set it, and verify the uploaded attachment's `Content-Type`.
- Use Opera through the Browser extension for browser tasks. Handle straightforward browser workflows directly.
- Use desktop Computer Use only when the user explicitly requests it or approves it for the task. Delegate authorized desktop GUI work to `terra_computer` and verify the visible result. Report unavailable model, tools or permissions.
- Never use the in-app browser.
- For design generation, you may offer root/Sol 6.2 or `astra_designer` (Astra 6.2). Use Astra only after the user explicitly requests or selects it.
## Files and tooling
- Keep agent-only scratch files, downloads, one-off scripts, and logs in the project's `temp/`; add `temp/` to `.gitignore`.
- Verify required tools before use.
- On Windows, use PowerShell 7 (`pwsh`).
- Install standalone user tools under `$HOME/Programs`.
- Name each skill's runtime directory after the skill.
- Install project dependencies in the project's environment.
- Report installed tools/dependencies and their purpose in the final response.
## Work and verification
- Run focused tests while implementing; run broader checks after the full implementation.
- Store task workflow files in `temp/task-plans/`.
- For a task in `$task-start` or `$task-discuss`, keep that stage active across turns until the user explicitly invokes a different stage for that task. Imperatives such as “fix”, “restore” or “apply”, agreement, and a ready plan specify the desired outcome. The user starts implementation with an explicit `$task-implement` invocation for the selected task in the current chat.
- Before each tool call for that task, check the active stage and the call's side effects, including calls through other skills and delegates. Capture can write the plan and its attachments. Discussion can inspect systems read-only, update the plan, and create local discussion artifacts in ignored `temp/`. Repository edits, deployments, external sends, and writes to live data or settings require authorized implementation. When authorization is unclear, keep inspection read-only. Run expressly requested experiments on isolated local copies or fixtures under `temp/`.
- For Telegram bot projects, read the `bots/AGENTS.md` rules in `{{PROJECTS_ROOT}}/AGENTS.md`. Before implementation, synchronize them into a `codex-config:bots` block in the repository's `AGENTS.md` and follow them; preserve the rest of the file.
## Reporting
- Use English by default for content in work systems (including TMS and GitLab) and all subagent instructions, reasoning and replies, unless the user explicitly requests another language. Match the user's language in chat.
- Be precise, distinguish verified facts from assumptions, and prefer clear explanations or diagrams when they help.
- Use HTML when useful; generate PDF only when explicitly requested.
- Keep external tickets, reviews, and release notes focused on observable changes, not raw agent logs.
- Summarize changes, checks, unresolved risks, and required manual steps. Match the user's numbering when they gave a numbered task list.
