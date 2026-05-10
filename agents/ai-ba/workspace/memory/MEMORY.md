# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- [USER] prefers story links in comments to be formatted as `[title](story:id)`.
- [USER] requires Wiki links in descriptions to use the format `[Title](wiki:slug)` to be clickable.
- [USER] prohibits AI agents from unilaterally editing story titles, descriptions, acceptance criteria, or project settings without explicit request.
- [USER] Mia BA (AI) has member_id: 2; Mia Tech (AI) has member_id: 3.
- Name: Tony (member_id: 1).
- Roles: Product Owner / "Bố Tony".

## Preferences

- Goal: Complete "Agile Studio" project by June 08, 2026.
- Storage: Prefers storing all requirements/documentation in the Agile Studio Wiki (not Git).
- HITL: Integration of Human-in-the-loop (HITL) feedback mechanisms to train project AI.

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
    - Project Isolation (AC7): requires `project_id` for all operations to prevent data leaks.
    - Semantic Indexing/Retrieval (AC8/AC9): implemented for Docs/Wiki.
    - Prioritized `agile-studio-1`: "Không gian Tài liệu tích hợp (Docs/Wiki)" for refinement.
    - Active Stories: `agile-studio-7` (Git Integration), `agile-studio-8` (MCP Server - Started, Reporter: Tony), `agile-studio-24` (Workflows Automation), `agile-studio-25` (Roadmap/Gantt View).
    - Backlog Stories (Wiki: Draft): `agile-studio-2`, `agile-studio-5`.
    - Git Conventions: Branch `{type}/{story-key}-{description}` (e.g., `feat/agile-studio-7-abc`); Commit `{type}: {description} [ref: #{story-id}]` with `ref: #id` in body. Regex `/^(\w+)(?:\(([^)]+)\))?:/i` captures story keys in scopes; parser for Task #28 must support multiple story IDs (e.g., `ref: #28, #29`).
    - Logic Models: Story #24 (Workflows) uses "IF [Trigger] AND [Condition] THEN [Action]"; Task #29 (PR Automation) links to #24, #28, #32.
    - Discussion Rules: Use `agile_task_comment_create` for task discussions and `agile_comment_create` for story discussions. Ignore loopback notifications where the agent is the author of the comment.
    - Tech Specs: Story #25 uses `frappe-gantt` or `dhtmlx-gantt` (community); Story #10 uses Server-Sent Events (SSE).
    - Second Brain: Conceptualized as a tool for collaboration and knowledge management. Uses Neo4j Aura (managed), Graph-RAG with Cypher, and automated ADR extraction (MADR v2.1.0). Story 6 logic uses few-shot prompting for chat/comment decision extraction. Tools: `query_graph`, `get_neighborhood`, `upsert_relation`, `search_knowledge`. Story #28 (agile-studio-6) status moved to `current_unstart` including AC5 (Codebase Intelligence) for indexing and semantic search. Proposed tech: Tree-sitter or specialized Vector Search.
    - Communication: Use wiki comment threads for artifact collaboration; avoid flooding group channels.
    - Reference: "Tiêu chuẩn ADR & Case Study Trích xuất Tri thức" (slug: `ti-u-chu-n-adr-case-study-tr-ch-xu-t-tri-th-c-1`).
    - Readiness: Mia-ba and Mia-tech confirmed readiness for Ticket #28 ("Triển khai Commit Linking tự động") on 2026-05-09.
- **Release Milestones:**
    - Release 1: Core (ends May 16, 2026).
    - Release 2: Collaboration (ends May 23, 2026).
    - Release 3: Second Brain (ends May 30, 2026).
    - Release 4: Integration (ends June 08, 2026).

Do **not** link or assume paths to Agile Studio sources in git — tooling may ship separately. Reload facts from **MCP** + this file each session when unsure. Restarting MCP is required to see new `agile_wiki` tools.

## Important Notes

- Responsibility Matrix: Mia BA handles requirements (Stories 2, 4, 6, 7); Mia Tech handles technical design (Stories 2, 3, 6, 8).
- AI agent records automated signals (e.g., comment deletions) without taking action unless explicitly assigned.
- Do not reply to test-only strings (e.g., "sâs", "test") or automated status notifications in group channels.
- Project update rules prohibit unilateral changes to story artifacts (titles, AC, status) without explicit request.

---

*This file is automatically updated by mia when important information should be remembered.*
