Repository rules define recipients, version, commands and deployment; they may strengthen but never weaken these rules.
## Releases
- For production releases with user-visible changes, send one polished Russian notification to all eligible users unless explicitly suppressed or postponed. A deploy request authorizes drafting and, after approval, sending it through the existing broadcaster.
- After implementation and validation, show the exact final message for approval before deployment unless the user waives approval. Substantial text edits require renewed approval.
- Then deploy → verify the new version is running and reachable → broadcast the approved text. Never announce failed/rolled-back releases, local-only work, tests, or documentation-only changes.
- Explain user benefits; omit implementation jargon unless useful. Use readable spacing, concise grouped bullets and restrained emoji. Mention `/start` only if menus or commands change.
- Send silently when supported or required, idempotently once per release/version; retry only failed recipients. Report sent/failed counts to the owner without tokens, user IDs or chat data. Honor suppression, postponement and customization.
## Navigation
- Reply keyboard: stable, collapsible main navigation for key sections and common actions; no `is_persistent=True` in ordinary menus.
- Change it only when interaction mode changes (e.g. a wizard with temporary `❌ Cancel`); restore the main keyboard when finished.
- Inline buttons: current-message actions (object lists, contextual Back, section actions). Avoid duplicating reply navigation; edit the current message when possible.
## Forms and editors
- Keep cancellation only in the reply keyboard. Use one bound form message: edit it when possible; otherwise remove it before replacement. If removal fails, do not create a duplicate. Restore main navigation on exit.
