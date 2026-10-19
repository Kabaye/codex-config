# Telegram Bot Contract

Repository rules define recipients, version, commands and deployment mechanics; they may strengthen but not weaken these safeguards.

## Releases

- A production deployment with user-visible changes requires **one polished Russian notification** to all eligible users, unless explicitly suppressed or postponed. A deploy request authorizes preparing the message and, after approval, sending it through the existing broadcaster.
- After implementation and validation, show the **exact final message** and get approval **before deployment** (unless the user explicitly waives this gate). Approval covers the actual text, not a draft; substantial edits require renewed approval.
- Then **deploy → verify** the new version is running and reachable → broadcast the approved text. Never announce a failed/rolled-back release, local-only work, tests, or documentation-only changes.
- Explain user-visible benefits, not a technical changelog. Use readable spacing, bullets for distinct changes, concise grouped points and restrained emoji. Omit implementation jargon unless useful; mention `/start` only if menus or commands changed.
- Deliver silently when supported or required; send **idempotently** once per release/version and retry **only failed recipients**. Report sent/failed counts to the owner without revealing tokens, user IDs or chat data. Respect suppression, postponement and customization requests.

## Navigation

- **Reply keyboard** = stable, collapsible main navigation; reserve it for key sections and common actions. Ordinary menus must not use `is_persistent=True`.
- Change the reply keyboard only when interaction mode changes (e.g. a wizard with temporary `❌ Cancel`); restore the main keyboard when finished.
- **Inline buttons** = actions for the current message: object lists, contextual Back and section actions. Avoid duplicating reply navigation; edit the current message instead of sending more messages when feasible.

## Forms and editors

- Keep cancellation only in the reply keyboard during a form. Maintain one bound form message: edit it when possible; otherwise remove it before replacing it. If removal fails, **do not create a duplicate**. Restore main navigation on exit.
