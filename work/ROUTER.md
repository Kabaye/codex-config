## Runtime account policy
- Runtime instruction files beside this `AGENTS.md` are exactly `WORK.md` and `PRIVATE.md`.
- For each task, resolve the target repository root with `git rev-parse --show-toplevel`; when the target is not in a Git repository, use the current working directory. Normalize the absolute path before comparing it with `{{PRIVATE_ROOT}}`.
- Select `PRIVATE.md` only when the target path is that directory or a descendant by path component; otherwise select `WORK.md`. Do not use substring matching. On Windows, compare normalized path components case-insensitively.
- Before any task action or delegation (including native `spawn_agent`, OpenCode, and Cursor), read the selected sidecar in a completed, standalone preflight step. Never combine that read with task actions or agent launches in the same command or parallel tool batch; remembered routing rules are not a substitute.
- Re-read the selected sidecar for every new user request. Within one request, reuse it only while the target repository and file are unchanged; re-evaluate immediately if the target repository changes.
