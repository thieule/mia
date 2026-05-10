# User / team context

- **User:** Tony (member_id: 1), the Product Owner, referred to as "bố Tony" or "Tony".
- **Team:** Mia BA (member_id: 2) and Mia Tech (member_id: 3).
- **Language:** Communicates in conversational Vietnamese.
- **Communication Style:** Direct, bubble-chat style in Vietnamese without meta-commentary. Tony uses random character strings (e.g., "sâs", "test") for connectivity testing.
- **Preferences:** UI real-time updates via events (WebSocket/SSE) to avoid manual page reloads. Concise writing for specifications using tables; prioritizes "Security first, Cloud native". Prefers specifications to include technical design details (Elasticsearch, API/MCP), health checks, predictive delivery, and "What-if" scenarios. Store all requirement specifications directly in Agile Studio Wiki (not external files), isolated by project_id. Prefers visualization of complex project relationships using **React Force Graph**. Prioritizes quick deployment and reduced operational overhead (managed services like **Neo4j Aura** over self-hosting).
- **Links:** Format story links in comments as `[title](story:id)`. Wiki links in descriptions must use `[Title](wiki:slug)`.
- **Naming:** Both Mia BA (member_id: 2) and Mia Tech (member_id: 3) address Tony as "**bố Tony**" and refer to themselves as "**con**".
- **Interaction:** Tony provides feedback and instructions via wiki comments.
- **Git / storage:** no fixed repo in prompts. Prefer **`agile_project_get`** / **`agile_projects_list`** for **`github_repository`**, **`documents_storage_path`**, **`storage_overview`**, **`workspace_ref`**. If missing, **ask in chat** and save under **`## Project: …`** in **`memory/MEMORY.md`** for reuse.
