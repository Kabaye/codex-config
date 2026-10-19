# Shared Telegram Bot Contract

These defaults apply only to Telegram bot work. Repository-specific rules set the audience, deploy/broadcast commands, version, and verification; they may tighten but not weaken the gates below.

## Production releases

- For a production release with user-visible changes, prepare **one polished Russian notification** for all eligible users unless the user suppresses or postpones it. An explicit deploy request authorizes preparation and, after approval, use of the existing broadcast mechanism.
- After implementing and validating, show the **exact final message** and obtain approval **before deployment**. The user may explicitly waive this gate. Do not substitute a draft or summary; a material edit after approval requires fresh approval.
- After approval, **deploy → verify the new version is running and available → send the approved notification**. Never announce a failed or rolled-back deployment, local-only work, tests, or documentation-only changes. Approval of text is not permission to announce failure.
- Write for end users: explain what improved or became possible, not technical steps or a changelog. Use a clear opening, sensible line breaks and bullets for distinct changes; group related points, avoid dense paragraphs and repetitive status lines. Use emoji sparingly. Omit internal terms (commits, APIs, migrations, infrastructure) unless genuinely useful. Mention `/start` only if menus or commands changed.
- Send silently when supported (or required by the project); broadcast **idempotently per release/version**, retrying only failed recipients. Verify and report sent/failed counts **to the owner only**, never user IDs, names, chats, tokens, or secrets.
- Respect explicit instructions to suppress, customize, postpone, or waive approval. Project rules own the concrete delivery mechanics.

## Keyboards and screens

- **Reply keyboard = stable main navigation**; reserve it for top-level sections and common actions. Ordinary navigation must remain collapsible (never `is_persistent=True`) and reopenable; do not change it for each screen.
- Change the reply keyboard only when **interaction mode** changes (e.g. a temporary wizard). A forced-visible `❌ Cancel` is acceptable during that mode; restore the collapsible main keyboard afterward.
- **Inline buttons = actions on the current screen**: show object lists and the contextual **Back** button there. Keep keyboards short, avoid duplicate navigation, and edit the current message for in-section navigation where practical.

## Forms and editors

- Put cancellation **only in the reply keyboard** during a form. Keep one bound form message; edit it where possible. Before sending a replacement, remove the previous one; if removal fails, do not create a duplicate. Restore the main keyboard at the end.
