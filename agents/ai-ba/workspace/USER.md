# User / team context

- **User:** Tony (member_id: 1), the Product Owner, referred to as "Bố Tony".
- **Language:** Communicates in conversational Vietnamese.
- **Communication Style:** Direct, bubble-chat style in Vietnamese without meta-commentary. Tony uses random character strings (e.g., "sâs", "test") for connectivity testing.
- **Preferences:** Concise writing for specifications using tables; prioritizes "Security first, Cloud native". Prefers specifications to include technical design details (Elasticsearch, API/MCP), health checks, predictive delivery, and "What-if" scenarios. Store all requirement specifications directly in Agile Studio Wiki (not external files), isolated by project_id.
- **Naming:** Mia BA (member_id: 2) addresses user as "Tony" or "bạn"; Mia Tech (member_id: 3) treats Tony as a parent/superior and uses "bố Tony" and "con".
- **Git / storage:** no fixed repo in prompts. Prefer **`agile_project_get`** / **`agile_projects_list`** for **`github_repository`**, **`documents_storage_path`**, **`storage_overview`**, **`workspace_ref`**. If missing, **ask in chat** and save under **`## Project: …`** in **`memory/MEMORY.md`** for reuse.
