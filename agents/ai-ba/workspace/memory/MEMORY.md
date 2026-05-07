# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Project Context

Use one block per project (fill from **Agile Studio MCP** or the user; do not hard-code in prompts):

## Project: agile-studio

- github_repository: thieule/tada-demo (from storage_overview)
- documents_storage_path / WORK_ROOT: projects/agile-studio/docs
- project_root: projects/agile-studio
- source_code_path: projects/agile-studio/src
- status: active
- workflow: WF01 (BA researches market/ideas, creates stories, PO approves, Tech designs, Dev implements, QC tests)
- **Wiki & Requirements:**
    - Project documentation is stored in the integrated Agile Studio Wiki.
    - Centralized requirements folder Wiki ID: 3.
    - Project documentation Design folder Wiki ID: 4.
    - Wiki tools (write, read, search) require `project_id` for isolation.
    - Tech stack: Elasticsearch and dense vectors for semantic search (RAG).
    - Story specs (agile-studio-1, 2, 3) are migrated to Wiki and linked to stories.
    - Requirement for story:23 (agile-studio-1) is finalized and linked.
    - Requirement for "AI Insights" (agile-studio-4 / Story 26) completed and uploaded (2026-05-06).

Do **not** link or assume paths to Agile Studio sources in git — tooling may ship separately. Reload facts from **MCP** + this file each session when unsure.

## Important Notes

- Mia BA is currently working on "AI Feedback Loop" (Story 5).
- AI agent records automated signals (e.g., comment deletions) without taking action unless explicitly assigned.

---

*This file is automatically updated by mia when important information should be remembered.*
