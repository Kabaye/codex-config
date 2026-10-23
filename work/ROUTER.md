## Runtime account policy
- Runtime instruction files beside this `AGENTS.md` are exactly `WORK.md` and `PRIVATE.md`.
- For each task, resolve the target repository root with `git rev-parse --show-toplevel`; when the target is not in a Git repository, use the current working directory. Normalize the absolute path before comparing it with `{{PRIVATE_ROOT}}`.
- Select `PRIVATE.md` only when the target path is that directory or a descendant by path component; otherwise select `WORK.md`. Do not use substring matching. On Windows, compare normalized path components case-insensitively.
- Load only the selected sidecar. Reuse it while the task remains in context and its file is unchanged; re-evaluate if the target repository changes.
