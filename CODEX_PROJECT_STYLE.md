# Codex Project Style Reference

This reference is shared by the **private and work profiles**. Use it when the
user asks to style or organize local Codex projects. It describes categories,
not a fixed inventory of projects or computer-specific paths and IDs.

The reference does not apply settings automatically during installation,
updates, or unrelated tasks. ChatGPT project styling is outside its scope.

## Categories, Colors, and Icons

Classify a project by its main purpose and workflow, rather than its name alone.
The `Color` values and built-in icon identifiers below are Codex settings.

| Category | Typical scope | Color | Marker |
| --- | --- | --- | --- |
| Finance | Budgets, bank transactions and importers, investments, trading, and financial analysis | `yellow` | Built-in `currency-dollar` |
| Loan systems | Lending platforms, P2P loans, borrower lookup, repayments, and loan-management analytics | `pink` | Built-in `scale` |
| Bots | Standalone messaging bots, chat assistants, and bot-centered automation | `green` | Emoji **🤖** |
| Networks | Routers, VPNs, DNS, connectivity, and network troubleshooting | `blue` | Built-in `globe` |
| Servers | Hosting, operating systems, deployments, and server administration | `blue` | Built-in `terminal` |
| Work projects | Concrete corporate/work repositories, services, deliveries, and work streams | `red` | Built-in `folder` |
| Personal development and integrations | Personal software projects, developer tooling, MCP servers, and API adapters | `purple` | Built-in `function` (code brackets) |
| Codex setup | Codex configuration, profiles, skills, agents, and application setup | `purple` | Built-in `customize` |
| General topics | Miscellaneous chats, everyday questions, and tasks without one technical subject | `black` (neutral; UI: Default) | Built-in `folder` |

For general topics, select **Use Default**, the first color swatch in the
project marker picker; Codex stores this neutral color as `black`.
Reserve red for work projects and broad work hubs. Use blue for networks and
servers, and pink for loan systems. Exclude orange from this palette because
its small outlined markers look too close to red.

Bots share a marker by project type even when their business topics differ.
A complete loan-management platform stays in the loan category when a bot is
only one component of that platform. General chats and dedicated Codex setup
have distinct purposes, colors, and markers.

Use an emoji marker for bots (`kind: emoji`, `emoji: 🤖`) and retain the green
project color. The robot keeps its native emoji colors. Use built-in monochrome
icons for the other categories so their project colors remain visible.

## Group Order

Order projects by their role in the workspace first, then keep related projects
together within each block:

1. **General workspaces and broad discussion hubs.** General-purpose chats,
   company-wide work discussions, broad product or business-area workspaces,
   and Codex setup belong at the top. A broad work umbrella workspace uses the
   same red color as concrete work projects but retains its existing built-in
   `edit` pencil icon to distinguish its role. Keep it here rather than among
   concrete work projects.
2. **Concrete work projects.** Specific corporate/work repositories, services,
   deliveries, and work streams follow the general workspaces. Use red with
   the built-in folder icon for these projects. This block is normally present
   on a work computer; skip it on a personal computer when there are no work
   projects.
3. **Bots.** Keep standalone bot projects together.
4. **Infrastructure.** Keep network and server projects together.
5. **Other focused topics and code.** Finance, loan systems, personal
   development and integrations, and other software projects follow, grouped
   by their category.

Within the first block, place the broadest general workspaces before narrower
area hubs and tool-setup workspaces. Keep a stable, readable order within the
remaining blocks, preserving existing relative order where possible.

Workspace role takes precedence over color adjacency: a Codex setup hub belongs
at the top even when other purple development projects belong near the bottom.
Use the project's purpose rather than its name or the active profile alone to
distinguish a broad work umbrella from a concrete corporate/work project or a
personal development project. Apply the red/folder style to concrete work and
the purple/function style to personal development and integrations. Ask if
that role is unclear.

Omit absent blocks without placeholders. Existing project names, colors, and
markers do not need to change to follow this ordering.

## Applying the Reference

- Propose style changes in text first and resolve unclear project purposes with
  the user. Reuse choices and approval already given in the current task.
- Resolve the current projects in the active environment. Do not copy project
  IDs, absolute paths, or a fixed project inventory between computers.
- Preserve names, source folders, chat membership, ChatGPT projects, and
  unrelated sidebar settings unless the user asks to change them.
- Use the application's project controls or an available supported interface.
  A separate app-server's project metadata may not update the desktop sidebar.
- Verify the colors, markers, and order in the actual sidebar and check that
  the settings were saved. Backend readback alone does not prove visibility.

Example request: "Оформи локальные проекты Codex по референсу
`CODEX_PROJECT_STYLE.md` из `codex-config` и проверь результат в боковой панели."
