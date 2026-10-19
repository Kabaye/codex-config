# Private Profile Rules

## Scope and Access

- Follow the shared `AGENTS.md` security rules.
- Access personal credentials only when the task specifically requires and
  authorizes them. An available private skill is not blanket authorization.
- Use password-manager CLIs and elevated authentication tools only when
  specifically authorized. Never disclose or commit decrypted access files.

## Workspace and Git

- Reuse an existing project checkout before considering a clone.
- Use the verified personal Git identity for personal repositories.
- Run `git fetch` before starting work in a repository with a remote.

## Local Applications

- A request to restart an application authorizes action on that application
  only; it does not automatically authorize changing background services,
  scheduled tasks, system settings, or other processes.
