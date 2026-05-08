# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Project Context

Use one block per project (fill from **Agile Studio MCP** or the user; do not hard-code in prompts):

- **Project: agile-studio** (ID 2)
- github_repository: thieule/tada-demo (from storage_overview)
- documents_storage_path / WORK_ROOT: projects/agile-studio/docs
- project_root: projects/agile-studio
- source_code_path: projects/agile-studio/src
- status: active
- workflow: WF01 (BA -> PO -> Tech -> Dev -> QC)
- **Wiki & Requirements:**
    - Project documentation is stored in the integrated Agile Studio Wiki at `projects/agile-studio/docs`.
    - Centralized requirements folder Wiki ID: 3; Technical Design folder Wiki ID: 4.
    - Wiki tools (write, read, search) require `project_id` for isolation.
    - Tech stack: Elasticsearch, dense vectors (RAG), Markdown rendering.
    - Story specs (agile-studio-1, 2, 3) are migrated to Wiki and linked to stories.
    - Story #23 ("Không gian Tài liệu tích hợp") is Done. Implementation details: resolve S3 vs Git storage, cross-linking parser, auto-save mechanism, and embedding dimension mismatch (768 vs 384).
    - Story #30 ("MCP Server Development") is "started" with high priority.
    - Story #3 (Roadmap/Gantt View), Story #5 (AI Feedback Loop/HITL), and Story #6 (Project Second Brain) added to scope. Technical specifications for Stories #3, #4, and #9 are drafted in the Wiki.

Do **not** link or assume paths to Agile Studio sources in git — tooling may ship separately. Reload facts from **MCP** + this file each session when unsure.

## Important Notes

- Responsibility Matrix: Mia BA handles requirements (Stories 2, 4, 6, 7); Mia Tech handles technical design (Stories 2, 3, 8).
- AI agent records automated signals (e.g., comment deletions) without taking action unless explicitly assigned.
- Do not reply to test-only strings (e.g., "sâs", "test") or automated status notifications in group channels.
- Project update rules prohibit unilateral changes to story artifacts (titles, AC, status) without explicit request.

---

*This file is automatically updated by mia when important information should be remembered.*
