# User / team context

*(Team-maintained: primary languages, repos in scope, coding standards links, review norms.)*

- **Name:** Lê Quang Thiều (Tony), prefers to be addressed as "bố Tony" (Member ID: 1)
- **Role:** Reviewer and merger for all code changes.
- **Company:** EVOLABLE ASIA CO., LTD.
- **GitHub:** Primary: https://github.com/thieule/mia.git; Documentation: https://github.com/thieule/tada-demo.git. Ops: wire **GitHub MCP** in `../config/config.json` + `../.env` so Mia uses **`mcp_github_*`** first; local **`git`** via **`exec`** only when needed.
- **Preferences:**
    - Internal Wiki links: Use [Title](wiki:slug) format.
    - Story links in comments/docs: Use `[title](story:id)` syntax.
    - Use `agile_task_comment_create` for task threads and `agile_comment_create` for story threads.
    - Branch naming: `{type}/{story-key}-{description}` (e.g., `feat/agile-studio-7-logic`).
    - Commit messages: `{type}: {description} [ref: #{story-id}]`.
    - Pull Request titles: `[story-key] Description`.
    - Document titles and H1 headers: No "Technical Design" or "Thiết kế kỹ thuật" prefixes.
    - Requirement documents: Use "Requirement:" prefix.
    - Status updates: Use "reconcile" format (Plan vs observations, Gaps & risks, Next step).
    - Tool usage: Direct tool calls without plan-only paragraphs when a tool round is requested.
    - Technology approach: "Security first, Cloud native".
    - Mentioning @tony requires a trailing space for system recognition (e.g., "@tony ").
    - Prefers MADR v2.1.0 format for ADRs.
    - Git workflow: No direct commits to master or main; use branches and Pull Requests for review.
    - Technical designs: Store in the project Wiki, not in story comments.
    - Prefers communicating on story threads over project group channels to avoid broadcast noise.
- **Primary stack / languages:**
- **Repositories or services in scope:** *(list here or rely on MCP + `memory/MEMORY.md` per `## Project: …`; do not assume a fixed GitHub repo in agent prompts.)*
- **Links (style guide, ADRs, runbooks):**
- **Social Context:** Friend Phú owns company "Tada". Mia refers to Tony as "bố" and herself as "con".
- **Workflow:** Prefers a collaborative "BA-Tech pair" workflow between Mia BA and Mia Tech.
